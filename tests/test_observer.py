"""Observer hooks fired around each converge pass, plus Chorus composition."""
import logging
import time
import unittest

from cabaxiom import (
    Assessment,
    Chorus,
    DriftItem,
    Fixpoint,
    Journal,
    Logging,
    Observer,
    OnError,
    Parallel,
    Reconciler,
    Retry,
    Span,
    Stamp,
    Step,
    ThreadDispatcher,
    Timing,
)

# The new observability leaves are imported from their module, not the package root: __init__.py is wired
# once, afterwards, so three parallel authors never collide on it.


class _OneFix(Step):
    # Drifts once, then apply() clears it. Enough to make a converge pass do real work.
    def __init__(self) -> None:
        self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("x", "needs fix")]), {}

    def apply(self, inputs):
        changed = self.assess({})[0].deviation   # what this pass is about to fix
        self.__done[0] = True
        return changed, {}


class _Recorder(Observer):
    # Records each hook and its payload names, so a test can assert the order and the contents.
    def __init__(self) -> None:
        self.events: list[tuple] = []

    def began(self) -> None:
        self.events.append(("began",))

    def acted(self, applied) -> None:
        self.events.append(("acted", [item.name for item in applied]))

    def remained(self, residual) -> None:
        self.events.append(("remained", [item.name for item in residual]))


class ObserverTests(unittest.IsolatedAsyncioTestCase):
    async def test_hooks_fire_in_order_around_a_pass(self):
        recorder = _Recorder()
        await Reconciler([_OneFix()], observer=recorder).converge()
        self.assertEqual([event[0] for event in recorder.events], ["began", "acted", "remained"])
        self.assertEqual(recorder.events[1], ("acted", ["x"]))   # acted saw what apply changed
        self.assertEqual(recorder.events[2], ("remained", []))   # nothing remained after the fix

    async def test_default_observer_is_a_silent_no_op(self):
        # No observer means the base Observer, which does nothing, so converge behaves as always.
        self.assertEqual(await Reconciler([_OneFix()]).converge(), [])

    async def test_chorus_relays_to_every_observer(self):
        a, b = _Recorder(), _Recorder()
        await Reconciler([_OneFix()], observer=Chorus(a, b)).converge()
        self.assertEqual([event[0] for event in a.events], ["began", "acted", "remained"])
        self.assertEqual([event[0] for event in b.events], ["began", "acted", "remained"])

    async def test_chorus_is_itself_an_observer_and_nests(self):
        inner, outer = _Recorder(), _Recorder()
        await Reconciler([_OneFix()], observer=Chorus(Chorus(inner), outer)).converge()
        self.assertEqual([event[0] for event in inner.events], ["began", "acted", "remained"])
        self.assertEqual([event[0] for event in outer.events], ["began", "acted", "remained"])

    async def test_an_empty_chorus_is_a_no_op(self):
        self.assertEqual(await Reconciler([_OneFix()], observer=Chorus()).converge(), [])


class _Hooks(Observer):
    # Records every unit-level and teardown hook, so the live-progress surface can be asserted.
    def __init__(self) -> None:
        self.steps: list[tuple] = []
        self.retries: list[tuple] = []
        self.prunes: list[list] = []

    def stepped(self, step, changes, error) -> None:
        self.steps.append((step.__class__.__name__, changes, error.__class__.__name__ if error else None))

    def retried(self, step, attempt, error) -> None:
        self.retries.append((step.__class__.__name__, attempt, str(error)))

    def pruned(self, residue) -> None:
        self.prunes.append([item.name for item in residue])


class ObserverHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_stepped_fires_per_unit_with_changes_and_errors(self):


        class Creates(Step):
            def apply(self, inputs):
                return [DriftItem("svc", "created")], {}

        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("bang")

                return None, {}
        hooks = _Hooks()
        await Reconciler((Creates(), Boom()), mode=Parallel(OnError.BestEffort), observer=hooks).converge()
        names = [(name, error) for name, _, error in hooks.steps]
        self.assertIn(("Creates", None), names)          # a clean unit, with its changes
        self.assertIn(("Boom", "RuntimeError"), names)   # and the failure, seen live

    async def test_a_blocked_step_never_fires_stepped(self):


        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("bang")

                return None, {}
        class Dependent(Step):
            expects = (Boom,)

        hooks = _Hooks()
        await Reconciler((Boom(), Dependent()), mode=Parallel(OnError.BestEffort), observer=hooks).converge()
        self.assertEqual([name for name, _, _ in hooks.steps], ["Boom"])   # the blocked step did not run

    async def test_retried_fires_per_spent_attempt_before_the_pause(self):


        class Flaky(Step):
            def __init__(self) -> None:
                self.tries = [0]

            def assess(self, inputs):
                return Assessment(deviation=[] if self.tries[0] >= 2 else [DriftItem("f", "flaky")]), {}

            def apply(self, inputs):
                self.tries[0] += 1
                if self.tries[0] < 3:
                    raise RuntimeError("transient")

                return None, {}
        hooks = _Hooks()
        await Reconciler((Flaky(),), retry=Retry(3), observer=hooks).converge()
        self.assertEqual([(name, attempt) for name, attempt, _ in hooks.retries],
                         [("Flaky", 1), ("Flaky", 2)])       # two spent attempts announced, success is silent

    async def test_pruned_fires_with_the_teardown_residue(self):
        class Survivor(Step):
            def prune(self, inputs):
                return [DriftItem("vol", "survives")], {}

        hooks = _Hooks()
        await Reconciler((Survivor(),), observer=hooks).prune()
        self.assertEqual(hooks.prunes, [["vol"]])

    async def test_chorus_relays_the_unit_and_teardown_hooks(self):
        a, b = _Hooks(), _Hooks()
        chorus = Chorus(a, b)
        await Reconciler((_OneFix(),), observer=chorus).converge()
        await Reconciler((_OneFix(),), observer=chorus).prune()
        chorus.retried(_OneFix(), 1, RuntimeError("transient"))   # the relay, hook for hook
        for hooks in (a, b):
            self.assertEqual([name for name, _, _ in hooks.steps][:1], ["_OneFix"])
            self.assertEqual(hooks.prunes, [[]])
            self.assertEqual([(name, attempt) for name, attempt, _ in hooks.retries], [("_OneFix", 1)])


class _Staged(Step):
    # Clears one unit of drift per apply() and reports it, so a Fixpoint run takes `passes` recordable passes.
    def __init__(self, passes: int) -> None:
        self.__remaining = [passes]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__remaining[0] == 0 else [DriftItem("s", f"{self.__remaining[0]} left")]), {}

    def apply(self, inputs):
        if self.__remaining[0]:
            self.__remaining[0] -= 1
            return [DriftItem("s", "cleared one")], {}
        return None, {}


class JournalTests(unittest.IsolatedAsyncioTestCase):
    async def test_journal_pairs_applied_with_residual_for_a_single_pass(self):
        journal = Journal()
        await Reconciler([_OneFix()], observer=journal).converge()
        self.assertEqual(len(journal.passes), 1)
        self.assertEqual([item.name for item in journal.passes[0].applied], ["x"])
        self.assertEqual(journal.passes[0].residual, ())

    async def test_journal_records_every_pass_of_a_fixpoint_run_as_data(self):
        journal = Journal()
        await Reconciler([_Staged(2)], convergence=Fixpoint(), observer=journal).converge()
        self.assertEqual(len(journal.passes), 2)
        self.assertEqual([[i.message for i in p.applied] for p in journal.passes],
                         [["cleared one"], ["cleared one"]])
        self.assertEqual([[i.message for i in p.residual] for p in journal.passes], [["1 left"], []])

    async def test_journal_composes_under_chorus(self):
        journal, recorder = Journal(), _Recorder()
        await Reconciler([_OneFix()], observer=Chorus(journal, recorder)).converge()
        self.assertEqual(len(journal.passes), 1)
        self.assertEqual([event[0] for event in recorder.events], ["began", "acted", "remained"])

    async def test_a_recorded_pass_reprs_both_channels(self):
        journal = Journal()
        await Reconciler([_OneFix()], observer=journal).converge()
        self.assertIn("applied=", repr(journal.passes[0]))
        self.assertIn("residual=", repr(journal.passes[0]))

    async def test_a_recorded_pass_cannot_be_rewritten_in_place(self):
        # A Pass is a RECORD: tuple channels behind read-only properties, so the recorded run cannot be
        # falsified after the fact - neither by mutating a channel nor by reassigning one.
        journal = Journal()
        await Reconciler([_OneFix()], observer=journal).converge()
        recorded = journal.passes[0]
        with self.assertRaises(AttributeError):
            recorded.applied = ()
        with self.assertRaises(AttributeError):
            recorded.residual = ()


