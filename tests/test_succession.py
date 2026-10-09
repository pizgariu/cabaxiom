"""Succession. The derivation's delta between two declarations, read without touching a world. Two channels
vote - a soft edge whose whole match set left, plus a comparison that recognised nothing at all."""
import unittest

from cabaxiom import Graph, Step, Succession


class Database(Step):
    def __init__(self, label: str = "primary") -> None:
        self.label = label
        self.provides = frozenset({"database"})


class Api(Step):
    wants = ("database",)


class Cache(Step):
    expects = (Database,)


class Migration(Step):
    requires = (Database,)


class Audit(Step):
    demands = ("database",)


class Web(Step):
    pass


class MatchTests(unittest.TestCase):
    """The per-name view the derivation never surfaced - every declared name with what it matched, misses
    included, because a miss leaves no edge and so cannot be seen in dependencies()."""

    def test_it_reports_every_slot_with_its_match_set(self):
        db, api, cache = Database(), Api(), Cache()
        graph = Graph((db, api, cache))
        self.assertEqual([(m.slot, m.label, len(m.matched)) for m in graph.matching(api)],
                         [("wants", "'database'", 1)])
        self.assertEqual([(m.slot, m.label, len(m.matched)) for m in graph.matching(cache)],
                         [("expects", "Database", 1)])

    def test_a_miss_is_reported_where_an_edge_cannot_be(self):
        api = Api()
        graph = Graph((api,))
        missed = graph.matching(api)[0]
        self.assertEqual(missed.matched, ())
        self.assertEqual(graph.dependencies(api), ())   # the edge view cannot show it at all

    def test_soft_reads_the_slot(self):
        db, migration, audit, cache = Database(), Migration(), Audit(), Cache()
        graph = Graph((db, migration, audit, cache))
        self.assertFalse(graph.matching(migration)[0].soft)   # requires is loud, demand() raises on it
        self.assertFalse(graph.matching(audit)[0].soft)       # demands likewise
        self.assertTrue(graph.matching(cache)[0].soft)        # after trusts an absent name

    def test_label_renders_each_declared_shape(self):
        db, api, cache = Database(), Api(), Cache()
        web = Web()
        web.needs = (db,)
        graph = Graph((db, api, cache, web))
        self.assertEqual(graph.matching(api)[0].label, "'database'")   # a capability, quoted
        self.assertEqual(graph.matching(cache)[0].label, "Database")   # a class, by its name
        self.assertEqual(graph.matching(web)[0].label, "Database")     # an instance, by its class name

    def test_needs_is_scoped_to_the_present_set(self):
        db, absent = Database(), Database("elsewhere")
        here, gone = Web(), Web()
        here.needs = (db,)
        gone.needs = (absent,)
        graph = Graph((db, here, gone))
        self.assertEqual(graph.matching(here)[0].matched, (db,))
        self.assertEqual(graph.matching(gone)[0].matched, ())   # declared, yet outside this set

    def test_the_step_and_name_are_readable_and_the_repr_says_what_matched(self):
        db, cache, api = Database(), Cache(), Api()
        graph = Graph((db, cache, api))
        hit = graph.matching(cache)[0]
        self.assertIs(hit.step, cache)
        self.assertIs(hit.name, Database)
        self.assertIn("Cache.expects Database -> Database", repr(hit))
        self.assertIn("-> nothing", repr(Graph((api,)).matching(api)[0]))

    def test_a_provider_reached_twice_is_reported_twice(self):
        class Both(Step):
            expects = (Database,)
            wants = ("database",)

        db, both = Database(), Both()
        graph = Graph((db, both))
        self.assertEqual(len(graph.matching(both)), 2)      # two declarations that both landed
        self.assertEqual(graph.dependencies(both), (db,))   # one edge, deduplicated


