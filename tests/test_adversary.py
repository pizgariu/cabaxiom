"""The Adversary axis - fault injection with the kernel's own shape. One roll decides the strike and
every strike lands as something the run already knows how to speak - an abort cuts through, a drop is a
failure the Ledger records, a delay just slows the step so a Deadline can catch it."""
import random
import unittest

from cabaxiom import Cancelled, DriftItem, OnError, Parallel, Permit, Reconciler, Retry, Step, ThreadDispatcher
from cabaxiom.core.declaration import Authority
from cabaxiom.core.record import Observer
from cabaxiom.laboratory import ChaosDispatcher, Sabotage


class SeededSabotageTests(unittest.IsolatedAsyncioTestCase):
    """A chaos run is worth nothing if it cannot be re-run. The rng is injected, exactly as Jitter's is, so
    a seed pins the strike sequence and a failure a chaos run finds is a REPRODUCTION rather than a story."""

    class _Fine(Step):
        def apply(self, inputs):
            return None, {}

    async def _struck(self, seed):
        # The same declaration under the same seed, run twice. Which steps the dice hit must not depend on
        # anything outside this adversary's own generator.
        chaos = ChaosDispatcher(Parallel(OnError.BestEffort),
                                Sabotage(drop_rate=0.5, rng=random.Random(seed)))
        residual = await Reconciler(tuple(self._Fine() for _ in range(12)), mode=chaos).converge()
        return [item.message for item in residual]

    async def test_one_seed_replays_the_same_strikes(self):
        self.assertEqual(await self._struck(1234), await self._struck(1234))

    async def test_the_module_global_random_cannot_shift_a_seeded_run(self):
        # THE DEFECT THIS CLOSES. The roll used to come off the module-global random, so one unrelated draw
        # between two seeded runs moved the strikes and the run could not be replayed.
        first = await self._struck(7)
        random.random()   # somebody else's draw, anywhere in the process
        self.assertEqual(await self._struck(7), first)

    async def test_two_seeds_strike_differently(self):
        # The pin is a real pin and not a flattened dice. A different seed must reach a different sequence,
        # or the test above would pass on an adversary that never strikes at all.
        self.assertNotEqual(await self._struck(1), await self._struck(99))


class SabotageStrikeTests(unittest.IsolatedAsyncioTestCase):
    """Each strike at rate one, so the dice are loaded and the claim is the strike's own semantics."""

    async def test_an_abort_strike_cuts_the_run_as_a_cancelled(self):
        # An abort is a DECISION, not a failure - the strike raises Cancelled, which cuts through
        # every policy exactly as a real abort would - no residual, no "step failed" impersonation.
        class Fine(Step):
            def apply(self, inputs):
                return None, {}

        chaos = ChaosDispatcher(Parallel(OnError.BestEffort), Sabotage(abort_rate=1.0))
        with self.assertRaises(Cancelled) as cut:
            await Reconciler((Fine(),), mode=chaos).converge()
        self.assertIn("The injected adversary aborted the step", str(cut.exception))

    async def test_a_drop_strike_is_recorded_as_the_steps_failure(self):
        # A drop is transient-network weather - an ordinary exception the Ledger records against the step,
        # blocking its dependents - exactly what a real ConnectionError would do.
        ran = []

        class Fine(Step):
            def apply(self, inputs):
                ran.append("ran")

                return None, {}
        chaos = ChaosDispatcher(Parallel(OnError.BestEffort), Sabotage(drop_rate=1.0))
        residual = await Reconciler((Fine(),), mode=chaos).converge()
        self.assertEqual(ran, [])   # the strike lands BEFORE the write, so the step never ran
        spoken = " ".join(item.message for item in residual)
        self.assertIn("step failed: ConnectionError: The injected adversary dropped the connection", spoken)

    async def test_a_delay_strike_slows_the_step_and_the_run_still_converges(self):
        # A delay is not a fault at all - the step runs late and clean, which is what lets a Deadline be
        # tested against a hung-looking wave without faking one.
        class Fine(Step):
            def apply(self, inputs):
                return [DriftItem("svc", "made")], {}

        chaos = ChaosDispatcher(Parallel(), Sabotage(max_delay=0.0001))
        residual = await Reconciler((Fine(),), mode=chaos).converge()
        self.assertEqual(residual, [])
        self.assertEqual([item.message for item in residual.applied], ["made"])

    async def test_a_sync_hook_rides_the_poison_unharmed(self):
        # The strike closure flattens both hook colours - a plain sync apply is a legal typed override and
        # its produce and artifacts cross the chaos wrapper exactly as an awaited one's do.
        seen = []

        class Producer(Step):
            def apply(self, inputs):
                return None, {"uri": "s3://x"}

        class Reader(Step):
            expects = (Producer,)

            def apply(self, inputs):
                seen.append(inputs["uri"])

                return None, {}
        chaos = ChaosDispatcher(Parallel(), Sabotage())
        await Reconciler((Producer(), Reader()), mode=chaos).converge()
        self.assertEqual(seen, ["s3://x"])


class Counting(Observer):
    """Records every attempt the retry announced, so a strike's place in the stack is read off the run."""

    def __init__(self) -> None:
        self.retries: list[int] = []

    def retried(self, step, attempt, error) -> None:
        self.retries.append(attempt)


