"""The README and the roadmap against the package they document.

Every gate this project had read the CODE. None read the prose, so 0.4.1 published a sentence saying a `Step`
can implement the Reconciler's reads. Each verb it named was real, which is why no check for a retired name
would have caught it - the OWNER was wrong rather than the word. These tests read the sentences."""
import importlib
import pathlib
import re
import unittest

import cabaxiom

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
PYPROJECT = ROOT / "pyproject.toml"
# A colon used as punctuation, never one that is syntax. A dict literal, a URL and a host-and-port pair all
# carry one legitimately, so the lookbehinds exclude what sits to the left of those.
PUNCTUATION_COLON = re.compile(r"(?<![:/\w\"\'`\]\)}])(?<!\d):(?= [A-Za-z`*(])")


class TheProseTellsTheTruthAboutTheTreeTests(unittest.TestCase):

    def setUp(self):
        self.told = README.read_text(encoding="utf-8")

    def test_no_engine_read_is_taught_as_a_step_hook(self):
        # The sentence that shipped. It is checked as a sentence because the names in it all exist.
        for engine_only in ("drift", "plan", "audit", "footprint"):
            self.assertFalse(hasattr(cabaxiom.Step, engine_only),
                             f"Step grew {engine_only}() and this guard is now stale")
        self.assertNotIn("each of which a `Step` can implement", self.told)

    def test_every_verb_the_front_page_lists_is_one_the_reconciler_has(self):
        listed = re.findall(r"^- `([a-z_]+)\(\)`", self.told, re.M)
        self.assertTrue(listed, "the verb list is gone, so this guard guards nothing")
        for verb in listed:
            self.assertTrue(hasattr(cabaxiom.Reconciler, verb),
                            f"the README lists {verb}(), which a Reconciler does not answer")

    def test_the_prose_uses_no_colon_as_punctuation(self):
        for number, line in enumerate(self.told.split("\n"), 1):
            if line.startswith(("    ", "|", "#")) or "://" in line:
                continue
            self.assertIsNone(PUNCTUATION_COLON.search(re.sub(r"`[^`]*`", "", line)),
                              f"README line {number} uses a colon as punctuation")

    def test_no_milestone_promises_a_module_this_release_already_ships(self):
        # A roadmap is read as what is COMING. 0.4.1 promised `cabaxiom.testing` for 1.1.0 and a freeze cut
        # from a 0.11.0 this line never plans. Both read as plans to whoever opened the page.
        for promised in re.findall(r"`(cabaxiom\.[a-z_.]+)`", self.roadmap()):
            with self.assertRaises(ImportError, msg=f"the roadmap promises {promised}, which already ships"):
                importlib.import_module(promised)

    def test_no_milestone_names_a_release_this_line_does_not_plan(self):
        for unplanned in ("0.9.0", "0.10.0", "0.11.0"):
            self.assertNotIn(unplanned, self.roadmap(),
                             f"the roadmap names {unplanned}, which this line does not cut")

    def test_every_changelog_link_names_the_repository_this_package_declares(self):
        # Two documents in one release disagreeing about where the project lives. The old name answers
        # with a redirect, which lasts exactly as long as nobody else claims it.
        declared = re.search(r'Repository = "https://github\.com/([\w.-]+/[\w.-]+)"', PYPROJECT.read_text(encoding="utf-8"))
        self.assertTrue(declared, "pyproject no longer declares a Repository url")
        for named in sorted(set(re.findall(r"https://github\.com/([\w.-]+/[\w.-]+)/compare/", CHANGELOG.read_text(encoding="utf-8")))):
            self.assertEqual(named, declared.group(1), f"a changelog link names {named}")

    def roadmap(self):
        return CHANGELOG.read_text(encoding="utf-8").split("## Roadmap", 1)[1].split("\n[", 1)[0]


class TheReadmeNamesOnlyThingsThatExistTests(unittest.TestCase):
    """0.4.0 shipped a README describing `drift()` as a hook, a synchronous `converge()`, a `Controller`
    and an `Executor`, all of which that same release had deleted. It went unnoticed because the suite
    ran the examples and never read the prose."""

    def setUp(self):
        self.told = README.read_text(encoding="utf-8")
        self.public = set(cabaxiom.__all__)

    def test_every_capitalised_name_in_a_code_fence_is_one_the_package_exports(self):
        # Only inside fences and only names that look like a public class. Prose says "Reconciler" in
        # sentences too, yet a fence is where a reader copies from, so a fence is where a lie costs.
        for fence in re.findall(r"```python\n(.*?)```", self.told, re.S):
            for imported in re.findall(r"^from cabaxiom import (.+)$", fence, re.M):
                for name in (part.strip() for part in imported.split(",")):
                    self.assertIn(name, self.public, f"README imports {name}, which cabaxiom does not export")

    def test_no_retired_name_survives_anywhere_in_the_prose(self):
        # The names 0.4.0 deleted. Each one was still being taught after it stopped existing.
        for gone in ("Controller", "BaseExecutor", "BaseReconciler", "AsyncReconciler", "OnError.Halt"):
            self.assertNotIn(gone, self.told, f"README still teaches {gone}, which no longer exists")

    def test_the_retired_read_hooks_are_not_taught_as_step_methods(self):
        for gone in ("def drift(self)", "def plan(self)", "def audit(self)", "def footprint(self)"):
            self.assertNotIn(gone, self.told, f"README still teaches {gone}, replaced by assess()")

    def test_the_engine_verbs_are_shown_awaited(self):
        # They became coroutines in 0.4.0. A README that shows them called bare teaches a coroutine leak.
        for fence in re.findall(r"```python\n(.*?)```", self.told, re.S):
            for called in re.findall(r"(?<!await )reconciler\.(converge|plan|drift|prune|audit)\(\)", fence):
                self.fail(f"README calls reconciler.{called}() without await")

    def test_every_declaration_slot_the_kernel_ships_is_documented(self):
        from cabaxiom.vocabulary import Vocabulary
        for kind in Vocabulary.shipped():
            self.assertIn(f"`{kind.slot}`", self.told, f"README does not mention the {kind.slot} slot")
        for slot in ("provides", "contends"):
            self.assertIn(f"`{slot}`", self.told)
