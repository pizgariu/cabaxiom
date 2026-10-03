"""Parallel and Parallel execution semantics: FailFast vs BestEffort, per-wave fan-out."""
import asyncio
import unittest

from cabaxiom import (
    DFS,
    Arranger,
    Assessment,
    Cancelled,
    Dispatcher,
    DriftItem,
    Flow,
    Graph,
    Kahn,
    Ledger,
    Observer,
    OnError,
    Ordering,
    Overlap,
    Parallel,
    Reading,
    Reconciler,
    RunMode,
    Serial,
    Skew,
    Statement,
    Step,
    Walk,
    WalkPartition,
    Waves,
    WavesPartition,
)
from support import A, B, Boom, C, X, Y, Z


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    """The injected Executor: Parallel (default) and Parallel, plus the OnError failure policy."""

    async def test_serial_is_the_default_and_fails_fast(self):
        # No executor -> Parallel(FailFast), so an apply() exception aborts the whole converge.
        with self.assertRaises(RuntimeError):
            await Reconciler((Boom(),)).converge()
    async def test_best_effort_collects_failures_as_residual_drift(self):
        # BestEffort catches the exception, records it as Drift and keeps applying the rest.
        log = []

        class Ok(Step):
            def apply(self, inputs):
                log.append("ok")

                return None, {}
        residual = await Reconciler((Boom(), Ok()), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(log, ["ok"])                 # sibling still ran after Boom blew up
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    async def test_parallel_preserves_dependency_order_across_waves(self):
        # The level barrier keeps every Step.expects edge even while fanning each level out.
        log = []
        await Reconciler((C(log), A(log), B(log)), Kahn(), mode=Parallel()).converge()
        self.assertEqual(log, ["A", "B", "C"])

    async def test_parallel_runs_every_independent_step(self):
        # One level of independents. Order within is unspecified, yet all must run.
        log = []
        await Reconciler((X(log), Y(log), Z(log)), Kahn(), mode=Parallel()).converge()
        self.assertEqual(sorted(log), ["X", "Y", "Z"])

    async def test_parallel_failfast_reraises_on_the_calling_thread(self):
        with self.assertRaises(RuntimeError):
            await Reconciler((Boom(),), Kahn(), mode=Parallel()).converge()
    async def test_parallel_best_effort_collects_failures(self):
        residual = await Reconciler((Boom(),), Kahn(), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    def test_reconciler_rejects_parallel_with_a_flat_only_ordering(self):
        # DFS yields no real waves (one-wave fallback), so Parallel's Waves shape would ignore expects -> refuse at build.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((A([]),), DFS(), mode=Parallel())
        self.assertIn("Waves", str(ctx.exception))   # the shape names itself, plus the fix
        self.assertIn("Kahn", str(ctx.exception))

    def test_the_wave_shape_and_guard_live_in_arrange_on_any_executor(self):
        # No capability flag. Each executor owns its shape through the Arranger it composes. A custom
        # executor composing Waves rejects a flat-only Ordering (the one-wave fallback would ignore
        # expects) and accepts real Kahn waves - tied to the composed shape, not to the Parallel class.
        class WaveExecutor(Dispatcher):
            overlaps = Overlap.WITHIN

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                return Statement((), ())

        with self.assertRaises(ValueError):
            Reconciler((A([]), B([])), DFS(), mode=RunMode(Waves(), WaveExecutor()))   # DFS one-wave fallback: B beside dep A
        Reconciler((A([]), B([])), Kahn(), mode=RunMode(Waves(), WaveExecutor()))      # Kahn splits A then B - independent

    def test_guard_rejects_a_custom_ordering_whose_waves_violate_after(self):
        # A level-aware Ordering that overrides waves() but returns one wave of DEPENDENT steps passes the
        # capability check, yet a fanning executor would run them together and ignore expects. The structural
        # invariant catches the mis-split at construction.
        class OneBigWave(Ordering):
            def __call__(self, graph):
                return graph.steps

            def waves(self, graph):
                return (graph.steps,)   # everything in one wave, dependencies be damned

        with self.assertRaises(ValueError):
            Reconciler((A([]), B([])), OneBigWave(), mode=Parallel())   # B is after A, same wave

    def test_an_ordering_that_drops_a_step_is_rejected_at_arrange(self):
        # verify() guards placement. The membership guard catches an Ordering that silently loses (or doubles)
        # a step, which would otherwise converge a smaller world with no error. Parallel arranges too, so the
        # guard is universal, not only for the fanning executors.
        class DropsOne(Ordering):
            def __call__(self, graph):
                return graph.steps[:-1]   # silently drops the last step

            def waves(self, graph):
                return (graph.steps[:-1],)   # a wave shape past the split guard, still missing a step

        with self.assertRaises(ValueError) as ctx:
            Reconciler((A([]), B([])), DropsOne(), mode=Parallel())
        self.assertIn("every supplied step exactly once", str(ctx.exception))

    async def test_parallel_routes_what_apply_returns_to_the_applied_channel(self):
        # A step whose apply() returns what it changed. The executor hands those back as its returns list,
        # and converge routes them to the applied channel, keeping them out of the residual.
        class Applied(Step):
            def apply(self, inputs):
                return [DriftItem("svc", "created")], {}

        residual = await Reconciler((Applied(),), Kahn(), mode=Parallel()).converge()
        self.assertEqual(residual, [])                                       # nothing still wrong
        self.assertEqual([item.message for item in residual.applied], ["created"])


class BlockedDependentTests(unittest.IsolatedAsyncioTestCase):
    """Under BestEffort a failed step BLOCKS its transitive dependents. They are not executed against
    state nobody put there, so the residual reports them as blocked, distinct from failed."""

    def _world(self, ran: list):
        # Boom -> Middle -> Leaf is the failing chain. Free is independent and must still run.
        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("prerequisite exploded")

                return None, {}
        class Middle(Step):
            expects = (Boom,)

            def apply(self, inputs):
                ran.append("middle")

                return None, {}
        class Leaf(Step):
            expects = (Middle,)

            def apply(self, inputs):
                ran.append("leaf")

                return None, {}
        class Free(Step):
            def apply(self, inputs):
                ran.append("free")

                return None, {}
        return (Boom(), Middle(), Leaf(), Free())

    def _kinds(self, residual):
        failed = sum("step failed" in item.message for item in residual)
        blocked = sum("step blocked" in item.message for item in residual)
        return failed, blocked

    async def test_serial_blocks_the_transitive_dependents_of_a_failure(self):
        ran: list = []
        residual = await Reconciler(self._world(ran), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(ran, ["free"])                   # the independent step ran, the dependents did not
        self.assertEqual(self._kinds(residual), (1, 2))   # one failed, two transitively blocked
        blocked = [item for item in residual if "blocked" in item.message]
        self.assertTrue(all("prerequisite Boom failed" in item.message for item in blocked))

    async def test_a_step_downstream_of_two_failures_names_both_in_declaration_order(self):
        # The blame used to go to whichever failure fired FIRST, where which of two independent failures
        # fires first is a property of the Ordering. So one declaration with one set of failures read
        # differently under Kahn than under DFS - the blocked SET always agreed, only the sentence moved.
        # Naming every failure the step stands on takes the run order back out of the verdict.
        class Left(Step):
            def apply(self, inputs):
                raise RuntimeError("boom")

                return None, {}
        class Right(Step):
            def apply(self, inputs):
                raise RuntimeError("bang")

                return None, {}
        class Downstream(Step):
            expects = (Left, Right)

        residual = await Reconciler((Left(), Right(), Downstream()),
                                    mode=Parallel(OnError.BestEffort)).converge()
        blocked = [item.message for item in residual if "blocked" in item.message]
        # The message names the prerequisites in DECLARATION order, not the order they happened to fail in,
        # so the verdict is the world's and never the run's - whichever failure the schedule met first.
        self.assertEqual(blocked, ["step blocked: prerequisites Left, Right failed"])

    async def test_parallel_blocks_across_waves_but_not_wave_mates(self):
        ran: list = []
        executor = Parallel(OnError.BestEffort)
        residual = await Reconciler(self._world(ran), Kahn(), mode=executor).converge()
        self.assertEqual(ran, ["free"])                    # Free shares wave 1 with Boom and still ran
        self.assertEqual(self._kinds(residual), (1, 2))

    async def test_an_instance_needs_dependent_is_blocked_too(self):
        # The guard follows every edge kind. An instance-level needs edge blocks exactly like after.
        ran: list = []

        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("exploded")

                return None, {}
        class Needy(Step):
            def apply(self, inputs):
                ran.append("needy")

                return None, {}
        boom = Boom()
        needy = Needy()
        needy.needs = (boom,)
        residual = await Reconciler((boom, needy), mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(ran, [])
        self.assertEqual(self._kinds(residual), (1, 1))

    async def test_failfast_is_unchanged_by_blocking(self):
        ran: list = []
        with self.assertRaises(RuntimeError):
            await Reconciler(self._world(ran), mode=Parallel()).converge()
        self.assertEqual(ran, ["free"])   # Free shares Boom's wave and runs, the dependents never start

    async def test_a_second_failure_reuses_the_built_edge_map_and_a_diamond_blames_once(self):
        # Two independent failures spend one edge-map build (the second fail() reuses it), while a diamond
        # dependent reachable through both arms is blocked exactly once, blamed on the failure that fired.
        ran: list = []

        class BoomA(Step):
            def apply(self, inputs):
                raise RuntimeError("a exploded")

                return None, {}
        class BoomB(Step):
            def apply(self, inputs):
                raise RuntimeError("b exploded")

                return None, {}
        class ArmOne(Step):
            expects = (BoomA,)

            def apply(self, inputs):
                ran.append("arm-one")

                return None, {}
        class ArmTwo(Step):
            expects = (BoomA,)

            def apply(self, inputs):
                ran.append("arm-two")

                return None, {}
        class Join(Step):
            expects = (ArmOne, ArmTwo)

            def apply(self, inputs):
                ran.append("join")

                return None, {}
        steps = (BoomA(), BoomB(), ArmOne(), ArmTwo(), Join())
        residual = await Reconciler(steps, mode=Parallel(OnError.BestEffort)).converge()
        self.assertEqual(ran, [])
        self.assertEqual(self._kinds(residual), (2, 3))    # two failed, both arms + the join blocked once each


class WalkArrangerTests(unittest.IsolatedAsyncioTestCase):
    def test_a_trivial_custom_executor_composes_the_public_walk(self):
        # Walk is the serial-safe shape on the open seam. A custom executor composes it, publishes it as
        # its arranger and inherits the covers-guarded level walk without reimplementing it - the third
        # built-in beside Waves and Chains. The reconciler resolves the run through exactly this read.
        from cabaxiom import Walk

        class Custom(Dispatcher):
            overlaps = Overlap.NEITHER

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                return Statement((), ())

        steps = (A([]), B([]))
        partition = RunMode(Walk(), Custom()).resolve(Kahn(), Graph(steps))
        self.assertEqual([[s.__class__.__name__ for s in level] for level in partition], [["A"], ["B"]])

    def test_walk_still_guards_an_ordering_that_drops_a_step(self):
        from cabaxiom import Walk

        class Drops(Ordering):
            def __call__(self, graph):
                return graph.steps[:-1]

            def waves(self, graph):
                return (graph.steps[:-1],)

        steps = (A([]), B([]))
        with self.assertRaises(ValueError):
            Walk().arrange(Drops(), Graph(steps))


class InheritedGuardTests(unittest.IsolatedAsyncioTestCase):
    """arrange() is concrete and owns resolution's guards, so a custom shape inherits them instead of being
    trusted to remember them. The seam is shape(), which builds and nothing else - a subclass never gets the
    chance to write the sequence, so it never gets the chance to leave a guard out."""

    class _Naive(Arranger):
        """The whole of a custom shape - build the partition, nothing else. It says it is walked in
        order by BUILDING a WalkPartition, so the rule and the shape cannot disagree."""

        def shape(self, ordering, graph):
            return WalkPartition((tuple(ordering(graph)),))

    def _custom(self):
        naive = self._Naive()

        class Custom(Dispatcher):
            overlaps = Overlap.NEITHER

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                return Statement((), ())

        return RunMode(naive, Custom())

    def test_a_custom_shape_inherits_the_hard_presence_rule(self):
        # The exact hole this replaced. A four-line Arranger used to converge a run whose `requires` named
        # a step nobody supplied, because demand() lived only inside the abstract entry point.
        class Network(Step):
            pass

        class Api(Step):
            requires = (Network,)

        with self.assertRaises(ValueError) as ctx:
            Reconciler((Api(),), mode=self._custom())
        self.assertIn("requires Network", str(ctx.exception))

    def test_a_custom_shape_inherits_the_coverage_guard(self):
        class Drops(Ordering):
            def __call__(self, graph):
                return graph.steps[:-1]

        steps = (A([]), B([]))
        with self.assertRaises(ValueError) as ctx:
            self._Naive().arrange(Drops(), Graph(steps))
        self.assertIn("must return every supplied step exactly once", str(ctx.exception))

    def test_a_custom_shape_that_is_sound_still_resolves(self):
        first, second = A([]), B([])
        resolved = Reconciler((first, second), mode=self._custom()).explain()
        self.assertEqual(resolved.groups, (("A", "B"),))

    def test_the_seam_is_shape_and_not_the_entry_point(self):
        self.assertEqual(set(Arranger.__abstractmethods__), {"shape"})

    def test_the_shape_declares_its_rule_by_the_partition_it_returns(self):
        # The same groups, two shapes. One group holding a dependency and its dependent is legal for a
        # walk (the dependency comes first) and illegal for a fan (the whole group runs at once). The rule
        # rides the Partition the seam RETURNS, so a shape cannot claim one and hand back the other.
        class Flat(Ordering):
            def __call__(self, graph):
                return graph.steps

            def waves(self, graph):
                return (graph.steps,)

        class Fanning(Arranger):
            def shape(self, ordering, graph):
                return WavesPartition((tuple(ordering(graph)),))

        first, second = A([]), B([])   # B declares expects=(A,)
        steps = (first, second)
        self.assertIsNotNone(self._Naive().arrange(Flat(), Graph(steps)))
        with self.assertRaises(ValueError):
            Fanning().arrange(Flat(), Graph(steps))

    def test_a_serial_walk_is_verified_too_so_a_reversed_order_is_refused(self):
        # The shipped kernel used to accept this. A Walk never verified, so a walking executor silently
        # applied the steps backwards. The Walk shape verifies now, so a custom dispatcher composing it
        # refuses the reversed declaration at construction.
        class Backwards(Ordering):
            def __call__(self, graph):
                return tuple(reversed(graph.steps))

            def waves(self, graph):
                return (tuple(reversed(graph.steps)),)

        first, second = A([]), B([])
        with self.assertRaises(ValueError) as ctx:
            Reconciler((first, second), Backwards(), mode=self._custom())
        self.assertIn("earlier in the walk", str(ctx.exception))


class HaltTests(unittest.IsolatedAsyncioTestCase):
    """OnError.Halt, the third failure policy - stop like FailFast, report like BestEffort. The whole
    policy lives in the Ledger's one raise-or-collect rule, so every executor inherits it with no
    executor-side change - the gates they already ask (blocked / admit) carry the halt."""

    async def test_halt_records_the_failure_and_skips_everything_after_it(self):
        # A dependency chain, so the halt has later waves to skip: Front runs, Boom fails in the next wave
        # and halts the run, so the two waves after it are reported skipped (naming the culprit) instead
        # of running - and converge returns, never raises.
        log = []

        class Front(Step):
            def apply(self, inputs):
                log.append("Front")
                return None, {}

        class Boom(Step):
            expects = (Front,)

            def apply(self, inputs):
                raise RuntimeError("boom")

        class Mid(Step):
            expects = (Boom,)

            def apply(self, inputs):
                log.append("Mid")
                return None, {}

        class Tail(Step):
            expects = (Mid,)

            def apply(self, inputs):
                log.append("Tail")
                return None, {}

        residual = await Reconciler((Front(), Boom(), Mid(), Tail()), mode=Parallel(OnError.Halt)).converge()
        self.assertEqual(log, ["Front"])
        messages = [item.message for item in residual]
        self.assertEqual(sum("step failed" in message for message in messages), 1)
        self.assertEqual(sum("step skipped: the run halted after Boom failed" in message for message in messages), 2)

    async def test_halt_keeps_the_applied_channel_failfast_would_lose(self):
        # The policy's whole point. The caller still learns what the run DID change before it stopped,
        # where FailFast's raise would unwind straight through converge() and lose the applied channel.
        class Creates(Step):
            def apply(self, inputs):
                return [DriftItem("made", "created the thing")], {}

        residual = await Reconciler((Creates(), Boom()), mode=Parallel(OnError.Halt)).converge()
        self.assertEqual([item.message for item in residual.applied], ["created the thing"])

    async def test_halt_lets_the_failing_wave_settle_under_parallel(self):
        # The wave is a barrier: Boom's wave-mate A still runs (it was in flight when the failure
        # settled), while the later waves (B, then C) never start - each reported skipped.
        log = []
        executor = Parallel(OnError.Halt)
        residual = await Reconciler((A(log), Boom(), B(log), C(log)), Kahn(), mode=executor).converge()
        self.assertEqual(log, ["A"])
        self.assertEqual(sum("step skipped" in item.message for item in residual), 2)

    async def test_a_cancelled_still_cuts_through_halt(self):
        # An abort is a decision, not a failure. It is never recorded and it propagates under Halt too.
        class Aborting(Step):
            def apply(self, inputs):
                raise Cancelled("step observed the abort")

                return None, {}
        with self.assertRaises(Cancelled):
            await Reconciler((Aborting(),), mode=Parallel(OnError.Halt)).converge()
    async def test_halt_gates_teardown_so_the_proof_stays_honest(self):
        # prune() has no re-probe, so an unrun teardown must be visible. Teardown runs in reverse build
        # order, so TearsDown (built last) is torn down first. Its failing prune halts the run and Stands,
        # whose prune would have run in a later teardown wave, is reported skipped rather than left standing.
        class Stands(Step):
            def prune(self, inputs):
                return [], {}

        class TearsDown(Step):
            expects = (Stands,)

            def prune(self, inputs):
                raise RuntimeError("teardown dies")

        residual = await Reconciler((Stands(), TearsDown()), mode=Parallel(OnError.Halt)).prune()
        messages = sorted(item.message for item in residual)
        self.assertEqual(len(messages), 2)
        self.assertIn("step failed", messages[0])
        self.assertIn("step skipped: the run halted after TearsDown failed", messages[1])


class PooledProbeAggregationTests(unittest.IsolatedAsyncioTestCase):
    """The group is a barrier even for a broken read, in BOTH colours. The pooled probe used to re-raise
    whichever failure pool.map met first, so the same three-way breakage told less truth under Parallel
    than under Parallel - one diagnostic pass now surfaces every broken read at once, mirroring the
    async family exactly."""

    class _Broken(Step):
        def __init__(self, name: str):
            self.name = name

        def assess(self, inputs):
            raise RuntimeError(f"{self.name} broke")

            return Assessment(), {}
    class _Fine(Step):
        def assess(self, inputs):
            return Assessment(deviation=[DriftItem("fine", "absent")]), {}

    async def test_every_broken_read_in_a_group_raises_together(self):
        # The barrier is the wave. Two broken reads in ONE wave must surface together, instead of the
        # first-raised hiding the second until the next run.
        with self.assertRaises(ExceptionGroup) as caught:
            await Reconciler((self._Broken("one"), self._Broken("two")), mode=Parallel()).assess()
        messages = sorted(str(error) for error in caught.exception.exceptions)
        self.assertEqual(messages, ["one broke", "two broke"])

    async def test_the_surviving_reads_still_settle_before_the_group_raises(self):
        # The barrier half of the promise. A broken sibling does not vaporise the findings the healthy
        # reads produced - they settled, the group then raised and nothing ran twice to prove it.
        with self.assertRaises(ExceptionGroup):
            await Reconciler((self._Fine(), self._Broken("one")), mode=Parallel()).assess()

    async def test_a_cancelled_read_cuts_through_alone(self):
        # An abort is a decision, never part of the diagnosis - the same sift the async probe runs.
        class Aborting(Step):
            def assess(self, inputs):
                raise Cancelled("abort")

        with self.assertRaises(Cancelled):
            await Reconciler((Aborting(), self._Broken("two")), mode=Parallel()).assess()


class LedgerPublishesWhatItRecordsOverTests(unittest.IsolatedAsyncioTestCase):
    """A Ledger publishes its groups for reading, so a custom executor can ask what it is recording over
    instead of threading them through its own state - and read-only, because the record's whole discipline
    is that it is returned, never reached into."""

    async def test_the_groups_are_readable_in_the_direction_the_caller_walks(self):
        seen: list[tuple[tuple[Step, ...], ...]] = []

        class Asking(Dispatcher):
            overlaps = Overlap.NEITHER

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                ledger = self._ledger(groups, observer, graph)
                seen.append(ledger.groups)
                return ledger.outcome()

        first, second = A([]), B([])
        reconciler = Reconciler((first, second), mode=RunMode(Walk(), Asking()))
        await reconciler.converge()
        await reconciler.prune()
        self.assertEqual(seen[0], ((first,), (second,)))   # converge walks the partition forward
        self.assertEqual(seen[1], ((second,), (first,)))   # a teardown walks it back and says so

    def test_the_groups_cannot_be_re_pointed_mid_run(self):
        ledger = Ledger((), OnError.FailFast, Observer(), Graph(()))
        with self.assertRaises(AttributeError):
            ledger.groups = ((A([]),),)   # type: ignore[misc]


class OverlapPairingTests(unittest.IsolatedAsyncioTestCase):
    """The pairing between an executor and the shape it composes, which nothing checked.

    A pooled executor handed the serial-safe Walk constructed without a word and then ran a step BESIDE
    its own declared prerequisite, reporting the pass clean - reproduced before this guard was written.
    The check derives rather than declares. A shape already states its ordering rule as a Placement, so
    whether a dependency may share a group with its dependent is a question that rule can be asked, where a
    custom Partition answers it for free.
    """

    class _Schema(Step):
        def assess(self, inputs):
            return Assessment(deviation=[DriftItem("Schema", "pending")]), {}

    class _Seed(Step):
        def assess(self, inputs):
            return Assessment(deviation=[DriftItem("Seed", "pending")]), {}

    def setUp(self):
        self._Seed.expects = (self._Schema,)

    def _steps(self):
        return (self._Seed(), self._Schema())

    def test_an_executor_that_never_says_where_it_overlaps_is_refused(self):
        class Silent(Dispatcher):
            def __init__(self):
                super().__init__(Walk())

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                return Statement((), ())

        with self.assertRaises(TypeError) as refused:
            Silent()
        self.assertIn("Silent declares no overlaps", str(refused.exception))

    def test_a_fanner_composing_the_serial_shape_is_refused_at_construction(self):
        # THE BUG. Walk's rule is "earlier in the walk", so a dependency may share a group with its
        # dependent - correct for one thread, a silent wrong run for anything that fans that group.
        class Mine(Dispatcher):
            overlaps = Overlap.WITHIN

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                return Statement((), ())

        with self.assertRaises(ValueError) as refused:
            Reconciler(self._steps(), DFS(), mode=RunMode(Walk(), Mine()))
        spoken = str(refused.exception)
        self.assertIn("runs the steps inside one group at the same time", spoken)
        self.assertIn("WalkPartition", spoken)
        self.assertIn("beside its own prerequisite", spoken)

    def test_a_chain_fanner_composing_the_wave_shape_is_refused(self):
        # The other direction. Waves are ordered BETWEEN groups, so an executor that overlaps the groups
        # would run a wave beside the wave it depends on.
        class Crossed(Dispatcher):
            overlaps = Overlap.ACROSS

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                return Statement((), ())

        with self.assertRaises(ValueError) as refused:
            Reconciler(self._steps(), Kahn(), mode=RunMode(Waves(), Crossed()))
        self.assertIn("runs the groups at the same time", str(refused.exception))

    def test_every_shipped_pairing_is_honest(self):
        from cabaxiom import Supervised, ThreadDispatcher

        for executor in (Parallel(), Supervised(), ThreadDispatcher()):
            with self.subTest(mode=executor.__class__.__name__):
                Reconciler(self._steps(), Kahn(), mode=executor)

    def test_a_decorator_answers_for_the_worker_it_wraps_and_not_for_itself(self):
        # THE HOLE THE GUARD USED TO HAVE, plus the reason a green suite proved nothing about it. Every pure
        # decorator fans nothing ITSELF and truthfully declares NEITHER, so a guard reading the CLASS
        # attribute short-circuited and waved any shape through. A wave fanner wrapped in the chaos axis or
        # the thread bridge walked a CHAIN shape, ran a step beside its own prerequisite, handed it an empty
        # payload and reported the run clean - while the identical BARE pairing was correctly refused. The
        # decorator answers for the pair now, so wrapping cannot launder a mismatch.
        from cabaxiom import Chains, ChaosDispatcher, Components, Sabotage, ThreadDispatcher
        from cabaxiom.dispatcher import _Gather

        with self.assertRaises(ValueError):
            Reconciler(self._steps(), Components(), mode=RunMode(Chains(), _Gather()))   # the bare mismatch
        wrapped = (
            ChaosDispatcher(RunMode(Chains(), _Gather()), Sabotage()),
            ThreadDispatcher(RunMode(Chains(), _Gather())),
        )
        for decorated in wrapped:
            with self.subTest(decorator=decorated.__class__.__name__):
                with self.assertRaises(ValueError) as refused:
                    Reconciler(self._steps(), Components(), mode=decorated)
                self.assertIn("beside its own prerequisite", str(refused.exception))

    def test_a_serial_executor_walks_any_shape(self):
        # Overlap.NEITHER asks the rule nothing, because there is nothing to overlap.
        for shape in (Walk(), Waves()):
            with self.subTest(shape=shape.__class__.__name__):
                class Quiet(Dispatcher):
                    overlaps = Overlap.NEITHER

                    async def probe(self, groups, graph, read, cancellation, observer):
                        return Reading(())

                    async def execute(self, groups, graph, do, cancellation, observer):
                        return Statement((), ())

                Reconciler(self._steps(), Kahn(), mode=RunMode(shape, Quiet()))


class HaltWithoutAFailureTests(unittest.IsolatedAsyncioTestCase):
    """Standing a run still for a reason that is not a failure, without lying about one.

    The stop-and-still-report path used to be reachable only through record() with an exception, so an
    error budget, a canary verdict or an operator pause had to impersonate a failure to get there - and
    that lie lands in the exact channel Idempotence and Isolation read as evidence.
    """

    def _budgeted(self, allowance):
        class Budgeted(Dispatcher):
            overlaps = Overlap.NEITHER

            async def probe(self, groups, graph, read, cancellation, observer):
                return Reading(())

            async def execute(self, groups, graph, do, cancellation, observer):
                ledger = self._ledger(groups, observer, graph)
                attempt = self._attempt(do)
                spent = 0
                for group in groups:
                    for step in group:
                        if ledger.blocked(step):
                            continue
                        if spent >= allowance:
                            ledger.halt(step)      # not a failure. A decision.
                            ledger.blocked(step)
                            continue
                        spent += 1
                        _, produced, artifacts, failure = await attempt((step, ledger.assemble(step)))
                        ledger.record(step, produced, artifacts, failure)
                return ledger.outcome()

        return RunMode(Walk(), Budgeted())

    async def test_a_spent_budget_stops_the_run_and_records_no_failure(self):
        log: list[str] = []
        residual = await Reconciler((A(log), B(log), C(log)), mode=self._budgeted(1)).converge()
        spoken = [item.message for item in residual.failures]
        self.assertTrue(spoken, "the run stood still, so the record must say which steps never ran")
        for message in spoken:
            with self.subTest(message=message):
                self.assertIn("step skipped", message)
                self.assertNotIn("step failed", message)

    async def test_a_budget_that_covers_the_run_halts_nothing(self):
        log: list[str] = []
        residual = await Reconciler((A(log), B(log), C(log)), mode=self._budgeted(99)).converge()
        self.assertEqual(list(residual.failures), [])

    def test_the_first_reason_to_stop_is_the_one_the_recap_names(self):
        # The run halted when it halted. A second reason does not rewrite the first.
        log: list[str] = []
        first, second = A(log), B(log)
        ledger = Ledger(((first, second),), OnError.Halt, Observer(), Graph((first, second)))
        ledger.halt(first)
        ledger.halt(second)
        ledger.blocked(second)
        failures = ledger.outcome().failures
        self.assertIn(first.__class__.__name__, failures[0].message)

    def test_a_decision_to_stop_speaks_no_verb_over_the_step_it_stopped_at(self):
        # halt() exists so a non-failure stop stops impersonating a failure, yet one place still undid that.
        # the skipped sentence spelled "the run halted after X failed" by hand, so an error budget or an
        # operator pause accused a step that never raised. A decision names the step it halted AT.
        log: list[str] = []
        first, second = A(log), B(log)
        ledger = Ledger(((first, second),), OnError.Halt, Observer(), Graph((first, second)))
        ledger.halt(first)
        ledger.blocked(second)
        failures = ledger.outcome().failures
        self.assertEqual(failures[0].message, "step skipped: the run halted at A")
        self.assertNotIn("failed", failures[0].message)

    def test_a_halt_behind_a_real_failure_still_names_the_failure(self):
        # The counterpart, plus the reason the fate is READ rather than assumed. When the run really did
        # stand still because a step raised, the sentence is exactly what it always was.
        log: list[str] = []
        first, second = A(log), B(log)
        ledger = Ledger(((first, second),), OnError.Halt, Observer(), Graph((first, second)))
        ledger.record(first, None, {}, RuntimeError("db down"))
        ledger.blocked(second)
        failures = ledger.outcome().failures
        self.assertEqual(failures[0].message, "step failed: RuntimeError: db down")
        self.assertEqual(failures[1].message, "step skipped: the run halted after A failed")

    def test_a_halt_behind_a_skew_says_the_write_did_not_settle(self):
        # A skewed write may well have LANDED, so neither its own line nor the sentence its dependents read
        # may call it a failure. Both words come off the one fate the record kept.
        log: list[str] = []
        first, second = A(log), B(log)
        ledger = Ledger(((first, second),), OnError.Halt, Observer(), Graph((first, second)))
        ledger.record(first, None, {}, Skew("the apply ran on the worker"))
        ledger.blocked(second)
        failures = ledger.outcome().failures
        self.assertEqual(failures[0].message, "step unconfirmed: Skew: the apply ran on the worker")
        self.assertEqual(failures[1].message, "step skipped: the run halted after A did not settle")


class SerialModeTests(unittest.IsolatedAsyncioTestCase):
    """Serial is the shipped single-file run mode. The Walk shape walked one step at a time by the private
    _Walker. It fans nothing, so it overlaps nothing and can walk any shape - and it inherits the Ledger,
    the failure policy, the artifact merge and the Cancellation check rather than re-deriving any of them,
    which is the whole reason it is worth shipping over letting every caller hand-roll it."""

    def _chain(self, log):
        class First(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("first", "pending")]), {}

            def apply(self, inputs):
                log.append("First")
                return [DriftItem("first", "made first")], {"token": "from-first"}

        class Second(Step):
            expects = (First,)

            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("second", "pending")]), {}

            def apply(self, inputs):
                log.append(f"Second saw {inputs.get('token')}")
                return None, {}

        return First(), Second()

    async def test_the_steps_run_one_at_a_time_in_resolved_order_carrying_artifacts(self):
        log: list[str] = []
        first, second = self._chain(log)
        residual = await Reconciler((second, first), mode=Serial()).converge()   # handed shuffled
        self.assertEqual(log, ["First", "Second saw from-first"])   # resolved order, with the payload arriving
        self.assertEqual([item.message for item in residual.applied], ["made first"])

    async def test_a_failure_blocks_its_dependent_exactly_as_a_fanned_run_does(self):
        # The whole point of inheriting the Ledger. The serial walk asks blocked() per step, so a dependent
        # of a failed step is reported blocked rather than run against state nobody put there.
        ran: list[str] = []

        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("first exploded")

        class After(Step):
            expects = (Boom,)

            def apply(self, inputs):
                ran.append("after")
                return None, {}

        residual = await Reconciler((Boom(), After()), mode=Serial(OnError.BestEffort)).converge()
        self.assertEqual(ran, [])   # the dependent never ran
        messages = [item.message for item in residual]
        self.assertEqual(sum("step failed" in message for message in messages), 1)
        self.assertEqual(sum("step blocked" in message for message in messages), 1)

    async def test_the_cancellation_is_checked_between_steps(self):
        # A serial walk has no wave to settle, so the abort lands on the very next step.
        from cabaxiom import Cancelled, Flag

        flag = Flag()
        ran: list[str] = []

        class Trips(Step):
            def apply(self, inputs):
                ran.append("trips")
                flag.cancel()
                return None, {}

        class Never(Step):
            expects = (Trips,)

            def apply(self, inputs):   # pragma: no cover - the abort lands before it
                ran.append("never")
                return None, {}

        with self.assertRaises(Cancelled):
            await Reconciler((Trips(), Never()), mode=Serial(), cancellation=flag).converge()
        self.assertEqual(ran, ["trips"])

    async def test_the_read_serves_a_coroutine_assess_and_a_plain_one_alike(self):
        # The read walk takes both colours, exactly as the wave fan does, then collects every channel the
        # assess answered with - not only the deviations converge re-probes for.
        class Coroutine(Step):
            async def assess(self, inputs):
                return Assessment(deviation=[DriftItem("async", "unconverged")], plan=[DriftItem("async", "would fix")]), {}

        class Plain(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("plain", "unconverged")], advisory=[DriftItem("plain", "note")],
                                  footprint=[DriftItem("plain", "owns a file")]), {}

        reading = await Reconciler((Coroutine(), Plain()), mode=Serial()).assess()
        self.assertEqual(sorted(item.name for item in reading), ["async", "plain"])
        self.assertEqual([item.message for item in reading.plan], ["would fix"])
        self.assertEqual([item.message for item in reading.advisory], ["note"])
        self.assertEqual([item.message for item in reading.footprint], ["owns a file"])

    async def test_the_read_honours_an_abort_between_steps_too(self):
        # A Deadline must bound the proof phase as firmly as it bounds the work, which on a serial walk
        # means the check sits between the reads.
        from cabaxiom import Cancelled, Flag

        flag = Flag()
        read: list[str] = []

        class Trips(Step):
            def assess(self, inputs):
                read.append("trips")
                flag.cancel()
                return Assessment(deviation=[]), {}

        class Never(Step):
            expects = (Trips,)

            def assess(self, inputs):   # pragma: no cover - the abort lands before it
                read.append("never")
                return Assessment(deviation=[]), {}

        with self.assertRaises(Cancelled):
            await Reconciler((Trips(), Never()), mode=Serial(), cancellation=flag).assess()
        self.assertEqual(read, ["trips"])

    def test_a_serial_mode_walks_any_shape_because_it_overlaps_nothing(self):
        # Overlap.NEITHER asks the shape's rule nothing, so the one mode that fans nothing is the one mode
        # that is safe against every partition - including the chain shape no wave worker may walk.
        from cabaxiom import Chains, Components
        from cabaxiom.dispatcher import _Walker

        Reconciler((A([]), B([])), Components(), mode=RunMode(Chains(), _Walker()))
        Reconciler((A([]), B([])), Kahn(), mode=Serial())