class _Boom(Step):
    # Fails on write, so the failure channels of both observers have something real to carry.
    def apply(self, inputs):
        raise RuntimeError("bang")


        return None, {}
class _Survivor(Step):
    # Its teardown leaves something behind, which is what the prune hook reports.
    def prune(self, inputs):
        return [DriftItem("vol", "survives")], {}


class LoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_logging_configures_nothing_for_its_host(self):
        # The whole promise - no handler, no level, no basicConfig. A library that wires its host's logging
        # tree has chosen destination and verbosity for a program it does not own.
        root = list(logging.getLogger().handlers)
        logger = logging.getLogger("cabaxiom")
        await Reconciler([_OneFix()], observer=Logging()).converge()
        self.assertEqual(logger.handlers, [])
        self.assertEqual(logger.level, logging.NOTSET)
        self.assertEqual(logging.getLogger().handlers, root)   # nothing added to root either

    async def test_logging_configures_nothing_with_the_root_logger_left_bare(self):
        # The check above cannot fail on its own. pytest's logging plugin has already put a handler on
        # root, where basicConfig is a documented no-op when root has one, so a Logging that DID call it
        # would still pass. Strip root back to bare first, which is the state a plain script starts in,
        # and the promise becomes assertable rather than merely stated.
        root = logging.getLogger()
        installed, level = list(root.handlers), root.level
        root.handlers = []
        try:
            await Reconciler([_OneFix()], observer=Logging()).converge()
            self.assertEqual(root.handlers, [])   # no basicConfig, which is what would land one here
            self.assertEqual(root.level, level)   # and no level set on a tree the kernel does not own
        finally:
            root.handlers = installed

    async def test_logging_emits_the_pass_hooks_under_its_own_logger(self):
        with self.assertLogs("cabaxiom", level="INFO") as captured:
            await Reconciler([_OneFix()], observer=Logging()).converge()
        self.assertEqual([record.levelname for record in captured.records], ["INFO", "INFO", "INFO"])
        self.assertIn("converge pass began", captured.output[0])
        self.assertIn("applied 1 change(s)", captured.output[1])
        self.assertIn("left 0 residual item(s)", captured.output[2])

    async def test_logging_traces_a_settled_unit_at_debug_and_a_failed_one_at_warning(self):
        # A failure logged at DEBUG is a failure nobody reads, so the two branches of stepped part company.
        with self.assertLogs("cabaxiom", level="DEBUG") as captured:
            await Reconciler((_OneFix(), _Boom()), mode=Parallel(OnError.BestEffort), observer=Logging()).converge()
        traced = [(record.levelname, record.getMessage()) for record in captured.records]
        self.assertIn(("DEBUG", "_OneFix settled with 1 change(s)"), traced)
        self.assertIn(("WARNING", "_Boom failed: RuntimeError: bang"), traced)

    def test_logging_announces_a_spent_retry_at_warning(self):
        # Fired before the backoff pause, so this line is what explains a run that looks stalled.
        with self.assertLogs("cabaxiom", level="WARNING") as captured:
            Logging().retried(_OneFix(), 2, RuntimeError("transient"))
        self.assertEqual(captured.records[0].getMessage(),
                         "_OneFix attempt 2 failed, retrying: RuntimeError: transient")

    async def test_logging_reports_what_a_teardown_left_behind(self):
        with self.assertLogs("cabaxiom", level="INFO") as captured:
            await Reconciler((_Survivor(),), observer=Logging()).prune()
        self.assertIn("teardown left 1 survivor(s)", captured.output[-1])

    async def test_logging_takes_the_hosts_own_logger(self):
        # A name is resolved through getLogger, a ready Logger is taken as handed - both land where the host
        # configured, never in a tree the kernel picked for it.
        with self.assertLogs("app.converge", level="INFO") as named:
            await Reconciler([_OneFix()], observer=Logging("app.converge")).converge()
        with self.assertLogs("app.given", level="INFO") as given:
            await Reconciler([_OneFix()], observer=Logging(logging.getLogger("app.given"))).converge()
        self.assertIn("converge pass began", named.output[0])
        self.assertIn("converge pass began", given.output[0])


