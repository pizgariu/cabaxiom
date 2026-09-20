"""Scope - which of the handed steps take part, Only with its dependency closure, Skip without cascade."""
import asyncio
import unittest

from cabaxiom import Assessment, DriftItem, Only, Reconciler, Scope, Skip, Step
from support import A, B, C, X, Y, Z


class ScopeTests(unittest.TestCase):
    def test_the_default_scope_keeps_everything(self):
        log = []
        asyncio.run(Reconciler((A(log), B(log), C(log)), scope=Scope()).converge())
        self.assertEqual(log, ["A", "B", "C"])

    def test_only_pulls_in_the_transitive_dependencies_of_its_target(self):
        # C alone is named, yet its whole prerequisite chain comes along, since a target converging
        # before its prerequisites would trust state nobody put there.
        log = []
        asyncio.run(Reconciler((C(log), A(log), B(log)), scope=Only(C)).converge())
        self.assertEqual(log, ["A", "B", "C"])

    def test_only_leaves_unrelated_steps_out(self):
        log = []
        asyncio.run(Reconciler((X(log), Y(log), Z(log)), scope=Only(X)).converge())
        self.assertEqual(log, ["X"])

    def test_only_with_overlapping_targets_selects_each_step_once(self):
        # B is both named and C's dependency, so the closure meets it twice and keeps it once.
        log = []
        asyncio.run(Reconciler((A(log), B(log), C(log)), scope=Only(B, C)).converge())
        self.assertEqual(log, ["A", "B", "C"])

    def test_skip_drops_the_named_steps_and_does_not_cascade(self):
        # C is after B, yet skipping B leaves C in. `after` orders the steps present, it does not
        # demand their presence, so a skipped prerequisite is trusted, not propagated.
        log = []
        asyncio.run(Reconciler((A(log), B(log), C(log)), scope=Skip(B)).converge())
        self.assertEqual(log, ["A", "C"])

    def test_skipping_every_step_leaves_a_clean_no_op_run(self):
        log = []
        residual = asyncio.run(Reconciler((A(log),), scope=Skip(A)).converge())
        self.assertEqual(residual, [])
        self.assertEqual(log, [])

    def test_every_verb_sees_the_scoped_set(self):
        # The scope resolves once at construction, so the reads shrink with it too.
        class InScope(Step):
            def assess(self) -> list:
                return Assessment(deviation=[DriftItem("in", "drifting")])

        class OutOfScope(Step):
            def assess(self) -> list:
                return Assessment(deviation=[DriftItem("out", "drifting")])

        drift = asyncio.run(Reconciler((InScope(), OutOfScope()), scope=Only(InScope)).drift())
        self.assertEqual([item.name for item in drift], ["in"])

    def test_an_empty_selection_is_rejected(self):
        for scope_type in (Only, Skip):
            with self.subTest(scope=scope_type.__name__):
                with self.assertRaises(ValueError):
                    scope_type()

    def test_a_named_type_with_no_step_in_the_run_is_rejected(self):
        # Strict on purpose. The typo fails loudly instead of silently converging a smaller world.
        for scope_type in (Only, Skip):
            with self.subTest(scope=scope_type.__name__):
                with self.assertRaises(ValueError) as ctx:
                    Reconciler((A([]),), scope=scope_type(X))
                self.assertIn("X", str(ctx.exception))


class Vault(Step):
    provides = frozenset({"secrets"})

    async def assess(self):
        return self.verified()


class Softly(Step):
    wants = ("secrets",)

    async def assess(self):
        return self.verified()


class Hardly(Step):
    demands = ("secrets",)

    async def assess(self):
        return self.verified()


class AScopeCannotNarrowARunIntoAWrongOneTests(unittest.TestCase):
    """A scope chooses membership, which is what the hard-presence rule reads. So a scope can
    produce a run the caller's own declaration refuses, so the refusal has to say which of the two is
    at fault - the fixes are opposite."""

    def test_skipping_a_softly_wanted_provider_is_allowed(self):
        # Soft is the slot that trusts the world, so skipping it is exactly that trust being exercised.
        reconciler = Reconciler((Vault(), Softly()), scope=Skip(Vault))
        self.assertEqual(reconciler.explain().groups, (("Softly",),))

    def test_skipping_a_hard_provider_is_refused_and_the_scope_is_named(self):
        with self.assertRaises(ValueError) as ctx:
            Reconciler((Vault(), Hardly()), scope=Skip(Vault))
        told = str(ctx.exception)
        self.assertIn("the scope of this run dropped", told)
        self.assertIn("Vault", told)
        self.assertNotIn("'wants'", told)          # not the fix here - the declaration was right

    def test_a_hard_edge_nothing_ever_answered_still_blames_the_declaration(self):
        with self.assertRaises(ValueError) as ctx:
            Reconciler((Hardly(),))
        told = str(ctx.exception)
        self.assertIn("this run has no such capability", told)
        self.assertIn("'wants'", told)             # here loosening the slot IS the fix
        self.assertNotIn("scope", told)

    def test_only_never_hits_this_because_its_closure_pulls_the_provider_in(self):
        # Only grows along the derivation, so a hard prerequisite of the target comes with it unasked.
        reconciler = Reconciler((Vault(), Hardly()), scope=Only(Hardly))
        self.assertEqual(reconciler.explain().groups, (("Vault",), ("Hardly",)))
