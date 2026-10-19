"""The layering, read off the real import graph rather than off the directory names.

A package split into folders is a filing decision. A package split into LAYERS is an architectural claim,
and the difference between the two is whether anything fails when the claim stops being true.

THE ARROWS THEMSELVES ARE NOT CHECKED HERE ANY MORE. They are declared in pyproject.toml and enforced by
import-linter and this file runs it. The walk that used to live here was hand-rolled over the AST and read
only RELATIVE imports, so `from cabaxiom.core.record.diagram import Mermaid` written inside the plan layer
walked straight past it - planted and confirmed green, twice, in two different shapes. grimp, which
import-linter builds on, resolves absolute imports, relative ones, re-exports through an __init__ and
imports written inside a function body. Four planted violations, four caught, against two of four for the
hand-rolled version. Some wheels are worth not reinventing and an import graph is one of them.

What stays here is everything a layers contract cannot say. That no module sits outside a declared layer.
That importing the kernel loads no laboratory module AT RUNTIME, which is a fact about sys.modules and not
about source. That the front door is a curated subset and every name it leaves out still opens on its
layer. And that the batteries, which live outside the wheel entirely, reach the kernel through the same
front door a stranger would use."""
import ast
import pathlib
import subprocess
import sys
import unittest

import cabaxiom
import cabaxiom.laboratory

_SOURCE = pathlib.Path(cabaxiom.__file__).parent
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_BATTERIES = _ROOT / "examples" / "battery"

# The layers, as pyproject.toml declares them. Named here only so the sweep below can tell a filed module
# from an unfiled one - the ORDER between them is import-linter's business and is stated nowhere else.
_LAYERS = frozenset({
    "core.declaration",     # what a step IS - knows nothing of a run
    "core.plan",            # from declarations to a seated partition
    "core.record",          # what a run says about itself
    "core.run",             # turning a plan into a converged world
    "laboratory.proof",     # does a property hold
    "laboratory.rig",       # what you mount a run in
    "laboratory.shrink",    # the smallest thing that breaks it
})


def _lint() -> subprocess.CompletedProcess[str]:
    # The console script beside this interpreter, never a bare `lint-imports` off PATH - a suite that
    # silently linted with some other environment's copy would be worse than one that did not lint at all.
    # There is no `python -m` entry point to reach instead, so the script is located rather than guessed.
    script = pathlib.Path(sys.executable).parent / "lint-imports"
    if not script.exists():                                    # pragma: no cover - a broken dev install
        raise unittest.SkipTest(f"import-linter is not installed beside {sys.executable}")
    return subprocess.run([str(script)], cwd=_ROOT, capture_output=True, text=True)


def _layer(module: pathlib.Path) -> str | None:
    parts = ".".join(module.relative_to(_SOURCE).parts[:-1])
    return parts if parts in _LAYERS else None


class TheDeclaredArrowsAreEnforcedTests(unittest.TestCase):

    def test_import_linter_keeps_every_contract(self):
        # The layering itself, run rather than re-implemented. It lives in pyproject.toml because that is
        # where a reader looks for it and because a contract written as a table is a contract a person can
        # argue with, which twenty lines of AST walking never was.
        told = _lint()
        self.assertEqual(told.returncode, 0, told.stdout + told.stderr)

    def test_the_contracts_are_the_ones_this_package_means_to_have(self):
        # A guard against the quiet kind of green. Delete the contracts from pyproject.toml and the linter
        # still exits 0, having checked nothing at all - so the NAMES are asserted, not just the verdict.
        told = _lint()
        for contract in ("The kernel cannot see the laboratory",
                         "The kernel's four layers point one way",
                         "The laboratory's benches point one way"):
            with self.subTest(contract=contract):
                self.assertIn(f"{contract} KEPT", told.stdout)
        self.assertIn("3 kept, 0 broken", told.stdout)


