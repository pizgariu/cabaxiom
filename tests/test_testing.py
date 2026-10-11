"""The published doubles - a scripted Staged, a settling Fixable, a RecordingBackoff that keeps the pauses
it never takes, plus a Recording that keeps every Observer hook as data.

The doubles are tested the way the kernel is. Alone for the contract each promises, then inside a real
run, because a double that only behaves under direct calls is a double that will lie the first time a
reconciler drives it.
"""
import time
import unittest

from cabaxiom import (
    Chorus,
    DriftItem,
    Exponential,
    Fixed,
    Fixpoint,
    Idempotence,
    Journal,
    OnError,
    Parallel,
    Reconciler,
    Retry,
    Step,
)
from cabaxiom.testing import Firing, Fixable, Recording, RecordingBackoff, Staged


class StagedTests(unittest.IsolatedAsyncioTestCase):
    """The scripted world. One reading per read, in order, with a refusal past the end."""

    def test_it_answers_its_readings_in_order(self):
        world = Staged([DriftItem("rollout", "pending")], [DriftItem("rollout", "half")], [])
        self.assertEqual([item.message for item in world.assess({})[0].deviation], ["pending"])
        self.assertEqual([item.message for item in world.assess({})[0].deviation], ["half"])
        self.assertEqual(list(world.assess({})[0].deviation), [])

    def test_it_counts_the_readings_it_has_answered(self):
        world = Staged([DriftItem("svc", "one")], [])
        self.assertEqual(world.answered, 0)
        world.assess({})[0].deviation
        self.assertEqual(world.answered, 1)

    def test_the_script_reads_back_as_the_declared_world(self):
        item = DriftItem("svc", "one")
        world = Staged([item], [])
        self.assertEqual(world.script, ((item,), ()))

    def test_the_script_cannot_be_rewritten_through_the_list_that_declared_it(self):
        # Snapshotted at construction, so a caller holding the list it passed cannot change the readings a
        # later pass will meet, which would make a failing run unreproducible from its own source.
        readings = [DriftItem("svc", "one")]
        world = Staged(readings)
        readings.append(DriftItem("svc", "smuggled"))
        self.assertEqual([item.message for item in world.assess({})[0].deviation], ["one"])

    def test_a_read_past_the_script_refuses_instead_of_inventing_one(self):
        world = Staged([DriftItem("svc", "one")])
        world.assess({})[0].deviation
        with self.assertRaises(AssertionError) as refused:
            world.assess({})[0].deviation
        self.assertIn("1 readings", str(refused.exception))
        self.assertIn("reading 2", str(refused.exception))

    def test_an_empty_script_is_refused_at_construction(self):
        with self.assertRaises(ValueError):
            Staged()

    def test_apply_is_a_no_op_and_never_advances_the_script(self):
        # The script advances on the READ, so the world moves whether or not this run touched it. That is
        # what makes Staged the double for drift that clears because something external caught up.
        world = Staged([DriftItem("svc", "one")], [])
        self.assertIsNone(world.apply({})[0])
        self.assertEqual(world.answered, 0)

    def test_one_assess_spends_one_reading_and_fills_only_the_deviation(self):
        # The four read hooks are one assess() now. It reads the script into the deviation channel and
        # leaves the advisory, plan and teardown previews at Step's empty defaults, spending one reading.
        world = Staged([DriftItem("svc", "one")], [])
        assessment, _ = world.assess({})
        self.assertEqual([item.message for item in assessment.deviation], ["one"])
        self.assertEqual((list(assessment.advisory), list(assessment.footprint)), ([], []))
        self.assertEqual(world.answered, 1)

    async def test_a_scripted_world_settles_a_fixpoint_run_that_a_stall_would_have_ended(self):
        # The whole point, end to end. The same drift twice would be terminal for Fixpoint, a backoff turns
        # it into a paced retry, where the third reading is the world catching up.
        world = Staged([DriftItem("rollout", "pending")], [DriftItem("rollout", "pending")], [])
        residual = await Reconciler((world,), convergence=Fixpoint(backoff=RecordingBackoff())).converge()
        self.assertEqual(residual, [])
        self.assertEqual(world.answered, 3)   # every scripted reading spent, none invented

    async def test_a_run_that_outlives_its_script_fails_the_test_instead_of_passing_it(self):
        # The reads sit under no OnError policy, so the refusal propagates out of converge() - carried in the
        # wave's ExceptionGroup - rather than settling into a residual a green assertion would then read.
        world = Staged([DriftItem("rollout", "pending")], [DriftItem("rollout", "moved")])
        run = Reconciler((world,), convergence=Fixpoint(backoff=RecordingBackoff()),
                         mode=Parallel(OnError.BestEffort))
        with self.assertRaises(BaseExceptionGroup) as caught:
            await run.converge()
        self.assertIsInstance(caught.exception.exceptions[0], AssertionError)