class _Slow(Step):
    # Sleeps a measurable amount inside apply(), so a timing assertion rests on a real interval rather than
    # on clock noise. One drift item, cleared on the first pass.
    def __init__(self, seconds: float = 0.02) -> None:
        self.__seconds = seconds
        self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.__done[0] else [DriftItem("slow", "needs fix")]), {}

    def apply(self, inputs):
        time.sleep(self.__seconds)
        self.__done[0] = True
        return [DriftItem("slow", "fixed")], {}


class TimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_timing_records_one_span_per_pass_the_way_journal_records_them(self):
        timing = Timing()
        await Reconciler([_Staged(2)], convergence=Fixpoint(), observer=timing).converge()
        self.assertEqual(len(timing.passes), 2)
        self.assertTrue(all(isinstance(span, Span) for span in timing.passes))

    async def test_each_span_keeps_only_the_units_that_settled_inside_it(self):
        # began() opens a pass by clearing the stamps as well as the clock. Without that reset every Span
        # after the first would carry the units of the passes before it, so the count would still look
        # plausible, so the partition is asserted here rather than inferred from len(passes).
        first, second = _Staged(2), _OneFix()
        timing = Timing()
        await Reconciler((first, second), convergence=Fixpoint(), observer=timing).converge()
        opening, closing = timing.passes
        self.assertEqual([stamp.step for stamp in opening.stamps], [first, second])
        self.assertEqual([stamp.step for stamp in closing.stamps], [first, second])
        self.assertTrue(all(stamp.at <= closing.elapsed for stamp in closing.stamps))

    async def test_a_span_measures_the_whole_pass_apply_and_reprobe(self):
        timing = Timing()
        await Reconciler([_Slow(0.02)], observer=timing).converge()
        self.assertGreaterEqual(timing.passes[0].elapsed, 0.02)

    async def test_a_stamp_marks_when_each_unit_settled_within_its_pass(self):
        # A moment, not a duration. The hooks expose no step start, so a Stamp says WHEN a unit settled,
        # measured from the pass its own began() opened.
        slow, quick = _Slow(0.02), _OneFix()
        timing = Timing()
        await Reconciler((slow, quick), observer=timing).converge()
        stamps = timing.passes[0].stamps
        self.assertEqual([stamp.step for stamp in stamps], [slow, quick])   # settle order, the hook's order
        self.assertTrue(all(isinstance(stamp, Stamp) for stamp in stamps))
        self.assertGreaterEqual(stamps[0].at, 0.02)                     # the slow one settled after its sleep
        self.assertGreaterEqual(stamps[1].at, stamps[0].at)             # and the next one after that
        self.assertLessEqual(stamps[-1].at, timing.passes[0].elapsed)   # every mark falls inside the pass

    async def test_timing_sums_the_passes_it_measured(self):
        timing = Timing()
        await Reconciler([_Staged(2)], convergence=Fixpoint(), observer=timing).converge()
        self.assertEqual(timing.elapsed, sum(span.elapsed for span in timing.passes))

    async def test_a_teardown_is_not_timed_because_no_hook_opens_it(self):
        # prune() fires pruned and stepped but never began, so there is no origin to measure from and the
        # units that settled are left unrecorded rather than dated from an invented one.
        timing = Timing()
        await Reconciler((_Survivor(),), observer=timing).prune()
        self.assertEqual(timing.passes, ())
        self.assertEqual(timing.elapsed, 0.0)

    def test_a_hook_arriving_outside_a_pass_is_not_timed(self):
        timing = Timing()
        timing.remained(())        # a close with nothing open records no span rather than a bogus one
        self.assertEqual(timing.passes, ())

    async def test_a_timed_pass_cannot_be_rewritten_in_place(self):
        # A Span and its Stamps are RECORDS, like Pass - read-only, so nobody re-dates a measurement after
        # the run that made it.
        timing = Timing()
        await Reconciler([_OneFix()], observer=timing).converge()
        span = timing.passes[0]
        with self.assertRaises(AttributeError):
            span.elapsed = 0.0
        with self.assertRaises(AttributeError):
            span.stamps = ()
        with self.assertRaises(AttributeError):
            span.stamps[0].at = 0.0
        with self.assertRaises(AttributeError):
            span.stamps[0].step = None

    async def test_the_timing_records_repr_their_measurements(self):
        timing = Timing()
        await Reconciler([_OneFix()], observer=timing).converge()
        self.assertIn("elapsed=", repr(timing.passes[0]))
        self.assertIn("stamps=", repr(timing.passes[0]))
        self.assertTrue(repr(timing.passes[0].stamps[0]).startswith("Stamp(_OneFix, at="))

    async def test_timing_stamps_every_unit_of_a_run_fanned_across_worker_threads(self):
        # ThreadDispatcher runs each blocking apply() on a worker thread, so the unit hook fires from
        # several threads at once and the lock is what keeps every stamp.
        first, second = _Slow(0.02), _Slow(0.02)
        timing = Timing()
        await Reconciler((first, second), mode=ThreadDispatcher(), observer=timing).converge()
        span = timing.passes[0]
        self.assertEqual({stamp.step for stamp in span.stamps}, {first, second})
        self.assertTrue(all(stamp.at <= span.elapsed for stamp in span.stamps))

    async def test_logging_and_timing_compose_under_one_chorus(self):
        # How a caller actually runs two observers. Neither knows the other exists, while a Journal beside
        # them keeps WHAT moved while Timing keeps what it cost.
        timing, journal = Timing(), Journal()
        with self.assertLogs("cabaxiom", level="INFO") as captured:
            await Reconciler([_OneFix()], observer=Chorus(Logging(), timing, journal)).converge()
        self.assertEqual(len(timing.passes), 1)
        self.assertEqual(len(journal.passes), 1)
        self.assertIn("converge pass began", captured.output[0])