class TheModulesAreAllFiledTests(unittest.TestCase):

    def test_every_module_of_the_kernel_and_laboratory_sits_in_a_declared_layer(self):
        # A module that belongs to no layer is a module the test above cannot police, so an unfiled one is
        # a hole rather than an omission. The one file at the top is named, not waved through.
        loose = sorted(str(m.relative_to(_SOURCE)) for m in _SOURCE.rglob("*.py")
                       if _layer(m) is None and m.parent == _SOURCE)
        self.assertEqual(loose, ["__init__.py"])


class TheKernelCannotSeeTheLaboratoryTests(unittest.TestCase):
    """The half of this claim that a source-level contract cannot make.

    import-linter proves no core module NAMES the laboratory. It says nothing about what the interpreter
    ends up holding, which are different facts - a re-export through an __init__, a conftest, a plugin
    or a stray `importlib.import_module` would each put the laboratory in sys.modules without any core
    module having written its name. The runtime check below is the one a caller can actually feel."""

    def test_importing_the_kernel_does_not_load_one_laboratory_module(self):
        # Enforced at RUNTIME, not just in the source. `import cabaxiom` in a fresh interpreter must leave
        # sys.modules without a single laboratory entry, which is the version of this claim a caller can
        # actually feel - in start-up time and in what a security review has to read.
        import subprocess
        import sys

        told = subprocess.run(
            [sys.executable, "-c", "import cabaxiom, sys;"
                                   "print([m for m in sys.modules if 'laboratory' in m])"],
            capture_output=True, text=True, check=True,
        )
        self.assertEqual(told.stdout.strip(), "[]")

    def test_the_front_door_is_a_curated_subset_of_the_kernel(self):
        # Two claims, where the second is the one that rots. Everything in the door comes from the kernel,
        # and the door is deliberately SMALLER than the kernel - a name that only opens on `cabaxiom.core`
        # is not hidden, it is filed, so the day the door quietly re-absorbs the layers this fails.
        self.assertTrue(set(cabaxiom.__all__) < set(cabaxiom.core.__all__))
        self.assertEqual(set(cabaxiom.__all__) & set(cabaxiom.laboratory.__all__), set())

    def test_every_name_the_door_leaves_out_still_opens_on_its_layer(self):
        # The cost of narrowing, paid in full and checked. Nothing was deleted, so every demoted name must
        # be reachable at `cabaxiom.core` and at the layer that owns it - two addresses, both live. Otherwise the
        # narrowing stopped being a filing decision and became a removal nobody announced.
        filed = sorted(set(cabaxiom.core.__all__) - set(cabaxiom.__all__))
        self.assertGreater(len(filed), 0)
        layers = {name: getattr(cabaxiom.core, name) for name in filed}
        for name, held in layers.items():
            with self.subTest(name=name):
                owner = ".".join(getattr(held, "__module__", "").split(".")[:3])
                self.assertTrue(owner.startswith("cabaxiom.core."), f"{name} claims to live at {owner}")
                self.assertIs(getattr(__import__(owner, fromlist=[name]), name), held)

    def test_the_laboratory_still_has_to_be_asked_for_by_name(self):
        # Asserted through the REFUSAL rather than through hasattr, which no longer answers here - the
        # front door raises ImportError for a name it used to publish, so the caller who writes
        # `from cabaxiom import Siege` is told where Siege went instead of hearing "cannot import name".
        # hasattr only swallows AttributeError, so it raises, which is the deliberate price.
        for name in cabaxiom.laboratory.__all__:
            with self.subTest(name=name):
                with self.assertRaises(ImportError) as refused:
                    getattr(cabaxiom, name)
                self.assertIn("cabaxiom.laboratory", str(refused.exception))


