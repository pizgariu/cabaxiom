"""Flat ordering strategies. Kahn, DFS and Priority."""
import random
import unittest

from cabaxiom import (
    DFS,
    Components,
    Graph,
    Kahn,
    Parallel,
    Priority,
    Reconciler,
    Step,
    WavesPartition,
)
from support import A, B, C, X, Y, Z, _RecStep


class TopoSortTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_caller_order_when_no_deps(self):
        # The stable tie-break keeps the caller's intentional order where deps don't force otherwise.
        log = []
        await Reconciler((X(log), Y(log), Z(log))).converge()
        self.assertEqual(log, ["X", "Y", "Z"])
        log2 = []
        await Reconciler((Z(log2), Y(log2), X(log2))).converge()
        self.assertEqual(log2, ["Z", "Y", "X"])

    async def test_reorders_to_satisfy_after(self):
        # B.expects = (A,) so listed B-first must still emit A before B.
        log = []
        await Reconciler((B(log), A(log))).converge()
        self.assertEqual(log, ["A", "B"])

    async def test_transitive_chain(self):
        # C -> B -> A, handed in shuffled, resolves to A, B, C.
        log = []
        await Reconciler((C(log), A(log), B(log))).converge()
        self.assertEqual(log, ["A", "B", "C"])

    async def test_dep_outside_supplied_set_is_ignored(self):
        # B declares expects=(A,) but only B is supplied - the absent dep is ignored, no raise.
        log = []
        await Reconciler((B(log),)).converge()
        self.assertEqual(log, ["B"])

    def test_cycle_raises_naming_the_stuck_steps(self):
        class P(_RecStep):
            pass

        class Q(_RecStep):
            expects = (P,)

        P.expects = (Q,)  # close the cycle
        with self.assertRaises(ValueError) as ctx:
            Reconciler((P([]), Q([])))
        self.assertIn("P", str(ctx.exception))
        self.assertIn("Q", str(ctx.exception))


class RequiresTests(unittest.IsolatedAsyncioTestCase):
    """requires is the hard companion of after. It orders like after, yet an absent required class raises."""

    async def test_requires_orders_after_the_required_class(self):
        class Needy(_RecStep):
            requires = (A,)

        log: list = []
        await Reconciler((Needy(log), A(log))).converge()
        self.assertEqual(log, ["A", "Needy"])          # ordered after A, exactly as `expects` would

    def test_requires_raises_when_the_required_class_is_absent(self):
        # The distinction from after. test_dep_outside_supplied_set_is_ignored trusts an absent soft dep.
        # A hard requires demands it, failing loudly at construction instead.
        class Needy(_RecStep):
            requires = (A,)

        with self.assertRaises(ValueError) as ctx:
            Reconciler((Needy([]),))                    # no A in the run
        self.assertIn("Needy", str(ctx.exception))
        self.assertIn("A", str(ctx.exception))


class OrderingStrategyTests(unittest.IsolatedAsyncioTestCase):
    """Both ordering strategies resolve a valid flat order that honours the same contract. Kahn is the
    default and the only one a wave dispatcher can drive. DFS is a flat-only Ordering - no waves() to fan -
    so its contract is proven on the order it resolves, read straight off the strategy."""

    STRATEGIES = (Kahn(), DFS())

    def _order(self, ordering, steps):
        return [step.__class__.__name__ for step in ordering(Graph(steps))]

    def test_both_keep_caller_order_when_independent(self):
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=ordering.__class__.__name__):
                self.assertEqual(self._order(ordering, (X([]), Y([]), Z([]))), ["X", "Y", "Z"])

    def test_both_resolve_a_transitive_chain(self):
        # C -> B -> A handed in shuffled, both strategies resolve to A, B, C.
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=ordering.__class__.__name__):
                self.assertEqual(self._order(ordering, (C([]), A([]), B([]))), ["A", "B", "C"])

    def test_both_ignore_a_dep_outside_the_supplied_set(self):
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=ordering.__class__.__name__):
                self.assertEqual(self._order(ordering, (B([]),)), ["B"])

    def test_both_keep_every_instance_of_a_class(self):
        # Two A instances collapse to one graph node, yet BOTH must come out, before B.
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=ordering.__class__.__name__):
                self.assertEqual(self._order(ordering, (B([]), A([]), A([]))), ["A", "A", "B"])

    def test_both_raise_valueerror_naming_the_cycle(self):
        class P(_RecStep):
            pass

        class Q(_RecStep):
            expects = (P,)

        P.expects = (Q,)  # close the cycle
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=ordering.__class__.__name__):
                with self.assertRaises(ValueError) as ctx:
                    ordering(Graph((P([]), Q([]))))
                self.assertIn("P", str(ctx.exception))
                self.assertIn("Q", str(ctx.exception))

    async def test_default_ordering_is_kahn(self):
        # No explicit strategy -> Kahn. DFS is available but not the default.
        log = []
        await Reconciler((B(log), A(log))).converge()
        self.assertEqual(log, ["A", "B"])

    def test_base_chains_falls_back_to_one_chain_of_the_flat_order(self):
        # An Ordering that does not override chains() inherits the base fallback: ONE chain equal to its flat
        # order, the sentinel a pipelining executor rejects since it runs nothing concurrently. Kahn overrides
        # waves() but not chains(), so it lands on the fallback here.
        steps = (C([]), A([]), B([]))
        chains = Kahn().chains(Graph(steps))
        [chain] = chains   # exactly one chain of everything
        self.assertEqual([step.__class__.__name__ for step in chain], ["A", "B", "C"])


