"""Contention - the declaration that is NOT an edge.

Every other slot on a Step orders two steps - one runs, then the other. `contends` orders nothing. It says
two steps may never be IN FLIGHT together, in either order, with any gap. Buying that with `expects` buys it
by lying, so the lie is read as truth by everything downstream, so these tests check the seating AND check
that the derivation stayed honest.
"""
import threading
import time
import unittest

from cabaxiom import Assessment, DriftItem, Parallel, Reconciler, Step, ThreadDispatcher
from cabaxiom.core.plan import Components, Ordering, Seat
from cabaxiom.core.record import Reading, Statement


class _Timed(Step):
    """Records the peak number of instances in flight at once, across every subclass."""

    live = 0
    peak = 0
    lock = threading.Lock()

    @classmethod
    def reset(cls) -> None:
        _Timed.live = _Timed.peak = 0

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem(self.__class__.__name__, "pending")]), {}

    def apply(self, inputs):
        with _Timed.lock:
            _Timed.live += 1
            _Timed.peak = max(_Timed.peak, _Timed.live)
        time.sleep(0.02)
        with _Timed.lock:
            _Timed.live -= 1
        return None, {}


class Migrate(_Timed):
    contends = frozenset({"database"})


class Backfill(_Timed):
    contends = frozenset({"database"})


class Report(_Timed):
    contends = frozenset({"database"})


class Free(Step):
    def assess(self, inputs):
        return Assessment(deviation=[DriftItem("Free", "pending")]), {}


def _shaped(arranger, overlap):
    # A dispatcher composing a non-wave arranger, so the contention seating under Chains and Walk can be
    # read off explain(). The verbs are stubs - these tests only arrange and explain, never converge - so
    # the shape and its guard, both the arranger's, are reachable without a shipped chain/walk dispatcher.
    from cabaxiom.core.run import Dispatcher, RunMode

    class _Shaped(Dispatcher):
        overlaps = overlap

        async def execute(self, groups, graph, do, cancellation, observer):
            return Statement((), ())

        async def probe(self, groups, graph, read, cancellation, observer):
            return Reading(())

    return lambda: RunMode(arranger(), _Shaped())

    return _Shaped


class DeclarationTests(unittest.IsolatedAsyncioTestCase):
    def test_a_step_contends_for_nothing_by_default(self):
        self.assertEqual(Step.contends, frozenset())

    def test_a_bare_string_is_refused_where_it_is_written(self):
        with self.assertRaises(TypeError) as refused:
            class Careless(Step):
                contends = "database"
        spoken = str(refused.exception)
        self.assertIn("must be a set of resource labels", spoken)
        self.assertIn("frozenset({'database'})", spoken)


class SeatingTests(unittest.IsolatedAsyncioTestCase):
    """Every shipped shape honours it, each moving the way its own rule says it must."""

    def setUp(self):
        _Timed.reset()

    async def _run(self, executor, ordering=None):
        steps = (Migrate(), Backfill(), Report(), Free())
        kernel = Reconciler(steps, ordering, mode=executor) if ordering else Reconciler(steps, mode=executor)
        groups = kernel.explain().groups
        await kernel.converge()
        return groups, kernel

    async def test_waves_push_contenders_into_different_waves(self):
        # ThreadDispatcher runs the blocking applies concurrently, so the peak is a real measurement. The
        # contention seating keeps rivals in different waves and never lets two run at once.
        groups, _ = await self._run(ThreadDispatcher())
        for wave in groups:
            with self.subTest(wave=wave):
                self.assertLessEqual(len([one for one in wave if one != "Free"]), 1)
        self.assertEqual(_Timed.peak, 1)

    def test_chains_pull_contenders_into_one_chain(self):
        # A chain is serial inside and chains overlap, so the move is the mirror image - merge, not split.
        # Read off a Chains-composing dispatcher's explain, since no shipped dispatcher runs chains.
        from cabaxiom.core.plan import Chains, Overlap

        steps = (Migrate(), Backfill(), Report(), Free())
        groups = Reconciler(steps, Components(), mode=_shaped(Chains, Overlap.ACROSS)()).explain().groups
        holding = next(chain for chain in groups if "Migrate" in chain)
        for rival in ("Backfill", "Report"):
            with self.subTest(rival=rival):
                self.assertIn(rival, holding)

    def test_a_serial_walk_needs_no_moving_at_all(self):
        # A Walk runs everything in one serial group, so contention is already satisfied and seats nothing.
        from cabaxiom.core.plan import Overlap, Walk

        steps = (Migrate(), Backfill(), Report(), Free())
        groups = Reconciler(steps, mode=_shaped(Walk, Overlap.NEITHER)()).explain().groups
        self.assertEqual(len(groups), 1)

    async def test_an_uncontended_step_is_not_dragged_along(self):
        groups, _ = await self._run(ThreadDispatcher())
        self.assertIn("Free", groups[0], "a step that contends for nothing keeps its earliest wave")

    async def test_no_edge_is_invented(self):
        # THE WHOLE POINT. Buying exclusion with `expects` would put an arrow here, so foresee(), Enclosure
        # and every drawing read arrows as truth.
        _, kernel = await self._run(ThreadDispatcher())
        self.assertEqual(kernel.explain().arrows, ())

    async def test_contention_does_not_disturb_a_real_dependency(self):
        class First(_Timed):
            contends = frozenset({"disk"})

        class Second(_Timed):
            expects = (First,)

        class Third(_Timed):
            contends = frozenset({"disk"})

        kernel = Reconciler((Third(), Second(), First()), mode=Parallel())
        groups = kernel.explain().groups
        self.assertLess(groups.index(next(g for g in groups if "First" in g)),
                        groups.index(next(g for g in groups if "Second" in g)))
        await kernel.converge()
        self.assertEqual(_Timed.peak, 1)


