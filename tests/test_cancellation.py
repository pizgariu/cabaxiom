"""Cancellation signals and Quorum composition."""
import unittest

from cabaxiom import (
    AllOf,
    AnyOf,
    Async,
    Cancellation,
    Cancelled,
    Components,
    Deadline,
    Every,
    Flag,
    Kahn,
    Majority,
    Most,
    OnError,
    Parallel,
    Pipeline,
    Quorum,
    Reconciler,
    Serial,
    Step,
)
from support import A, B, Boom, C


class CancellationTests(unittest.TestCase):
    """The injected Cancellation: the executor checks it before each step (Serial) or level (Parallel)
    and raises Cancelled. The default never cancels, so an un-configured Reconciler is unaffected."""

    class _CancelAfter(Cancellation):
        # Cancels once it has been checked more than `checks_allowed` times.
        def __init__(self, checks_allowed: int):
            self.__allowed = checks_allowed
            self.__seen = 0

        def cancelled(self) -> bool:
            self.__seen += 1
            return self.__seen > self.__allowed

    def test_default_never_cancels(self):
        log = []
        Reconciler((A(log), B(log), C(log))).converge()
        self.assertEqual(log, ["A", "B", "C"])

    def test_cancellation_aborts_serial_mid_run(self):
        log = []
        with self.assertRaises(Cancelled):
            Reconciler((A(log), B(log), C(log)), cancellation=self._CancelAfter(2)).converge()
        self.assertEqual(log, ["A", "B"])   # checked before C, raised, C never ran

    def test_cancellation_aborts_parallel_before_a_level(self):
        log = []
        with self.assertRaises(Cancelled):
            Reconciler((C(log), A(log), B(log)), Kahn(), executor=Parallel(),
                       cancellation=self._CancelAfter(1)).converge()
        self.assertEqual(log, ["A"])   # level A ran, checked before level B, raised

    def test_deadline_zero_cancels_before_the_first_step(self):
        log = []
        with self.assertRaises(Cancelled):
            Reconciler((A(log),), cancellation=Deadline(0)).converge()
        self.assertEqual(log, [])

    def test_deadline_rejects_negative_seconds(self):
        # Deadline validates its budget the way Fixpoint validates max_passes - a negative deadline is a bug.
        with self.assertRaises(ValueError):
            Deadline(-1)

    def test_deadline_clock_starts_once_and_reuses_it_across_checks(self):
        # The clock starts on the FIRST check, so construction-to-run latency is not billed. A second check
        # within budget reuses that started stamp instead of restarting it - the already-started branch.
        deadline = Deadline(1000)
        self.assertFalse(deadline.cancelled())   # first check starts the clock, well within budget
        self.assertFalse(deadline.cancelled())   # second check reuses the started stamp, still within budget

    def test_flag_cancels_when_set(self):
        flag = Flag()
        flag.cancel()
        log = []
        with self.assertRaises(Cancelled):
            Reconciler((A(log),), cancellation=flag).converge()
        self.assertEqual(log, [])

    def test_cancelled_names_the_cancellation_that_fired(self):
        # The executor knows WHICH cancellation it consulted - the exception says so, for any consumer
        # that lets it reach a traceback or a log.
        flag = Flag()
        flag.cancel()
        with self.assertRaises(Cancelled) as caught:
            Reconciler((A([]),), cancellation=flag).converge()
        self.assertIn("Flag", str(caught.exception))

    def test_partial_run_is_idempotent_and_resumes(self):
        # After a cancelled converge, a clean re-run completes the rest - steps are idempotent.
        log = []
        steps = (A(log), B(log), C(log))
        with self.assertRaises(Cancelled):
            Reconciler(steps, cancellation=self._CancelAfter(2)).converge()
        Reconciler(steps).converge()   # resume, no cancellation
        self.assertEqual(log.count("C"), 1)


class QuorumTests(unittest.TestCase):
    """Quorum is a composite Cancellation that fires when an injected Rule is met across its members:
    Some (any fired, the default), Every (all fired), Most (strict majority). Quorum is itself a
    Cancellation, so it nests and drops straight into a Reconciler."""

    @staticmethod
    def __fired() -> Flag:
        flag = Flag()
        flag.cancel()
        return flag

    def test_some_is_the_default_and_fires_on_any(self):
        self.assertTrue(Quorum(Cancellation(), self.__fired()).cancelled())    # one member fired -> cancel
        self.assertFalse(Quorum(Cancellation(), Cancellation()).cancelled())   # none fired -> continue

    def test_every_fires_only_when_all_fired(self):
        self.assertFalse(Quorum(self.__fired(), Cancellation(), rule=Every()).cancelled())
        self.assertTrue(Quorum(self.__fired(), self.__fired(), rule=Every()).cancelled())

    def test_most_needs_a_strict_majority(self):
        self.assertTrue(Quorum(self.__fired(), self.__fired(), Cancellation(), rule=Most()).cancelled())   # 2 of 3
        self.assertFalse(Quorum(self.__fired(), Cancellation(), rule=Most()).cancelled())                  # 1 of 2, a tie does not cancel

    def test_some_short_circuits_over_a_generator(self):
        # Quorum polls members lazily, so Some stops at the first that fired without touching the rest.
        polled = []

        class Watching(Cancellation):
            def __init__(self, name, fires):
                self.__name = name
                self.__fires = fires

            def cancelled(self) -> bool:
                polled.append(self.__name)
                return self.__fires

        self.assertTrue(Quorum(Watching("a", True), Watching("b", True)).cancelled())
        self.assertEqual(polled, ["a"])   # b never polled - short-circuited on a

    def test_empty_quorum_is_rejected(self):
        with self.assertRaises(ValueError):
            Quorum()

    def test_quorum_is_a_cancellation_that_nests_and_threads_into_a_run(self):
        log = []
        with self.assertRaises(Cancelled):
            Reconciler((A(log),), cancellation=Quorum(Deadline(30), self.__fired())).converge()
        self.assertEqual(log, [])


