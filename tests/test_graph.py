"""The Graph, one home for the dependency structure - derivation, the demand guard, inversion, closure,
and the component split."""
import unittest
from dataclasses import dataclass

from cabaxiom import Graph, Step
from cabaxiom.vocabulary import Roster
from support import A, B, C, X, Y


class GraphDerivationTests(unittest.IsolatedAsyncioTestCase):
    """Derivation is total and instance-keyed: KIND edges fan to every present instance, the INSTANCE edge
    is scoped to the set, duplicates collapse in first-seen order, where absence is a dead end, not an error."""

    def test_a_kind_edge_fans_to_every_present_instance(self):
        first_a, second_a, b = A([]), A([]), B([])
        graph = Graph((first_a, second_a, b))
        self.assertEqual(graph.dependencies(b), (first_a, second_a))
        self.assertEqual(graph.dependencies(first_a), ())

    def test_requires_derives_exactly_like_after(self):
        class Needy(Step):
            requires = (A,)

        a, needy = A([]), Needy()
        graph = Graph((a, needy))
        self.assertEqual(graph.dependencies(needy), (a,))

    def test_needs_is_instance_scoped_and_an_absent_needs_is_a_dead_end(self):
        class Node(Step):
            pass

        first, second, stranger = Node(), Node(), Node()
        second.needs = (first, stranger)   # stranger is never supplied to the graph
        graph = Graph((first, second))
        self.assertEqual(graph.dependencies(second), (first,))

    def test_a_prerequisite_reached_twice_collapses_keeping_first_seen_order(self):
        class Dual(Step):
            expects = (A,)

        a, dual = A([]), Dual()
        dual.needs = (a,)   # the same instance arrives via its kind AND via the instance edge
        graph = Graph((a, dual))
        self.assertEqual(graph.dependencies(dual), (a,))

    def test_an_absent_soft_kind_is_a_dead_end_not_an_error(self):
        b = B([])   # B declares expects = (A,), with no A supplied
        graph = Graph((b,))
        self.assertEqual(graph.dependencies(b), ())


class GraphDemandTests(unittest.IsolatedAsyncioTestCase):
    """demand() is the hard-edge presence guard, apart from the total derivation on purpose."""

    def test_demand_raises_for_a_requires_with_no_instance(self):
        class Needy(Step):
            requires = (A,)

        graph = Graph((Needy(),))   # derivation itself stays total: constructing never raises
        with self.assertRaises(ValueError) as ctx:
            graph.demand()
        self.assertIn("Needy requires A", str(ctx.exception))
        self.assertIn("demands its presence", str(ctx.exception))

    def test_demand_passes_when_every_hard_edge_is_met(self):
        class Needy(Step):
            requires = (A,)

        Graph((A([]), Needy())).demand()   # no raise: the required kind has an instance present


class GraphDependentsTests(unittest.IsolatedAsyncioTestCase):
    """dependents() is the exact inversion of dependencies(), built lazily and cached."""

    def test_dependents_is_the_exact_inversion(self):
        a, b, c = A([]), B([]), C([])   # the support chain: B after A, C after B
        graph = Graph((a, b, c))
        self.assertEqual(graph.dependents(a), (b,))
        self.assertEqual(graph.dependents(b), (c,))
        self.assertEqual(graph.dependents(c), ())

    def test_the_inversion_is_built_once_and_reused(self):
        a, b = A([]), B([])
        graph = Graph((a, b))
        first_ask = graph.dependents(a)
        self.assertEqual(first_ask, (b,))
        self.assertEqual(graph.dependents(a), first_ask)   # the second ask reads the cache, same answer


