"""Reconciler core lifecycle and the reactive watch() standing converge."""
import asyncio
import unittest

from cabaxiom import (
    Assessment,
    Dispatcher,
    DriftItem,
    Explanation,
    Flag,
    OnError,
    Overlap,
    Parallel,
    Reading,
    Reconciler,
    Residual,
    RunMode,
    Statement,
    Step,
    Unresolvable,
    Walk,
)
from support import A, B, Boom, C, Fixable, ReportOnly


class ExplainTests(unittest.IsolatedAsyncioTestCase):
    def test_explain_shows_resolved_waves_and_edges(self):
        log: list = []
        rec = Reconciler((C(log), A(log), B(log)))   # shuffled - Kahn resolves A -> B -> C into waves
        explanation = rec.explain()
        self.assertIsInstance(explanation, Explanation)
        self.assertEqual(explanation.groups, (("A",), ("B",), ("C",)))
        self.assertEqual(dict(explanation.dependencies), {"B": ("A",), "C": ("B",)})        # the resolved arrows
        self.assertEqual(dict(explanation.declared["expects"]), {"B": ("A",), "C": ("B",)})   # sparse: A declares no expects
        self.assertEqual(explanation.declared["needs"], ())                                 # expects-only run: no instance edges to surface
        self.assertEqual(explanation.declared["requires"], ())                              # nor any hard requires edges
        self.assertIn("(A) -> (B) -> (C)", repr(explanation))

    def test_a_slot_that_is_not_a_slot_is_refused_by_name(self):
        # An unused slot is present and empty, so a typo answered the same way read as a run that simply
        # never wrote it. The two are different findings and CPython spells both KeyError.
        explanation = Reconciler((C([]), A([]), B([]))).explain()
        with self.assertRaises(Unresolvable) as refused:
            explanation.declared["expcets"]
        self.assertIn("expcets", str(refused.exception))
        self.assertIn("expects", str(refused.exception))   # the slots it does carry, so the fix is readable
        self.assertEqual(explanation.declared["needs"], ())

    def test_explain_surfaces_instance_needs_edges(self):
        class P(Step):
            pass

        class Q(Step):
            pass

        p = P()
        q = Q()
        q.needs = (p,)   # an instance edge, invisible to `expects`
        explanation = Reconciler((q, p)).explain()
        self.assertEqual(explanation.declared["needs"], (("Q", ("P",)),))   # Q needs P - P (no needs) is omitted
        self.assertEqual(explanation.dependencies, (("Q", ("P",)),))        # and the resolved mapping carries it

    def test_explain_surfaces_hard_requires_edges(self):
        class Guard(Step):
            pass

        class Guarded(Step):
            requires = (Guard,)

        explanation = Reconciler((Guarded(), Guard())).explain()
        self.assertEqual(explanation.declared["requires"], (("Guarded", ("Guard",)),))   # Guarded requires Guard
        self.assertEqual(explanation.declared["expects"], ())                              # requires is not an `expects` edge, so the mappings are sparse
        self.assertEqual(dict(explanation.dependencies), {"Guarded": ("Guard",)})        # resolved all the same

    def test_explain_labels_instances_of_one_kind_apart(self):
        # Two instances of one class used to collapse to one name, so the mappings held duplicate keys whose
        # sides could not be told apart. Labels are per instance now. The first keeps the bare type name (a
        # duplicate-free run reads unchanged) and later ones are numbered in run order.
        class Dir(Step):
            pass

        parent = Dir()
        child = Dir()
        child.needs = (parent,)
        explanation = Reconciler((child, parent)).explain()
        self.assertEqual(explanation.groups, (("Dir",), ("Dir#2",)))
        self.assertEqual(explanation.declared["needs"], (("Dir#2", ("Dir",)),))          # each side its own label
        self.assertEqual(explanation.dependencies, (("Dir#2", ("Dir",)),))

    def test_explain_surfaces_capability_edges(self):
        # The window's anchor edge reaches the structural read too. The resolved mapping carries the fanned
        # arrows (a wanter after EVERY provider), with the declarations saying which capability produced them.
        class Primary(Step):
            provides = frozenset({"database"})

        class Replica(Step):
            provides = frozenset({"database"})

        class Api(Step):
            wants = ("database",)
            demands = ("cache",)

        class Memcache(Step):
            provides = frozenset({"cache"})

        explanation = Reconciler((Api(), Replica(), Primary(), Memcache())).explain()
        self.assertEqual(dict(explanation.dependencies), {"Api": ("Replica", "Primary", "Memcache")})
        self.assertEqual(explanation.declared["wants"], (("Api", ("database",)),))
        self.assertEqual(explanation.declared["demands"], (("Api", ("cache",)),))
        self.assertEqual(dict(explanation.declared["provides"]),
                         {"Replica": ("database",), "Primary": ("database",), "Memcache": ("cache",)})

    def test_explain_omits_a_uses_edge_to_an_absent_instance(self):
        # Derivation is total, so a uses edge pointing outside the run is a dead end. It cannot be
        # labelled and it produced no arrow, so neither mapping shows it.
        class Node(Step):
            pass

        absent = Node()
        present = Node()
        present.uses = (absent,)
        explanation = Reconciler((present,)).explain()
        self.assertEqual(explanation.groups, (("Node",),))
        self.assertEqual(explanation.declared["uses"], ())
        self.assertEqual(explanation.dependencies, ())

    def test_an_explanation_cannot_be_reassigned_in_place(self):
        # The structural read is a RECORD: tuples all the way down, behind read-only properties, so what a
        # run resolved cannot be rewritten after the fact.
        explanation = Reconciler(()).explain()
        with self.assertRaises(AttributeError):
            explanation.groups = ()
        with self.assertRaises(AttributeError):
            explanation.dependencies = ()

    def test_explain_of_empty_run(self):
        explanation = Reconciler(()).explain()
        self.assertEqual(explanation.groups, ())
        self.assertEqual(explanation.dependencies, ())
        self.assertEqual(explanation.declared["expects"], ())
        self.assertEqual(explanation.declared["needs"], ())
        self.assertEqual(explanation.declared["requires"], ())
        self.assertEqual(explanation.declared["wants"], ())
        self.assertEqual(explanation.declared["demands"], ())
        self.assertEqual(explanation.declared["provides"], ())
        self.assertEqual(repr(explanation), "Explanation(())")


class ConvergeTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_reconciler_is_clean(self):
        rec = Reconciler(())
        self.assertEqual(await rec.assess(), [])
        self.assertEqual(await rec.converge(), [])

    async def test_converge_applies_then_reports_clean_residual(self):
        f = Fixable()
        rec = Reconciler((f,))
        self.assertEqual(len(await rec.assess()), 1)   # opening status: drift present
        self.assertEqual(await rec.converge(), [])    # apply -> re-probe -> verified clean
        self.assertTrue(f.applied)

    async def test_report_only_step_surfaces_in_residual_not_crash(self):
        residual = await Reconciler((ReportOnly(),)).converge()
        self.assertEqual(len(residual), 1)
        self.assertEqual(residual[0].name, "svc")
        self.assertEqual(residual[0].message, "still wrong")

    async def test_apply_exception_propagates_not_swallowed(self):
        with self.assertRaises(RuntimeError):
            await Reconciler((Boom(),)).converge()
    async def test_drift_flattens_in_resolved_order(self):
        class D1(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("1", "x")]), {}

        class D2(Step):
            expects = (D1,)

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("2", "y")]), {}

        rec = Reconciler((D2(), D1()))   # shuffled, D1 must come first
        self.assertEqual([d.name for d in await rec.assess()], ["1", "2"])

    async def test_converge_reports_what_apply_changed_on_the_applied_channel(self):
        # A write-oriented step reports its change from apply(). It lands on applied, NOT the residual.
        class Writer(Step):
            def __init__(self):
                self.__written = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                return Assessment(deviation=[] if self.__written[0] else [DriftItem("thing.conf", "out of date")]), {}

            def apply(self, inputs):
                if self.__written[0]:
                    return None, {}
                self.__written[0] = True
                return [DriftItem("thing.conf", "rewrote /etc/thing.conf")], {}

        residual = await Reconciler((Writer(),)).converge()
        self.assertEqual(residual, [])                                       # residual clean, still a plain list
        self.assertEqual([c.message for c in residual.applied], ["rewrote /etc/thing.conf"])

    async def test_applied_is_empty_when_apply_returns_none(self):
        # A step whose apply() returns None (the default, git-hooks style) contributes nothing to applied.
        residual = await Reconciler((Fixable(),)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(residual.applied, ())

    async def test_a_raising_drift_during_the_reprobe_propagates_and_loses_applied(self):
        # Contract pin. The reads have no OnError policy, so a drift() that raises during converge's
        # re-probe propagates - and the applied record is lost with the exception. A step guarding a
        # real invariant keeps drift() total (return Drift, never raise).
        class Fragile(Step):
            def __init__(self):
                self.__touched = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs):
                if self.__touched[0]:
                    raise RuntimeError("probe broke after apply")
                return Assessment(deviation=[DriftItem("f", "needs fix")]), {}

            def apply(self, inputs):
                self.__touched[0] = True
                return [DriftItem("f", "fixed it")], {}

        with self.assertRaises(BaseExceptionGroup) as caught:
            await Reconciler((Fragile(),)).converge()
        self.assertIsInstance(caught.exception.exceptions[0], RuntimeError)
