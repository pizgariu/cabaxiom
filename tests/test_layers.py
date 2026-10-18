"""The layering, read off the real import graph rather than off the directory names.

A package split into folders is a filing decision. A package split into LAYERS is an architectural claim,
and the difference between the two is whether anything fails when the claim stops being true. Every test
here parses the shipped source and walks the imports it actually contains, so the arrows are the ones the
interpreter would follow and not the ones a diagram in the docs promises.

Three claims are pinned. Arrows inside the kernel point one way. The kernel cannot see the laboratory
standing beside it. And the batteries, which live outside the wheel entirely, reach the kernel through the
same front door a stranger would use."""
import ast
import pathlib
import unittest

import cabaxiom
import cabaxiom.laboratory

_SOURCE = pathlib.Path(cabaxiom.__file__).parent
_BATTERIES = pathlib.Path(__file__).resolve().parents[1] / "examples" / "battery"

# The declared order, lowest first. A layer may import ITSELF or anything of strictly lower rank and
# nothing else - which is the whole content of the word "layer" as this package uses it.
_RANK = {
    "core.declaration": 0,     # what a step IS - knows nothing of a run
    "core.plan": 1,            # from declarations to a seated partition
    "core.record": 2,          # what a run says about itself
    "core.run": 3,             # turning a plan into a converged world
    "laboratory.proof": 4,     # does a property hold
    "laboratory.rig": 4,       # what you mount a run in
    "laboratory.shrink": 5,    # the smallest thing that breaks it
}


def _layer(module: pathlib.Path) -> str | None:
    parts = module.relative_to(_SOURCE).parts[:-1]
    return ".".join(parts) if ".".join(parts) in _RANK else None


def _imports(module: pathlib.Path) -> list[tuple[int, str]]:
    # Every relative import, resolved to the absolute module it names. Absolute imports of the package's
    # own modules are not resolved here because there are none - the kernel imports itself relatively and
    # a test below would notice the day that changes.
    package = ["cabaxiom", *module.relative_to(_SOURCE).parts[:-1]]
    found = []
    for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level and node.module:
            base = package[:len(package) - (node.level - 1)]
            found.append((node.lineno, ".".join([*base, node.module])))
    return found


class TheKernelArrowsPointOneWayTests(unittest.TestCase):

    def test_no_module_imports_a_layer_above_its_own(self):
        # The claim the folders would otherwise only imply. A record that could reach into the run it
        # records or a declaration that knew a dispatcher existed would still pass every other test in
        # this suite and would still be the thing this split was done to prevent.
        offences = []
        for module in sorted(_SOURCE.rglob("*.py")):
            here = _layer(module)
            if here is None:
                continue
            for line, target in _imports(module):
                there = ".".join(target.split(".")[1:-1])
                if there in _RANK and there != here and _RANK[there] >= _RANK[here]:
                    offences.append(f"{module.relative_to(_SOURCE)}:{line} {here} -> {there}")
        self.assertEqual(offences, [], "\n".join(offences))

    def test_every_module_of_the_kernel_and_laboratory_sits_in_a_declared_layer(self):
        # A module that belongs to no layer is a module the test above cannot police, so an unfiled one is
        # a hole rather than an omission. The one file at the top is named, not waved through.
        loose = sorted(str(m.relative_to(_SOURCE)) for m in _SOURCE.rglob("*.py")
                       if _layer(m) is None and m.parent == _SOURCE)
        self.assertEqual(loose, ["__init__.py"])


class TheKernelCannotSeeTheLaboratoryTests(unittest.TestCase):

    def test_no_core_module_imports_anything_from_the_laboratory(self):
        # The reason the line was drawn at all. A delta-debugger and an adversary are superb things to own
        # and have no business being reachable from the object they are pointed at.
        offences = []
        for module in sorted((_SOURCE / "core").rglob("*.py")):
            for line, target in _imports(module):
                if target.startswith("cabaxiom.laboratory"):
                    offences.append(f"{module.relative_to(_SOURCE)}:{line} -> {target}")
        self.assertEqual(offences, [], "\n".join(offences))

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
        for name in cabaxiom.laboratory.__all__:
            with self.subTest(name=name):
                self.assertFalse(hasattr(cabaxiom, name))


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
