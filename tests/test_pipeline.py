"""Chain axis - Components weakly-connected grouping and Pipeline per-chain fan-out."""
import asyncio
import unittest

from cabaxiom import (
    Cancellation,
    Cancelled,
    Chains,
    Components,
    Deadline,
    Dispatcher,
    DriftItem,
    Kahn,
    OnError,
    Ordering,
    Pipeline,
    Reconciler,
    Serial,
    Step,
)
from support import A, B, Boom, C, X, Y, _RecStep


class PipelineOrderingTests(unittest.TestCase):
    """The dual of the wave model. Components splits into independent CHAINS, Pipeline runs each chain in
    series with the chains concurrent, where Chains.verify() is the guard that keeps it correct."""

    def test_components_groups_a_connected_chain_and_isolates_independents(self):
        # C -> B -> A is one weakly-connected component (one chain), X and Y are edgeless singletons.
        chains = Components().chains((C([]), A([]), B([]), X([]), Y([])))
        names = {tuple(type(step).__name__ for step in chain) for chain in chains}
        self.assertEqual(names, {("A", "B", "C"), ("X",), ("Y",)})

    def test_components_flat_call_is_a_valid_topo_order(self):
        # Its __call__ concatenates the components, each internally topo-sorted, so expects= still holds.
        log = []
        asyncio.run(Reconciler((C(log), A(log), B(log)), Components(), dispatcher=Serial()).converge())
        self.assertEqual(log, ["A", "B", "C"])

    def test_components_keeps_every_instance_of_a_class(self):
        chains = Components().chains((B([]), A([]), A([])))
        [chain] = chains   # A, A, B are one connected component
        self.assertEqual([type(step).__name__ for step in chain], ["A", "A", "B"])

    def test_components_ignores_a_dep_outside_the_supplied_set(self):
        chains = Components().chains((B([]),))   # B.expects = (A,), yet A is not supplied
        self.assertEqual([[type(s).__name__ for s in chain] for chain in chains], [["B"]])

    def test_components_raises_valueerror_naming_a_cycle(self):
        class P(_RecStep):
            pass

        class Q(_RecStep):
            expects = (P,)

        P.expects = (Q,)  # close the cycle within one component
        with self.assertRaises(ValueError) as ctx:
            Components().chains((P([]), Q([])))
        self.assertIn("P", str(ctx.exception))
        self.assertIn("Q", str(ctx.exception))

    def test_pipeline_serialises_the_steps_within_a_chain(self):
        # One connected chain -> one pipeline on one worker, so the within-chain order is deterministic.
        log = []
        asyncio.run(Reconciler((C(log), A(log), B(log)), Components(), dispatcher=Pipeline()).converge())
        self.assertEqual(log, ["A", "B", "C"])

    def test_pipeline_runs_independent_chains_and_keeps_each_chains_order(self):
        # Chain A->B->C runs alongside singletons X and Y. All run, with A before B before C within its chain.
        log = []
        asyncio.run(Reconciler((C(log), A(log), B(log), X(log), Y(log)), Components(), dispatcher=Pipeline()).converge())
        self.assertEqual(sorted(log), ["A", "B", "C", "X", "Y"])
        self.assertLess(log.index("A"), log.index("B"))
        self.assertLess(log.index("B"), log.index("C"))

    def test_pipeline_failfast_reraises_on_the_calling_thread(self):
        with self.assertRaises(RuntimeError):
            asyncio.run(Reconciler((Boom(),), Components(), dispatcher=Pipeline()).converge())

    def test_pipeline_best_effort_collects_failures(self):
        residual = asyncio.run(Reconciler((Boom(),), Components(), dispatcher=Pipeline(OnError.BestEffort)).converge())
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    def test_pipeline_routes_what_apply_returns_to_the_applied_channel(self):
        # A chain step whose apply() returns what it changed. run_chain accumulates it and converge routes
        # it to the applied channel rather than the residual.
        class Applied(Step):
            def apply(self):
                return [DriftItem("svc", "created")]

        residual = asyncio.run(Reconciler((Applied(),), Components(), dispatcher=Pipeline()).converge())
        self.assertEqual(residual, [])                                       # nothing still wrong
        self.assertEqual([item.message for item in residual.applied], ["created"])

    def test_pipeline_cancellation_aborts_regardless_of_on_error(self):
        # A fired cancellation always raises Cancelled, even under BestEffort - the between-steps check.
        with self.assertRaises(Cancelled):
            asyncio.run(Reconciler((A([]), B([]), C([])), Components(),
                                   dispatcher=Pipeline(OnError.BestEffort), cancellation=Deadline(0)).converge())

    def test_reconciler_rejects_pipeline_with_a_non_chain_ordering(self):
        # Kahn does not override chains() (one-chain fallback), so Pipeline would run nothing concurrently.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((A([]),), Kahn(), dispatcher=Pipeline())
        self.assertIn("Components", str(ctx.exception))

    def test_the_chain_shape_and_guard_live_in_arrange_on_any_executor(self):
        # A custom dispatcher that builds a chain partition and verifies it accepts a clean split and rejects a
        # leaky one - the disjoint guard is tied to arrange(), not to the Pipeline class.
        class ChainExecutor(Dispatcher):
            def arrange(self, ordering, steps):
                chains = Chains(ordering.chains(steps))
                chains.verify()
                return chains

            async def probe(self, groups, read):
                return [read(step) for group in groups for step in group]

            async def execute(self, groups, do, cancellation):
                return [], []

        class LeakyChains(Ordering):
            def __call__(self, steps):
                return steps

            def chains(self, steps):
                return tuple((step,) for step in steps)   # B lands in a chain apart from its dep A

        Reconciler((A([]),), Components(), dispatcher=ChainExecutor())   # one clean component - fine
        with self.assertRaises(ValueError):
            Reconciler((A([]), B([])), LeakyChains(), dispatcher=ChainExecutor())

    def test_guard_rejects_chains_that_leak_an_edge_across_chains(self):
        # An Ordering that overrides chains() but scatters dependent steps into SEPARATE chains passes the
        # capability check, yet concurrent chains would ignore that edge. verify catches it upfront.
        class LeakyChains(Ordering):
            def __call__(self, steps):
                return steps

            def chains(self, steps):
                return tuple((step,) for step in steps)   # every step its own chain, deps be damned

        with self.assertRaises(ValueError):
            Reconciler((A([]), B([])), LeakyChains(), dispatcher=Pipeline())   # B is after A, different chain

    def test_chains_inverse_reverses_within_each_chain_and_their_order(self):
        # Owned by the Chains type. Within-chain steps flip (teardown a dependent first) and the chain order
        # flips too - harmless since the chains are independent and symmetric with Levels.inverse.
        self.assertEqual(Chains((("a", "b", "c"), ("x", "y"))).inverse(), (("y", "x"), ("c", "b", "a")))

    def test_chains_verify_passes_when_every_edge_stays_inside_one_chain(self):
        Chains((Components().chains((C([]), A([]), B([]))))).verify()