class GuardTests(unittest.IsolatedAsyncioTestCase):
    """The second guard. A shape that seats rivals together is refused, however it was built."""

    def test_a_shape_that_seats_rivals_together_is_refused(self):
        from cabaxiom.core.plan import Arranger, Overlap, WavesPartition

        class Careless(Arranger):
            def shape(self, ordering, graph):
                return WavesPartition((tuple(graph.steps),))   # everything in one wave, rivals included

        with self.assertRaises(ValueError) as refused:
            Reconciler((Migrate(), Backfill()), mode=_shaped(Careless, Overlap.WITHIN)())
        spoken = str(refused.exception)
        self.assertIn("both contend for 'database'", spoken)
        self.assertIn("run at the same time", spoken)
        self.assertIn("not an edge", spoken)


class TogetherTests(unittest.IsolatedAsyncioTestCase):
    """together() is derived from the placement rule, never declared beside it."""

    def test_each_shape_answers_from_its_own_rule(self):
        from cabaxiom.core.plan import ChainsPartition, WalkPartition, WavesPartition

        same, apart = (Seat(0, 0), Seat(0, 1)), (Seat(0, 0), Seat(1, 0))
        for shape, inside, across in ((WavesPartition, True, False),
                                      (ChainsPartition, False, True),
                                      (WalkPartition, False, False)):
            with self.subTest(shape=shape.__name__):
                built = shape(())
                self.assertEqual(built.together(*same), inside)
                self.assertEqual(built.together(*apart), across)


class AlreadyApartTests(unittest.IsolatedAsyncioTestCase):
    def test_rivals_a_real_edge_already_separated_are_left_alone(self):
        # Components puts a dependency and its dependent in ONE chain, which is already serial, so the merge
        # has nothing to do for this pair. The seating must not churn just because the labels matched. Read
        # off a Chains-composing dispatcher's explain, since no shipped dispatcher runs chains.
        from cabaxiom.core.plan import Chains, Overlap

        class Lock(_Timed):
            contends = frozenset({"tape"})

        class Rewind(_Timed):
            expects = (Lock,)
            contends = frozenset({"tape"})

        groups = Reconciler((Rewind(), Lock()), Components(), mode=_shaped(Chains, Overlap.ACROSS)()).explain().groups
        self.assertEqual(len(groups), 1, "one chain already holds both, so nothing merges")


class ExplanationTests(unittest.IsolatedAsyncioTestCase):
    """The seating is visible, so the reason for it has to be too.

    Contention leaves no arrow - that is the property it exists for - so without this read a run says two
    steps landed in different waves and offers nothing about why.
    """

    def _explained(self):
        return Reconciler((Migrate(), Backfill(), Report(), Free()), mode=Parallel()).explain()

    def test_the_declaration_rides_beside_provides(self):
        declared = self._explained().declared["contends"]
        self.assertEqual(dict(declared)["Migrate"], ("database",))
        self.assertNotIn("Free", dict(declared), "a step that contends for nothing is left out")

    def test_the_constraint_is_keyed_by_resource(self):
        held = dict(self._explained().contention)
        self.assertIn("database", held)
        for rival in ("Migrate", "Backfill", "Report"):
            with self.subTest(rival=rival):
                self.assertIn(rival, held["database"])

    def test_a_resource_only_one_step_names_constrains_nothing_and_is_omitted(self):
        class Alone(Step):
            contends = frozenset({"nobody-else"})

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("Alone", "pending")]), {}

        explained = Reconciler((Alone(), Free()), mode=Parallel()).explain()
        self.assertEqual(explained.contention, ())
        self.assertEqual(dict(explained.declared["contends"])["Alone"], ("nobody-else",))

    def test_it_explains_a_seating_the_groups_alone_cannot(self):
        # Two resources, three steps and one step caught by both - the wave it lands in is not guessable
        # from the groups, so the contention read is what makes it readable.
        class Tape(Step):
            contends = frozenset({"tape"})

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("Tape", "pending")]), {}

        class Both(Step):
            contends = frozenset({"tape", "database"})

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("Both", "pending")]), {}

        explained = Reconciler((Migrate(), Tape(), Both()), mode=Parallel()).explain()
        held = dict(explained.contention)
        self.assertEqual(set(held), {"tape", "database"})
        alone = next(group for group in explained.groups if "Both" in group)
        self.assertEqual(alone, ("Both",), "the step caught by both resources gets a wave of its own")

    def test_no_arrow_is_added_by_the_read(self):
        self.assertEqual(self._explained().arrows, ())


