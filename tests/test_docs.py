"""The prose is checked against the live package, so a rename cannot leave the documentation quietly
wrong. Most blocks in README.md and docs/ are FRAGMENTS - they import from cabaxiom and then use names
the block never binds - so nothing here executes them. Executing is not the only way to catch a lie:
the imported names, the dotted references in the prose and the syntax of every README block are all
decidable without running a line. Those three are what this file decides.
"""
import ast
import importlib
import pathlib
import re
import unittest

import cabaxiom

_ROOT = pathlib.Path(__file__).resolve().parents[1]

_MARKDOWN = [_ROOT / "README.md", *sorted((_ROOT / "docs").glob("*.md"))]
_EXPORTS = frozenset(cabaxiom.__all__)

# A ```python block. The body is captured without its fence lines, so offsets inside it still map onto
# the page's own line numbers and a failure can name a line the reader can open.
_BLOCK = re.compile(r"^```python[^\n]*\n(.*?)^```", re.M | re.S)

# `from cabaxiom... import a, b` wherever it sits, inside a fence or quoted mid-sentence. The
# parenthesised form is matched too, since a long import list wraps. The name list may hold ONLY what an
# import list can hold, which is what stops the sweep at a closing backtick: README's "you `from
# cabaxiom.setup import ...`. See `examples/dev_setup.py` for the full arc - declare, converge, prove"
# would otherwise read the rest of the sentence as four imported names and accuse the README of all four.
_IMPORT = re.compile(
    r"from\s+(cabaxiom(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s+import\s+(\([^)]*\)|[A-Za-z_*][A-Za-z0-9_ ,*]*)")

# A backticked token that is EXACTLY `Owner.member` or `Owner.member()` with no arguments. Anchoring on
# both backticks is what keeps this free of false positives. `Retry(attempts, backoff=...)` and
# `WithTag(...)` carry dots but are not this shape, while a lower-case left side (`graph.steps`,
# `asyncio.gather`) names a local variable or another library rather than a cabaxiom class.
_REFERENCE = re.compile(r"`([A-Z][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)(?:\(\))?`")

# Pages that record CHANGE rather than the surface as it stands. Every removal entry in the release
# notes names something that must NOT resolve today, since the notes are written ahead of the code they
# announce, so resolving their references would fail on the truth. Their import lines are still checked
# below, because an import shown to a reader has to work whatever the page is for.
_HISTORY = frozenset({"docs/release-notes.md", "docs/design-2.0.0.md"})


class _Page:
    """One markdown page, read once and sliced the three ways the checks below need it."""

    def __init__(self, path: pathlib.Path) -> None:
        self.path = path
        self.name = path.relative_to(_ROOT).as_posix()
        self.text = path.read_text(encoding="utf-8")

    def at(self, offset: int) -> int:
        """The 1-indexed line holding a character offset, so every failure points somewhere editable."""
        return self.text.count("\n", 0, offset) + 1

    def blocks(self) -> list[tuple[int, str]]:
        """Every ```python block as (first line of the body, source)."""
        return [(self.at(match.start(1)), match.group(1)) for match in _BLOCK.finditer(self.text)]

    def imports(self) -> list[tuple[int, str, str]]:
        """Every (line, module, name) the page imports from cabaxiom, ast first and a regex behind it.

        A block that parses is read by ast, which never miscounts an alias or a wrapped list. A fragment
        that does NOT parse, plus every mention outside a fence, is still swept by the regex. Both feed
        one set keyed by line, so a line both of them see is reported once.
        """
        found = set()
        for start, source in self.blocks():
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue                                   # a fragment, left to the regex sweep below
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                    continue                               # a relative import cannot appear in prose
                if node.module.split(".")[0] == "cabaxiom":
                    for alias in node.names:
                        found.add((start + node.lineno - 1, node.module, alias.name))
        for match in _IMPORT.finditer(self.text):
            names = match.group(2).split("#")[0].strip().strip("()")
            for name in names.split(","):
                bound = name.split(" as ")[0].strip()
                # Drops the elision in a quoted `from cabaxiom.setup import ...` and the trailing
                # backslash of a continued line, neither of which names anything.
                if bound.isidentifier():
                    found.add((self.at(match.start()), match.group(1), bound))
        return sorted(found)

    def references(self) -> list[tuple[int, str, str]]:
        """Every (line, owner, member) written as `Owner.member` where Owner is a real cabaxiom export.

        Filtering on __all__ is the second half of the false-positive guard. It drops the domain classes
        the examples invent (`DatabaseStep.apply`) and the standard library types the prose names, so
        only a claim about THIS package's surface is ever asserted.
        """
        return [(self.at(match.start()), match.group(1), match.group(2))
                for match in _REFERENCE.finditer(self.text)
                if match.group(1) in _EXPORTS]


_PAGES = [_Page(path) for path in _MARKDOWN]


class ExportedSurfaceTests(unittest.IsolatedAsyncioTestCase):
    """__all__ is the ORACLE the two sweeps below trust, so it is checked before it is trusted. An entry
    naming something the package does not bind is invisible to every other check here. No page imports it,
    no page writes it as `Owner.member`, so the reference sweep silently narrows because the owner it
    filters on is gone. The only place it surfaces is an AttributeError inside a reader's star import."""

    def test_every_exported_name_is_bound(self):
        for name in cabaxiom.__all__:
            with self.subTest(name=name):
                self.assertTrue(
                    hasattr(cabaxiom, name),
                    f"cabaxiom.__all__ lists '{name}', which the package does not bind, so "
                    f"'from cabaxiom import *' raises AttributeError on it. Point the entry at the "
                    f"current name or drop it.",
                )