class FixableTests(unittest.IsolatedAsyncioTestCase):
    """The ordinary world - wrong until applied, then settled, then idempotent."""

    def test_the_default_settles_on_one_apply(self):
        step = Fixable()
        self.assertEqual([item.message for item in step.assess({})[0].deviation], ["1 left"])
        self.assertIsNone(step.apply({})[0])
        self.assertEqual(list(step.assess({})[0].deviation), [])
        self.assertTrue(step.settled)

    def test_it_takes_as_many_applies_as_it_was_given(self):
        step = Fixable(3)
        for expected in (3, 2, 1):
            self.assertEqual(step.remaining, expected)
            step.apply({})[0]
        self.assertEqual(step.remaining, 0)
        self.assertEqual(step.tries, 3)

    def test_a_settled_step_applies_as_a_no_op_and_spends_no_try(self):
        # Idempotence is the contract every proof in the kernel leans on. A second run must not look
        # like work or the churn hunt convicts an innocent step.
        step = Fixable()
        step.apply({})[0]
        self.assertIsNone(step.apply({})[0])
        self.assertEqual(step.tries, 1)
        self.assertEqual(step.remaining, 0)

    async def test_it_proves_idempotent_under_the_kernels_own_protocol(self):
        self.assertTrue(await Idempotence(Reconciler((Fixable(),))).prove())

    async def test_the_name_is_the_drift_subject_so_two_in_one_run_are_told_apart(self):
        residual = await Reconciler((Fixable(2, name="database"), Fixable(2, name="cache"))).converge()
        self.assertEqual(sorted(item.name for item in residual), ["cache", "database"])

    async def test_reporting_puts_each_productive_apply_on_the_applied_channel(self):
        residual = await Reconciler((Fixable(2, reports=True),), convergence=Fixpoint()).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["applied, 1 left", "applied, 0 left"])

    async def test_a_silent_apply_contributes_nothing_to_the_applied_channel(self):
        residual = await Reconciler((Fixable(),)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(residual.applied, ())

    def test_raising_fails_every_apply_that_does_not_settle_it(self):
        broken = RuntimeError("transient io failure")
        step = Fixable(3, raising=broken)
        for _ in range(2):
            with self.assertRaises(RuntimeError) as caught:
                step.apply({})[0]
            self.assertIs(caught.exception, broken)
        self.assertIsNone(step.apply({})[0])   # the settling try always gets through
        self.assertTrue(step.settled)

    def test_a_single_apply_fixable_never_raises_however_it_was_armed(self):
        # `applies` counts the calls it takes to settle, so the raises are applies - 1 and the default has
        # none. One counter, one meaning, whichever way the step fails.
        self.assertIsNone(Fixable(raising=RuntimeError("never thrown")).apply({})[0])

    async def test_a_flaky_write_settles_within_its_retry_budget(self):
        step = Fixable(3, raising=RuntimeError("transient io failure"))
        residual = await Reconciler((step,), retry=Retry(3)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.tries, 3)   # both failures and the settling try, spent inside one pass

    async def test_an_exhausted_budget_leaves_the_failure_to_the_error_policy(self):
        step = Fixable(5, raising=RuntimeError("transient io failure"))
        with self.assertRaises(RuntimeError):
            await Reconciler((step,), retry=Retry(2)).converge()
        self.assertEqual(step.tries, 2)

    def test_fewer_than_one_apply_is_refused_at_construction(self):
        for bad in (0, -1):
            with self.subTest(applies=bad):
                with self.assertRaises(ValueError):
                    Fixable(bad)


class RecordingBackoffTests(unittest.IsolatedAsyncioTestCase):
    """The pauses asked for, kept as a value, never taken."""

    def test_it_records_the_stall_counts_it_was_paced_with(self):
        backoff = RecordingBackoff()
        backoff.delay(1)
        backoff.delay(2)
        self.assertEqual(backoff.stalls, (1, 2))

    def test_without_a_wrapped_policy_every_pause_is_zero(self):
        backoff = RecordingBackoff()
        backoff.delay(4)
        self.assertEqual(backoff.pauses, (0.0,))

    def test_it_records_what_the_wrapped_policy_asked_for(self):
        backoff = RecordingBackoff(Exponential(base=1, cap=8))
        for stall in range(1, 6):
            backoff.delay(stall)
        self.assertEqual(backoff.pauses, (1.0, 2.0, 4.0, 8.0, 8.0))

    def test_it_answers_zero_however_long_the_wrapped_pause_was(self):
        # Fixpoint yields delay() to whichever reconciler drives it, where that reconciler sleeps on the
        # number it gets back, so the recorder has to answer zero or the pause is taken anyway.
        self.assertEqual(RecordingBackoff(Fixed(30.0)).delay(1), 0.0)

    def test_waiting_records_the_pause_and_returns_without_taking_it(self):
        backoff = RecordingBackoff(Fixed(30.0))
        opened = time.monotonic()
        backoff.wait(1)
        self.assertLess(time.monotonic() - opened, 1.0)
        self.assertEqual(backoff.stalls, (1,))
        self.assertEqual(backoff.pauses, (30.0,))

    async def test_a_paced_fixpoint_run_yields_its_schedule_without_sleeping_through_it(self):
        world = Staged(*([[DriftItem("rollout", "pending")]] * 3), [])
        backoff = RecordingBackoff(Exponential(base=30.0, cap=120.0))
        opened = time.monotonic()
        residual = await Reconciler((world,), convergence=Fixpoint(backoff=backoff)).converge()
        self.assertLess(time.monotonic() - opened, 1.0)     # ninety scripted seconds, none of them taken
        self.assertEqual(residual, [])
        self.assertEqual(backoff.stalls, (1, 2))
        self.assertEqual(backoff.pauses, (30.0, 60.0))

    async def test_it_paces_a_retry_with_the_same_vocabulary(self):
        # Retry and Fixpoint speak one stall vocabulary, so one recorder reads either. This is the path
        # that calls wait() rather than delay().
        backoff = RecordingBackoff(Fixed(45.0))
        step = Fixable(3, raising=RuntimeError("transient io failure"))
        await Reconciler((step,), retry=Retry(3, backoff=backoff)).converge()
        self.assertEqual(backoff.stalls, (1, 2))
        self.assertEqual(backoff.pauses, (45.0, 45.0))


class FiringTests(unittest.IsolatedAsyncioTestCase):
    """One hook call, captured."""

    def test_it_keeps_the_hook_and_what_it_carried(self):
        item = DriftItem("svc", "one")
        firing = Firing("acted", (item,))
        self.assertEqual(firing.hook, "acted")
        self.assertEqual(firing.arguments, ((item,),))

    def test_a_captured_firing_cannot_be_rewritten_in_place(self):
        firing = Firing("began")
        with self.assertRaises(AttributeError):
            firing.hook = "acted"

    def test_a_no_argument_hook_reprs_without_a_trailing_comma(self):
        self.assertEqual(repr(Firing("began")), "Firing('began')")

    def test_a_carrying_hook_reprs_its_arguments(self):
        self.assertEqual(repr(Firing("retried", 1, "boom")), "Firing('retried', 1, 'boom')")


class RecordingTests(unittest.IsolatedAsyncioTestCase):
    """Every hook, as data, readable after the run."""

    async def test_the_pass_hooks_fire_in_order_around_a_converge(self):
        recording = Recording()
        await Reconciler((Fixable(reports=True),), observer=recording).converge()
        self.assertEqual(recording.hooks, ("began", "stepped", "acted", "remained"))

    async def test_a_pass_hook_keeps_what_it_was_handed(self):
        recording = Recording()
        await Reconciler((Fixable(reports=True),), observer=recording).converge()
        acted, = recording.fired("acted")
        self.assertEqual([item.message for item in acted.arguments[0]], ["applied, 0 left"])
        remained, = recording.fired("remained")
        self.assertEqual(remained.arguments, ((),))

    async def test_the_unit_hook_keeps_the_step_its_changes_and_its_failure(self):
        broken = Fixable(2, raising=RuntimeError("bang"))
        recording = Recording()
        await Reconciler((Fixable(reports=True), broken), mode=Parallel(OnError.BestEffort),
                         observer=recording).converge()
        settled, failed = recording.fired("stepped")
        self.assertEqual([item.message for item in settled.arguments[1]], ["applied, 0 left"])
        self.assertIsNone(settled.arguments[2])
        self.assertIs(failed.arguments[0], broken)
        self.assertIsNone(failed.arguments[1])            # a write that raised handed nothing back
        self.assertIsInstance(failed.arguments[2], RuntimeError)

    async def test_a_silent_write_is_kept_as_none_not_flattened_to_empty(self):
        # None is the no-op write and means something other than an empty report, so the trace keeps both.
        recording = Recording()
        await Reconciler((Fixable(),), observer=recording).converge()
        stepped, = recording.fired("stepped")
        self.assertIsNone(stepped.arguments[1])

    async def test_the_retry_hook_keeps_the_step_the_attempt_and_the_failure(self):
        recording = Recording()
        step = Fixable(3, raising=RuntimeError("transient io failure"))
        await Reconciler((step,), retry=Retry(3), observer=recording).converge()
        self.assertEqual([firing.arguments[1] for firing in recording.fired("retried")], [1, 2])
        self.assertEqual([firing.arguments[0] for firing in recording.fired("retried")], [step, step])

    async def test_the_teardown_hook_is_recorded_too(self):
        recording = Recording()
        await Reconciler((Fixable(),), observer=recording).prune()
        pruned, = recording.fired("pruned")
        self.assertEqual(pruned.arguments, ((),))

    async def test_every_firing_reads_back_in_one_ordered_trace(self):
        recording = Recording()
        await Reconciler((Fixable(),), observer=recording).converge()
        self.assertEqual([firing.hook for firing in recording.firings], list(recording.hooks))

    def test_the_trace_is_read_never_edited(self):
        recording = Recording()
        recording.began()
        self.assertIsInstance(recording.firings, tuple)
        with self.assertRaises(AttributeError):
            recording.firings = ()

    def test_a_recorded_sequence_keeps_what_it_was_handed(self):
        # The reconciler reuses its own lists between passes, so a trace that did not snapshot would show
        # every recorded pass holding the last pass's contents.
        recording = Recording()
        applied = [DriftItem("svc", "one")]
        recording.acted(applied)
        applied.append(DriftItem("svc", "smuggled"))
        acted, = recording.fired("acted")
        self.assertEqual([item.message for item in acted.arguments[0]], ["one"])

    def test_asking_for_a_hook_observer_does_not_have_is_refused(self):
        # An empty tuple is exactly what an assertion that nothing fired wants to hear, so a typo would
        # turn a real check green. It refuses instead, naming the six.
        recording = Recording()
        with self.assertRaises(ValueError) as refused:
            recording.fired("acted ")
        self.assertIn("began", str(refused.exception))
        self.assertIn("pruned", str(refused.exception))

    async def test_it_nests_under_chorus_beside_a_journal(self):
        recording, journal = Recording(), Journal()
        await Reconciler((Fixable(),), observer=Chorus(journal, recording)).converge()
        self.assertEqual(len(journal.passes), 1)
        self.assertEqual(recording.hooks, ("began", "stepped", "acted", "remained"))

    async def test_it_records_the_hooks_a_journal_cannot_see(self):
        # The reason the suite kept growing a second observer beside its Journal assertions: Journal
        # records passes, while the unit and teardown hooks are not passes.
        recording = Recording()
        run = Reconciler((Fixable(),), observer=recording)
        await run.converge()
        await run.prune()
        self.assertEqual(set(recording.hooks) - {"began", "acted", "remained"}, {"stepped", "pruned"})


class HonestyTests(unittest.IsolatedAsyncioTestCase):
    """A double that answers outside the real contract teaches a test to pass against a kernel that would
    break, so the shapes the doubles hand back are pinned here rather than assumed."""

    def test_every_double_is_the_citizen_it_stands_in_for(self):
        self.assertIsInstance(Staged([]), Step)
        self.assertIsInstance(Fixable(), Step)

    def test_the_reads_hand_back_a_plain_assessment_that_runs_inline(self):
        # Both doubles answer with a plain (Assessment, artifacts) tuple, not a coroutine, so the async
        # engine takes their reads inline - the shape a sync domain step is entitled to.
        for double in (Staged([DriftItem("svc", "one")]), Fixable()):
            with self.subTest(double=double.__class__.__name__):
                self.assertEqual([(item.name, item.message) for item in double.assess({})[0].deviation], [("svc", "one")]
                                 if isinstance(double, Staged) else [("fixable", "1 left")])

    def test_a_write_hands_back_changes_or_none_never_an_awaitable(self):
        self.assertIsNone(Fixable().apply({})[0])
        reported = Fixable(reports=True).apply({})[0]
        self.assertEqual([(item.name, item.message) for item in reported or ()], [("fixable", "applied, 0 left")])

    def test_the_backoff_hands_back_a_float(self):
        self.assertIsInstance(RecordingBackoff(Fixed(2.5)).delay(1), float)

