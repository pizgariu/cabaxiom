"""Scope - which of the handed steps take part, Only with its dependency closure, Skip without cascade."""
import unittest

from cabaxiom import Assessment, DriftItem, Graph, Only, Reconciler, Skip, Step, WithoutTag, WithTag
from cabaxiom.core.plan import BaseTagged, Scope, WithEveryTag
from support import A, B, C, X, Y, Z


class ScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_default_scope_keeps_everything(self):
        log = []
        await Reconciler((A(log), B(log), C(log)), scope=Scope()).converge()
        self.assertEqual(log, ["A", "B", "C"])

    async def test_only_pulls_in_the_transitive_dependencies_of_its_target(self):
        # C alone is named, yet its whole prerequisite chain comes along. A target converging
        # before its prerequisites would trust state nobody put there.
        log = []
        await Reconciler((C(log), A(log), B(log)), scope=Only(C)).converge()
        self.assertEqual(log, ["A", "B", "C"])

    async def test_only_leaves_unrelated_steps_out(self):
        log = []
        await Reconciler((X(log), Y(log), Z(log)), scope=Only(X)).converge()
        self.assertEqual(log, ["X"])

    async def test_only_with_overlapping_targets_selects_each_step_once(self):
        # B is both named and C's dependency, so the closure meets it twice and keeps it once.
        log = []
        await Reconciler((A(log), B(log), C(log)), scope=Only(B, C)).converge()
        self.assertEqual(log, ["A", "B", "C"])

    def test_only_stops_at_an_after_edge_to_an_absent_type(self):
        # C -> B -> A, yet A is not handed in. Only(C) follows the chain through the PRESENT steps and stops at
        # the edge to absent A (the kernel ignores an edge to an absent type), keeping C and B, not leaking on.
        kept = Only(C).select(Graph((C([]), B([])))).steps
        self.assertEqual({step.__class__.__name__ for step in kept}, {"B", "C"})

    def test_only_follows_an_instance_needs_edge(self):
        # X and Y are independent - no `expects` between them - so only a `needs` edge can pull X in. Without it
        # Only(Y) would converge the target trusting a prerequisite nobody placed.
        prereq = X([])
        target = Y([])
        target.needs = (prereq,)
        kept = Only(Y).select(Graph((prereq, target))).steps
        self.assertEqual({step.__class__.__name__ for step in kept}, {"X", "Y"})

    def test_only_ignores_a_needs_edge_to_an_absent_instance(self):
        # A needs pointing at a step not handed in is a dead end, like an after-edge to an absent type.
        target = Y([])
        target.needs = (X([]),)          # that X instance is never handed to the reconciler
        kept = Only(Y).select(Graph((target,))).steps
        self.assertEqual({step.__class__.__name__ for step in kept}, {"Y"})

    async def test_only_pulls_in_a_required_class(self):
        # Only follows requires as it follows after. A hard prerequisite must not be dropped by a targeted run,
        # or the ordering would then raise on the absent requirement.
        class Needy(Step):
            requires = (A,)

            def apply(self, inputs):
                pass

                return None, {}
        log: list = []
        await Reconciler((Needy(), A(log)), scope=Only(Needy)).converge()
        self.assertEqual(log, ["A"])                     # A was pulled in by Needy's requires edge

    async def test_skip_drops_the_named_steps_and_does_not_cascade(self):
        # C is after B, yet skipping B leaves C in. `expects` orders the steps present, it does not
        # demand their presence, so a skipped prerequisite is trusted, not propagated.
        log = []
        await Reconciler((A(log), B(log), C(log)), scope=Skip(B)).converge()
        self.assertEqual(log, ["A", "C"])

    async def test_skipping_every_step_leaves_a_clean_no_op_run(self):
        log = []
        residual = await Reconciler((A(log),), scope=Skip(A)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(log, [])

    async def test_every_verb_sees_the_scoped_set(self):
        # The scope resolves once at construction, so the reads shrink with it too.
        class InScope(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("in", "drifting")]), {}

        class OutOfScope(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("out", "drifting")]), {}

        drift = await Reconciler((InScope(), OutOfScope()), scope=Only(InScope)).assess()
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


