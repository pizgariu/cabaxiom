"""battery.setup filesystem batteries: each self-verifies and reverses, where a declared setup
converges idempotently. Run against a throwaway temp tree, the way a real setup should be rehearsed."""
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path

from battery.setup import Directory, File, JsonKey, LineInFile, Symlink
from cabaxiom import Parallel, Reconciler
from cabaxiom.laboratory import Idempotence


class _Tmp(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)


class DirectoryTests(_Tmp):
    def test_it_converges_and_is_idempotent(self):
        target = self.root / "nested" / "deep"
        step = Directory(target)
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["directory missing"])
        self.assertEqual([d.message for d in step.apply({})[0]], ["directory created"])
        self.assertTrue(target.is_dir())
        self.assertEqual(step.assess({})[0].deviation, [])
        self.assertIsNone(step.apply({})[0])                       # idempotent - a second apply is a no-op

    async def test_prune_removes_an_empty_directory_but_spares_a_full_one(self):
        target = self.root / "d"
        step = Directory(target)
        step.apply({})[0]
        (target / "keep.txt").write_text("x")
        self.assertEqual([d.message for d in step.prune({})[0]], ["directory not empty, left standing"])
        self.assertTrue(target.is_dir())                      # never nukes contents it did not place
        (target / "keep.txt").unlink()
        self.assertEqual(step.prune({})[0], [])                    # now empty, torn down
        self.assertFalse(target.exists())

    async def test_prune_of_an_absent_directory_is_clean(self):
        self.assertEqual(Directory(self.root / "never").prune({})[0], [])

    def test_footprint_reports_presence(self):
        step = Directory(self.root / "f")
        self.assertEqual(step.assess({})[0].footprint, [])
        step.apply({})[0]
        self.assertEqual([d.message for d in step.assess({})[0].footprint], ["directory present"])


class FileTests(_Tmp):
    def test_it_writes_and_verifies_content(self):
        target = self.root / "sub" / "config.ini"
        step = File(target, "[core]\nmode=fast\n")
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["file missing"])
        self.assertEqual([d.message for d in step.apply({})[0]], ["file written"])
        self.assertEqual(target.read_text(), "[core]\nmode=fast\n")
        self.assertEqual(step.assess({})[0].deviation, [])
        self.assertIsNone(step.apply({})[0])                       # idempotent

    def test_drift_catches_changed_content(self):
        target = self.root / "c"
        File(target, "want").apply({})[0]
        target.write_text("someone else changed it")
        self.assertEqual([d.message for d in File(target, "want").assess({})[0].deviation], ["content differs"])
        File(target, "want").apply({})[0]                          # converge closes the drift
        self.assertEqual(target.read_text(), "want")

    async def test_prune_and_footprint(self):
        target = self.root / "p"
        step = File(target, "x")
        self.assertEqual(step.assess({})[0].footprint, [])
        self.assertEqual(step.prune({})[0], [])                    # nothing to remove
        step.apply({})[0]
        self.assertEqual([d.message for d in step.assess({})[0].footprint], ["file present"])
        self.assertEqual(step.prune({})[0], [])
        self.assertFalse(target.exists())


class SymlinkTests(_Tmp):
    def test_it_creates_and_repoints(self):
        target_a = self.root / "vimrc"
        target_b = self.root / "vimrc.new"
        target_a.write_text("a")
        target_b.write_text("b")
        link = self.root / "home" / ".vimrc"
        step = Symlink(link, target_a)
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["symlink missing"])
        self.assertEqual([d.message for d in step.apply({})[0]], ["symlink created"])
        self.assertEqual(link.readlink(), target_a)
        self.assertIsNone(step.apply({})[0])   # idempotent
        moved = Symlink(link, target_b)   # same link, new target
        self.assertEqual([d.message for d in moved.assess({})[0].deviation], ["symlink points elsewhere"])
        moved.apply({})[0]
        self.assertEqual(link.readlink(), target_b)

    def test_it_refuses_to_replace_a_real_file(self):
        occupied = self.root / "real"
        occupied.write_text("precious")
        step = Symlink(occupied, self.root / "target")
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["path is a real file, not a symlink"])
        with self.assertRaises(FileExistsError):
            step.apply({})[0]
        self.assertEqual(occupied.read_text(), "precious")    # the real file is untouched

    async def test_prune_and_footprint(self):
        link = self.root / "l"
        (self.root / "t").write_text("t")
        step = Symlink(link, self.root / "t")
        self.assertEqual(step.assess({})[0].footprint, [])
        self.assertEqual(step.prune({})[0], [])                    # nothing to remove
        step.apply({})[0]
        self.assertEqual([d.message for d in step.assess({})[0].footprint], ["symlink present"])
        self.assertEqual(step.prune({})[0], [])
        self.assertFalse(link.is_symlink())
        self.assertTrue((self.root / "t").exists())           # the target survives the prune


