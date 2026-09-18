"""The Graph - one derivation, read by everything, over one membership."""
import unittest

from cabaxiom import Identity, Malformed, Presence, Step
from cabaxiom.graph import Graph
from cabaxiom.vocabulary import BY_CLASS, EdgeKind, Vocabulary


class Db(Step):
    provides = frozenset({"database"})


class Api(Step):
    wants = ("database",)


class Web(Step):
    expects = (Api,)


class OneDerivationTests(unittest.TestCase):

    def test_a_class_edge_and_a_capability_edge_are_the_same_kind_of_answer(self):
        # The point of the table. Two different addressings, one derivation, so dependencies() cannot
        # tell you which slot an edge came from because that is not its question.
        db, api, web = Db(), Api(), Web()
        graph = Graph((web, api, db))
        self.assertEqual(graph.dependencies(api), (db,))
        self.assertEqual(graph.dependencies(web), (api,))

    def test_a_capability_fans_in_across_every_provider(self):
        class Spare(Step):
            provides = frozenset({"database"})

        db, spare, api = Db(), Spare(), Api()
        self.assertEqual(set(Graph((api, db, spare)).dependencies(api)), {db, spare})

    def test_an_edge_is_deduplicated_and_keeps_first_seen_order(self):
        class Twice(Step):
            provides = frozenset({"database"})
            pass

        db = Db()
        both = Api()
        both.expects = (Db,)                      # the same target, named twice by two different slots
        self.assertEqual(Graph((both, db)).dependencies(both), (db,))

    def test_the_membership_is_published_beside_the_derivation(self):
        # So a consumer cannot be handed a graph of one world beside the steps of another.
        db, api = Db(), Api()
        self.assertEqual(Graph((api, db)).steps, (api, db))


class TheInversionTests(unittest.TestCase):

    def test_dependents_is_the_other_direction_of_the_same_edges(self):
        db, api = Db(), Api()
        graph = Graph((api, db))
        self.assertEqual(graph.dependents(db), (api,))
        self.assertEqual(graph.dependents(api), ())

    def test_closure_keeps_what_a_targeted_run_must_not_drop(self):
        db, api, web = Db(), Api(), Web()
        graph = Graph((web, api, db))
        self.assertEqual(graph.closure([web]), frozenset({web, api, db}))

    def test_fallout_is_what_one_failure_would_cost(self):
        db, api, web = Db(), Api(), Web()
        graph = Graph((web, api, db))
        self.assertEqual(graph.fallout([db]), frozenset({db, api, web}))

    def test_both_walks_survive_a_seed_that_reaches_nothing(self):
        alone = Db()
        graph = Graph((alone,))
        self.assertEqual(graph.closure([alone]), frozenset({alone}))
        self.assertEqual(graph.fallout([alone]), frozenset({alone}))


class TheComponentsTests(unittest.TestCase):

    def test_unconnected_steps_split_into_separate_components(self):
        class Alone(Step):
            pass

        db, api, alone = Db(), Api(), Alone()
        components = Graph((db, api, alone)).components()
        self.assertEqual([len(group) for group in components], [2, 1])

    def test_a_component_split_reads_the_derived_edges_and_not_one_slot(self):
        # A capability edge connects two steps as surely as a class edge does, so a split that walked
        # only `expects` would call these two components.
        db, api = Db(), Api()
        self.assertEqual(len(Graph((db, api)).components()), 1)


class TheHardPresenceRuleTests(unittest.TestCase):

    def test_a_hard_edge_that_matched_nothing_is_refused(self):
        class Insists(Step):
            demands = ("database",)

        with self.assertRaises(Presence) as refused:
            Graph((Insists(),)).demand()
        self.assertIn("database", str(refused.exception))

    def test_the_refusal_names_the_soft_companion_as_the_alternative(self):
        class Insists(Step):
            demands = ("database",)

        with self.assertRaises(Presence) as refused:
            Graph((Insists(),)).demand()
        self.assertIn("wants", str(refused.exception))

    def test_a_soft_edge_that_matched_nothing_is_a_shrug(self):
        Graph((Api(),)).demand()          # wants a database, there is none, which is allowed

    def test_hardness_is_read_off_the_row_and_not_off_a_list_of_names(self):
        # A kind grown today answers the hard-presence question correctly today.
        grown = Vocabulary.shipped().grown(
            *EdgeKind.paired("follows", "insists_on", BY_CLASS))

        class Insists(Step):
            insists_on = (Db,)

        with self.assertRaises(Presence):
            Graph((Insists(),), grown).demand()


