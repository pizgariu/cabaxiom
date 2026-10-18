"""Capacity across processes, plus the decision that a denial is a READING rather than a wait.

The axis exists because `contends` could never be it. Contention is mutual exclusion of ONE inside one
resolved partition in one process, derived statically from a placement rule, so a pool of eight is
inexpressible and two coordinators share no exclusion at all.

The load-bearing choice is what happens when a permit is unavailable. Blocking was refused, because a step
suspended on a queue holds its dispatcher slot while the Cancellation cannot fire, so a Deadline would
bound the work and never the waiting. A denied step did not run, is therefore not settled and says so in
the residual - which makes distributed concurrency visible as data instead of hiding it in a coroutine
nobody can see. These pin that choice at every place it shows.
"""
import asyncio
import unittest

from cabaxiom import (
    Assessment,
    Authority,
    Deferred,
    DriftItem,
    Local,
    OnError,
    Parallel,
    Permit,
    Reconciler,
    Retry,
    Step,
    Supervised,
)


class Counted(Step):
    """A step that needs a permit and counts what it did, so a claim can be about writes and not words."""

    def __init__(self, name: str, permit: Permit) -> None:
        self._name = name
        self.leases = (permit,)
        # A LIST created here and mutated in place, never a reassigned attribute. The freeze refuses the
        # obvious counter and it is right to - runtime state on a step is state hiding between passes.
        self._writes: list[int] = []

    @property
    def identifier(self) -> str:
        return self._name

    @property
    def calls(self) -> int:
        return len(self._writes)

    def assess(self, inputs):
        return Assessment(deviation=[] if self._writes else [DriftItem(self._name, "not done")]), {}

    def apply(self, inputs):
        if self._writes:
            return None, {}
        self._writes.append(1)
        return [DriftItem(self._name, "done")], {}


class _Never(Authority):
    """Refuses every ask and records who asked, standing in for a pool other coordinators have filled."""

    def __init__(self, asked: list[str]) -> None:
        self._asked = asked

    def acquire(self, permit: Permit, holder: str) -> bool:
        self._asked.append(holder)
        return False

    def release(self, permit: Permit, holder: str) -> None:
        pass


class Greedy(Authority):
    """Grants up to the capacity and never gives a slot back, standing in for other coordinators holding
    the pool. It implements the port rather than subclassing Local, because Local is @final and because a
    hoarding authority is a different authority and not a variant of the honest one."""

    def __init__(self) -> None:
        self._held: dict[str, int] = {}

    def acquire(self, permit: Permit, holder: str) -> bool:
        taken = self._held.get(permit.name, 0)
        if taken >= permit.capacity:
            return False
        self._held[permit.name] = taken + 1
        return True

    def release(self, permit: Permit, holder: str) -> None:
        pass


class LocalAuthorityTests(unittest.TestCase):
    def test_it_grants_up_to_the_capacity_and_then_refuses(self):
        authority, permit = Local(), Permit("api", 2)
        self.assertEqual([authority.acquire(permit, f"h{n}") for n in range(4)], [True, True, False, False])
        self.assertEqual(authority.held("api"), 2)

    def test_a_release_frees_exactly_one_slot(self):
        authority, permit = Local(), Permit("api", 1)
        authority.acquire(permit, "first")
        self.assertFalse(authority.acquire(permit, "second"))
        authority.release(permit, "first")
        self.assertTrue(authority.acquire(permit, "second"))

    def test_releasing_a_holder_that_never_held_one_is_a_no_op(self):
        # An abort can land between acquire and release, so this is the ordinary case and not the exception.
        Local().release(Permit("api", 1), "never-had-it")

    def test_re_acquiring_the_same_holder_is_not_a_second_slot(self):
        authority, permit = Local(), Permit("api", 1)
        self.assertTrue(authority.acquire(permit, "same"))
        self.assertTrue(authority.acquire(permit, "same"))
        self.assertEqual(authority.held("api"), 1)

    def test_it_never_blocks_even_when_the_pool_is_empty(self):
        # The whole axis rests on this. An authority that waited would reintroduce the suspended step.
        self.assertFalse(Local().acquire(Permit("api", 0), "anyone"))


class DeniedWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_denial_is_drift_and_never_a_failure(self):
        # THE decision, asserted where it matters. Nothing broke, so the failures channel stays empty and
        # the run is still not clean because a step that did not run is not settled.
        permit = Permit("api", 2)
        steps = tuple(Counted(name, permit) for name in "abc")
        residual = await Reconciler(steps, mode=Parallel(OnError.BestEffort),
                                    authority=Greedy()).converge()
        self.assertEqual(list(residual.failures), [])
        self.assertNotEqual(residual, [])
        spoken = " ".join(item.message for item in residual)
        self.assertIn("step deferred", spoken)
        self.assertIn("had none free", spoken)
        self.assertEqual([step.calls for step in steps], [1, 1, 0])

    async def test_the_denied_step_never_ran_at_all(self):
        # A permit refused before the write means the hook was not touched, which is the difference between
        # a capacity limit and an apology.
        permit = Permit("api", 0)
        step = Counted("only", permit)
        await Reconciler((step,), mode=Parallel(OnError.BestEffort), authority=Local()).converge()
        self.assertEqual(step.calls, 0)

    async def test_a_deferral_names_the_pool_and_its_capacity(self):
        # The message has to be actionable at three in the morning, so it names the pool and the size an
        # operator would go and look at rather than only saying no.
        step = Counted("only", Permit("snowflake", 7))
        residual = await Reconciler((step,), mode=Parallel(OnError.BestEffort),
                                    authority=_Never([])).converge()
        spoken = " ".join(item.message for item in residual)
        self.assertIn("'snowflake'", spoken)
        self.assertIn("pool of 7", spoken)

    async def test_a_dependent_of_a_deferred_step_says_waited_and_not_failed(self):
        # The fate carries its own grammar, so a later sentence about it cannot call it a failure.
        permit = Permit("api", 0)
        first = Counted("first", permit)
        second = Counted("second", permit)
        second.uses = (first,)
        residual = await Reconciler((first, second), mode=Parallel(OnError.BestEffort),
                                    authority=Local()).converge()
        spoken = " ".join(item.message for item in residual)
        self.assertIn("step blocked: prerequisite first waited for a permit", spoken)
        self.assertNotIn("first failed", spoken)

    async def test_the_pool_is_released_so_a_later_wave_can_have_it(self):
        # One slot, two steps in sequence. The second gets the slot only because the first gave it back.
        permit = Permit("api", 1)
        first = Counted("first", permit)
        second = Counted("second", permit)
        second.uses = (first,)
        residual = await Reconciler((first, second), authority=Local()).converge()
        self.assertEqual(residual, [])
        self.assertEqual((first.calls, second.calls), (1, 1))

    async def test_a_run_with_no_authority_ignores_the_declaration_entirely(self):
        # The neutral default, the Retry(1) precedent. A declared lease costs nothing until somebody grants.
        step = Counted("only", Permit("api", 0))
        residual = await Reconciler((step,)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.calls, 1)

    async def test_a_retried_write_re_asks_for_its_permit(self):
        # This is what "re-acquired per attempt" means, plus why the permit sits INSIDE the retry loop. A
        # write that failed transiently asks again on its second attempt, so a slot is never held across a
        # backoff it is not using. It does NOT mean a denial is retried - a denial ends the attempts, which
        # the test below pins.
        asked, released = [], []

        class Watching(Authority):
            def acquire(self, seeking: Permit, holder: str) -> bool:
                asked.append(holder)
                return True

            def release(self, seeking: Permit, holder: str) -> None:
                released.append(holder)

        tries = []

        class Flaky(Step):
            leases = (Permit("api", 1),)

            def apply(self, inputs):
                tries.append(1)
                if len(tries) < 2:
                    raise ConnectionError("transient")
                return [DriftItem("flaky", "wrote")], {}

        residual = await Reconciler((Flaky(),), retry=Retry(3), authority=Watching()).converge()
        self.assertEqual(residual, [])
        self.assertEqual(len(tries), 2)
        self.assertEqual(len(asked), 2)        # once per attempt, not once per step
        self.assertEqual(len(released), 2)     # and given back each time, never held across the backoff

    async def test_a_denial_does_not_spend_the_whole_retry_budget(self):
        # Deferred is a BaseException so the retry loop's `except Exception` cannot see it, which is the same
        # reason Skew is one. A permanently full pool costs ONE ask, not the budget.
        asked: list[str] = []
        step = Counted("only", Permit("api", 3))
        await Reconciler((step,), mode=Parallel(OnError.BestEffort), retry=Retry(5),
                         authority=_Never(asked)).converge()
        self.assertEqual(len(asked), 1)

    async def test_the_slot_comes_back_even_when_the_write_raises(self):
        # A slot a dead write still holds is a slot nobody can reclaim, so the release rides a finally.
        authority, permit = Local(), Permit("api", 1)

        class Broken(Step):
            leases = (permit,)

            def apply(self, inputs):
                raise RuntimeError("no")

        await Reconciler((Broken(),), mode=Parallel(OnError.BestEffort),
                         authority=authority).converge()
        self.assertEqual(authority.held("api"), 0)

    async def test_a_deadline_still_bounds_a_run_whose_pool_is_full(self):
        # The reason blocking was refused, proved. A denied step reports and returns, so the run finishes
        # instead of holding a dispatcher slot where no Cancellation could reach it.
        steps = tuple(Counted(str(n), Permit("api", 0)) for n in range(5))
        started = asyncio.get_running_loop().time()
        residual = await Reconciler(steps, mode=Supervised(OnError.BestEffort, poll=0.01),
                                    authority=Local()).converge()
        self.assertLess(asyncio.get_running_loop().time() - started, 5.0)
        self.assertEqual(len(list(residual.failures)), 0)
        self.assertEqual([step.calls for step in steps], [0] * 5)


class StatementChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_statement_keeps_deferrals_apart_from_failures(self):
        permit = Permit("api", 0)

        class Broken(Step):
            def apply(self, inputs):
                raise RuntimeError("broke")

        denied, broken = Counted("denied", permit), Broken()
        residual = await Reconciler((denied, broken), mode=Parallel(OnError.BestEffort),
                                    authority=Local()).converge()
        failures = " ".join(item.message for item in residual.failures)
        self.assertIn("RuntimeError: broke", failures)
        self.assertNotIn("deferred", failures)      # the two kinds never share a channel
        self.assertIn("step deferred", " ".join(item.message for item in residual))

    def test_deferred_is_a_baseexception_so_a_retry_cannot_see_it(self):
        self.assertTrue(issubclass(Deferred, BaseException))
        self.assertFalse(issubclass(Deferred, Exception))


class PolicyIndependenceTests(unittest.IsolatedAsyncioTestCase):
    """A denial reports the same way whatever the error policy, because there is no error to have a policy
    about.

    The clause sat below the OnError check first, where writing the test above found what that costs. Under the
    DEFAULT dispatcher, which is FailFast, a momentarily full pool aborted the run and re-raised a
    BaseException out of converge() - so a capacity limit was indistinguishable from a crash for every caller
    who never chose a policy. Reported now, under all three, pinned here so nobody moves it back."""

    async def test_every_policy_reports_a_denial_rather_than_aborting(self):
        for policy in (OnError.FailFast, OnError.BestEffort, OnError.Halt):
            with self.subTest(policy=policy.name):
                step = Counted("only", Permit("api", 0))
                residual = await Reconciler((step,), mode=Parallel(policy),
                                            authority=Local()).converge()
                self.assertEqual(list(residual.failures), [])
                self.assertIn("step deferred", " ".join(item.message for item in residual))
                self.assertEqual(step.calls, 0)

    async def test_the_default_reconciler_does_not_blow_up_on_a_full_pool(self):
        # The exact shape the bug took. No dispatcher chosen, so FailFast, where a full pool must be a report.
        step = Counted("only", Permit("api", 0))
        residual = await Reconciler((step,), authority=Local()).converge()
        self.assertNotEqual(residual, [])
        self.assertEqual(list(residual.failures), [])

    async def test_an_abort_still_cuts_through_a_deferral(self):
        # Cancelled keeps its precedence, since an abort is not a report about the world.
        from cabaxiom import Cancelled, Flag

        raised = Flag()
        raised.cancel()
        with self.assertRaises(Cancelled):
            await Reconciler((Counted("only", Permit("api", 0)),), cancellation=raised,
                             authority=Local()).converge()