class LineInFileTests(_Tmp):
    def test_it_appends_once_and_is_idempotent(self):
        profile = self.root / ".bashrc"
        profile.write_text("export A=1\n")
        step = LineInFile(profile, "export PATH=$PATH:/opt/bin")
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["line absent"])
        self.assertEqual([d.message for d in step.apply({})[0]], ["line added"])
        self.assertEqual(profile.read_text(), "export A=1\nexport PATH=$PATH:/opt/bin\n")
        self.assertIsNone(step.apply({})[0])                       # already there, no duplicate

    def test_it_creates_the_file_when_missing(self):
        ignore = self.root / "sub" / ".gitignore"
        LineInFile(ignore, "*.pyc").apply({})[0]
        self.assertEqual(ignore.read_text(), "*.pyc\n")

    async def test_prune_removes_every_copy_and_footprint_reports(self):
        target = self.root / "hosts"
        target.write_text("127.0.0.1 local\nkeep\n127.0.0.1 local\n")
        step = LineInFile(target, "127.0.0.1 local")
        self.assertEqual([d.message for d in step.assess({})[0].footprint], ["line present"])
        self.assertEqual(step.prune({})[0], [])
        self.assertEqual(target.read_text(), "keep\n")   # both copies gone, the rest kept
        self.assertEqual(step.prune({})[0], [])               # absent now, clean
        self.assertEqual(step.assess({})[0].footprint, [])

    def test_it_refuses_a_declaration_holding_a_line_break(self):
        # A block could never be found again by the line-wise membership test, so the step would append
        # it on every pass and grow the file forever. Caught at construction instead.
        for declared in ("export A=1\nPermitRootLogin yes", "trailing\r", ""):
            with self.assertRaises(ValueError) as ctx:
                LineInFile(self.root / "profile", declared)
            self.assertIn("takes ONE line", str(ctx.exception))

    async def test_prune_to_empty_leaves_no_stray_newline(self):
        target = self.root / "only"
        target.write_text("solo\n")
        LineInFile(target, "solo").prune({})[0]
        self.assertEqual(target.read_text(), "")


