"""The refusal family - three unrelated bases, each for a different audience, every one still a built-in.

The kernel raised bare ValueError and TypeError from these sites for its whole life. The names are
ADDITIVE - they let a caller who wants to tell a cycle from a bad backoff do it by type instead of by
matching message text, so they cost nothing to adopt because every existing `except ValueError` keeps
working. These tests pin both halves. The new dispatch and the old catch."""
import unittest

from cabaxiom import (
    Coverage,
    Cycle,
    DataFlow,
    Fixed,
    Graph,
    Identity,
    Kahn,
    Malformed,
    Misconfigured,
    Pairing,
    Presence,
    Reconciler,
    Seating,
    Step,
    Supervised,
    Unresolvable,
)
from cabaxiom.core.plan import Chains, Components, Ordering, Walk
from cabaxiom.core.run import RunMode
from cabaxiom.core.run.dispatcher import _Gather
from cabaxiom.laboratory import ChaosDispatcher, Sabotage
from support import A, B


class TheBasesAreSegregatedTests(unittest.IsolatedAsyncioTestCase):
    """Three bases, no shared root. A caller who wants to hear about one has no business being handed the
    other two, which is the whole reason there is no single `Refusal` above them."""

    def test_the_three_bases_share_no_root_but_the_builtins(self):
        self.assertFalse(issubclass(Misconfigured, Unresolvable))   # a bad knob is not a bad declaration
        self.assertFalse(issubclass(Unresolvable, Misconfigured))
        self.assertFalse(issubclass(Malformed, Unresolvable))       # a wrong shape is not a wrong meaning
        self.assertFalse(issubclass(Unresolvable, Malformed))

    def test_every_refusal_is_still_the_builtin_it_always_was(self):
        # THE ADOPTION COST, which is zero. Code written against the old bare raises keeps catching.
        for refusal in (Unresolvable, Cycle, Coverage, Seating, Pairing, Presence, DataFlow, Identity):
            with self.subTest(refusal=refusal.__name__):
                self.assertTrue(issubclass(refusal, ValueError))
        self.assertTrue(issubclass(Misconfigured, ValueError))
        self.assertTrue(issubclass(Malformed, TypeError))

    def test_the_base_catches_every_leaf_under_it(self):
        for leaf in (Cycle, Coverage, Seating, Pairing, Presence, DataFlow, Identity):
            with self.subTest(leaf=leaf.__name__):
                self.assertTrue(issubclass(leaf, Unresolvable))


class TheRefusalsAreRaisedByTypeTests(unittest.IsolatedAsyncioTestCase):
    """Each guard mints the refusal that names its own fault, so a caller can dispatch instead of grepping
    the message. Every case below is reached through the public surface."""

    def test_a_dependency_loop_raises_a_cycle(self):
        class Left(Step):
            pass

        class Right(Step):
            expects = (Left,)

        Left.expects = (Right,)   # close the loop
        with self.assertRaises(Cycle):
            Reconciler((Left(), Right()))

    def test_an_absent_hard_edge_raises_presence(self):
        class Network(Step):
            pass

        class Api(Step):
            requires = (Network,)

        with self.assertRaises(Presence):
            Reconciler((Api(),))

    def test_a_key_no_prerequisite_produces_raises_dataflow(self):
        class Reader(Step):
            consumes = frozenset({"dsn"})

        with self.assertRaises(DataFlow):
            Reconciler((Reader(),))

    def test_a_worker_that_cannot_walk_the_shape_raises_pairing(self):
        with self.assertRaises(Pairing):
            Reconciler((A([]), B([])), Components(), mode=RunMode(Chains(), _Gather()))

    def test_a_decorated_mismatch_raises_pairing_too(self):
        # The guard asks the PAIR, so wrapping cannot launder the fault - and the type says so.
        with self.assertRaises(Pairing):
            Reconciler((A([]), B([])), Components(),
                       mode=ChaosDispatcher(RunMode(Chains(), _Gather()), Sabotage()))

    def test_the_refusal_reads_as_a_sentence_for_every_shape_it_can_refuse(self):
        # The wording contract, pinned on the LIVE message. An Overlap value is a VERB'S OBJECT, which this
        # refusal spends one in a second frame, where it once shipped as "an overlap the groups" - correct
        # and unreadable. Only a WITHIN worker reaches here at all, since NEITHER and EDGES short-circuit
        # the guard, so these two shapes are every shape whose overlap this sentence can ever speak.
        for shape, reads in ((Chains(), "it overlaps the groups"), (Walk(), "it overlaps nothing")):
            with self.subTest(shape=shape.__class__.__name__):
                with self.assertRaises(Pairing) as refused:
                    Reconciler((A([]), B([])), Components(), mode=RunMode(shape, _Gather()))
                told = str(refused.exception)
                self.assertIn(reads, told)
                self.assertNotIn("an overlap", told)

    def test_the_pairing_refusal_names_both_halves_of_the_mismatch(self):
        with self.assertRaises(Pairing) as refused:
            Reconciler((A([]), B([])), Components(), mode=RunMode(Chains(), _Gather()))
        told = str(refused.exception)
        self.assertIn("runs the steps inside one group at the same time", told)   # the worker's half
        self.assertIn("it overlaps the groups", told)                             # the shape's half
        self.assertNotIn("an overlap", told)

    def test_an_ordering_that_drops_a_step_raises_coverage(self):
        class Drops(Ordering):
            def __call__(self, graph):
                return graph.steps[:-1]

            def waves(self, graph):
                return (graph.steps[:-1],)

        with self.assertRaises(Coverage):
            Reconciler((A([]), B([])), Drops())

    def test_a_wave_holding_a_dependency_beside_its_dependent_raises_seating(self):
        class OneBigWave(Ordering):
            def __call__(self, graph):
                return graph.steps

            def waves(self, graph):
                return (graph.steps,)   # B sits beside the A it depends on

        with self.assertRaises(Seating):
            Reconciler((A([]), B([])), OneBigWave())

    def test_the_same_step_handed_twice_raises_identity(self):
        only = A([])
        with self.assertRaises(Identity):
            Graph((only, only))

    def test_a_nonsense_axis_argument_raises_misconfigured(self):
        with self.assertRaises(Misconfigured):
            Fixed(-1.0)
        with self.assertRaises(Misconfigured):
            Supervised(poll=0)

    def test_a_declaration_of_the_wrong_shape_raises_malformed(self):
        with self.assertRaises(Malformed):
            class Commaless(Step):
                expects = (A)          # the forgotten trailing comma - a class, not a one-tuple

        with self.assertRaises(Malformed):
            class Stringy(Step):
                provides = "database"   # a string iterates into single characters, the silent one


class TheSegregationBuysSomethingTests(unittest.IsolatedAsyncioTestCase):
    """What the split is FOR: a caller can wrap one concern without swallowing the others."""

    def test_catching_unresolvable_leaves_a_bad_knob_alone(self):
        # A caller who wants to report "your declaration cannot run" must not also swallow "you passed a
        # negative delay", which is their own bug in a different place entirely.
        with self.assertRaises(Misconfigured):
            try:
                Fixed(-1.0)
            except Unresolvable:                      # pragma: no cover - the point is that it does not catch
                self.fail("a misconfigured axis was caught as an unresolvable declaration")

    def test_catching_unresolvable_catches_every_declaration_fault_at_once(self):
        class Api(Step):
            requires = (B,)

        for build in (lambda: Reconciler((Api(),)), lambda: Reconciler((A([]), B([])), Kahn(), mode=RunMode(Chains(), _Gather()))):
            with self.subTest(build=build):
                with self.assertRaises(Unresolvable):
                    build()
