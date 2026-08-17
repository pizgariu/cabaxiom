"""The declared floor, checked on whatever interpreter happens to be running.

pyproject says `requires-python = ">=3.10"` and the classifiers list 3.10 through 3.14. A signature is
evaluated when its `def` runs, so a subscript in one of a type that only became subscriptable later kills
the import on every version below that - the package does not fail a test there, it fails to load at all.
This is invisible on a newer interpreter, which is exactly how it shipped.
"""
import ast
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).parent.parent / "src" / "cabaxiom"

# Standard-library types the kernel uses that gained __class_getitem__ ABOVE the declared floor. Each entry
# is the name as it is written in this codebase and the first version where subscripting it works.
LATE = {
    "TopologicalSorter": (3, 11),      # graphlib, gained __class_getitem__ in 3.11
}


class TheDeclaredFloorHoldsTests(unittest.TestCase):

    def test_no_signature_subscripts_a_type_the_floor_cannot_subscript(self):
        offences = []
        for module in sorted(SOURCE.glob("*.py")):
            tree = ast.parse(module.read_text(encoding="utf-8"))
            if any(isinstance(node, ast.ImportFrom) and node.module == "__future__"
                   and any(alias.name == "annotations" for alias in node.names) for node in tree.body):
                continue          # every annotation in this module is already lazy
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                written = [node.returns, *(arg.annotation for arg in node.args.args),
                           *(arg.annotation for arg in node.args.kwonlyargs)]
                for annotation in filter(None, written):
                    if isinstance(annotation, ast.Constant):
                        continue  # quoted, so never evaluated
                    for inner in ast.walk(annotation):
                        if isinstance(inner, ast.Subscript) and isinstance(inner.value, ast.Name):
                            since = LATE.get(inner.value.id)
                            if since:
                                offences.append(f"{module.name}:{node.lineno} {node.name}() subscripts "
                                                f"{inner.value.id}, which needs {since[0]}.{since[1]}")
        self.assertEqual(offences, [], "\n".join(offences))

    def test_the_floor_this_guard_checks_is_the_floor_that_is_declared(self):
        # If the floor is raised, an entry in LATE may become dead and should be dropped rather than left
        # asserting something the project no longer promises.
        declared = (SOURCE.parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.10"', declared)