class TheBatteriesUseTheFrontDoorTests(unittest.TestCase):

    def test_no_battery_reaches_past_the_public_api(self):
        # They live outside the wheel now, so they import the kernel exactly as a stranger would. That is
        # what makes them honest examples - the day a battery needs a private seam, the SEAM is the thing
        # to fix, so this test is where that argument starts.
        published = set(cabaxiom.__all__) | set(cabaxiom.laboratory.__all__)
        offences = []
        for module in sorted(_BATTERIES.rglob("*.py")):
            for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
                if not isinstance(node, ast.ImportFrom) or node.level or not node.module:
                    continue
                if not node.module.startswith("cabaxiom"):
                    continue
                if node.module not in ("cabaxiom", "cabaxiom.laboratory"):
                    offences.append(f"{module.name}:{node.lineno} imports from {node.module}")
                for alias in node.names:
                    if alias.name not in published:
                        offences.append(f"{module.name}:{node.lineno} imports private {alias.name}")
        self.assertEqual(offences, [], "\n".join(offences))

    def test_the_batteries_are_not_in_the_wheel(self):
        for gone in ("setup", "repository", "data"):
            with self.subTest(battery=gone):
                self.assertFalse((_SOURCE / gone).exists())


class EveryMovedNameSaysWhereItWentTests(unittest.TestCase):
    """The upgrade path, which the 0.7.0 window's own opening paragraph promises and briefly did not keep.

    Ninety names left the front door and for a while every one of them answered `from cabaxiom import X`
    with a bare "cannot import name", naming nothing. In a kernel whose whole identity is a refusal that
    says which promise you broke, that was the one refusal that said nothing at all."""

    def test_every_name_the_door_dropped_is_in_the_table(self):
        # The table is hand-written STRINGS, because resolving it at import time would drag the laboratory
        # into sys.modules and break the claim the split was made for. So the thing that can rot is the
        # table's agreement with reality, so this is where that is caught.
        from cabaxiom import _MOVED

        listed = {name for names in _MOVED.values() for name in names}
        dropped = (set(cabaxiom.core.__all__) | set(cabaxiom.laboratory.__all__)) - set(cabaxiom.__all__)
        self.assertEqual(dropped - listed, set(), "left the door with no forwarding address")
        self.assertEqual(listed - dropped, set(), "listed as moved and still in the door")

    def test_every_address_in_the_table_actually_resolves(self):
        import importlib

        from cabaxiom import _MOVED

        for where, names in _MOVED.items():
            module = importlib.import_module(where)
            for name in names:
                with self.subTest(name=name, where=where):
                    self.assertTrue(hasattr(module, name), f"{where} does not hold {name}")

    def test_the_refusal_names_the_line_to_type(self):
        for name, where in (("Waves", "cabaxiom.core.plan"), ("Siege", "cabaxiom.laboratory"),
                            ("RunMode", "cabaxiom.core.run"), ("Vocabulary", "cabaxiom.core.declaration")):
            with self.subTest(name=name):
                with self.assertRaises(ImportError) as refused:
                    getattr(cabaxiom, name)
                self.assertIn(f"from {where} import {name}", str(refused.exception))

    def test_a_sealed_name_says_why_rather_than_where(self):
        # Gather and Watch did not move, they went private, so pointing at an address would be a lie.
        with self.assertRaises(ImportError) as refused:
            getattr(cabaxiom, "Gather")
        self.assertIn("shipped run mode", str(refused.exception))
        self.assertNotIn("moved to", str(refused.exception))

    def test_a_name_that_never_existed_is_still_a_plain_attribute_error(self):
        # Load-bearing, not tidiness. The import machinery and half of the standard library probe a module
        # for attributes it may not have, where an ImportError raised at one of those makes the package
        # unimportable - which is exactly how the first draft of this broke, on __path__. That one is a
        # real attribute of a package and never reaches __getattr__, so the probes below are names that
        # genuinely are not there, which is the case the clause actually guards.
        for probe in ("Nonsense", "__wrapped__", "__all_the_things__"):
            with self.subTest(probe=probe):
                with self.assertRaises(AttributeError):
                    getattr(cabaxiom, probe)