class TheShapeGuardTests(unittest.TestCase):

    def test_the_forgotten_comma_is_caught_by_name(self):
        class Careless(Step):
            expects = Db          # the class, not a one-tuple

        with self.assertRaises(Malformed) as refused:
            Graph((Careless(),))
        self.assertIn("trailing comma", str(refused.exception))

    def test_a_wrongly_addressed_entry_is_told_where_it_belongs(self):
        class Confused(Step):
            expects = ("database",)      # a label in a by-class slot

        with self.assertRaises(Malformed) as refused:
            Graph((Confused(),))
        self.assertIn("capability label", str(refused.exception))

    def test_a_bare_string_in_a_label_set_is_refused(self):
        # It would iterate into single characters, which is the silent kind of wrong.
        class Careless(Step):
            provides = "database"

        with self.assertRaises(Malformed):
            Graph((Careless(),))


class TheIdentityGateTests(unittest.TestCase):

    def test_the_same_instance_handed_in_twice_is_refused(self):
        db = Db()
        with self.assertRaises(Identity) as refused:
            Graph((db, db))
        self.assertIn("twice", str(refused.exception))


class TheReversedKindTests(unittest.TestCase):
    """`prepares` points the other way, because a domain often cannot edit the class it must run before."""

    def test_a_reversed_edge_makes_the_declaring_step_the_prerequisite(self):
        class Third(Step):
            pass

        class Bootstrap(Step):
            prepares = (Third,)

        boot, third = Bootstrap(), Third()
        graph = Graph((third, boot))
        self.assertEqual(graph.dependencies(third), (boot,))    # Third needs Bootstrap
        self.assertEqual(graph.dependencies(boot), ())          # and Bootstrap needs nothing

    def test_the_hard_flavour_still_demands_the_match_is_present(self):
        class Absent(Step):
            pass

        class Bootstrap(Step):
            mandates = (Absent,)

        with self.assertRaises(Presence):
            Graph((Bootstrap(),)).demand()


class TheInstanceKindTests(unittest.TestCase):
    """`uses` names ONE step where `expects` names a kind and reaches every instance of it."""

    def test_an_instance_edge_reaches_exactly_the_named_one(self):
        class Store(Step):
            pass

        class Reader(Step):
            pass

        wanted, other, reader = Store(), Store(), Reader()
        reader.uses = (wanted,)
        graph = Graph((reader, wanted, other))
        self.assertEqual(graph.dependencies(reader), (wanted,))

    def test_a_class_edge_beside_it_reaches_both(self):
        # The distinction the two kinds exist for, in one assertion.
        class Store(Step):
            pass

        class Reader(Step):
            expects = (Store,)

        first, second, reader = Store(), Store(), Reader()
        self.assertEqual(set(Graph((reader, first, second)).dependencies(reader)), {first, second})

    def test_a_named_instance_outside_the_run_is_absent_however_alike(self):
        class Store(Step):
            pass

        class Reader(Step):
            pass

        outside, inside, reader = Store(), Store(), Reader()
        reader.uses = (outside,)
        self.assertEqual(Graph((reader, inside)).dependencies(reader), ())


class TheRosterIndexTests(unittest.TestCase):
    """Naming an instance costs a lookup, not a scan of the whole run."""

    @staticmethod
    def _chain(size):
        steps = []
        for index in range(size):
            step = type(f"S{index}", (Step,), {})()
            if steps:
                step.uses = (steps[-1],)
            steps.append(step)
        return steps

    def test_the_derivation_scales_linearly_in_the_number_of_steps(self):
        # Asserted as a RATIO rather than as a wall-clock number, so it says something true on a slow
        # machine and on a fast one. Before the index this was quadratic - a four-thousand step chain took
        # 0.284 seconds and rose by three and a half on every doubling.
        import time

        timings = []
        for size in (1000, 2000, 4000):
            steps = self._chain(size)
            # The best of five. A loaded machine adds noise on top of the cost and never takes any away,
            # so the minimum is the one reading it cannot inflate.
            fastest = float("inf")
            for _ in range(5):
                start = time.perf_counter()
                Graph(steps)
                fastest = min(fastest, time.perf_counter() - start)
            timings.append(fastest)
        # doubling the work roughly doubles the time. Three is generous headroom for a loaded machine and
        # still nowhere near the four a quadratic would show.
        self.assertLess(timings[2] / timings[1], 3.0)
        self.assertLess(timings[1] / timings[0], 3.0)

    def test_membership_is_answered_by_identity_and_in_constant_time(self):
        from cabaxiom.vocabulary import Roster

        class Store(Step):
            pass

        held, alike = Store(), Store()
        roster = Roster([held])
        self.assertIn(held, roster)
        self.assertNotIn(alike, roster)

    def test_the_roster_keeps_supplied_order_because_order_is_part_of_the_answer(self):
        # A class edge reaches every instance of the class, in the order they were supplied, which is what
        # makes a resolved run reproducible rather than merely correct.
        from cabaxiom.vocabulary import Roster

        class Store(Step):
            pass

        first, second = Store(), Store()
        self.assertEqual(list(Roster([first, second])), [first, second])