class _Fickle(Authority):
    """Grants the FIRST ask of a run and refuses every later one, which is a pool that filled between two
    attempts of the same write.

    It is the narrowest authority that can build that composition, where the narrowness is the point. A
    permanently full pool denies the first attempt too, so the write never runs and there is no earlier
    failure for anything to remember - which is why _Never above cannot reach this case at all."""

    def __init__(self) -> None:
        self.asks: list[str] = []

    def acquire(self, permit: Permit, holder: str) -> bool:
        self.asks.append(holder)
        return len(self.asks) == 1

    def release(self, permit: Permit, holder: str) -> None:
        pass


class _Breaks(Step):
    """A step whose apply ALWAYS raises, so any sentence saying it did not run is false about it."""

    leases = (Permit("api", 1),)

    def __init__(self) -> None:
        self._runs: list[int] = []   # a list mutated in place, since the frozen Step forbids a counter

    @property
    def runs(self) -> int:
        return len(self._runs)

    def apply(self, inputs):
        self._runs.append(1)
        raise RuntimeError("the write broke")


class APoolThatFillsBetweenTwoAttempts(unittest.IsolatedAsyncioTestCase):
    """A denial may only describe a write that NEVER RAN, which after a real failure it no longer can.

    THE BUG CLASS is this axis crossed with the retry axis, which nothing had crossed in the direction where
    the permit is refused SECOND. The permit is asked per attempt, deliberately, so a pool that fills between
    two tries denies an attempt of a write whose earlier attempt already ran and broke. Deferred is a
    BaseException, so it sailed past the attempt loop's `except Exception` and reached the Ledger as the
    step's only fate - which under the DEFAULT FailFast meant a RuntimeError was swallowed, the failures
    channel came back empty, so the whole residual was a deferral saying "the apply did not run. Nothing
    broke and nothing changed". Every clause of that was false, where a half-written world would have read as a
    clean one waiting for capacity.

    The attempt loop remembers the failure it caught and re-raises THAT instead, so the four cases below are
    the whole surface of the change - the one that moves plus the three that must not."""

    async def test_a_real_failure_already_seen_outranks_a_later_denial(self):
        # CASE B, the defect itself, in the composition it shipped in - no policy chosen, so FailFast, which
        # must abort on a step that broke. The write ran ONCE, because the denial still ends the attempts.
        step, pool = _Breaks(), _Fickle()
        with self.assertRaises(RuntimeError) as broke:
            await Reconciler((step,), retry=Retry(2), authority=pool).converge()
        self.assertEqual(str(broke.exception), "the write broke")
        self.assertEqual(step.runs, 1)
        self.assertEqual(len(pool.asks), 2)   # asked again on the second attempt, refused
        # The denial's own sentence does not ride out as the failure's context, because a traceback closing
        # on "nothing broke and nothing changed" beside the thing that broke is the same lie made longer.
        self.assertTrue(broke.exception.__suppress_context__)

    async def test_the_remembered_failure_lands_in_the_failures_channel_and_the_deferral_is_gone(self):
        # CASE B again under a policy that COLLECTS, so both channels are read rather than inferred from an
        # abort. One step settled once, so a record holding the deferral as well would be a record of two.
        step = _Breaks()
        residual = await Reconciler((step,), mode=Parallel(OnError.BestEffort), retry=Retry(2),
                                    authority=_Fickle()).converge()
        self.assertEqual([item.message for item in residual.failures],
                         ["step failed: RuntimeError: the write broke"])
        spoken = " ".join(item.message for item in residual)
        self.assertNotIn("step deferred", spoken)
        self.assertNotIn("did not run", spoken)

    async def test_a_denial_ends_the_attempts_even_when_a_failure_is_remembered(self):
        # CASE B at a wider budget, which pins the half of the promise a fix could quietly spend. A denial is
        # not retryable, so remembering a failure must not buy the write a third try on a pool it cannot
        # shorten - one run, one ask per attempt, where the third attempt never happens.
        step, pool = _Breaks(), _Fickle()
        with self.assertRaises(RuntimeError):
            await Reconciler((step,), retry=Retry(3), authority=pool).converge()
        self.assertEqual(step.runs, 1)
        self.assertEqual(len(pool.asks), 2)

    async def test_a_denial_with_nothing_broken_behind_it_is_still_a_deferral_under_every_policy(self):
        # CASE A, unchanged, pinned against the guard above rather than assumed from it.
        # PolicyIndependenceTests proves this for the neutral Retry(1), which wraps nothing at all - this
        # proves it for the attempt loop, which is the code that changed. Nothing ever ran, so there is no
        # failure to remember and the denial is the honest fate under all three policies.
        for policy in OnError:
            with self.subTest(policy=policy.name):
                step = _Breaks()
                residual = await Reconciler((step,), mode=Parallel(policy), retry=Retry(2),
                                            authority=_Never([])).converge()
                self.assertEqual(list(residual.failures), [])
                self.assertIn("step deferred", " ".join(item.message for item in residual))
                self.assertEqual(step.runs, 0)

    async def test_a_failure_healed_by_a_later_attempt_is_no_failure_at_all(self):
        # CASE C, unchanged, the one a careless guard breaks. A remembered failure may only be spoken
        # when a DENIAL escapes - re-raised on the way out of a write that recovered, it would turn every
        # transient flake in the tree into a failed step.
        tries = []

        class _Heals(Step):
            leases = (Permit("api", 1),)

            def apply(self, inputs):
                tries.append(1)
                if len(tries) == 1:
                    raise ConnectionError("transient")
                return [DriftItem("heals", "wrote")], {}

        residual = await Reconciler((_Heals(),), retry=Retry(2), authority=Local()).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["wrote"])
        self.assertEqual(len(tries), 2)

    async def test_an_abort_on_a_later_attempt_cuts_through_a_remembered_failure(self):
        # CASE D, unchanged. Cancelled keeps its precedence over everything, an abort being a decision rather
        # than a report about the world, where the loop's `except Exception` cannot see one in the first place.
        from cabaxiom import Cancelled

        tries = []

        class _Aborts(Step):
            leases = (Permit("api", 1),)

            def apply(self, inputs):
                tries.append(1)
                if len(tries) == 1:
                    raise RuntimeError("broke first")
                raise Cancelled("the step aborted itself")

        with self.assertRaises(Cancelled) as cut:
            await Reconciler((_Aborts(),), retry=Retry(3), authority=Local()).converge()
        self.assertEqual(str(cut.exception), "the step aborted itself")
        self.assertEqual(len(tries), 2)   # the abort ended the attempts, so the third was never spent