class TagScopeTests(unittest.IsolatedAsyncioTestCase):
    """WithTag / WithoutTag select along Step.tags, the axis orthogonal to type that Only / Skip walk."""

    def _tagged(self, log: list) -> tuple[A, B, C]:
        a, b, c = A(log), B(log), C(log)
        a.tags = frozenset({"prod"})
        b.tags = frozenset({"prod", "network"})
        c.tags = frozenset({"dev"})
        return a, b, c

    def test_withtag_keeps_only_steps_carrying_a_named_tag(self):
        a, b, c = self._tagged([])
        kept = WithTag("prod").select(Graph((a, b, c))).steps
        self.assertEqual({step.__class__.__name__ for step in kept}, {"A", "B"})

    def test_withtag_matches_any_of_several_named_tags(self):
        a, b, c = self._tagged([])
        kept = WithTag("dev", "network").select(Graph((a, b, c))).steps   # B carries network, C carries dev
        self.assertEqual({step.__class__.__name__ for step in kept}, {"B", "C"})

    def test_withouttag_drops_steps_carrying_a_named_tag(self):
        a, b, c = self._tagged([])
        kept = WithoutTag("prod").select(Graph((a, b, c))).steps
        self.assertEqual({step.__class__.__name__ for step in kept}, {"C"})

    async def test_withtag_scopes_a_real_run_to_the_tagged_steps(self):
        log: list = []
        a, b, c = self._tagged(log)
        await Reconciler((a, b, c), scope=WithTag("prod")).converge()
        self.assertEqual(sorted(log), ["A", "B"])            # only prod-tagged A and B ran, in order

    def test_an_empty_tag_selection_is_rejected(self):
        for scope_type in (WithTag, WithoutTag):
            with self.subTest(scope=scope_type.__name__):
                with self.assertRaises(ValueError):
                    scope_type()

    def test_a_tag_no_step_carries_is_rejected(self):
        # Strict like the type scopes. A mistyped tag fails loudly instead of selecting nothing.
        a, b, c = self._tagged([])
        for scope_type in (WithTag, WithoutTag):
            with self.subTest(scope=scope_type.__name__):
                with self.assertRaises(ValueError) as ctx:
                    scope_type("staging").select(Graph((a, b, c))).steps
                self.assertIn("staging", str(ctx.exception))


class TagPredicateTests(unittest.IsolatedAsyncioTestCase):
    """`keeps` is the tag-axis twin of `narrow`. The guard verifies presence and walks once, the subclass
    says only what to keep. It replaced a declared polarity flag, which admitted exactly two answers and
    already shipped both, so it could carry no new scope at all."""

    def _tagged(self, *tags: str):
        step = A([])
        step.tags = frozenset(tags)
        return step

    def test_a_subclass_that_forgets_the_predicate_cannot_be_instantiated(self):
        class Forgetful(BaseTagged):
            pass

        with self.assertRaises(TypeError) as ctx:
            Forgetful("prod")
        self.assertIn("abstract", str(ctx.exception))
        self.assertIn("keeps", str(ctx.exception))

    def test_the_bare_base_is_refused_by_the_same_rule(self):
        # A flag needed a hand-written guard for this. An abstract method refuses it for free.
        with self.assertRaises(TypeError):
            BaseTagged("prod")

    def test_the_three_shipped_scopes_read_as_any_every_and_none(self):
        both, one, other = self._tagged("prod", "network"), self._tagged("prod"), self._tagged("network")
        steps = (both, one, other)
        self.assertEqual(WithTag("prod", "network").select(Graph(steps)).steps, steps)          # at least one
        self.assertEqual(WithEveryTag("prod", "network").select(Graph(steps)).steps, (both,))   # all of them
        self.assertEqual(WithoutTag("prod").select(Graph(steps)).steps, (other,))               # none of them

    def test_every_tag_naming_one_tag_matches_with_tag(self):
        prod, dev = self._tagged("prod"), self._tagged("dev")
        self.assertEqual(WithEveryTag("prod").select(Graph((prod, dev))).steps, WithTag("prod").select(Graph((prod, dev))).steps)

    def test_every_tag_still_refuses_a_tag_no_step_carries(self):
        # The declaration must be meaningful, which is about the SCOPE, not about one step carrying them all.
        with self.assertRaises(ValueError):
            WithEveryTag("prod", "typo").select(Graph((self._tagged("prod"),))).steps

    def test_a_predicate_beyond_all_three_shipped_scopes(self):
        # The seam stays open past the trio. A scope keying on how MANY named tags a step carries.
        class Exactly(BaseTagged):
            def keeps(self, carried):
                return len(carried & self._tags) == 1

        both, one = self._tagged("prod", "network"), self._tagged("prod")
        self.assertEqual(Exactly("prod", "network").select(Graph((both, one))).steps, (one,))