class GraphClosureTests(unittest.IsolatedAsyncioTestCase):
    """closure() grows the seeds along every edge kind until nothing new joins."""

    def test_closure_grows_over_every_edge_kind_until_it_closes(self):
        class Root(Step):
            pass

        class Mid(Step):
            requires = (Root,)

        class Top(Step):
            pass

        class Bystander(Step):
            pass

        root, mid, top, bystander = Root(), Mid(), Top(), Bystander()
        top.needs = (mid,)   # instance edge into a requires edge: the walk crosses both kinds
        graph = Graph((root, mid, top, bystander))
        self.assertEqual(graph.closure((top,)), frozenset({top, mid, root}))   # bystander stays out

    def test_the_closure_of_no_seeds_is_empty(self):
        self.assertEqual(Graph((A([]),)).closure(()), frozenset())

    def test_a_prerequisite_already_closed_is_not_walked_twice(self):
        # Two seeds whose walks meet: C leads back to B, which is already a seed, so the walk skips it
        # instead of re-frontiering it - the closure terminates on convergent paths, not just on chains.
        a, b, c = A([]), B([]), C([])
        graph = Graph((a, b, c))
        self.assertEqual(graph.closure((b, c)), frozenset({a, b, c}))


class GraphComponentsTests(unittest.IsolatedAsyncioTestCase):
    """components() splits where no edge crosses, groups and members in supplied order."""

    def test_components_split_where_no_edge_crosses(self):
        a, b, c, x, y = A([]), B([]), C([]), X([]), Y([])
        graph = Graph((c, a, x, b, y))   # supplied scrambled: membership must not care
        names = [tuple(step.__class__.__name__ for step in component) for component in graph.components()]
        self.assertEqual(names, [("C", "A", "B"), ("X",), ("Y",)])   # chain joined, singletons apart, supplied order

    def test_a_needs_edge_joins_components_too(self):
        class Node(Step):
            pass

        first, second = Node(), Node()
        second.needs = (first,)
        self.assertEqual(Graph((first, second)).components(), ((first, second),))


class GraphCapabilityTests(unittest.IsolatedAsyncioTestCase):
    """The fourth edge kind. wants and demands fan to every present provider, landing in the same one
    derivation every guard reads - which is the entire point of the Graph."""

    def test_wants_fans_to_every_present_provider(self):
        class Db(Step):
            provides = frozenset({"database"})

        class Api(Step):
            wants = ("database",)

        primary, replica, api = Db(), Db(), Api()
        graph = Graph((primary, replica, api))
        self.assertEqual(graph.dependencies(api), (primary, replica))   # fan-in, supplied order

    def test_an_unprovided_want_is_a_dead_end_not_an_error(self):
        class Api(Step):
            wants = ("database",)

        api = Api()
        graph = Graph((api,))
        self.assertEqual(graph.dependencies(api), ())
        graph.demand()   # soft: nothing to insist on

    def test_demands_orders_exactly_like_wants_when_provided(self):
        class Db(Step):
            provides = frozenset({"database"})

        class Api(Step):
            demands = ("database",)

        db, api = Db(), Api()
        graph = Graph((db, api))
        self.assertEqual(graph.dependencies(api), (db,))
        graph.demand()   # the insistence is met

    def test_demand_raises_for_a_demand_nothing_provides(self):
        class Api(Step):
            demands = ("database",)

        graph = Graph((Api(),))   # derivation stays total, constructing never raises
        with self.assertRaises(ValueError) as ctx:
            graph.demand()
        self.assertIn("Api demands 'database'", str(ctx.exception))
        self.assertIn("insists on a provider", str(ctx.exception))

    def test_provides_is_overridable_per_instance_like_tags(self):
        class Node(Step):
            pass

        class Api(Step):
            wants = ("cache",)

        node, api = Node(), Api()
        node.provides = frozenset({"cache"})
        self.assertEqual(Graph((node, api)).dependencies(api), (node,))

    def test_a_provider_reached_by_kind_and_capability_collapses_once(self):
        class Db(Step):
            provides = frozenset({"database"})

        class Api(Step):
            expects = (Db,)
            wants = ("database",)

        db, api = Db(), Api()
        self.assertEqual(Graph((db, api)).dependencies(api), (db,))

    def test_capability_edges_join_closure_dependents_and_components(self):
        class Db(Step):
            provides = frozenset({"database"})

        class Api(Step):
            wants = ("database",)

        db, api = Db(), Api()
        graph = Graph((db, api))
        self.assertEqual(graph.closure((api,)), frozenset({api, db}))
        self.assertEqual(graph.dependents(db), (api,))
        self.assertEqual(graph.components(), ((db, api),))