class DocumentedImportTests(unittest.IsolatedAsyncioTestCase):
    """Every name the docs import from cabaxiom exists and is public. A rename that misses the prose
    lands here rather than in a reader's traceback on their first five minutes with the library."""

    def test_the_sweep_reads_the_pages(self):
        # A regex that silently matched nothing would turn the whole file green and prove nothing. The
        # floor is far under today's count, so it guards the sweep without breaking on an edited page.
        self.assertTrue(_PAGES, "no markdown pages found - README.md and docs/ moved")
        self.assertGreater(sum(len(page.imports()) for page in _PAGES), 20,
                           "almost no cabaxiom imports found in the docs - the import sweep is broken")

    def test_every_imported_name_exists(self):
        for page in _PAGES:
            for line, module_name, name in page.imports():
                with self.subTest(page=page.name, line=line, name=name):
                    module = self._module(page, line, module_name)
                    self.assertTrue(
                        hasattr(module, name),
                        f"{page.name}:{line} imports '{name}' from {module_name}, which does not exist. "
                        f"Rename it in the docs to whatever it is called now or restore the export.",
                    )

    def test_every_imported_name_is_exported(self):
        for page in _PAGES:
            for line, module_name, name in page.imports():
                with self.subTest(page=page.name, line=line, name=name):
                    module = self._module(page, line, module_name)
                    public = getattr(module, "__all__", None)
                    if public is None:
                        continue                           # no declared surface, existence is the whole contract
                    # assertTrue rather than assertIn, so the verdict is not buried under a dump of the
                    # whole 130-name __all__ that the reader already has open.
                    self.assertTrue(
                        name in public,
                        f"{page.name}:{line} imports '{name}' from {module_name}, which is missing from "
                        f"{module_name}.__all__, so the docs teach a private name as public. Add it to "
                        f"__all__ or stop documenting it.",
                    )

    def _module(self, page, line, module_name):
        try:
            return importlib.import_module(module_name)
        except ImportError:
            self.fail(f"{page.name}:{line} imports from '{module_name}', which is not an importable module. "
                      f"Fix the module path in the docs or restore the module.")


class DocumentedAttributeTests(unittest.IsolatedAsyncioTestCase):
    """A `Reconciler.explain()` in the prose is a promise about the surface exactly as an import is.
    Only the exports are checked, only where the page describes the surface as it stands now."""

    def test_the_sweep_reads_the_pages(self):
        current = [page for page in _PAGES if page.name not in _HISTORY]
        self.assertGreater(sum(len(page.references()) for page in current), 5,
                           "almost no `Owner.member` references found - the reference sweep is broken")

    def test_every_dotted_reference_resolves(self):
        for page in _PAGES:
            if page.name in _HISTORY:
                continue
            for line, owner, member in page.references():
                with self.subTest(page=page.name, line=line, reference=f"{owner}.{member}"):
                    self.assertTrue(
                        hasattr(getattr(cabaxiom, owner), member),
                        f"{page.name}:{line} writes `{owner}.{member}` but {owner} has no '{member}'. "
                        f"Point the docs at the current name or restore the attribute. If the page is "
                        f"deliberately naming a retired API, it belongs in _HISTORY beside the release "
                        f"notes rather than in this sweep.",
                    )


class ReadmeBlockTests(unittest.IsolatedAsyncioTestCase):
    """The README's blocks are the first code anyone reads. A fragment cannot be run, yet a fragment
    that is not even Python is simply wrong, which the parser settles for free."""

    def test_every_python_block_parses(self):
        readme = _PAGES[0]
        self.assertEqual(readme.name, "README.md")
        blocks = readme.blocks()
        self.assertTrue(blocks, "no ```python blocks found in README.md - the fence sweep is broken")
        for line, source in blocks:
            with self.subTest(line=line):
                try:
                    ast.parse(source)
                except SyntaxError as broken:
                    self.fail(f"README.md:{line} opens a ```python block that is not valid Python "
                              f"({broken.msg} on its line {broken.lineno}). Fix the block or fence it as "
                              f"plain text if it was never meant to be code.")


class TheFrontPageNamesTheOwnerOfEveryVerbTests(unittest.TestCase):
    """The README once said a `Step` can implement verbs only the `Reconciler` has. Every name in that
    sentence existed, so a sweep that resolves names passed it. These read the owner instead."""

    told = (_ROOT / "README.md").read_text(encoding="utf-8")

    def test_no_engine_read_is_taught_as_a_step_hook(self):
        for engine_only in ("explain", "foresee", "converge"):
            self.assertFalse(hasattr(cabaxiom.Step, engine_only), f"Step grew {engine_only}() and this guard is now stale")
        self.assertNotIn("each of which a `Step` can implement", self.told)

    def test_every_verb_the_front_page_lists_is_one_the_reconciler_has(self):
        listed = re.findall(r"^- `([a-z_]+)\(\)`", self.told, re.M)
        self.assertTrue(listed, "The verb list is gone, so this guard guards nothing")
        for verb in listed:
            self.assertTrue(hasattr(cabaxiom.Reconciler, verb), f"The README lists {verb}(), which a Reconciler does not answer")
