"""Flat ordering strategies. Kahn, DFS and Priority."""
import asyncio
import random
import unittest

from cabaxiom import DFS, Components, Kahn, Parallel, Priority, Reconciler, Serial, Step, Unresolvable
from cabaxiom.graph import Graph
from cabaxiom.partition import Levels, Partition
from support import A, B, C, X, Y, Z, _RecStep


class TopoSortTests(unittest.TestCase):
    def test_preserves_caller_order_when_no_deps(self):
        # The stable tie-break keeps the caller's intentional order where deps don't force otherwise.
        log = []
        asyncio.run(Reconciler((X(log), Y(log), Z(log))).converge())
        self.assertEqual(log, ["X", "Y", "Z"])
        log2 = []
        asyncio.run(Reconciler((Z(log2), Y(log2), X(log2))).converge())
        self.assertEqual(log2, ["Z", "Y", "X"])

    def test_reorders_to_satisfy_after(self):
        # B.expects = (A,) so listed B-first must still emit A before B.
        log = []
        asyncio.run(Reconciler((B(log), A(log))).converge())
        self.assertEqual(log, ["A", "B"])

    def test_transitive_chain(self):
        # C -> B -> A, handed in shuffled, resolves to A, B, C.
        log = []
        asyncio.run(Reconciler((C(log), A(log), B(log))).converge())
        self.assertEqual(log, ["A", "B", "C"])

    def test_dep_outside_supplied_set_is_ignored(self):
        # B declares expects=(A,) but only B is supplied - the absent dep is ignored, no raise.
        log = []
        asyncio.run(Reconciler((B(log),)).converge())
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


class OrderingStrategyTests(unittest.TestCase):
    """Both ordering strategies honour the same contract. Kahn is the default. DFS is the additional,
    not-wired-in-by-default strategy, run here to prove the sort is a swappable Ordering."""

    STRATEGIES = (Kahn(), DFS())

    def test_both_keep_caller_order_when_independent(self):
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=type(ordering).__name__):
                log = []
                asyncio.run(Reconciler((X(log), Y(log), Z(log)), ordering).converge())
                self.assertEqual(log, ["X", "Y", "Z"])

    def test_both_resolve_a_transitive_chain(self):
        # C -> B -> A handed in shuffled, both strategies resolve to A, B, C.
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=type(ordering).__name__):
                log = []
                asyncio.run(Reconciler((C(log), A(log), B(log)), ordering).converge())
                self.assertEqual(log, ["A", "B", "C"])

    def test_both_ignore_a_dep_outside_the_supplied_set(self):
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=type(ordering).__name__):
                log = []
                asyncio.run(Reconciler((B(log),), ordering).converge())
                self.assertEqual(log, ["B"])

    def test_both_keep_every_instance_of_a_class(self):
        # Two A instances collapse to one graph node, yet BOTH must come out, before B.
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=type(ordering).__name__):
                log = []
                asyncio.run(Reconciler((B(log), A(log), A(log)), ordering).converge())
                self.assertEqual(log, ["A", "A", "B"])

    def test_both_raise_valueerror_naming_the_cycle(self):
        class P(_RecStep):
            pass

        class Q(_RecStep):
            expects = (P,)

        P.expects = (Q,)  # close the cycle
        for ordering in self.STRATEGIES:
            with self.subTest(ordering=type(ordering).__name__):
                with self.assertRaises(ValueError) as ctx:
                    Reconciler((P([]), Q([])), ordering)
                self.assertIn("P", str(ctx.exception))
                self.assertIn("Q", str(ctx.exception))

    def test_default_ordering_is_kahn(self):
        # No explicit strategy -> Kahn. DFS is available but not the default.
        log = []
        asyncio.run(Reconciler((B(log), A(log))).converge())
        self.assertEqual(log, ["A", "B"])

    def test_base_chains_falls_back_to_one_chain_of_the_flat_order(self):
        # An Ordering that does not override chains() inherits the base fallback - ONE chain equal to its flat
        # order, the sentinel a pipelining dispatcher rejects since it runs nothing concurrently. Kahn overrides
        # levels() but not chains(), so it lands on the fallback here.
        chains = Kahn().chains(Graph((C([]), A([]), B([]))))
        [chain] = chains   # exactly one chain of everything
        self.assertEqual([type(step).__name__ for step in chain], ["A", "B", "C"])