class GraphDeclarationGuardTests(unittest.IsolatedAsyncioTestCase):
    """A declaration in the wrong slot is a loud TypeError at construction, never a silent dead end - and
    the error names the slot the stray belongs in, so the fix ships inside the message."""

    def test_a_label_in_expects_is_refused_pointing_at_the_right_slots(self):
        class Api(Step):
            expects = ("database",)   # a capability label where a step class belongs

        with self.assertRaises(TypeError) as ctx:
            Graph((Api(),))
        self.assertIn("names 'database' in `expects`, which takes step CLASSES", str(ctx.exception))   # the actual slot, not the pair
        self.assertIn("A capability label belongs in `wants` or `demands` and a step instance in `uses` or `needs`", str(ctx.exception))

    def test_a_class_in_wants_is_refused_pointing_at_expects(self):
        class Db(Step):
            pass

        class Api(Step):
            wants = (Db,)   # a step class where a capability label belongs

        with self.assertRaises(TypeError) as ctx:
            Graph((Api(),))
        self.assertIn("in `wants`, which takes capability labels", str(ctx.exception))
        self.assertIn("belongs in `expects` or `requires` or `prepares` or `mandates`", str(ctx.exception))

    def test_a_class_in_needs_is_refused_pointing_at_after(self):
        class Db(Step):
            pass

        class Api(Step):
            pass

        api = Api()
        api.needs = (Db,)   # a step class where an instance belongs
        with self.assertRaises(TypeError) as ctx:
            Graph((api,))
        self.assertIn("in `needs`, which takes step INSTANCES", str(ctx.exception))

    def test_a_non_label_in_provides_is_refused(self):
        class Db(Step):
            pass

        db = Db()
        db.provides = frozenset({3306})   # a port number is not a capability label
        with self.assertRaises(TypeError) as ctx:
            Graph((db,))
        self.assertIn("names 3306 in `provides`", str(ctx.exception))

    def test_a_bare_instance_in_needs_is_refused_before_iterating_it(self):
        class Db(Step):
            pass

        class Api(Step):
            pass

        db = Db()
        api = Api()
        api.needs = db   # a forgotten trailing comma - the instance itself, not a one-tuple
        with self.assertRaises(TypeError) as ctx:
            Graph((api, db))
        self.assertIn("needs must be a tuple of step INSTANCES", str(ctx.exception))
        self.assertIn("write needs = (entry,)", str(ctx.exception))   # one wording for every slot, off the registry

    def test_a_string_in_provides_is_refused_before_it_fans_into_characters(self):
        class Db(Step):
            pass

        db = Db()
        db.provides = "database"   # a string, not a set - would silently offer d, a, t, b, s, e
        with self.assertRaises(TypeError) as ctx:
            Graph((db,))
        self.assertIn("provides must be a set of capability labels", str(ctx.exception))
        self.assertIn("frozenset({'database'})", str(ctx.exception))