class StrandingTests(unittest.TestCase):
    """The flagship reading - the pre-flight of a Transition. A survivor's soft edge whose whole match set
    walked out with the leavers goes QUIET and nothing anywhere will say so."""

    def test_it_names_the_survivor_whose_only_provider_left(self):
        db, api, cache = Database(), Api(), Cache()
        rift = Succession((db, api, cache), (api, cache)).compare()
        self.assertTrue(rift.torn)
        self.assertTrue(rift)                               # truthy exactly when torn, the Indictment polarity
        self.assertEqual([(s.slot, s.step.__class__.__name__) for s in rift.quieted],
                         [("wants", "Api"), ("expects", "Cache")])
        self.assertEqual(rift.quieted[0].lost, (db,))
        self.assertEqual(rift.quieted[0].now, ())
        # A Shift carries the declaration it is about, so a caller can act on the name and the slot's
        # flavour without going back to either Graph.
        self.assertEqual(rift.quieted[0].name, "database")
        self.assertIs(rift.quieted[1].name, Database)
        self.assertTrue(all(shift.soft for shift in rift.quieted))   # only a soft name can go quiet

    def test_a_hard_edge_going_absent_is_not_the_silent_class(self):
        # requires and demands raise through Graph.demand() the moment membership is final, so they are
        # loud already. They still show up under standing.
        db, migration, audit = Database(), Migration(), Audit()
        rift = Succession((db, migration, audit), (migration, audit)).compare()
        self.assertFalse(rift.torn)
        self.assertEqual(len(rift.standing), 2)
        self.assertEqual([m.soft for m in rift.standing], [False, False])

    def test_a_declaration_that_never_resolved_is_not_a_tear(self):
        # It was already leaning on the world before the change, so nothing was taken away.
        api, cache = Api(), Cache()
        rift = Succession((api, cache), (api,)).compare()
        self.assertFalse(rift.torn)
        self.assertEqual(len(rift.standing), 1)

    def test_a_thinner_fan_in_that_still_resolves_is_reported_but_does_not_vote(self):
        primary, replica, api = Database(), Database("replica"), Api()
        rift = Succession((primary, replica, api), (primary, api)).compare()
        self.assertFalse(rift.torn)                          # it still resolves, so no promise was broken
        self.assertEqual(len(rift.narrowed), 1)
        self.assertEqual(rift.narrowed[0].lost, (replica,))
        self.assertEqual(rift.narrowed[0].was, (primary, replica))


class MergeTests(unittest.TestCase):
    """Point the same read at (ours, ours + theirs) and it answers the merge question instead."""

    def test_their_provider_answers_our_leaning(self):
        db, api = Database(), Api()
        mine = Succession((api,), (api, db)).compare()
        self.assertEqual(len(mine.materialised), 1)
        self.assertEqual(mine.materialised[0].gained, (db,))
        self.assertEqual(mine.materialised[0].was, ())

    def test_growth_can_only_give(self):
        # If desired contains previous, every match set can only grow, so the taking channels are provably
        # empty. The theorem is worth an assertion, since the whole merge reading rests on it.
        db, api, cache = Database(), Api(), Cache()
        mine = Succession((api, cache), (api, cache, db)).compare()
        self.assertEqual(mine.quieted, ())
        self.assertEqual(mine.narrowed, ())

    def test_a_wider_fan_in_is_reported(self):
        primary, replica, api = Database(), Database("replica"), Api()
        mine = Succession((primary, api), (primary, replica, api)).compare()
        self.assertEqual(len(mine.widened), 1)
        self.assertEqual(mine.widened[0].gained, (replica,))

    def test_a_joiner_contributes_its_leanings_but_never_a_delta(self):
        # A newcomer's own edges are not couplings. Every name it has would read as materialised, which is
        # true of the step and false of the declaration.
        db, cache = Database(), Cache()
        mine = Succession((db,), (db, cache)).compare()
        self.assertEqual(mine.materialised, ())
        self.assertEqual(mine.standing, ())              # cache's after resolved, so it leans on nothing

    def test_a_swap_puts_one_name_in_both_directions(self):
        # widened and narrowed are DIRECTIONS, not a partition. A fan-in that swapped its only provider
        # both gained and lost.
        primary, replacement, api = Database(), Database("replacement"), Api()
        both = Succession((primary, api), (replacement, api)).compare()
        self.assertEqual(len(both.widened), 1)
        self.assertEqual(len(both.narrowed), 1)
        self.assertIs(both.widened[0], both.narrowed[0])
        self.assertFalse(both.torn)                      # it still resolves, so nothing went quiet

    def test_an_unchanged_name_is_reported_in_no_channel(self):
        db, api = Database(), Api()
        calm = Succession((db, api), (db, api)).compare()
        self.assertEqual((calm.quieted, calm.materialised, calm.widened, calm.narrowed), ((), (), (), ()))
        self.assertFalse(calm)


