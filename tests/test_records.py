"""Records - what a run hands back plus the one-way arrow that keeps them readable without the engine."""
import ast
import pathlib
import unittest

from cabaxiom import Explanation, Reconciler, Residual
from cabaxiom.drift import DriftItem
from support import A, B


class TheRecordsStandWithoutTheEngineTests(unittest.TestCase):
    """A record answers a question about a run that has already happened. It holds what it was handed and
    does no work, so it outlives the Reconciler that made it - and the arrow has to point one way for that
    to stay true. The engine imports the records. Nothing here imports the engine."""

    def test_the_records_module_imports_nothing_from_the_engine(self):
        source = pathlib.Path(__file__).parent.parent / "src" / "cabaxiom" / "records.py"
        pulled = set()
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                pulled.add(node.module)
            elif isinstance(node, ast.Import):
                pulled.update(alias.name for alias in node.names)
        self.assertNotIn("reconciler", pulled)
        self.assertNotIn("cabaxiom.reconciler", pulled)

    def test_a_residual_is_a_list_and_carries_what_was_applied_beside_it(self):
        # The whole reason it subclasses list. A caller testing truthiness or comparing against [] is
        # asking "did it converge", which has to keep working.
        stuck, done = DriftItem("Disk", "still full"), DriftItem("Cache", "cleared")
        record = Residual([stuck], [done])
        self.assertTrue(record)
        self.assertEqual(list(record), [stuck])
        self.assertEqual(record.applied, [done])
        self.assertEqual(Residual([], []), [])

    def test_a_residual_shows_both_channels_because_the_list_repr_hides_one(self):
        self.assertIn("applied=", repr(Residual([], [DriftItem("Cache", "cleared")])))

    def test_an_explanation_reads_as_the_flow_the_dispatcher_walks(self):
        self.assertEqual(repr(Explanation((("A",), ("B",)), ())), "Explanation((A) -> (B))")
        self.assertEqual(repr(Explanation((), ())), "Explanation(())")

    def test_the_reconciler_hands_back_the_records_and_re_resolves_nothing(self):
        reconciler = Reconciler((A([]), B([])))
        self.assertIsInstance(reconciler.explain(), Explanation)
        self.assertEqual(reconciler.explain().groups, reconciler.explain().groups)
