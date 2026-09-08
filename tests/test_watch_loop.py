"""Reconciler.watch() - converge, hand back the residual, then wait for a step to say look again."""
import asyncio
import unittest

from cabaxiom import Reconciler, Settle, Stable, Step


class _Wakes(Step):
    """A step that announces its world a fixed number of times, then goes quiet."""

    def __init__(self, wakes: int, settles_after: int = 1):
        self.wakes = wakes
        self.passes = [0]
        self.settles_after = settles_after

    async def watch(self):
        for _ in range(self.wakes):
            await asyncio.sleep(0)
            yield None

    def assess(self):
        return self.verified() if self.passes[0] >= self.settles_after else self.drifted("not yet")

    def apply(self):
        self.passes[0] += 1
        return self.unchanged()


class TheLoopTests(unittest.TestCase):

    def test_a_declaration_that_announces_nothing_converges_once_and_finishes(self):
        # No source can ever wake it, so hanging on a wake that cannot arrive would be the wrong answer.
        class Quiet(Step):
            def assess(self):
                return self.drifted("never settles")

        async def drive():
            return [len(residual) async for residual in Reconciler((Quiet(),)).watch()]

        self.assertEqual(asyncio.run(drive()), [1])

    def test_it_stops_at_the_first_clean_pass_by_default(self):
        step = _Wakes(wakes=5, settles_after=1)

        async def drive():
            return [len(residual) async for residual in Reconciler((step,)).watch()]

        self.assertEqual(asyncio.run(drive()), [0])

    def test_a_wake_drives_another_converge(self):
        step = _Wakes(wakes=5, settles_after=3)

        async def drive():
            return [len(residual) async for residual in Reconciler((step,)).watch()]

        # dirty, dirty, then clean - one pass per wake until the world settles
        self.assertEqual(asyncio.run(drive()), [1, 1, 0])

    def test_the_settle_axis_decides_when_it_is_done(self):
        step = _Wakes(wakes=5, settles_after=1)

        async def drive():
            return [len(residual) async for residual in
                    Reconciler((step,)).watch(settle=Stable(2))]

        # Stable wants two consecutive clean passes, so the first clean one is not the end
        self.assertEqual(asyncio.run(drive()), [0, 0])

    def test_a_domain_can_refuse_to_ever_be_done(self):
        # A monitor. It ends only because the source runs dry, never because the world looked right.
        class Never(Settle):
            def settled(self, residual):
                return False

        step = _Wakes(wakes=3, settles_after=1)

        async def drive():
            return [len(residual) async for residual in Reconciler((step,)).watch(settle=Never())]

        self.assertEqual(len(asyncio.run(drive())), 4)   # the opening pass plus one per wake

    def test_the_loop_is_lazy_and_a_caller_may_walk_away(self):
        # An infinite source must not be an infinite list. Taking two and leaving cancels the rest.
        class Forever(Step):
            async def watch(self):
                while True:
                    await asyncio.sleep(0)
                    yield None

            def assess(self):
                return self.drifted("never settles")

        async def two():
            taken = []
            async for residual in Reconciler((Forever(),)).watch():
                taken.append(residual)
                if len(taken) == 2:
                    break
            return taken

        self.assertEqual(len(asyncio.run(two())), 2)