class StepDeclarationGuardTests(unittest.IsolatedAsyncioTestCase):
    """The class-level edge slots are vetted at class-definition time, so the classic forgotten comma is
    caught the moment the subclass is defined, not deep in the kernel with a cryptic message."""

    def test_a_bare_class_in_after_is_refused_with_the_comma_fix(self):
        class Db(Step):
            pass

        with self.assertRaises(TypeError) as ctx:
            class Api(Step):
                expects = (Db)   # a forgotten trailing comma - the class Db, not a one-tuple

        self.assertIn("Api.expects must be a tuple", str(ctx.exception))
        self.assertIn("write expects = (Db,)", str(ctx.exception))

    def test_a_bare_label_in_wants_is_refused_with_the_comma_fix(self):
        with self.assertRaises(TypeError) as ctx:
            class Api(Step):
                wants = ("database")   # a bare string, not a one-tuple

        self.assertIn("Api.wants must be a tuple", str(ctx.exception))
        self.assertIn("write wants = ('database',)", str(ctx.exception))

    def test_a_list_in_requires_is_refused_without_a_comma_hint(self):
        class Db(Step):
            pass

        with self.assertRaises(TypeError) as ctx:
            class Api(Step):
                requires = [Db]   # a list, not a tuple - no single-entry comma to suggest

        self.assertIn("Api.requires must be a tuple, got list.", str(ctx.exception))

    def test_a_class_level_string_in_provides_is_refused(self):
        with self.assertRaises(TypeError) as ctx:
            class Db(Step):
                provides = "database"   # a string fans into single characters - the silent wrong

        self.assertIn("Db.provides must be a set of capability labels", str(ctx.exception))
        self.assertIn("frozenset({'database'})", str(ctx.exception))


class IdentityIsTheCurrencyTests(unittest.IsolatedAsyncioTestCase):
    """Every structure the kernel derives is keyed by step INSTANCE, so the identity contract is enforced
    twice: a hand-written __eq__ or __hash__ is refused where it is written, while the Graph catches what no
    class-definition hook can see - a decorator that rewrote equality after the class was created, which
    used to collapse two steps into one node and blame an innocent Ordering for the shrunken world."""

    def test_a_hand_written_eq_is_refused_at_class_definition(self):
        with self.assertRaises(TypeError) as refused:
            class ValueEqual(Step):
                def __eq__(self, other: object) -> bool:
                    return True
        self.assertIn("identity IS the kernel's dependency addressing", str(refused.exception))

    def test_a_hand_written_hash_is_refused_at_class_definition(self):
        with self.assertRaises(TypeError):
            class ValueHashed(Step):
                def __hash__(self) -> int:
                    return 7

    def test_a_dataclass_that_rewrote_equality_is_caught_by_the_graph(self):
        # dataclass(eq=True) rewrites __eq__ AFTER Step.__init_subclass__ ran, so the class hook cannot
        # see it - and before this guard, two value-equal steps collapsed into one graphlib key and the
        # run was refused with a coverage error naming the Ordering, which had done nothing wrong.
        @dataclass(frozen=True)
        class Payload(Step):
            name: str = "same"

        with self.assertRaises(ValueError) as refused:
            Graph((Payload(), Payload()))
        self.assertIn("compare EQUAL", str(refused.exception))
        self.assertIn("eq=False", str(refused.exception))   # the fix rides in the message

    def test_a_dataclass_step_with_eq_false_is_the_documented_form(self):
        @dataclass(frozen=True, eq=False)
        class Payload(Step):
            name: str = "same"

        first, second = Payload(), Payload()
        graph = Graph((first, second))
        self.assertEqual(len(graph.steps), 2)   # two concerns, two nodes, no collapse

    def test_the_same_instance_handed_twice_gets_its_own_sentence(self):
        class Solo(Step):
            pass

        one = Solo()
        with self.assertRaises(ValueError) as refused:
            Graph((one, one))
        self.assertIn("handed to this run twice", str(refused.exception))


    def test_a_bare_dataclass_is_refused_by_name_and_not_by_a_hash_error(self):
        # The COMMONEST way to write it, the one the guard above could not reach. A bare @dataclass
        # takes eq=True, which writes __eq__ and drops __hash__ to None, so the set the equality check is
        # built on raised `unhashable type` first - a bare TypeError from inside the derivation, naming no
        # step and no fix, for the exact decorator that guard exists to catch. The frozen=True form was
        # tested and the bare one never was, which is how it survived.
        @dataclass
        class Payload(Step):
            name: str = "same"

        with self.assertRaises(ValueError) as refused:
            Graph((Payload(),))
        told = str(refused.exception)
        self.assertIn("Payload", told)          # names the class, where the TypeError named a set element
        self.assertIn("eq=False", told)         # and carries the fix, like its sibling above
        self.assertNotIn("unhashable", told)

    def test_one_unaddressable_step_is_enough_to_be_refused(self):
        # Not a duplicate problem. A single unhashable step cannot be addressed at all, so the run is
        # refused on its own and not only when a second one collides with it.
        @dataclass
        class Alone(Step):
            name: str = "only"

        with self.assertRaises(ValueError):
            Graph((Alone(),))