class RelianceTests(unittest.TestCase):
    """The degenerate call against the empty declaration answers what a declaration assumes the world has
    already done."""

    def test_an_empty_previous_leaves_standing_as_the_whole_answer(self):
        api, cache, migration = Api(), Cache(), Migration()
        rift = Succession((), (api, cache, migration)).compare()
        self.assertEqual((rift.quieted, rift.materialised, rift.widened, rift.narrowed), ((), (), (), ()))
        self.assertEqual(len(rift.standing), 3)
        self.assertEqual([m.soft for m in rift.standing], [True, True, False])

    def test_a_hermetic_declaration_leans_on_nothing(self):
        db, api = Database(), Api()
        self.assertEqual(Succession((), (db, api)).compare().standing, ())


class NamedIdentityTests(unittest.TestCase):
    """A step that names itself is recognised across the change even as a fresh object, which is what makes a
    declaration assembled from data comparable at all. And because the two sides are then DIFFERENT objects
    whose declarations may legitimately differ, names pair by what they say rather than by list position."""

    def test_a_rebuilt_declaration_is_compared_rather_than_written_off(self):
        # The whole point. Nothing is shared, every object is fresh, yet the reading still works because both
        # sides name themselves. The soft edge that went quiet is found exactly as if the instances were held.
        before = (_Named("db", provides={"database"}), _Named("api", wants=("database",)))
        after = (_Named("api", wants=("database",)),)
        rift = Succession(before, after).compare()

        self.assertTrue(rift.torn)
        self.assertEqual(rift.estranged, ())                  # something WAS recognised
        self.assertEqual(len(rift.quieted), 1)
        self.assertEqual(Step.named(rift.quieted[0].step), "api")

    def test_a_name_the_successor_added_pairs_with_nothing_and_materialises(self):
        # Impossible to express before. Two views of ONE object had the same names by construction, so a
        # positional zip was enough. A recognised survivor may declare something new.
        before = (_Named("cache", provides={"cache"}), _Named("api"))
        after = (_Named("cache", provides={"cache"}), _Named("api", wants=("cache",)))
        rift = Succession(before, after).compare()

        self.assertEqual(len(rift.materialised), 1)
        self.assertEqual(rift.materialised[0].was, ())         # there was no such name to compare against
        self.assertEqual(len(rift.materialised[0].now), 1)
        self.assertFalse(rift.torn)                            # a new coupling is structure moving as declared

    def test_a_name_the_successor_dropped_is_silent_on_purpose(self):
        # An edge the author deleted is a decision, so only an edge the author still believes in is a finding.
        before = (_Named("db", provides={"database"}), _Named("api", wants=("database",)))
        after = (_Named("db", provides={"database"}), _Named("api"))
        rift = Succession(before, after).compare()

        self.assertFalse(rift.torn)
        self.assertEqual((rift.quieted, rift.materialised, rift.widened, rift.narrowed), ((), (), (), ()))

    def test_names_pair_by_slot_and_not_by_position(self):
        # The successor reorders and grows its declaration. Positionally the old view would compare `wants`
        # against `expects` and raise on the length, so the pairing has to read what each name SAYS.
        before = (_Named("db", provides={"database"}), _Named("api", wants=("database",)))
        after = (_Named("db", provides={"database"}),
                 _Named("api", wants=("database", "cache"), tags=frozenset({"edge"})))
        rift = Succession(before, after).compare()

        self.assertEqual([match.name for match in rift.standing], ["cache"])   # declared, matched nothing
        self.assertEqual((rift.quieted, rift.widened, rift.narrowed), ((), (), ()))

    def test_an_instance_addressed_name_is_read_through_the_correspondence(self):
        # `uses` names an INSTANCE, so a rebuilt target is a different object under the same name. Without
        # translating it the fan-in would report as having swapped its whole match set while nothing moved.
        was_db = _Named("db")
        before = (was_db, _Named("api", uses=(was_db,)))
        now_db = _Named("db")
        after = (now_db, _Named("api", uses=(now_db,)))
        rift = Succession(before, after).compare()

        self.assertEqual((rift.widened, rift.narrowed), ((), ()))
        self.assertFalse(rift.torn)

    def test_a_shift_answers_the_step_that_is_in_the_run_now(self):
        # A finding about the successor's declaration names the successor's step, never the predecessor it
        # continues, since the predecessor is not in any run a reader can act on.
        before = (_Named("db", provides={"database"}), _Named("api", wants=("database",)))
        after = (_Named("api", wants=("database",)),)
        rift = Succession(before, after).compare()

        self.assertIs(rift.quieted[0].step, after[0])

    def test_the_repr_survives_a_shift_with_no_predecessor(self):
        # It used to read the before side for its label, which a materialised name has none of.
        before = (_Named("cache", provides={"cache"}), _Named("api"))
        after = (_Named("cache", provides={"cache"}), _Named("api", wants=("cache",)))
        shift = Succession(before, after).compare().materialised[0]
        self.assertIn("api.wants 'cache' 0 -> 1", repr(shift))