class OrderingContractTests(unittest.IsolatedAsyncioTestCase):
    """The ordering contract proven over RANDOMIZED DAGs, for both strategies at once. The resolved order
    honours expects, Kahn's waves pass verify, flattening the waves equals the flat order and a planted
    cycle raises ValueError. Seeded, so any failure reproduces byte-for-byte."""

    @staticmethod
    def __random_dag(randomness, size):
        # `size` fresh step classes with random expects edges pointing only BACKWARD (towards classes made
        # earlier), so the graph is a DAG by construction. Returned in a shuffled supplied order, so the
        # strategies never get to lean on definition order.
        classes = []
        for index in range(size):
            dependencies = tuple(randomness.sample(classes, randomness.randint(0, min(3, len(classes)))))
            classes.append(type(f"Random{index}", (Step,), {"expects": dependencies}))
        supplied = classes[:]
        randomness.shuffle(supplied)
        return supplied

    def test_every_strategy_honours_after_on_random_dags(self):
        randomness = random.Random(20260709)
        for _ in range(25):
            supplied = self.__random_dag(randomness, randomness.randint(2, 12))
            steps = tuple(cls() for cls in supplied)
            for ordering in (Kahn(), DFS(), Priority(), Components()):
                with self.subTest(ordering=ordering.__class__.__name__, graph=[cls.__name__ for cls in supplied]):
                    resolved = ordering(Graph(steps))
                    self.assertEqual(len(resolved), len(steps))   # no step dropped, no step invented
                    position = {type(step): index for index, step in enumerate(resolved)}
                    for step in resolved:
                        for dependency in type(step).expects:
                            self.assertLess(position[dependency], position[type(step)])

    def test_waves_inverse_reverses_them_and_their_contents(self):
        # The exact inverse of build order, owned by the WavesPartition type: both the wave order and the steps
        # within each wave flip, so a flat one-wave order inverts too (the DFS case).
        self.assertEqual(WavesPartition((("a", "b"), ("c",))).inverse(), (("c",), ("b", "a")))
        self.assertEqual(WavesPartition((("a", "b", "c"),)).inverse(), (("c", "b", "a"),))   # flat one-wave

    def test_kahn_waves_are_independent_and_flatten_to_the_flat_order(self):
        randomness = random.Random(20260710)
        for _ in range(25):
            supplied = self.__random_dag(randomness, randomness.randint(2, 12))
            steps = tuple(cls() for cls in supplied)
            kahn = Kahn()
            graph = Graph(steps)
            shaped = WavesPartition(kahn.waves(graph))
            shaped.verify(graph)   # raises on any mis-split - the fanning executor's own guard
            flattened = tuple(step for wave in shaped for step in wave)
            self.assertEqual(flattened, kahn(graph))

    def test_a_planted_cycle_raises_for_every_strategy(self):
        randomness = random.Random(20260711)
        for _ in range(10):
            supplied = self.__random_dag(randomness, randomness.randint(2, 8))
            first, second = randomness.sample(supplied, 2)
            first.expects = first.expects + (second,)    # close a two-class cycle on top of whatever edges
            second.expects = second.expects + (first,)   # the DAG already had - now unsatisfiable
            steps = tuple(cls() for cls in supplied)
            for ordering in (Kahn(), DFS(), Priority(), Components()):
                with self.subTest(ordering=ordering.__class__.__name__):
                    with self.assertRaises(ValueError):
                        ordering(Graph(steps))
            with self.assertRaises(ValueError):
                Kahn().waves(Graph(steps))


