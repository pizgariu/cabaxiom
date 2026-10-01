"""Bring a directory tree to a desired layout - the right directories, the right files, the right content.

Two Step kinds model an on-disk scaffold:

  Directory  ensure a directory exists (created with its parents)
  TextFile   ensure a file exists and holds exactly the desired content

TextFile declares `expects = (Directory,)`. Because `expects` edges are keyed by CLASS, that one
line means every directory is created before any file is written, no matter what order the
steps are supplied in. The files deliberately do NOT create their own parent directories, so
the dependency is load-bearing. Without it, a file could be written before its directory
exists.

drift() reads the filesystem (missing directory, missing file or wrong content) and apply()
writes it. converge() re-probes afterward, so an empty residual is a checked fact.

The example also shows self-healing. After the tree converges, it tampers with one file on
disk, then converges again. drift() catches the changed content and apply() rewrites it.

Run it:

    python examples/filesystem_layout.py

Expected stdout - an initial plan listing the missing directories and files, a first converge
that creates them and returns an empty residual, a clean second converge, then a tamper step
that reintroduces exactly one drift which the next converge repairs. The whole tree is built
under a temp directory and removed at the end.
"""

import asyncio
import shutil
import sys
import tempfile
from pathlib import Path

try:
    from cabaxiom import Assessment, DriftItem, Reconciler, Step
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, DriftItem, Reconciler, Step


class Directory(Step):
    """Ensure a directory (and any missing parents) exists."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def assess(self, inputs):
        if self.path.is_dir():
            return Assessment(deviation=[]), {}
        return Assessment(deviation=[DriftItem(str(self.path), "directory is missing")]), {}

    def apply(self, inputs):
        if self.path.is_dir():
            return None, {}
        self.path.mkdir(parents=True, exist_ok=True)
        return [DriftItem(str(self.path), "created directory")], {}


class TextFile(Step):
    """Ensure a text file exists and holds exactly the desired content."""

    expects = (Directory,)

    def __init__(self, path: Path, content: str):
        self.path = Path(path)
        self.content = content

    def assess(self, inputs):
        if not self.path.is_file():
            return Assessment(deviation=[DriftItem(str(self.path), "file is missing")]), {}
        if self.path.read_text(encoding="utf-8") != self.content:
            return Assessment(deviation=[DriftItem(str(self.path), "content does not match desired")]), {}
        return Assessment(deviation=[]), {}

    def apply(self, inputs):
        if not self.assess(inputs)[0].deviation:
            return None, {}
        # No parents=True on purpose. The Directory step must have run first.
        self.path.write_text(self.content, encoding="utf-8")
        return [DriftItem(str(self.path), "wrote desired content")], {}


def report(residual) -> None:
    if residual.applied:
        print("  applied this run:")
        for item in residual.applied:
            print(f"    + {item}")
    else:
        print("  applied this run: nothing")
    if residual:
        print("  residual (still wrong):")
        for item in residual:
            print(f"    ! {item}")
    else:
        print("  residual: empty -> layout verified by re-probe")


async def main() -> None:
    root = Path(tempfile.mkdtemp(prefix="reconciler-fs-"))
    try:
        app_toml = root / "config" / "app.toml"
        desired_toml = "name = \"demo\"\nport = 8080\n"
        # Files listed before their directories, to show the ordering resolves it.
        steps = [
            TextFile(root / "README.md", "# Demo site\n"),
            TextFile(app_toml, desired_toml),
            TextFile(root / "config" / "logging.ini", "[root]\nlevel = INFO\n"),
            Directory(root),
            Directory(root / "config"),
        ]
        reconciler = Reconciler(steps)

        print(f"Layout root: {root}")
        print()
        print("Plan (missing pieces, in resolved order - directories before files):")
        plan = await reconciler.assess()
        for item in plan:
            print(f"    - {item}")
        # The load-bearing edge, read straight off the plan. config/ is scheduled before the file inside
        # it, though the file was handed in first. Reverse that and the write below hits a missing parent.
        pending = [item.name for item in plan]
        assert pending.index(str(root / "config")) < pending.index(str(app_toml))
        print()

        print("First converge:")
        first = await reconciler.converge()
        report(first)
        assert not first                             # empty residual and it came from a re-read
        assert app_toml.read_text(encoding="utf-8") == desired_toml
        print()

        print("Second converge (should be a clean no-op):")
        again = await reconciler.converge()
        report(again)
        assert not again.applied   # a settled tree is not rewritten, so mtimes and watchers stay quiet
        print()

        print("Tampering: overwrite config/app.toml with the wrong content")
        app_toml.write_text("name = \"tampered\"\nport = 1\n", encoding="utf-8")
        drift = await reconciler.assess()
        print(f"  drift now sees {len(drift)} problem(s):")
        for item in drift:
            print(f"    ! {item}")
        # drift() reads CONTENT, not existence. The file is still there and it is still the only complaint.
        assert [item.name for item in drift] == [str(app_toml)]
        print()

        print("Converge again to self-heal:")
        healed = await reconciler.converge()
        report(healed)
        assert not healed
        assert app_toml.read_text(encoding="utf-8") == desired_toml   # the tamper was undone, not logged
        print()

        print(f"Final config/app.toml content:\n{app_toml.read_text(encoding='utf-8')}")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