class ChainInteriorTests(unittest.TestCase):
    """The two paths inside a chain, which only a chain can reach.

    A wave is one fan and a chain can be long, so a chain checks the cancellation BETWEEN its own steps
    and a read that breaks inside one has a whole chain of siblings still settling beside it."""

    def test_a_cancellation_between_two_steps_of_a_chain_stops_that_chain(self):
        log = []

        class First(Step):
            def apply(self):
                log.append("First")
                return self.unchanged()

        class Second(Step):
            expects = (First,)

            def apply(self):
                log.append("Second")
                return self.unchanged()

        class AfterOne(Cancellation):
            def __init__(self):
                self.seen = [0]

            def cancelled(self):
                self.seen[0] += 1
                return self.seen[0] > 2   # let the run start and the first step through, then fire

        with self.assertRaises(Cancelled):
            asyncio.run(Reconciler((Second(), First()), Components(),
                                   dispatcher=Pipeline(OnError.BestEffort),
                                   cancellation=AfterOne()).converge())
        self.assertEqual(log, ["First"], "the chain kept going past the abort")

    def test_a_broken_read_in_one_chain_raises_after_every_chain_settles(self):
        seen = []

        class Reads(Step):
            def __init__(self, log, breaks=False):
                self.log = log
                self.breaks = breaks

            async def assess(self):
                await asyncio.sleep(0)
                self.log.append(type(self).__name__)
                if self.breaks:
                    raise RuntimeError("the probe broke")
                return self.verified()

        class Alpha(Reads):
            pass

        class Beta(Reads):
            pass

        run = Reconciler((Alpha(seen, breaks=True), Beta(seen)), Components(), dispatcher=Pipeline())
        with self.assertRaises(RuntimeError):
            asyncio.run(run.drift())
        self.assertEqual(sorted(seen), ["Alpha", "Beta"], "a chain was abandoned mid-read")
