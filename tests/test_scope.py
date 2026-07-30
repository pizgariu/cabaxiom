"""Scope: which of the handed steps take part, Only with its dependency closure, Skip without cascade."""
import unittest

from state_reconciler import DriftItem, Only, Reconciler, Scope, Skip, Step
from support import A, B, C, X, Y, Z


class ScopeTests(unittest.TestCase):
    def test_the_default_scope_keeps_everything(self):
        log = []
        Reconciler((A(log), B(log), C(log)), scope=Scope()).converge()
        self.assertEqual(log, ["A", "B", "C"])

    def test_only_pulls_in_the_transitive_dependencies_of_its_target(self):
        # C alone is named, yet its whole prerequisite chain comes along: a target converging
        # before its prerequisites would trust state nobody put there.
        log = []
        Reconciler((C(log), A(log), B(log)), scope=Only(C)).converge()
        self.assertEqual(log, ["A", "B", "C"])

    def test_only_leaves_unrelated_steps_out(self):
        log = []
        Reconciler((X(log), Y(log), Z(log)), scope=Only(X)).converge()
        self.assertEqual(log, ["X"])

    def test_only_with_overlapping_targets_selects_each_step_once(self):
        # B is both named and C's dependency, so the closure meets it twice and keeps it once.
        log = []
        Reconciler((A(log), B(log), C(log)), scope=Only(B, C)).converge()
        self.assertEqual(log, ["A", "B", "C"])

    def test_skip_drops_the_named_steps_and_does_not_cascade(self):
        # C is after B, yet skipping B leaves C in: `after` orders the steps present, it does not
        # demand their presence, so a skipped prerequisite is trusted, not propagated.
        log = []
        Reconciler((A(log), B(log), C(log)), scope=Skip(B)).converge()
        self.assertEqual(log, ["A", "C"])

    def test_skipping_every_step_leaves_a_clean_no_op_run(self):
        log = []
        residual = Reconciler((A(log),), scope=Skip(A)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(log, [])

    def test_every_verb_sees_the_scoped_set(self):
        # The scope resolves once at construction, so the reads shrink with it too.
        class InScope(Step):
            def drift(self) -> list:
                return [DriftItem("in", "drifting")]

        class OutOfScope(Step):
            def drift(self) -> list:
                return [DriftItem("out", "drifting")]

        drift = Reconciler((InScope(), OutOfScope()), scope=Only(InScope)).drift()
        self.assertEqual([item.name for item in drift], ["in"])

    def test_an_empty_selection_is_rejected(self):
        for scope_type in (Only, Skip):
            with self.subTest(scope=scope_type.__name__):
                with self.assertRaises(ValueError):
                    scope_type()

    def test_a_named_type_with_no_step_in_the_run_is_rejected(self):
        # Strict on purpose: the typo fails loudly instead of silently converging a smaller world.
        for scope_type in (Only, Skip):
            with self.subTest(scope=scope_type.__name__):
                with self.assertRaises(ValueError) as ctx:
                    Reconciler((A([]),), scope=scope_type(X))
                self.assertIn("X", str(ctx.exception))
