"""Reconciler core lifecycle and Controller tick/run/settle composition."""
import asyncio
import unittest

from cabaxiom import Assessment, DriftItem, Explanation, Reconciler, Residual, Step
from support import A, B, Boom, C, Fixable, ReportOnly


class ExplainTests(unittest.TestCase):
    def test_explain_shows_resolved_waves_and_edges(self):
        log: list = []
        rec = Reconciler((C(log), A(log), B(log)))   # shuffled; Kahn resolves A -> B -> C into waves
        explanation = rec.explain()
        self.assertIsInstance(explanation, Explanation)
        self.assertEqual(explanation.groups, (("A",), ("B",), ("C",)))
        self.assertEqual(dict(explanation.edges), {"A": (), "B": ("A",), "C": ("B",)})
        self.assertIn("(A) -> (B) -> (C)", repr(explanation))

    def test_explain_of_empty_run(self):
        explanation = Reconciler(()).explain()
        self.assertEqual(explanation.groups, ())
        self.assertEqual(explanation.edges, ())
        self.assertEqual(repr(explanation), "Explanation(())")


class ConvergeTests(unittest.TestCase):
    def test_empty_reconciler_is_clean(self):
        rec = Reconciler(())
        self.assertEqual(asyncio.run(rec.drift()), [])
        self.assertEqual(asyncio.run(rec.converge()), [])

    def test_converge_applies_then_reports_clean_residual(self):
        f = Fixable()
        rec = Reconciler((f,))
        self.assertEqual(len(asyncio.run(rec.drift())), 1)   # opening status: drift present
        self.assertEqual(asyncio.run(rec.converge()), [])    # apply -> re-probe -> verified clean
        self.assertTrue(f.applied)

    def test_report_only_step_surfaces_in_residual_not_crash(self):
        residual = asyncio.run(Reconciler((ReportOnly(),)).converge())
        self.assertEqual(len(residual), 1)
        self.assertEqual(residual[0].name, "svc")
        self.assertEqual(residual[0].message, "still wrong")

    def test_apply_exception_propagates_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            asyncio.run(Reconciler((Boom(),)).converge())

    def test_drift_flattens_in_resolved_order(self):
        class D1(Step):
            def assess(self) -> list:
                return Assessment(deviation=[DriftItem("1", "x")])

        class D2(Step):
            after = (D1,)

            def assess(self) -> list:
                return Assessment(deviation=[DriftItem("2", "y")])

        rec = Reconciler((D2(), D1()))   # shuffled, D1 must come first
        self.assertEqual([d.name for d in asyncio.run(rec.drift())], ["1", "2"])

    def test_converge_reports_what_apply_changed_on_the_applied_channel(self):
        # A write-oriented step reports its change from apply(). It lands on applied, NOT the residual.
        class Writer(Step):
            def __init__(self):
                self.__written = [False]

            def assess(self) -> list:
                return Assessment(deviation=[] if self.__written[0] else [DriftItem("thing.conf", "out of date")])

            def apply(self):
                if self.__written[0]:
                    return None
                self.__written[0] = True
                return [DriftItem("thing.conf", "rewrote /etc/thing.conf")]

        result = asyncio.run(Reconciler((Writer(),)).converge())
        self.assertEqual(result, [])                                       # residual clean, still a plain list
        self.assertEqual([c.message for c in result.applied], ["rewrote /etc/thing.conf"])

    def test_applied_is_empty_when_apply_returns_none(self):
        # A step whose apply() returns None (the default, git-hooks style) contributes nothing to applied.
        result = asyncio.run(Reconciler((Fixable(),)).converge())
        self.assertEqual(result, [])
        self.assertEqual(result.applied, [])

    def test_a_raising_drift_during_the_reprobe_propagates_and_loses_applied(self):
        # Contract pin. The reads have no OnError policy, so a drift() that raises during converge's
        # re-probe propagates - and the applied record is lost with the exception. A step guarding a
        # real invariant keeps drift() total (return Drift, never raise).
        class Fragile(Step):
            def __init__(self):
                self.touched = [False]

            def assess(self) -> list:
                if self.touched[0]:
                    raise RuntimeError("probe broke after apply")
                return Assessment(deviation=[DriftItem("f", "needs fix")])

            def apply(self):
                self.touched[0] = True
                return [DriftItem("f", "fixed it")]

        with self.assertRaises(RuntimeError):
            asyncio.run(Reconciler((Fragile(),)).converge())


class ResidualTests(unittest.TestCase):
    def test_repr_shows_both_channels(self):
        # The inherited list repr would hide applied entirely - debugging output must show both channels.
        residual = Residual([DriftItem("svc", "still wrong")], [DriftItem("thing.conf", "rewrote it")])
        self.assertIn("applied=", repr(residual))
        self.assertIn("DriftItem('thing.conf', 'rewrote it')", repr(residual))
        self.assertIn("DriftItem('svc', 'still wrong')", repr(residual))