class OrderingContractTests(unittest.TestCase):
    """The ordering contract proven over RANDOMIZED DAGs, for both strategies at once. The resolved order
    honours after=, Kahn's waves pass verify, flattening the waves equals the flat order, and
    a planted cycle raises ValueError. Seeded, so any failure reproduces byte-for-byte."""

    @staticmethod
    def __random_dag(randomness, size):
        # `size` fresh step classes with random after= edges pointing only BACKWARD (towards classes made
        # earlier), so the graph is a DAG by construction. Returned in a shuffled supplied order, so the
        # strategies never get to lean on definition order.
        classes = []
        for index in range(size):
            dependencies = tuple(randomness.sample(classes, randomness.randint(0, min(3, len(classes)))))
            classes.append(type(f"Random{index}", (Step,), {"expects": dependencies}))
        supplied = classes[:]
        randomness.shuffle(supplied)
        return supplied

    def test_both_strategies_honour_after_on_random_dags(self):
        randomness = random.Random(20260709)
        for _ in range(25):
            supplied = self.__random_dag(randomness, randomness.randint(2, 12))
            steps = tuple(cls() for cls in supplied)
            for ordering in (Kahn(), DFS()):
                with self.subTest(ordering=type(ordering).__name__, graph=[cls.__name__ for cls in supplied]):
                    resolved = ordering(Graph(steps))
                    self.assertEqual(len(resolved), len(steps))   # no step dropped, no step invented
                    position = {type(step): index for index, step in enumerate(resolved)}
                    for step in resolved:
                        for dependency in type(step).expects:
                            self.assertLess(position[dependency], position[type(step)])

    def test_levels_inverse_reverses_waves_and_their_contents(self):
        # The exact inverse of build order, owned by the Levels type. Both the wave order and the steps
        # within each wave flip, so a flat one-wave order inverts too (the DFS case).
        self.assertEqual(Levels((("a", "b"), ("c",))).inverse(), (("c",), ("b", "a")))
        self.assertEqual(Levels((("a", "b", "c"),)).inverse(), (("c", "b", "a"),))   # flat one-wave

    def test_kahn_waves_are_independent_and_flatten_to_the_flat_order(self):
        randomness = random.Random(20260710)
        for _ in range(25):
            supplied = self.__random_dag(randomness, randomness.randint(2, 12))
            steps = tuple(cls() for cls in supplied)
            kahn, graph = Kahn(), Graph(steps)
            levels = Levels(kahn.levels(graph))
            levels.verify(graph)   # raises on any mis-split - the fanning dispatcher's own guard
            flattened = tuple(step for level in levels for step in level)
            self.assertEqual(flattened, kahn(graph))

    def test_a_planted_cycle_raises_for_both_strategies(self):
        randomness = random.Random(20260711)
        for _ in range(10):
            supplied = self.__random_dag(randomness, randomness.randint(2, 8))
            first, second = randomness.sample(supplied, 2)
            first.expects = first.expects + (second,)    # close a two-class cycle on top of whatever edges
            second.expects = second.expects + (first,)   # the DAG already had - now unsatisfiable
            steps = tuple(cls() for cls in supplied)
            for ordering in (Kahn(), DFS()):
                with self.subTest(ordering=type(ordering).__name__):
                    with self.assertRaises(ValueError):
                        ordering(Graph(steps))
            with self.assertRaises(ValueError):
                Kahn().levels(Graph(steps))