class OnePlaneForEveryDeclarationTests(unittest.IsolatedAsyncioTestCase):
    """The seven declaration slots speak ONE plane. The class value is the default, the instance may
    override, where the kernel reads the instance - `b.wants = ('db',)` used to be swallowed in silence,
    deriving no edge and leaving no trace, which is the worst kind of wrong this kernel knows."""

    def test_an_instance_level_capability_edge_is_a_real_edge(self):
        class Provider(Step):
            provides = frozenset({"db"})

        class Consumer(Step):
            pass

        provider, consumer = Provider(), Consumer()
        consumer.wants = ("db",)
        graph = Graph((provider, consumer))
        self.assertEqual(graph.dependencies(consumer), (provider,))   # the edge EXISTS now
        self.assertEqual([match.slot for match in graph.matching(consumer)], ["wants"])

    def test_an_instance_level_after_orders_one_instance_apart_from_its_kind(self):
        class Base(Step):
            pass

        class Worker(Step):
            pass

        base, eager, careful = Base(), Worker(), Worker()
        careful.expects = (Base,)
        graph = Graph((base, eager, careful))
        self.assertEqual(graph.dependencies(careful), (base,))
        self.assertEqual(graph.dependencies(eager), ())   # its twin keeps the class default

    def test_a_malformed_instance_container_is_refused_where_the_class_guard_cannot_see(self):
        class Provider(Step):
            pass

        lone = Provider()
        lone.expects = (Provider)   # the classic forgotten comma, now on the INSTANCE plane
        with self.assertRaises(TypeError) as refused:
            Graph((lone,))
        self.assertIn("must be a tuple", str(refused.exception))
        self.assertIn("trailing comma", str(refused.exception))


class RosterTests(unittest.IsolatedAsyncioTestCase):
    """The instance table's value type: a Sequence that can also be ASKED in constant time.

    It exists because `step in instances[cls]` over a list is linear, which made the whole derivation
    quadratic on any declaration addressing by instance - a 200000 step chain took a hundred seconds. The
    order is what every class-addressed edge fans in, so it cannot become a set, which these tests hold the
    Sequence contract the addressing signature still promises."""

    def test_a_roster_reads_as_the_sequence_it_wraps(self):
        first, second, third = A([]), A([]), A([])
        roster = Roster((first, second, third))
        self.assertEqual(len(roster), 3)
        self.assertIs(roster[0], first)
        self.assertIs(roster[-1], third)
        self.assertEqual(tuple(roster[1:]), (second, third))
        self.assertEqual(tuple(roster), (first, second, third))

    def test_membership_answers_by_identity_and_ignores_a_stranger(self):
        held, stranger = A([]), A([])
        roster = Roster((held,))
        self.assertIn(held, roster)
        self.assertNotIn(stranger, roster)
        self.assertNotIn("not a step", roster)

    def test_supplied_order_survives_the_index(self):
        # The order IS the fan order, so a Roster that reordered would reorder every class-addressed edge.
        made = [A([]) for _ in range(6)]
        graph = Graph((*made, B([])))
        self.assertEqual(graph.dependencies(graph.steps[-1]), tuple(made))