class CombinatorTests(unittest.TestCase):
    """AnyOf, AllOf and Majority are named Quorum shortcuts with a rule baked in. Each is a Cancellation
    itself, so it nests into a tree exactly as a raw Quorum does."""

    @staticmethod
    def __fired() -> Flag:
        flag = Flag()
        flag.cancel()
        return flag

    def test_anyof_fires_when_any_member_fires(self):
        self.assertTrue(AnyOf(Cancellation(), self.__fired()).cancelled())
        self.assertFalse(AnyOf(Cancellation(), Cancellation()).cancelled())

    def test_allof_fires_only_when_every_member_fires(self):
        self.assertFalse(AllOf(self.__fired(), Cancellation()).cancelled())
        self.assertTrue(AllOf(self.__fired(), self.__fired()).cancelled())

    def test_majority_needs_a_strict_majority(self):
        self.assertTrue(Majority(self.__fired(), self.__fired(), Cancellation()).cancelled())   # 2 of 3
        self.assertFalse(Majority(self.__fired(), Cancellation()).cancelled())                  # 1 of 2, a tie holds

    def test_combinators_nest_into_a_tree(self):
        # The inner AllOf is a member of the outer AnyOf, so the outer fires when the inner does.
        self.assertTrue(AnyOf(Cancellation(), AllOf(self.__fired(), self.__fired())).cancelled())
        self.assertFalse(AnyOf(Cancellation(), AllOf(self.__fired(), Cancellation())).cancelled())

    def test_an_empty_combinator_is_rejected(self):
        with self.assertRaises(ValueError):
            AnyOf()



class StepRaisedAbortTests(unittest.TestCase):
    """A step that raises Cancelled itself aborts the run, on every executor, under either error policy.

    An abort is a DECISION and a failure is an accident, so BestEffort must never collect one as the other.
    Before this the thread pool and the event loop both took a step-raised abort through their ordinary
    `except Exception` and handed it back as an outcome, where the error policy turned it into a
    `step failed` DriftItem and the run carried on converging a world somebody had stopped."""

    class Aborting(Step):
        def apply(self):
            raise Cancelled("step observed the abort")

    class AsyncAborting(Step):
        async def apply(self):
            raise Cancelled("step observed the abort")

    def test_serial_lets_a_step_raised_abort_through_best_effort(self):
        with self.assertRaises(Cancelled):
            Reconciler((self.Aborting(),), executor=Serial(OnError.BestEffort)).converge()

    def test_parallel_lets_a_step_raised_abort_through_best_effort(self):
        with self.assertRaises(Cancelled):
            with Parallel(OnError.BestEffort) as executor:
                Reconciler((self.Aborting(),), executor=executor).converge()

    def test_pipeline_lets_a_step_raised_abort_through_best_effort(self):
        with self.assertRaises(Cancelled):
            with Pipeline(OnError.BestEffort) as executor:
                Reconciler((self.Aborting(),), Components(), executor=executor).converge()

    def test_the_async_executor_lets_a_step_raised_abort_through_best_effort(self):
        with self.assertRaises(Cancelled):
            Reconciler((self.AsyncAborting(),), executor=Async(OnError.BestEffort)).converge()

    def test_a_greedy_except_clause_can_no_longer_eat_an_abort(self):
        # The whole reason Cancelled is a BaseException. A domain hook guarding its own I/O writes
        # `except Exception` and has said nothing about whether it wants to keep converging a world
        # somebody stopped. Before the re-parent it ate the abort and the run carried on.
        class Greedy(Step):
            seen = []

            def apply(self):
                try:
                    raise Cancelled("step observed the abort")
                except Exception:                       # noqa: BLE001 - the point of the test
                    Greedy.seen.append("swallowed")
                return None

        with self.assertRaises(Cancelled):
            Reconciler((Greedy(),), executor=Serial(OnError.BestEffort)).converge()
        self.assertEqual(Greedy.seen, [], "the abort was caught by an ordinary except clause")

    def test_a_real_failure_is_still_collected_under_best_effort(self):
        # The other half, so the cut-through is not just "everything raises now". An ordinary exception
        # still lands in the residual rather than aborting the run.
        residual = Reconciler((Boom(),), executor=Serial(OnError.BestEffort)).converge()
        self.assertTrue(any("step failed" in item.message for item in residual))
