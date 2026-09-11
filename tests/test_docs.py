"""The README and the roadmap against the package they document.

Every gate this project had read the CODE. None read the prose, so 0.4.1 published a sentence saying a `Step`
can implement the Reconciler's reads. Each verb it named was real, which is why no check for a retired name
would have caught it - the OWNER was wrong rather than the word. These tests read the sentences."""
import pathlib
import re
import unittest

import cabaxiom

ROOT = pathlib.Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
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