class DataFlowContractTests(unittest.IsolatedAsyncioTestCase):
    """`produces` and `consumes` are the DATA plane, deliberately not a fifth edge kind. Declaring a key
    creates no edge and moves no step - the dependency plane still says WHEN a step runs - so the two planes
    stay separable. What the declaration buys is one guard. A key nothing upstream produces is refused at
    resolution, where the dependency plane already refuses an absent `requires`, instead of arriving as an
    absent entry the hook cannot tell from a real one."""

    def _flow(self):
        class Db(Step):
            produces = frozenset({"dsn"})

            def apply(self, inputs):
                return None, {"dsn": "postgres://db"}

        class Api(Step):
            expects = (Db,)
            consumes = frozenset({"dsn"})

            def apply(self, inputs):
                return None, {}

        return Db, Api

    def test_a_declared_key_carried_by_a_prerequisite_resolves(self):
        Db, Api = self._flow()
        Graph((Api(), Db())).demand()   # the producer IS a prerequisite, so the payload really arrives

    def test_a_key_nothing_produces_is_refused_at_resolution(self):
        _Db, Api = self._flow()
        graph = Graph((Api(),))   # derivation stays total, so constructing never raises
        with self.assertRaises(ValueError) as refused:
            graph.demand()
        spoken = str(refused.exception)
        self.assertIn("consumes 'dsn'", spoken)
        self.assertIn("Nothing in this run produces it", spoken)

    def test_a_producer_that_is_not_a_prerequisite_is_named_as_the_fault(self):
        # THE SHARP CASE. The key is produced, just not anywhere the payload can reach from - the Ledger
        # mounts from the DIRECT prerequisites, so a sibling's artifacts never arrive. Counting it would
        # bless the exact hole this refuses, so the message names the step and says what is missing.
        class Sibling(Step):
            produces = frozenset({"dsn"})

        class Reader(Step):
            consumes = frozenset({"dsn"})

        with self.assertRaises(ValueError) as refused:
            Graph((Reader(), Sibling())).demand()
        spoken = str(refused.exception)
        self.assertIn("Sibling produces it but is not a prerequisite", spoken)
        self.assertIn("declare the edge that carries it", spoken)

    def test_a_producer_two_hops_up_does_not_count_because_its_payload_never_arrives(self):
        # The transitive case, pinned. Artifacts flow one hop, so a grandparent's key is exactly as absent
        # as a stranger's. This is the rule that keeps the guard honest about what mounted() really merges.
        class Root(Step):
            produces = frozenset({"dsn"})

        class Middle(Step):
            expects = (Root,)

        class Leaf(Step):
            expects = (Middle,)
            consumes = frozenset({"dsn"})

        with self.assertRaises(ValueError):
            Graph((Leaf(), Middle(), Root())).demand()

    def test_declaring_nothing_costs_nothing_and_the_planes_stay_apart(self):
        # The common case. No data declared, so the guard reads one attribute and stops - and a step that
        # comes after another for reasons that carry no payload is still perfectly legal.
        class First(Step):
            pass

        class Second(Step):
            expects = (First,)

        Graph((Second(), First())).demand()

    def test_a_string_in_a_key_set_is_refused_at_class_definition(self):
        # The silent one. A bare string iterates into single characters, so `produces = "dsn"` would offer
        # three keys named d, s and n and every match would miss without a word.
        with self.assertRaises(TypeError) as refused:
            class Wrong(Step):
                produces = "dsn"

        self.assertIn("must be a set of artifact keys", str(refused.exception))
        self.assertIn("frozenset({'dsn'})", str(refused.exception))

    def test_a_non_key_in_consumes_is_refused_at_construction(self):
        # The per-instance half, which no class hook can see.
        class Reader(Step):
            pass

        reader = Reader()
        reader.consumes = frozenset({3306})
        with self.assertRaises(TypeError) as refused:
            Graph((reader,))
        self.assertIn("names 3306 in `consumes`", str(refused.exception))

