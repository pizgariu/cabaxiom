"""Chain axis: Components weakly-connected grouping and the ChainsPartition guard. The wave dispatchers
that ship run waves, not chains, so chain execution lives on a custom dispatcher composing the Chains
arranger - which is exactly what proves the shape and its disjoint guard belong to arrange(), not to any
one dispatcher class."""
import unittest

from cabaxiom import Graph, Reconciler
from cabaxiom.core.plan import Chains, ChainsPartition, Components, Ordering, Overlap
from cabaxiom.core.record import Reading, Statement
from cabaxiom.core.run import Dispatcher, RunMode
from support import A, B, C, X, Y, _RecStep


class _ChainRunner(Dispatcher):
    """A dispatcher that composes the Chains arranger. Its verbs are stubs - the tests here only build a
    reconciler, which arranges and verifies at construction, never converge - so it exists to prove the
    chain shape and its guard are the arranger's, reachable by any dispatcher that opts into Chains."""

    overlaps = Overlap.ACROSS

    async def execute(self, groups, graph, do, cancellation, observer):
        return Statement((), ())

    async def probe(self, groups, graph, read, cancellation, observer):
        return Reading(())


class ComponentsGroupingTests(unittest.IsolatedAsyncioTestCase):
    """Components splits the graph into weakly-connected chains, the dual of Kahn's waves."""

    def test_components_groups_a_connected_chain_and_isolates_independents(self):
        # C -> B -> A is one weakly-connected component (one chain), X and Y are edgeless singletons.
        steps = (C([]), A([]), B([]), X([]), Y([]))
        chains = Components().chains(Graph(steps))
        names = {tuple(step.__class__.__name__ for step in chain) for chain in chains}
        self.assertEqual(names, {("A", "B", "C"), ("X",), ("Y",)})

    def test_components_keeps_every_instance_of_a_class(self):
        steps = (B([]), A([]), A([]))
        chains = Components().chains(Graph(steps))
        [chain] = chains   # A, A, B are one connected component
        self.assertEqual([step.__class__.__name__ for step in chain], ["A", "A", "B"])

    def test_components_ignores_a_dep_outside_the_supplied_set(self):
        steps = (B([]),)   # B.expects = (A,), yet A is not supplied
        chains = Components().chains(Graph(steps))
        self.assertEqual([[s.__class__.__name__ for s in chain] for chain in chains], [["B"]])

    def test_components_raises_valueerror_naming_a_cycle(self):
        class P(_RecStep):
            pass

        class Q(_RecStep):
            expects = (P,)

        P.expects = (Q,)  # close the cycle within one component
        steps = (P([]), Q([]))
        with self.assertRaises(ValueError) as ctx:
            Components().chains(Graph(steps))
        self.assertIn("P", str(ctx.exception))
        self.assertIn("Q", str(ctx.exception))


class ChainsGuardTests(unittest.IsolatedAsyncioTestCase):
    """The chain shape and its disjoint guard live in arrange(), so any dispatcher composing the Chains
    arranger inherits both - the guard is tied to the composed shape, not to a dispatcher class."""

    def test_a_clean_component_is_accepted_and_a_leaky_split_is_refused(self):
        class LeakyChains(Ordering):
            def __call__(self, graph):
                return graph.steps

            def chains(self, graph):
                return tuple((step,) for step in graph.steps)   # B lands in a chain apart from its dep A

        Reconciler((A([]),), Components(), mode=RunMode(Chains(), _ChainRunner()))   # one clean component - fine
        with self.assertRaises(ValueError):
            Reconciler((A([]), B([])), LeakyChains(), mode=RunMode(Chains(), _ChainRunner()))   # B is after A, split apart

    def test_chains_inverse_reverses_within_each_chain_and_their_order(self):
        # Owned by the ChainsPartition type: within-chain steps flip (teardown a dependent first) and the
        # chain order flips too - harmless since the chains are independent, symmetric with WavesPartition.inverse.
        self.assertEqual(ChainsPartition((("a", "b", "c"), ("x", "y"))).inverse(), (("y", "x"), ("c", "b", "a")))

    def test_chains_verify_passes_when_every_edge_stays_inside_one_chain(self):
        steps = (C([]), A([]), B([]))
        graph = Graph(steps)
        ChainsPartition(Components().chains(graph)).verify(graph)

    def test_a_chain_holding_its_dependency_after_its_dependent_is_refused(self):
        # A placement rule that saw only the GROUP asked the same question of a correct chain and its
        # reverse - both are group 0 - so it could seat the dependent first. Seats carry the slot, so the
        # rule can finally say both its clauses.
        log: list = []
        first, second = A(log), B(log)   # B declares expects=(A,)
        graph = Graph((first, second))
        ChainsPartition(((first, second),)).verify(graph)          # dependency first: honoured
        with self.assertRaises(ValueError) as ctx:
            ChainsPartition(((second, first),)).verify(graph)      # dependency LAST in its own chain
        self.assertIn("earlier in the same group", str(ctx.exception))