class _Named(Step):
    """A step built from data rather than written by hand, which is the reader `identifier` exists for."""

    def __init__(self, name: str, *, provides: frozenset[str] | set[str] = frozenset(),
                 wants: tuple[str, ...] = (), uses: tuple[Step, ...] = (),
                 tags: frozenset[str] = frozenset()) -> None:
        self.name = name
        self.provides = frozenset(provides)
        self.wants = wants
        self.uses = uses
        self.tags = tags

    @property
    def identifier(self) -> str:
        return self.name


class VerdictShapeTests(unittest.TestCase):
    """The record discipline every kernel verdict keeps - frozen channels plus a repr that counts them."""

    def test_the_channels_are_tuples_and_cannot_be_rewritten(self):
        db, api = Database(), Api()
        rift = Succession((db, api), (api,)).compare()
        self.assertIsInstance(rift.quieted, tuple)
        with self.assertRaises(AttributeError):
            rift.quieted = ()

    def test_the_reprs_count_what_they_carry(self):
        db, api = Database(), Api()
        rift = Succession((db, api), (api,)).compare()
        self.assertIn("Rift(torn=True, quieted=1", repr(rift))
        self.assertIn("Api.wants 'database' 1 -> 0", repr(rift.quieted[0]))

    def test_a_wrong_slot_declaration_raises_at_construction(self):
        class Sloppy(Step):
            expects = ("database",)   # a capability label where a step class belongs

        with self.assertRaises(TypeError):
            Succession((), (Sloppy(),))   # the Graph vets as it derives, before any question is asked

    def test_a_rebuild_of_unnamed_steps_is_reported_instead_of_reading_clean(self):
        # The trap this used to document as unguardable. A declaration rebuilt from fresh unnamed instances
        # has NO survivors, so no name pairs and every other channel comes back empty - which read as a clean
        # bill over a declaration whose every edge was in fact torn down and remade. The emptiness is now the
        # finding, naming the kinds that stood on both sides without being recognised.
        db, api = Database(), Api()
        rebuilt = Succession((db, api), (Database(), Api())).compare()
        self.assertTrue(rebuilt.torn)
        self.assertEqual(rebuilt.estranged, (Api, Database))
        self.assertEqual(rebuilt.quieted, ())            # it cannot say WHICH edges, only that it cannot say
        self.assertEqual(rebuilt.materialised, ())
        shared = Succession((db, api), (api,)).compare()
        self.assertTrue(shared.torn)   # the same change, with the instance shared, is seen
        self.assertEqual(shared.estranged, ())

    def test_one_survivor_is_enough_to_anchor_the_reading(self):
        # A per-kind version of the check fired on an ordinary provider swap and had to go. With a survivor
        # present the comparison works, so the swap is reported honestly rather than as an estrangement.
        api = Api()
        swapped = Succession((Database(), api), (Database("replacement"), api)).compare()
        self.assertEqual(swapped.estranged, ())
        self.assertEqual(len(swapped.widened), 1)
        self.assertEqual(len(swapped.narrowed), 1)

    def test_the_two_legitimately_survivorless_readings_stay_unremarked(self):
        # An empty predecessor is the "what does this declaration assume" reading, where two declarations that
        # share no kind are simply disjoint. Neither shares a kind, so neither is suspicious.
        assumed = Succession((), (Api(), Cache())).compare()
        self.assertFalse(assumed.torn)
        self.assertEqual(assumed.estranged, ())
        disjoint = Succession((Web(),), (Api(),)).compare()
        self.assertFalse(disjoint.torn)
        self.assertEqual(disjoint.estranged, ())