class PriorityOrderingTests(unittest.TestCase):
    """Priority - the best-first Ordering. The ready frontier is a priority queue, so among independent
    steps the smallest key wins, a canonical order independent of how the steps were supplied."""

    def test_orders_independent_steps_by_key_default_class_name(self):
        # Supplied Z, Y, X - Kahn would keep that order, Priority emits the canonical X, Y, Z by class name.
        order = Priority()(Graph((Z([]), Y([]), X([]))))
        self.assertEqual([type(step).__name__ for step in order], ["X", "Y", "Z"])

    def test_after_dominates_the_key(self):
        # C -> B -> A. The key cannot pull a dependency ahead of the thing that depends on it.
        order = Priority()(Graph((C([]), A([]), B([]))))
        self.assertEqual([type(step).__name__ for step in order], ["A", "B", "C"])

    def test_injected_key_changes_the_order(self):
        # A reverse key (largest name first) flips the canonical order to Z, Y, X.
        order = Priority(key=lambda step: -ord(type(step).__name__[0]))(Graph((X([]), Y([]), Z([]))))
        self.assertEqual([type(step).__name__ for step in order], ["Z", "Y", "X"])

    def test_keeps_every_instance_of_a_class(self):
        order = Priority()(Graph((B([]), A([]), A([]))))
        self.assertEqual([type(step).__name__ for step in order], ["A", "A", "B"])

    def test_is_flat_only_and_rejected_by_a_fanning_executor(self):
        # Best-first is a total order, so it does not override levels() - a fanning dispatcher refuses it.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((A([]), B([])), Priority(), dispatcher=Parallel())
        self.assertIn("Kahn", str(ctx.exception))

    def test_raises_valueerror_naming_a_cycle(self):
        class P(_RecStep):
            pass

        class Q(_RecStep):
            expects = (P,)

        P.expects = (Q,)  # close the cycle
        with self.assertRaises(ValueError) as ctx:
            Priority()(Graph((P([]), Q([]))))
        self.assertIn("P", str(ctx.exception))
        self.assertIn("Q", str(ctx.exception))

    def test_converges_through_serial_in_priority_order(self):
        log = []
        asyncio.run(Reconciler((Z(log), X(log), Y(log)), Priority(), dispatcher=Serial()).converge())
        self.assertEqual(log, ["X", "Y", "Z"])


class TheShapeDeclaresItsRuleTests(unittest.TestCase):
    """A Partition shape without a placement rule has nothing for verify() to check against. It was an
    abstractmethod, which a tuple subclass never enforces, so the shape constructed and only failed at its
    first verify() - a whole run away from the class statement that got it wrong."""

    def test_a_shape_that_declares_no_placement_is_refused_at_class_definition(self):
        with self.assertRaises(ValueError) as ctx:
            class Ruleless(Partition):
                __slots__ = ()

        told = str(ctx.exception)
        self.assertIn("Ruleless", told)
        self.assertIn("declares no _placement", told)

class SlotsAreReadOffTheInstanceTests(unittest.TestCase):
    """A declaration slot belongs to the object that carries it, whichever strategy is walking.

    Three of the four strategies read the TYPE, so a caller who set expects on one instance got a
    different order depending on which Ordering was injected - Kahn honoured it, DFS and Components
    dropped it silently and nothing anywhere said so."""

    @staticmethod
    def _order(ordering):
        class First(Step):
            pass

        class Second(Step):
            pass

        second, first = Second(), First()
        second.expects = (First,)                        # on the INSTANCE, never on the class
        explanation = Reconciler((second, first), ordering).explain()
        return [name for group in explanation.groups for name in group]

    def test_every_strategy_honours_an_instance_level_declaration(self):
        for ordering in (Kahn(), DFS(), Priority(), Components()):
            with self.subTest(ordering=type(ordering).__name__):
                order = self._order(ordering)
                self.assertLess(order.index("First"), order.index("Second"))

    def test_the_explanation_reads_the_instance_too(self):
        # It was reading type(step).expects, so a run could be correctly ordered and drawn wrongly.
        class First(Step):
            pass

        class Second(Step):
            pass

        second, first = Second(), First()
        second.expects = (First,)
        edges = dict(Reconciler((second, first)).explain().edges)
        self.assertEqual(edges["Second"], ("First",))


class TheSeatingCoversTheRunTests(unittest.TestCase):
    """The guard's other half. It used to ask only "is each dependency placed correctly RELATIVE to its
    dependent", which quietly excused a dependency that was placed nowhere at all - so an Ordering that
    dropped a step or seated one twice walked straight past a guard whose whole job is the seating."""

    def test_a_seating_that_drops_a_step_is_refused(self):
        a, b = A([]), B([])         # B expects A
        graph = Graph((a, b))
        with self.assertRaises(Unresolvable) as ctx:
            Levels(((b,),)).verify(graph)
        told = str(ctx.exception)
        self.assertIn("out of the seating entirely", told)
        self.assertIn("A", told)

    def test_a_seating_that_runs_one_step_twice_is_refused(self):
        a, b = A([]), B([])
        graph = Graph((a, b))
        with self.assertRaises(Unresolvable) as ctx:
            Levels(((a,), (a, b))).verify(graph)
        self.assertIn("more than one group", str(ctx.exception))

    def test_a_seating_that_covers_the_run_exactly_passes(self):
        a, b = A([]), B([])
        graph = Graph((a, b))
        Levels(((a,), (b,))).verify(graph)   # no raise