class JsonKeyTests(_Tmp):
    def test_it_sets_a_nested_key_creating_the_file(self):
        settings = self.root / "editor" / "settings.json"
        step = JsonKey(settings, ("editor", "tabSize"), 4)
        self.assertEqual([d.message for d in step.assess({})[0].deviation], ["key editor.tabSize absent"])
        self.assertEqual([d.message for d in step.apply({})[0]], ["key editor.tabSize set"])
        self.assertEqual(json.loads(settings.read_text()), {"editor": {"tabSize": 4}})
        self.assertIsNone(step.apply({})[0])                       # idempotent

    def test_drift_is_clean_when_the_value_already_matches(self):
        target = self.root / "s.json"
        step = JsonKey(target, ("editor", "tabSize"), 4)
        step.apply({})[0]
        self.assertEqual(step.assess({})[0].deviation, [])                    # present and equal, no drift

    def test_it_sets_a_key_beside_an_existing_one(self):
        target = self.root / "s.json"
        target.write_text(json.dumps({"editor": {"font": "mono"}}))
        JsonKey(target, ("editor", "tabSize"), 4).apply({})[0]     # editor is already an object, add into it
        self.assertEqual(json.loads(target.read_text()), {"editor": {"font": "mono", "tabSize": 4}})

    async def test_prune_of_an_absent_leaf_keeps_the_parent(self):
        target = self.root / "s.json"
        target.write_text(json.dumps({"editor": {"tabSize": 4}}))
        self.assertEqual(JsonKey(target, ("editor", "missing"), 1).prune({})[0], [])
        self.assertEqual(json.loads(target.read_text()), {"editor": {"tabSize": 4}})

    def test_drift_catches_a_changed_value(self):
        target = self.root / "s.json"
        JsonKey(target, "mode", "fast").apply({})[0]
        target.write_text('{"mode": "slow"}')
        self.assertEqual([d.message for d in JsonKey(target, "mode", "fast").assess({})[0].deviation], ["key mode differs"])
        JsonKey(target, "mode", "fast").apply({})[0]
        self.assertEqual(json.loads(target.read_text()), {"mode": "fast"})

    def test_it_refuses_to_destroy_a_non_object_on_the_path(self):
        target = self.root / "s.json"
        target.write_text('{"editor": "a config string somebody else owns"}')
        with self.assertRaises(TypeError) as ctx:
            JsonKey(target, ("editor", "tabSize"), 2).apply({})[0]
        self.assertIn("not an object", str(ctx.exception))
        self.assertEqual(json.loads(target.read_text()), {"editor": "a config string somebody else owns"})

    def test_it_refuses_a_document_that_is_not_an_object(self):
        target = self.root / "array.json"
        target.write_text("[1, 2]")
        with self.assertRaises(TypeError) as ctx:
            JsonKey(target, "key", 1).apply({})[0]
        self.assertIn("holds a JSON list, not an object", str(ctx.exception))
        self.assertEqual(json.loads(target.read_text()), [1, 2])

    async def test_prune_removes_only_that_key(self):
        target = self.root / "s.json"
        target.write_text(json.dumps({"editor": {"tabSize": 4, "font": "mono"}}))
        JsonKey(target, ("editor", "tabSize"), 4).prune({})[0]
        self.assertEqual(json.loads(target.read_text()), {"editor": {"font": "mono"}})

    async def test_prune_of_an_absent_path_is_clean(self):
        target = self.root / "s.json"
        target.write_text('{"a": 1}')
        self.assertEqual(JsonKey(target, ("x", "y"), 1).prune({})[0], [])   # the path leads nowhere
        self.assertEqual(json.loads(target.read_text()), {"a": 1})

    def test_footprint_shows_the_current_value(self):
        target = self.root / "s.json"
        step = JsonKey(target, "mode", "fast")
        self.assertEqual(step.assess({})[0].footprint, [])
        step.apply({})[0]
        self.assertEqual([d.message for d in step.assess({})[0].footprint], ['key mode = "fast"'])