class UnitLifecycleHookTests(unittest.IsolatedAsyncioTestCase):
    """The two hooks that close the unit's lifecycle. dispatching is the START stepped never was and
    produced is the lineage seam - which producer produced what, the attribution assemble() deliberately
    merges away for consumers."""

    class _Recorder(Observer):
        def __init__(self):
            self.dispatched: list = []
            self.attributed: list = []

        def dispatching(self, step, inputs):
            self.dispatched.append((step, inputs))

        def produced(self, step, artifacts):
            self.attributed.append((step, artifacts))

    async def test_dispatching_fires_with_the_very_payload_the_step_is_handed(self):
        seen: dict = {}

        class Producer(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://x"}

        class Reader(Step):
            expects = (Producer,)

            def apply(self, inputs):
                seen["inputs"] = dict(inputs)

                return None, {}
        recorder = self._Recorder()
        producer, reader = Producer(), Reader()
        await Reconciler((producer, reader), observer=recorder).converge()
        order = [step for step, _ in recorder.dispatched]
        # Per admitted step, wave by wave - and BOTH phases announce, so a converge lists each step twice:
        # once as the write fans, once as the proving read does.
        self.assertEqual(order, [producer, reader, producer, reader])
        self.assertEqual(dict(recorder.dispatched[1][1]), seen["inputs"])   # the mounted payload itself
        with self.assertRaises(TypeError):
            recorder.dispatched[1][1]["uri"] = "forged"   # a trace reads, never edits what the run mounts

    async def test_produced_attributes_artifacts_per_clean_step_and_skips_a_failure(self):
        class Producer(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://x"}

        class Boom(Step):
            def apply(self, inputs):
                raise RuntimeError("db down")

        recorder = self._Recorder()
        producer = Producer()
        await Reconciler((producer, Boom()), observer=recorder,
                         mode=Parallel(OnError.BestEffort)).converge()
        attributed = {step: dict(artifacts) for step, artifacts in recorder.attributed}
        self.assertEqual(attributed[producer], {"uri": "s3://x"})   # the attribution, per producer
        self.assertEqual(len(attributed), 1)                        # a failed write has nothing to attribute
        with self.assertRaises(TypeError):
            recorder.attributed[0][1]["uri"] = "forged"   # read-only: writing through would corrupt the run

    async def test_a_chorus_relays_both_hooks(self):
        class Quiet(Step):
            def apply(self, inputs):
                return None, {"made": True}

        first, second = self._Recorder(), self._Recorder()
        await Reconciler((Quiet(),), observer=Chorus(first, second)).converge()
        self.assertEqual(len(first.dispatched), len(second.dispatched))
        self.assertEqual(len(first.attributed), len(second.attributed))
        self.assertEqual(len(first.dispatched), 2)   # the write pass and the proving read both announce


class TheReadPhaseIsTracedTests(unittest.IsolatedAsyncioTestCase):
    """A read-only run used to be a blank page. `Dispatcher.probe` took no Observer at all and `assess()`
    passed none, so Journal, Timing, Logging and Recording saw NOTHING of a phase that fans every step,
    mounts every payload and is the half a converge proves itself with. The read announces now."""

    class _Seen(Observer):
        def __init__(self) -> None:
            self.dispatched: list[Step] = []
            self.attributed: list[Step] = []

        def dispatching(self, step, inputs) -> None:
            self.dispatched.append(step)

        def produced(self, step, artifacts) -> None:
            self.attributed.append(step)

    async def test_a_plain_assess_is_no_longer_a_blank_page(self):
        class Looks(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("svc", "drifted")]), {}

        seen = self._Seen()
        step = Looks()
        await Reconciler((step,), observer=seen).assess()
        self.assertEqual(seen.dispatched, [step])   # the read announced, where it used to say nothing

    async def test_the_read_does_not_claim_to_have_produced_anything(self):
        # THE LINE THAT MUST NOT MOVE. A re-probe runs after every converge, so if the read fired produced
        # its (usually empty) reading would land LAST and overwrite the write's attribution in any collector
        # keyed by step - lineage would quietly answer "nothing" for a run that really made something.
        class Makes(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("svc", "pending")]), {}

            def apply(self, inputs):
                return None, {"uri": "s3://made"}

        seen = self._Seen()
        step = Makes()
        await Reconciler((step,), observer=seen).converge()
        self.assertEqual(seen.attributed, [step])      # attributed ONCE, by the write
        self.assertEqual(seen.dispatched, [step, step])   # announced twice, once per phase

    async def test_every_shipped_mode_announces_its_reads(self):
        from cabaxiom import Serial, Supervised, ThreadDispatcher

        class Looks(Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}

        for mode in (Parallel(), Supervised(poll=0.01), ThreadDispatcher(), Serial()):
            with self.subTest(mode=mode.__class__.__name__):
                seen = self._Seen()
                await Reconciler((Looks(),), mode=mode, observer=seen).assess()
                self.assertEqual(len(seen.dispatched), 1)