class TheStrikeRidesInsideTheRunsOwnLayersTests(unittest.IsolatedAsyncioTestCase):
    """An injected fault is retried exactly as a real one is, because the strike sits INNERMOST.

    THE BUG CLASS is the dispatcher family's founding one, where this is the FOURTH class it shipped in - the
    retry, the probe, the permit and now here. A decorator rebuilt the write stack around a layer that was
    already wrapped. ChaosDispatcher wrapped the whole retry-wrapped callable, so its own strike landed
    OUTSIDE the attempt loop and the backoff this class exists to prove never saw a single injected fault.
    Measured before the fix, Retry(4) against a drop at rate one.

        0 times   ChaosDispatcher(Parallel(BestEffort), Sabotage(drop_rate=1.0))
        3 times   the SAME ConnectionError raised by the STEP, chaos at zero rates

    The fix is Write.relay, the seam the thread bridge and the wire already go through, so the CARRIER lays
    the order and the decorator only says how the call is wrapped."""

    class Fine(Step):
        def apply(self, inputs):
            return None, {}

    class Breaks(Step):
        def apply(self, inputs):
            raise ConnectionError("The injected adversary dropped the connection")

    async def test_an_injected_drop_is_retried_exactly_as_the_same_real_failure_is(self):
        # The equivalence is the whole claim, asserted against a REAL failure rather than against
        # a number, because a hard-coded three would still pass if both sides broke together.
        injected, real = Counting(), Counting()
        await Reconciler((self.Fine(),), mode=ChaosDispatcher(Parallel(OnError.BestEffort), Sabotage(drop_rate=1.0)),
                         retry=Retry(4), observer=injected).converge()
        await Reconciler((self.Breaks(),), mode=ChaosDispatcher(Parallel(OnError.BestEffort), Sabotage()),
                         retry=Retry(4), observer=real).converge()
        self.assertEqual(injected.retries, real.retries)
        self.assertEqual(injected.retries, [1, 2, 3])   # pinned as well, so two broken sides cannot agree

    async def test_a_strike_costs_the_permit_slot_it_would_really_have_held(self):
        # The permit layer is laid back OVER the strike, so an injected fault happens while the write HOLDS
        # its slot, exactly as a real one does. The ask is what proves the order - a strike landing outside
        # the stack drops the write before the pool is ever consulted, so a fault injected to exercise a
        # capacity limit would exercise nothing. And the slot still comes back, because the release sits in
        # that layer's finally rather than anywhere a strike can jump over.
        class Asked(Authority):
            """A pool that always grants and logs every ask. An Authority of its own rather than a subclass
            of Local, which is final for a reason worth respecting even in a test."""

            def __init__(self):
                self.asks = []
                self.holders = set()

            def acquire(self, permit, holder):
                self.asks.append(permit.name)
                self.holders.add(holder)
                return True

            def release(self, permit, holder):
                self.holders.discard(holder)

        class Leased(Step):
            leases = (Permit("chaos", 1),)

            def apply(self, inputs):
                return None, {}

        pool = Asked()
        await Reconciler((Leased(),), mode=ChaosDispatcher(Parallel(OnError.BestEffort), Sabotage(drop_rate=1.0)),
                         retry=Retry(2), authority=pool).converge()
        self.assertEqual(pool.asks, ["chaos", "chaos"])   # asked once per attempt, the strike inside the slot
        self.assertEqual(pool.holders, set())             # and handed back on the way out of each one

    async def test_a_delay_strike_still_lands_before_the_write_and_the_run_still_converges(self):
        # The control for the reordering. A strike that moved INSIDE the stack must still land before the
        # hook it sabotages or the whole axis is measuring the wrong moment.
        ran = []

        class Watched(Step):
            def apply(self, inputs):
                ran.append("ran")

                return [DriftItem("svc", "made")], {}

        residual = await Reconciler((Watched(),), mode=ChaosDispatcher(Parallel(), Sabotage(max_delay=0.0001))).converge()
        self.assertEqual(ran, ["ran"])
        self.assertEqual(residual, [])

    def test_the_bridge_outside_is_the_supported_order_and_the_other_one_is_refused(self):
        # The pairing that cannot be made to work by any change here, so it is REFUSED rather than left
        # silently un-bridging the bridge. relay() answers a plain callable, so whichever decorator
        # relocates last sits innermost - and the thread relocation has to be innermost, because
        # asyncio.to_thread of an async strike layer only BUILDS a coroutine on the worker. Measured at
        # 0.202s on MainThread against 0.102s on two workers with the order reversed.
        with self.assertRaises(ValueError) as refused:
            ChaosDispatcher(ThreadDispatcher(Parallel()), Sabotage())
        self.assertIn("cannot wrap a ThreadDispatcher", str(refused.exception))
        self.assertIn("INSIDE the bridge", str(refused.exception))
        # The supported order still composes. Otherwise the refusal above closes the only door.
        self.assertIsInstance(ThreadDispatcher(ChaosDispatcher(Parallel(), Sabotage())), ThreadDispatcher)


if __name__ == "__main__":
    unittest.main()