class PriorityOrderingTests(unittest.IsolatedAsyncioTestCase):
    """Priority - the best-first Ordering. The ready frontier is a priority queue, so among independent
    steps the smallest key wins, a canonical order independent of how the steps were supplied."""

    def test_orders_independent_steps_by_key_default_class_name(self):
        # Supplied Z, Y, X - Kahn would keep that order, Priority emits the canonical X, Y, Z by class name.
        steps = (Z([]), Y([]), X([]))
        order = Priority()(Graph(steps))
        self.assertEqual([step.__class__.__name__ for step in order], ["X", "Y", "Z"])

    def test_after_dominates_the_key(self):
        # C -> B -> A: the key cannot pull a dependency ahead of the thing that depends on it.
        steps = (C([]), A([]), B([]))
        order = Priority()(Graph(steps))
        self.assertEqual([step.__class__.__name__ for step in order], ["A", "B", "C"])

    def test_injected_key_changes_the_order(self):
        # A reverse key (largest name first) flips the canonical order to Z, Y, X.
        steps = (X([]), Y([]), Z([]))
        order = Priority(key=lambda step_class: -ord(step_class.__name__[0]))(Graph(steps))
        self.assertEqual([step.__class__.__name__ for step in order], ["Z", "Y", "X"])

    def test_keeps_every_instance_of_a_class(self):
        steps = (B([]), A([]), A([]))
        order = Priority()(Graph(steps))
        self.assertEqual([step.__class__.__name__ for step in order], ["A", "A", "B"])

    def test_is_flat_only_and_rejected_by_a_fanning_executor(self):
        # Best-first is a total order, so it does not override waves() - a fanning executor refuses it.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((A([]), B([])), Priority(), mode=Parallel())
        self.assertIn("Kahn", str(ctx.exception))

    def test_raises_valueerror_naming_a_cycle(self):
        class P(_RecStep):
            pass

        class Q(_RecStep):
            expects = (P,)

        P.expects = (Q,)  # close the cycle
        steps = (P([]), Q([]))
        with self.assertRaises(ValueError) as ctx:
            Priority()(Graph(steps))
        self.assertIn("P", str(ctx.exception))
        self.assertIn("Q", str(ctx.exception))


class InstanceDepsTests(unittest.IsolatedAsyncioTestCase):
    """Step.needs - instance-level edges, for ordering two steps of one class (or any precise edge expects
    cannot name). The graph is keyed by instance, so needs resolves alongside the kind-level expects."""

    async def test_needs_orders_two_instances_of_one_class(self):
        # expects relates only KINDS, so two Dir instances could not be ordered before. needs does it.
        log = []

        class Dir(Step):
            def __init__(self, name: str) -> None:
                self.__name = name

            def apply(self, inputs):
                log.append(self.__name)

                return None, {}
        parent = Dir("a")
        child = Dir("a/b")
        child.needs = (parent,)
        await Reconciler((child, parent)).converge()   # handed child-first - needs forces the parent first
        self.assertEqual(log, ["a", "a/b"])

    async def test_needs_is_honoured_across_waves_under_parallel(self):
        # An instance edge splits two steps into different waves, where the level barrier holds it, just like a
        # kind edge. verify() (needs-aware) accepts the split.
        log = []

        class Node(Step):
            def __init__(self, name: str) -> None:
                self.__name = name

            def apply(self, inputs):
                log.append(self.__name)

                return None, {}
        first = Node("first")
        second = Node("second")
        second.needs = (first,)
        await Reconciler((second, first), Kahn(), mode=Parallel()).converge()
        self.assertEqual(log, ["first", "second"])

    def test_verify_guards_the_requires_edge_like_the_after_edge(self):
        # requires is the HARD KIND edge. It orders a step after the named class exactly as after does, so a
        # fanning split that leaves the required step in the SAME wave must be caught by verify() - the same
        # guard that catches a mis-split expects edge (Only.narrow already closes over requires, so verify must too).
        class Dep(Step):
            pass

        class Dependent(Step):
            requires = (Dep,)

        dep, dependent = Dep(), Dependent()
        graph = Graph((dep, dependent))
        WavesPartition(((dep,), (dependent,))).verify(graph)   # required step in an earlier wave: honoured
        with self.assertRaises(ValueError):
            WavesPartition(((dep, dependent),)).verify(graph)  # required step in the SAME wave: edge ignored

    def test_a_needs_cycle_raises_naming_the_stuck_steps(self):
        class Node(Step):
            pass

        x = Node()
        y = Node()
        x.needs = (y,)
        y.needs = (x,)
        with self.assertRaises(ValueError) as ctx:
            Reconciler((x, y))
        self.assertIn("Node", str(ctx.exception))

    async def test_a_uses_edge_outside_the_supplied_set_is_ignored(self):
        # Scoped like expects=: a uses pointing at a step not handed in is dropped, so a subset still resolves.
        log = []

        class Node(Step):
            def __init__(self, tag: str) -> None:
                self.__tag = tag

            def apply(self, inputs):
                log.append(self.__tag)

                return None, {}
        absent = Node("absent")
        present = Node("present")
        present.uses = (absent,)
        await Reconciler((present,)).converge()
        # present resolved and ran. The absent edge was DROPPED, not resolved (else it would raise on the
        # missing node or pull it in). Proving the claim, not merely that nothing blew up.
        self.assertEqual(log, ["present"])