class ResidualTests(unittest.IsolatedAsyncioTestCase):
    def test_the_record_is_frozen_and_sealed(self):
        # The LAST mutable verdict in the family froze - no append, no channel writes, no stray attributes.
        residual = Residual([DriftItem("svc", "still wrong")], applied=[DriftItem("x", "made")])
        with self.assertRaises(AttributeError):
            residual.append(DriftItem("forged", "by hand"))   # type: ignore[attr-defined]
        with self.assertRaises(AttributeError):
            residual.applied = ()   # type: ignore[misc]
        with self.assertRaises(AttributeError):
            residual.appled = []   # the typo still fails loudly instead of minting a ghost attribute

    def test_the_sequence_view_still_compares_and_slices_like_the_list_it_was(self):
        residual = Residual([DriftItem("a", "x"), DriftItem("b", "y")],
                            failures=[DriftItem("a", "x")])
        self.assertEqual(residual, [DriftItem("a", "x"), DriftItem("b", "y")])   # == any sequence, by items
        self.assertEqual(residual[0].name, "a")
        self.assertEqual(residual[1:], (DriftItem("b", "y"),))   # a slice is a plain tuple, channels stay behind
        self.assertTrue(residual)
        self.assertEqual(Residual([]), [])
        self.assertEqual(residual, Residual([DriftItem("a", "x"), DriftItem("b", "y")]))   # and against its own kind
        self.assertNotEqual(residual, object())                                            # anything else is NotImplemented, not a guess

    def test_each_verdict_has_a_factory_that_knows_its_own_channels(self):
        # The constructor stays public, so this pins what the factories carry FOR a caller - which channel a
        # refusal rides beside, that nothing-broke means an empty failures channel, that a teardown's whole
        # statement is its proof. Four reconciler sites used to spell each of those out by hand.
        reason, found, made = DriftItem("policy", "too many"), DriftItem("svc", "drifted"), DriftItem("svc", "made")
        refused = Residual.refused([reason], beside=[found], produced={})
        self.assertEqual(refused, [reason, found])                 # reasons ride beside the verb's channel
        self.assertEqual(refused.vetoed, (reason,))                # and apart, so no caller reads a crash
        self.assertEqual(refused.failures, ())                     # nothing broke
        self.assertEqual(refused.applied, ())                      # nothing was written
        converged = Residual.converged([found], failures=[found], applied=[made], produced=None)
        self.assertEqual((converged.failures, converged.applied, converged.vetoed), ((found,), (made,), ()))
        statement = Statement([DriftItem("a", "survived")], [DriftItem("b", "step failed")], {}, [DriftItem("c", "waited")])
        pruned = Residual.pruned(statement)
        self.assertEqual([item.name for item in pruned], ["a", "b", "c"])   # returns, failures, deferrals - the whole residue
        self.assertEqual(pruned.failures, tuple(statement.failures))
        self.assertEqual(pruned.vetoed, ())

    async def test_the_failures_channel_replaces_the_message_prefix_hunt(self):
        # "Did anything BREAK or is the world merely still drifting" used to mean parsing a prefix out
        # of the message text. It is a channel now, told apart from the re-probe findings in the view.
        residual = await Reconciler((Boom(),), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(len(residual.failures), 1)
        self.assertIn("step failed", residual.failures[0].message)

    def test_repr_shows_every_channel(self):
        residual = Residual([DriftItem("svc", "still wrong")], applied=[DriftItem("thing.conf", "rewrote it")])
        self.assertIn("applied=", repr(residual))
        self.assertIn("failures=", repr(residual))
        self.assertIn("DriftItem('thing.conf', 'rewrote it')", repr(residual))
        self.assertIn("DriftItem('svc', 'still wrong')", repr(residual))


class WatchTests(unittest.IsolatedAsyncioTestCase):
    """watch() is the reactive standing converge. The opening pass runs unconditionally, then each wake
    from a step's watch() generator answers with a full re-converge, while a fired cancellation ends the
    loop between wakes. It replaced the tick-driven Controller. The world drives the cadence now, not a
    timer the caller feeds."""

    class _OneWake(Step):
        """A step whose world moves exactly once. Its watch yields a single wake, then idles forever."""

        async def watch(self):
            yield
            await asyncio.Event().wait()

        def assess(self, inputs):
            return Assessment(deviation=[]), {}

    async def test_the_opening_converge_runs_before_any_wake(self):
        # A watcher that starts on a drifted world says so at once rather than waiting for the world to move.
        seen = []
        async for residual in Reconciler((Fixable(),)).watch():
            seen.append(residual)
            break
        self.assertEqual(seen, [[]])   # one opening converge, with Fixable settling inside it

    async def test_a_single_wake_drives_a_second_converge(self):
        seen = []
        async for residual in Reconciler((self._OneWake(),)).watch():
            seen.append(residual)
            if len(seen) == 2:
                break
        self.assertEqual(len(seen), 2)   # the opening converge, then one woken by the single event

    async def test_a_burst_of_wakes_coalesces_into_one_converge(self):
        # Ten wakes queued during one pass are ONE drifted world. The loop drains the queue after each
        # get, so a wake means "look again", never "look once per event" - and a burst costs one converge,
        # not one per member.
        class _Burst(Step):
            async def watch(self):
                yield
                yield
                await asyncio.Event().wait()

            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        stream = Reconciler((_Burst(),)).watch()
        try:
            await anext(stream)                      # the opening converge
            await anext(stream)                      # ONE converge for the whole burst
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(anext(stream), timeout=0.05)   # the second wake was coalesced away
        finally:
            await stream.aclose()

    async def test_a_fired_cancellation_ends_the_loop_between_wakes(self):
        # The loop consults the cancellation after a wake and before the converge it would drive, so a
        # cancel raised after the opening pass stops the standing run instead of answering the next wake.
        flag = Flag()
        seen = []
        async for residual in Reconciler((self._OneWake(),), cancellation=flag).watch():
            seen.append(residual)
            flag.cancel()
        self.assertEqual(len(seen), 1)   # only the opening converge, the wake met a cancelled loop

    async def test_a_source_that_runs_dry_is_left_behind_while_the_others_keep_the_loop_awake(self):
        # A step whose world announces one move and then falls silent for good is not an error and does
        # not end the standing run. Its monitor finishes and the loop keeps answering the sources still
        # talking, so a declaration mixing a one-shot source with a live one converges on every wake the
        # live one sends.
        moved = asyncio.Event()

        class _Dry(Step):
            async def watch(self):
                yield                              # one move, then the source is exhausted for good

            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        class _Live(Step):
            async def watch(self):
                await moved.wait()
                yield
                await asyncio.Event().wait()

            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        seen = []
        async for residual in Reconciler((_Dry(), _Live())).watch():
            seen.append(residual)
            if len(seen) == 2:
                moved.set()                        # the live source speaks only after the dry one is spent
            if len(seen) == 3:
                break
        self.assertEqual(len(seen), 3)   # the opening converge, one for the dry wake, one for the live wake


class VersionTests(unittest.IsolatedAsyncioTestCase):
    def test_dunder_version_reads_the_installed_distribution(self):
        # One source of truth: __version__ is read back from packaging metadata, never hand-copied.
        import cabaxiom
        self.assertRegex(cabaxiom.__version__, r"^\d+\.\d+\.\d+$")


class ExplanationDiagramTests(unittest.IsolatedAsyncioTestCase):
    """The run drawn. Read-only tooling over what explain() already resolved, so a diagram that disagreed
    with the run would mean explain() itself disagreed with it."""

    def test_dot_declares_every_step_and_every_resolved_arrow(self):
        drawn = Reconciler((A([]), B([]), C([]))).explain().dot()
        self.assertTrue(drawn.startswith("digraph run {"))
        self.assertTrue(drawn.endswith("}"))
        for label in ('[label="A"]', '[label="B"]', '[label="C"]'):
            self.assertIn(label, drawn)
        self.assertIn('n0 -> n1 [label="expects", color="#4c6ef5"];', drawn)
        self.assertIn('n1 -> n2 [label="expects", color="#4c6ef5"];', drawn)

    def test_mermaid_declares_every_step_and_every_resolved_arrow(self):
        drawn = Reconciler((A([]), B([]), C([]))).explain().mermaid()
        self.assertTrue(drawn.startswith("graph LR"))
        self.assertIn('n0["A"]', drawn)
        self.assertIn("n0 -->|expects| n1", drawn)
        self.assertIn("n1 -->|expects| n2", drawn)

    def test_each_group_is_a_cluster_named_by_the_shapes_own_noun(self):
        # The same tuple of labels means opposite things under a wave dispatcher and a walk one, so the
        # group noun is the most load-bearing word on the drawing. It comes off the Partition, never guessed.
        waves = Reconciler((A([]), B([])), mode=Parallel()).explain()
        self.assertEqual(waves.shape, "wave")
        self.assertIn('label="wave 0";', waves.dot())
        self.assertIn('subgraph cluster_0["wave 0"]', waves.mermaid())

        class _WalkRunner(Dispatcher):
            overlaps = Overlap.NEITHER

            async def execute(self, groups, graph, do, cancellation, observer):
                return Statement((), ())

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

        walked = Reconciler((A([]), B([])), mode=RunMode(Walk(), _WalkRunner())).explain()
        self.assertEqual(walked.shape, "leg")
        self.assertIn('subgraph cluster_0["leg 0"]', walked.mermaid())

    def test_two_labels_that_squeeze_to_one_id_stay_two_nodes(self):
        # Spelling an id FROM the label is how `Api#2` and `Api_2` quietly become one node. Ids count.
        class Api(Step):
            pass

        first, second = Api(), Api()
        second.uses = (first,)
        explanation = Reconciler((second, first)).explain()
        self.assertIn('n1 [label="Api#2"]', explanation.dot())
        self.assertIn('n1["Api#2"]', explanation.mermaid())
        self.assertIn("n0 -->|uses| n1", explanation.mermaid())

    def test_an_empty_run_still_draws_a_valid_document(self):
        explanation = Reconciler(()).explain()
        self.assertEqual(explanation.dot().splitlines()[-1], "}")
        self.assertEqual(explanation.mermaid(), "graph LR")

    def test_every_arrow_carries_the_slot_that_produced_it(self):
        # "Why is this here" is the question a surprising order raises, where the answer is the slot. A hard
        # demand and a soft lean on the world are drawn apart, since confusing them is the whole risk.
        class Primary(Step):
            provides = frozenset({"database"})

        class Api(Step):
            wants = ("database",)

        explanation = Reconciler((Api(), Primary())).explain()
        self.assertEqual(explanation.arrows, (("Api", "Primary", "wants"),))
        self.assertIn('color="#2f9e44", style=dashed', explanation.dot())
        self.assertIn("n0 -.->|wants| n1", explanation.mermaid())

    def test_the_resolved_mapping_is_a_projection_of_the_arrows(self):
        # One prerequisite reached by TWO declarations is two arrows and ONE dependency. Storing both
        # views would be two facts nothing kept in agreement, so the mapping is derived, never stored.
        class Primary(Step):
            provides = frozenset({"database"})

        class Api(Step):
            wants = ("database",)
            expects = (Primary,)

        explanation = Reconciler((Api(), Primary())).explain()
        self.assertEqual(explanation.arrows,
                         (("Api", "Primary", "expects"), ("Api", "Primary", "wants")))
        self.assertEqual(explanation.dependencies, (("Api", ("Primary",)),))