class FlowModeTests(unittest.IsolatedAsyncioTestCase):
    """Flow removes the wave barrier. A step starts when ITS OWN prerequisites settle, not when the slowest
    member of its wave does. It reads the Graph rather than the seating, so it carries the two things the
    seating used to carry for it - the edges and contention."""

    async def test_a_chain_overtakes_a_slow_straggler_it_does_not_depend_on(self):
        # THE WHOLE POINT, measured rather than asserted about. Under a wave barrier the chain waits for the
        # straggler once per wave. Under Flow it never waits for it at all, so the run costs the SLOWEST
        # PATH instead of the sum of the slowest members.
        order: list[str] = []

        class Straggler(Step):
            def assess(self, inputs):
                return Assessment(deviation=[] if "Straggler" in order else [DriftItem("s", "pending")]), {}

            async def apply(self, inputs):
                await asyncio.sleep(0.12)
                order.append("Straggler")
                return None, {}

        def linked(name, after):
            class Link(Step):
                expects = after

                def assess(self, inputs):
                    return Assessment(deviation=[] if name in order else [DriftItem(name, "pending")]), {}

                async def apply(self, inputs):
                    await asyncio.sleep(0.01)
                    order.append(name)
                    return None, {}

            Link.__name__ = name
            return Link

        First = linked("First", ())
        Second = linked("Second", (First,))
        Third = linked("Third", (Second,))
        residual = await Reconciler((Straggler(), First(), Second(), Third()), mode=Flow()).converge()
        self.assertEqual(residual, [])
        # The chain finished BEFORE the straggler it shares no edge with - impossible under a barrier.
        self.assertEqual(order, ["First", "Second", "Third", "Straggler"])

    async def test_it_still_holds_every_declared_edge(self):
        # The freedom is bounded by the declaration and nothing else. A dependent may never precede its
        # prerequisite, however fast it would be to start it.
        order: list[str] = []

        class Early(Step):
            async def apply(self, inputs):
                await asyncio.sleep(0.02)
                order.append("Early")
                return None, {"token": "made"}

        class Late(Step):
            expects = (Early,)

            def apply(self, inputs):
                order.append(f"Late saw {inputs.get('token')}")
                return None, {}

        await Reconciler((Late(), Early()), mode=Flow()).converge()
        self.assertEqual(order, ["Early", "Late saw made"])   # the edge held, the payload arrived

    async def test_two_steps_that_contend_never_overlap_even_without_a_seating(self):
        # THE CONSTRAINT THE SEATING USED TO CARRY. `contends` is enforced by the arranger pushing rivals
        # into different groups - and this worker ignores groups, so it must hold the promise itself or
        # break it silently, which is the one thing this kernel refuses.
        inside: list[int] = []
        peak: list[int] = []

        class Rival(Step):
            contends = frozenset({"the-lock"})

            async def apply(self, inputs):
                inside.append(1)
                peak.append(len(inside))
                await asyncio.sleep(0.02)
                inside.pop()
                return None, {}

        await Reconciler((Rival(), Rival(), Rival()), mode=Flow()).converge()
        self.assertEqual(max(peak), 1)   # never two rivals in flight at once

    async def test_a_failure_blocks_its_dependents_and_leaves_independents_alone(self):
        ran: list[str] = []

        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("flow failure")

        class Downstream(Step):
            expects = (Boom,)

            def apply(self, inputs):   # pragma: no cover - blocked, never reached
                ran.append("downstream")
                return None, {}

        class Free(Step):
            def apply(self, inputs):
                ran.append("free")
                return None, {}

        residual = await Reconciler((Boom(), Downstream(), Free()), mode=Flow(OnError.BestEffort)).converge()
        self.assertEqual(ran, ["free"])
        messages = [item.message for item in residual]
        self.assertEqual(sum("step failed" in message for message in messages), 1)
        self.assertEqual(sum("step blocked" in message for message in messages), 1)

    async def test_failfast_raises_the_failure_bare_as_every_other_mode_does(self):
        # The tasks run under a TaskGroup, so a raise inside one arrives as a group. Flow unwraps a single
        # ordinary failure, because `except RuntimeError` at the converge call site is the contract the
        # whole dispatcher family keeps.
        with self.assertRaises(RuntimeError):
            await Reconciler((Boom(),), mode=Flow()).converge()

    async def test_an_abort_cuts_through_as_itself(self):
        from cabaxiom import Cancelled, Flag

        flag = Flag()

        class Trips(Step):
            def apply(self, inputs):
                flag.cancel()
                return None, {}

        class After(Step):
            expects = (Trips,)

            def apply(self, inputs):   # pragma: no cover - the abort lands before it
                return None, {}

        with self.assertRaises(Cancelled):
            await Reconciler((Trips(), After()), mode=Flow(), cancellation=flag).converge()

    async def test_the_read_side_keeps_the_wave_contract(self):
        # A probe writes nothing, so there is no barrier worth removing - and reusing the wave fan keeps a
        # Flow run's diagnosis identical to every other mode's.
        class Looks(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("svc", "drifted")]), {}

        drift = await Reconciler((Looks(),), mode=Flow()).assess()
        self.assertEqual([item.message for item in drift], ["drifted"])

    def test_it_walks_any_shape_because_it_governs_its_own_concurrency(self):
        # Overlap.EDGES: the worker leans on no seating, so the pairing guard has nothing to refuse.
        from cabaxiom import Chains, Components
        from cabaxiom.dispatcher import _Flow

        Reconciler((A([]), B([])), Components(), mode=RunMode(Chains(), _Flow()))
        Reconciler((A([]), B([])), Kahn(), mode=RunMode(Waves(), _Flow()))

    async def test_a_teardown_runs_the_dependent_down_first(self):
        # THE BUG THIS PINS. It shipped nowhere because the gate caught it. A teardown is the same
        # partition INVERTED, so a worker that always read `dependencies` would tear a thing down while its
        # dependent still stood - measured backwards every time before the seat index decided the direction.
        order: list[str] = []

        class Base(Step):
            def prune(self, inputs):
                order.append("Base")
                return None, {}

        class Dependent(Step):
            expects = (Base,)

            def prune(self, inputs):
                order.append("Dependent")
                return None, {}

        await Reconciler((Base(), Dependent()), mode=Flow()).prune()
        self.assertEqual(order, ["Dependent", "Base"])

    async def test_two_independent_failures_arrive_together_because_nothing_serialises_them(self):
        # The honest cost of removing the barrier, pinned rather than hidden. A wave settles fully and then
        # records IN ORDER, so FailFast always re-raises the first failure in resolved order. Flow has no
        # such moment, so two independent failures that settle together arrive together.
        class BoomLeft(Step):
            def apply(self, inputs):
                raise RuntimeError("left")

        class BoomRight(Step):
            def apply(self, inputs):
                raise RuntimeError("right")

        with self.assertRaises(BaseExceptionGroup) as raised:
            await Reconciler((BoomLeft(), BoomRight()), mode=Flow()).converge()
        self.assertEqual(sorted(str(failure) for failure in raised.exception.exceptions), ["left", "right"])

