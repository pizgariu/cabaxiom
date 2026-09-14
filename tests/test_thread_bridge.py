"""ThreadDispatcher - a blocking domain on the one engine, without blocking the loop it shares."""
import asyncio
import threading
import unittest

from cabaxiom import (
    OnError,
    Parallel,
    Reconciler,
    Retry,
    Serial,
    Step,
    ThreadDispatcher,
)


class BridgeTests(unittest.TestCase):

    def test_a_blocking_write_runs_off_the_calling_thread(self):
        # The whole point. A domain that shells out or talks to a driver with no async form would
        # otherwise stop every coroutine sharing the loop for the duration of its write.
        ran_on = []

        class Blocking(Step):
            def apply(self):
                ran_on.append(threading.current_thread().name)
                return self.unchanged()

        here = threading.current_thread().name
        asyncio.run(Reconciler((Blocking(),), dispatcher=ThreadDispatcher()).converge())
        self.assertEqual(len(ran_on), 1)
        self.assertNotEqual(ran_on[0], here)

    def test_a_blocking_read_moves_too(self):
        # A blocking assess() blocks the loop exactly as a blocking apply() does, so a domain that
        # needed the bridge for one almost always needs it for both.
        ran_on = []

        class Blocking(Step):
            def assess(self):
                ran_on.append(threading.current_thread().name)
                return self.verified()

        here = threading.current_thread().name
        asyncio.run(Reconciler((Blocking(),), dispatcher=ThreadDispatcher()).drift())
        self.assertNotEqual(ran_on[0], here)

    def test_the_retry_is_spent_on_the_far_side_of_the_hop(self):
        # THE ORDERING THAT MATTERS. A caller asking for three tries of a blocking write means three
        # tries OF THE WRITE. Relocating the already-retried callable would put the attempt loop on the
        # far side instead, where that loop awaits its pauses on the event loop, so a worker thread is
        # exactly where it cannot run.
        tries = []

        class Flaky(Step):
            def apply(self):
                tries.append(threading.current_thread().name)
                if len(tries) < 3:
                    raise RuntimeError("transient")
                return self.unchanged()

        asyncio.run(Reconciler((Flaky(),), dispatcher=ThreadDispatcher(), retry=Retry(3)).converge())
        self.assertEqual(len(tries), 3)
        self.assertNotIn(threading.current_thread().name, tries)

    def test_the_bridge_decorates_a_shape_rather_than_replacing_it(self):
        # It is a decorator, so the choice of SHAPE stays orthogonal to the choice of where work runs.
        # A serial blocking domain is a real thing and it should not have to give up either half.
        log = []

        class One(Step):
            def apply(self):
                log.append("One")
                return self.unchanged()

        class Two(Step):
            expects = (One,)

            def apply(self):
                log.append("Two")
                return self.unchanged()

        asyncio.run(Reconciler((Two(), One()), dispatcher=ThreadDispatcher(Serial())).converge())
        self.assertEqual(log, ["One", "Two"])

    def test_the_failure_policy_is_the_underlying_one(self):
        class Boom(Step):
            def apply(self):
                raise RuntimeError("boom")

        residual = asyncio.run(
            Reconciler((Boom(),), dispatcher=ThreadDispatcher(Parallel(OnError.BestEffort))).converge())
        self.assertTrue(any("step failed" in item.message for item in residual))