class AbortKeepsPrecedenceTests(unittest.TestCase):
    """The invariant the policy split had to preserve, tested where it lives.

    Before the split, one condition asked whether the fault was an abort OR the policy was FailFast, so the
    abort clause was covered by whichever arm happened to run. Separating them to lift a denial above the
    policy left the abort arm on its own, where an arm no test drives is an arm a later edit can quietly
    invert. A ferried abort reaches record() from a wire, which is why this drives record() directly rather
    than through a run."""

    @staticmethod
    def _ledger(step, policy):
        from cabaxiom import Observer
        from cabaxiom.core.plan.graph import Graph
        from cabaxiom.core.record.ledger import Ledger

        return Ledger(((step,),), policy, Observer(), Graph((step,)))

    def test_a_ferried_abort_re_raises_under_every_policy(self):
        from cabaxiom import Cancelled

        for policy in (OnError.FailFast, OnError.BestEffort, OnError.Halt):
            with self.subTest(policy=policy.name):
                step = Counted("only", Permit("api", 1))
                ledger = self._ledger(step, policy)
                with self.assertRaises(Cancelled):
                    ledger.record(step, None, {}, Cancelled("worker aborted"))

    def test_a_denial_never_re_raises_under_any_policy(self):
        # The other half of the same clause, plus the reason it moved. An abort cuts through, a denial reports.
        for policy in (OnError.FailFast, OnError.BestEffort, OnError.Halt):
            with self.subTest(policy=policy.name):
                step = Counted("only", Permit("api", 1))
                ledger = self._ledger(step, policy)
                ledger.record(step, None, {}, Deferred("the pool was full"))
                statement = ledger.outcome()
                self.assertEqual(list(statement.failures), [])
                self.assertIn("step deferred", statement.deferred[0].message)
