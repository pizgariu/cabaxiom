"""contends - mutual exclusion, which is a seating rule and never an ordering."""
import unittest

from cabaxiom import Components, Kahn, Step, Unresolvable
from cabaxiom.graph import Graph
from cabaxiom.partition import Chains, Levels
from cabaxiom.vocabulary import Vocabulary


class ContentionIsNotAnEdgeTests(unittest.TestCase):

    def test_a_step_declares_what_it_contends_for(self):
        class Writer(Step):
            contends = frozenset({"disk"})

        self.assertEqual(Writer().contends, frozenset({"disk"}))

    def test_contention_is_absent_from_the_edge_language(self):
        # The point of the slot. An edge says which of two steps comes first. Contention says neither may
        # run beside the other and does not care which goes first, so a row in this table would force an
        # order the domain never asked for and make the derivation assert something untrue.
        self.assertNotIn("contends", [kind.slot for kind in Vocabulary.shipped()])

    def test_it_is_a_declaration_slot_a_caller_may_still_set(self):
        # Like the edge slots, it is configuration the run reads once before anything executes.
        class Writer(Step):
            pass

        step = Writer()
        step.contends = frozenset({"disk"})
        self.assertEqual(step.contends, frozenset({"disk"}))

    def test_two_steps_may_contend_for_the_same_thing_without_depending_on_each_other(self):
        class Left(Step):
            contends = frozenset({"disk"})

        class Right(Step):
            contends = frozenset({"disk"})

        self.assertEqual(Left().expects, ())
        self.assertEqual(Right().expects, ())
        self.assertTrue(Left().contends & Right().contends)


class Migrate(Step):
    contends = frozenset({"db"})

    async def assess(self):
        return self.verified()


class Reindex(Step):
    contends = frozenset({"db"})

    async def assess(self):
        return self.verified()


class Vacuum(Step):
    contends = frozenset({"db", "disk"})

    async def assess(self):
        return self.verified()


class Cdn(Step):
    async def assess(self):
        return self.verified()


class ContentionIsASeatingRuleTests(unittest.TestCase):
    """`contends` is the one declaration in the family that is not an edge. An edge says which of two steps
    goes first, contention says neither may run beside the other and takes no view on the order - so it is
    read where the run is SEATED, where each shape keeps it a different way."""

    def test_a_wave_is_split_so_two_rivals_never_share_it(self):
        migrate, reindex = Migrate(), Reindex()
        waves = Kahn().levels(Graph((migrate, reindex)))
        self.assertEqual(waves, ((migrate,), (reindex,)))

    def test_a_bystander_does_not_pay_for_someone_else_s_contention(self):
        # The split is per-label, not per-wave. Cdn contends for nothing, so it keeps the first wave.
        migrate, reindex, cdn = Migrate(), Reindex(), Cdn()
        first, second = Kahn().levels(Graph((migrate, reindex, cdn)))
        self.assertEqual(first, (migrate, cdn))
        self.assertEqual(second, (reindex,))

    def test_a_step_contending_on_two_labels_is_kept_from_both_rivals(self):
        migrate, vacuum = Migrate(), Vacuum()
        waves = Kahn().levels(Graph((migrate, vacuum)))
        self.assertEqual(waves, ((migrate,), (vacuum,)))

    def test_rivals_land_in_one_chain_where_the_chain_runs_them_in_series(self):
        # The dual. A chain shape runs whole chains beside each other, so the arrangement that keeps two
        # rivals apart is the SAME chain - the opposite of what the wave shape needs.
        migrate, reindex, cdn = Migrate(), Reindex(), Cdn()
        chains = Components().chains(Graph((migrate, reindex, cdn)))
        self.assertEqual(chains, ((migrate, reindex), (cdn,)))

    def test_a_seating_that_runs_two_rivals_together_is_refused(self):
        migrate, reindex = Migrate(), Reindex()
        graph = Graph((migrate, reindex))
        with self.assertRaises(Unresolvable) as ctx:
            Levels(((migrate, reindex),)).verify(graph)     # one wave, both rivals in it
        told = str(ctx.exception)
        self.assertIn("contend for 'db'", told)
        self.assertIn("at the same time", told)

    def test_the_same_seating_is_read_the_other_way_round_by_the_chain_shape(self):
        migrate, reindex = Migrate(), Reindex()
        graph = Graph((migrate, reindex))
        Chains(((migrate, reindex),)).verify(graph)          # one chain is exactly right here
        with self.assertRaises(Unresolvable):
            Chains(((migrate,), (reindex,))).verify(graph)   # two chains run concurrently

    def test_one_step_alone_on_a_label_has_no_rival_and_costs_nothing(self):
        migrate, cdn = Migrate(), Cdn()
        self.assertEqual(Kahn().levels(Graph((migrate, cdn))), ((migrate, cdn),))

    def test_contention_the_dependencies_already_settle_costs_no_extra_wave(self):
        # Reindex expects Migrate, so the edges alone already put them in different waves. The split has
        # nothing left to do, so paying a barrier for it anyway would be a wave the run does not need.
        class Ordered(Reindex):
            expects = (Migrate,)

        migrate, reindex = Migrate(), Ordered()
        self.assertEqual(Kahn().levels(Graph((migrate, reindex))), ((migrate,), (reindex,)))
