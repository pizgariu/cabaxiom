"""Step.watch() - the per-step event source a standing run is woken by, empty until a domain fills it."""
import asyncio
import unittest

from cabaxiom import Step


class TheEmptySourceTests(unittest.TestCase):

    def test_a_step_that_overrides_nothing_announces_nothing(self):
        # So a standing loop over it converges once and then sleeps, rather than spinning on a source
        # that keeps saying look again for no reason.
        class Quiet(Step):
            pass

        async def drain():
            return [wake async for wake in Quiet().watch()]

        self.assertEqual(asyncio.run(drain()), [])

    def test_the_empty_source_is_still_an_async_iterator(self):
        # It has to BE one or a loop would have to ask whether each step has a source before using it.
        class Quiet(Step):
            pass

        self.assertTrue(hasattr(Quiet().watch(), "__anext__"))


class ADomainSourceTests(unittest.TestCase):

    def test_a_domain_yields_once_per_thing_it_noticed(self):
        class Polling(Step):
            async def watch(self):
                for _ in range(3):
                    await asyncio.sleep(0)
                    yield None

        async def drain():
            return [wake async for wake in Polling().watch()]

        self.assertEqual(len(asyncio.run(drain())), 3)

    def test_the_wake_carries_no_payload(self):
        # The level-triggered discipline the whole kernel rests on. A wake means look again, never here
        # is what changed. A spurious one costs one clean pass, where an edge-triggered delta would cost
        # correctness the first time a wake was missed, coalesced or delivered twice.
        class Polling(Step):
            async def watch(self):
                yield None

        async def drain():
            return [wake async for wake in Polling().watch()]

        self.assertEqual(asyncio.run(drain()), [None])