class DrawingTests(unittest.IsolatedAsyncioTestCase):
    """The drawing tells the two kinds apart, because they are not the same kind of claim.

    An arrow says one step runs before another. Contention says neither may run beside the other, in any
    order. Rendering the second with an arrowhead would put the false dependency back into the picture
    after the derivation was so careful not to carry it.
    """

    def _drawn(self):
        class Held(_Timed):
            contends = frozenset({"database"})

        class AlsoHeld(_Timed):
            expects = (Held,)
            contends = frozenset({"database"})

        return Reconciler((Held(), AlsoHeld()), mode=Parallel()).explain()

    def test_mermaid_draws_the_dependency_with_a_head_and_the_contention_without(self):
        drawn = self._drawn().mermaid()
        self.assertIn("-->|expects|", drawn)
        self.assertIn('-.-|"database"|', drawn)

    def test_a_resource_name_holding_syntax_stays_a_label_in_both_languages(self):
        # A slot is an EdgeKind name and refused unless it is an identifier. A contended resource is whatever
        # string the domain wrote and it was pasted into the Mermaid edge raw. A pipe is what ENDS an edge
        # label there, so a resource built from data closed its own label and spilled the rest of the line
        # into the drawing as syntax. Dot escaped it from the first day.
        class One(_Timed):
            contends = frozenset({'pool|x"y'})

        class Two(_Timed):
            expects = (One,)
            contends = frozenset({'pool|x"y'})

        explanation = Reconciler((One(), Two())).explain()
        drawn = next(line for line in explanation.mermaid().splitlines() if "pool" in line)
        self.assertEqual(drawn.count("|"), 3, f"the label has to close where the kernel closes it, got {drawn!r}")
        self.assertIn("#quot;", drawn, "Mermaid reads no backslash escape inside a label, only the entity")
        self.assertIn('\\"', next(line for line in explanation.dot().splitlines() if "pool" in line))

    def test_dot_draws_the_contention_undirected_and_out_of_the_ranking(self):
        drawn = next(line for line in self._drawn().dot().splitlines() if "database" in line)
        self.assertIn("dir=none", drawn)
        self.assertIn("constraint=false", drawn, "the layout is the run's order, so this says nothing about order")

    def test_every_pair_is_drawn_rather_than_a_chain(self):
        # Three rivals exclude each other three ways. A chain of two links would claim the ends are free
        # of one another, which is the convenient half-truth this whole plane refuses.
        drawn = Reconciler((Migrate(), Backfill(), Report()), mode=Parallel()).explain().mermaid()
        self.assertEqual(drawn.count('-.-|"database"|'), 3)

    def test_an_uncontended_run_draws_no_link_at_all(self):
        drawn = Reconciler((Free(),), mode=Parallel()).explain().mermaid()
        self.assertNotIn("-.-", drawn)

    def test_a_format_written_before_this_release_still_renders(self):
        # THE NON-BREAKING GUARANTEE. contended() is the one seam on this axis with a default, so a Diagram
        # that never heard of contention keeps working and simply says nothing about it.
        from cabaxiom.core.record import Diagram

        class Older(Diagram):
            def opening(self):
                return ("start",)

            def grouped(self, title, index, members):
                return tuple(f"{title}:{label}" for _, label, _ in members)

            def arrow(self, prerequisite, dependent, slot, tone):
                return f"{prerequisite}->{dependent}"

            def closing(self, used):
                return ("end",)

        drawn = Older().render(self._drawn())
        self.assertTrue(drawn.startswith("start"))
        self.assertNotIn("database", drawn, "a format that says nothing draws nothing and tells no lie")


class ReseatGuardTests(unittest.TestCase):
    """The re-seat trusts the Ordering's topology and says so. A backwards yield is refused by name
    before any seating is computed over it."""

    def test_a_backwards_ordering_is_refused_before_the_reseat_trusts_it(self):
        # The re-seat walks the groups in the order the Ordering resolved and seats each step past its
        # dependencies - which is only sound if the dependencies come FIRST. An Ordering yielding the
        # dependent ahead of its prerequisite is refused naming both, instead of being seated into a lie.
        class Dependency(Step):
            contends = frozenset({"db"})

        class Dependent(Step):
            expects = (Dependency,)
            contends = frozenset({"db"})

        class Backwards(Ordering):
            def flat(self, graph):
                return graph.steps

            def waves(self, graph):
                return tuple((step,) for step in graph.steps)   # supplied order, verbatim - backwards here

        with self.assertRaises(ValueError) as refused:
            Reconciler((Dependent(), Dependency()), Backwards(), mode=Parallel())
        spoken = str(refused.exception)
        self.assertIn("Dependent depends on Dependency, yet the Ordering yielded it first", spoken)
        self.assertIn("valid topological order", spoken)