class OwnershipGuardTests(_Tmp):
    """A fixture acts only where its OWN kind stands or where nothing does. Anything else at the path
    belongs to somebody else, so every battery refuses it instead of acting through it."""

    def test_a_file_refuses_to_write_through_a_symlink(self):
        victim = self.root / "victim.txt"
        victim.write_text("mine")
        declared = self.root / "declared.conf"
        declared.symlink_to(victim)

        fixture = File(declared, "OWNED")
        with self.assertRaises(FileExistsError) as ctx:
            fixture.assess({})[0].deviation
        self.assertIn("is a symlink, not a regular file", str(ctx.exception))
        with self.assertRaises(FileExistsError):
            fixture.apply({})[0]
        self.assertEqual(victim.read_text(), "mine")   # the target was never touched

    def test_a_directory_refuses_a_symlink_standing_in_for_it(self):
        elsewhere = self.root / "elsewhere"
        elsewhere.mkdir()
        declared = self.root / "workspace"
        declared.symlink_to(elsewhere)

        with self.assertRaises(FileExistsError) as ctx:
            Directory(declared).assess({})[0].deviation
        self.assertIn("is a symlink, not a directory", str(ctx.exception))

    def test_a_file_refuses_a_fifo_instead_of_blocking_on_it(self):
        declared = self.root / "pipe"
        os.mkfifo(declared)

        # Without the guard the write would open the FIFO and block until a reader appeared, wedging
        # the run. The guard names it and refuses instead.
        with self.assertRaises(FileExistsError) as ctx:
            File(declared, "content").apply({})[0]
        self.assertIn("is a FIFO, not a regular file", str(ctx.exception))

    def test_a_file_refuses_any_other_special_file(self):
        declared = self.root / "socket"
        with socket.socket(socket.AF_UNIX) as bound:
            bound.bind(str(declared))
            with self.assertRaises(FileExistsError) as ctx:
                File(declared, "content").assess({})[0].deviation
        self.assertIn("is a special file, not a regular file", str(ctx.exception))

    def test_line_in_file_and_json_key_refuse_a_symlink_too(self):
        victim = self.root / "victim.txt"
        victim.write_text("mine")
        for name, fixture in (("profile", LineInFile), ("settings", JsonKey)):
            declared = self.root / name
            declared.symlink_to(victim)
            step = fixture(declared, "export A=1") if fixture is LineInFile else fixture(declared, "k", 1)
            with self.assertRaises(FileExistsError):
                step.assess({})[0].deviation
        self.assertEqual(victim.read_text(), "mine")

    def test_the_home_shorthand_expands_instead_of_making_a_tilde_directory(self):
        fixture = File("~/.config/cabaxiom/probe.toml", "x")
        self.assertNotIn("~", str(fixture.path))
        self.assertTrue(str(fixture.path).startswith(str(Path.home())))


class AtomicWriteTests(_Tmp):
    """Content lands through a sibling temp file and a rename, so a reader never sees a torn file and a
    failed write leaves neither a half-written path nor litter behind."""

    def test_a_failed_replace_removes_the_temp_file_and_raises(self):
        standing = self.root / "occupied"
        standing.mkdir()
        fixture = File(standing, "content")   # a directory cannot be replaced by a file

        with self.assertRaises(OSError):
            fixture._replace("content")
        self.assertEqual([entry for entry in self.root.iterdir() if entry.name.startswith(".")], [])

    async def test_two_fixtures_racing_one_json_file_never_corrupt_it(self):
        settings = self.root / "settings.json"
        keys = [JsonKey(settings, f"key{index}", index) for index in range(16)]
        await Reconciler(keys, mode=Parallel()).converge()
        json.loads(settings.read_text())   # whatever was lost, the document is still valid JSON


class ComposedSetupTests(_Tmp):
    async def test_a_declared_setup_converges_and_proves_idempotent(self):
        class ProjectDir(Directory):
            pass

        class Marker(File):
            expects = (ProjectDir,)

        root = self.root / "project"
        steps = (Marker(root / "READY", "ok\n"), ProjectDir(root))   # handed out of order on purpose
        residual = await Reconciler(steps).converge()
        self.assertEqual(residual, [])                        # converged: the marker sits under its dir
        self.assertTrue((root / "READY").is_file())
        proof = await Idempotence(Reconciler((ProjectDir(root), Marker(root / "READY", "ok\n")))).prove()
        self.assertTrue(proof.stable)                         # a second run changes nothing, proven


class BareFixtureTests(unittest.IsolatedAsyncioTestCase):
    """The base's defaults ARE the contract. A battery overrides only the judgements it owns, where a
    fixture that owns none stays quiet on every channel instead of inventing findings."""

    async def test_a_fixture_that_overrides_nothing_is_quiet_on_every_channel(self):
        from battery.setup._base import Fixture

        class Inert(Fixture):
            pass

        with tempfile.TemporaryDirectory() as root:
            reconciler = Reconciler((Inert(Path(root) / "inert"),))
            self.assertEqual(await reconciler.converge(), [])   # no drift invented, apply a clean no-op
            self.assertEqual(await reconciler.prune(), [])      # nothing owned, so nothing survives