class OneMatchSaysWhoAskedAndWhatAnsweredTests(unittest.TestCase):
    """A Match is the per-name view of an edge, where dependencies() is the per-step one. It carries the
    ROW rather than the slot's name, so a consumer reads hardness and addressing off the vocabulary."""

    def setUp(self):
        class Store(Step):
            provides = frozenset({"shelf"})

        class Clerk(Step):
            wants = ("shelf",)

        self.Store, self.Clerk = Store, Clerk

    def test_a_match_names_the_step_that_asked_and_the_name_it_wrote(self):
        clerk, store = self.Clerk(), self.Store()
        asked, = Graph((store, clerk)).matching(clerk)
        self.assertIs(asked.step, clerk)
        self.assertEqual(asked.name, "shelf")
        self.assertEqual(asked.matched, (store,))

    def test_a_match_prints_the_declaration_and_what_answered_it(self):
        clerk, store = self.Clerk(), self.Store()
        asked, = Graph((store, clerk)).matching(clerk)
        self.assertEqual(repr(asked), "Match(Clerk.wants 'shelf' -> Store)")

    def test_a_match_that_answered_nothing_says_nothing_rather_than_an_empty_list(self):
        clerk = self.Clerk()
        asked, = Graph((clerk,)).matching(clerk)
        self.assertEqual(repr(asked), "Match(Clerk.wants 'shelf' -> nothing)")

    def test_the_vocabulary_is_published_beside_the_derivation_it_produced(self):
        # So a consumer reading a Match's row reads the table THIS graph was derived through rather than
        # whichever one happens to be shipped.
        grown = Vocabulary.shipped().grown(EdgeKind("ahead", BY_CLASS, hard=False, counterpart=None, precedes=True))
        self.assertIs(Graph((self.Store(),), grown).vocabulary, grown)


class AReversedRowDrawsTheEdgeTheOtherWayTests(unittest.TestCase):
    """`precedes` is the one direction flag the table carries, honoured by the same loop as every other
    row. That is the whole claim of making the language data instead of a branch per slot."""

    def test_a_step_that_declares_a_reversed_slot_runs_ahead_of_what_it_named(self):
        class Late(Step):
            pass

        class Early(Step):
            ahead = (Late,)

        grown = Vocabulary.shipped().grown(EdgeKind("ahead", BY_CLASS, hard=False, counterpart=None, precedes=True))
        early, late = Early(), Late()
        graph = Graph((late, early), grown)
        self.assertEqual(graph.dependencies(late), (early,))
        self.assertEqual(graph.dependencies(early), ())


class TheWalkVisitsAStepOnceTests(unittest.TestCase):
    """A diamond reaches the same step down two paths. The walk keeps what it reached and drops the
    second arrival rather than re-walking it, which is what stops a cycle spinning."""

    def test_a_diamond_reaches_its_base_once(self):
        class Base(Step):
            provides = frozenset({"ground"})

        class Left(Step):
            wants = ("ground",)

        class Right(Step):
            wants = ("ground",)

        base, left, right = Base(), Left(), Right()
        self.assertEqual(Graph((base, left, right)).closure((left, right)), frozenset({base, left, right}))


class TheIdentityGateHasTwoSentencesTests(unittest.TestCase):
    """Handing one instance in twice is a different mistake from handing in two that compare equal, and
    the fix differs, so the refusal says which one happened."""

    def test_two_steps_that_compare_equal_get_the_sentence_about_equality(self):
        # Step refuses equality at class definition and again at first construction, so the only way two
        # steps reach a derivation comparing equal is a class mutated after its instances exist. Worth
        # refusing anyway, since the derivation would fold the two into one node and reconcile a smaller
        # world than it was handed.
        class Twin(Step):
            pass

        twins = (Twin(), Twin())
        setattr(Twin, "__eq__", lambda self, other: isinstance(other, Twin))
        setattr(Twin, "__hash__", lambda self: 0)
        with self.assertRaises(Identity) as refused:
            Graph(twins)
        self.assertIn("compare equal", str(refused.exception))


class ARosterIsIndexableAsWellAsSearchableTests(unittest.TestCase):
    """The tuple sits beside the set rather than being replaced by it, so a Roster answers both questions
    a class edge asks - is this one present, and in what order are they all."""

    def test_it_reads_by_position_and_by_slice_the_way_the_list_it_replaced_did(self):
        from cabaxiom.vocabulary import Roster

        class Store(Step):
            pass

        first, second = Store(), Store()
        roster = Roster([first, second])
        self.assertIs(roster[0], first)
        self.assertEqual(list(roster[0:2]), [first, second])
        self.assertEqual(len(roster), 2)
