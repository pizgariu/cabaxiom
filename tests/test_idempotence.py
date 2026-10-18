"""Idempotence - a second converge on a settled world must be a clean no-op, proven not just asserted."""
import asyncio
import unittest

from cabaxiom import Assessment, DriftItem, Reconciler, Step
from cabaxiom.laboratory import Idempotence, Proof
from support import Fixable


class IdempotenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_idempotent_reconciler_proves_stable_with_no_churn(self):
        proof = await Idempotence(Reconciler((Fixable(),))).prove()
        self.assertTrue(proof.stable)
        self.assertEqual(proof.churned, ())

    async def test_a_churning_apply_is_caught_even_though_drift_reads_clean(self):
        # The tell of a non-idempotent apply(). drift() always reads clean (so the residual is always empty and
        # hides the problem), yet apply() reports doing work on every converge. The SECOND converge's applied
        # channel is what exposes it.
        class Churner(Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}   # always clean - the residual can never catch this

            def apply(self, inputs):
                return [DriftItem("cache", "rebuilt again")], {}   # but it works every single time

        proof = await Idempotence(Reconciler((Churner(),))).prove()
        self.assertFalse(proof.stable)
        self.assertEqual([item.message for item in proof.churned], ["rebuilt again"])

    async def test_a_reconciler_that_never_converges_is_unstable_via_the_residual_not_the_churn(self):
        # The other failure a single converge cannot tell apart. The world never reaches desired state. apply()
        # is a no-op, so there is no churn. It is the residual that stays non-empty. Surfacing both channels is
        # what lets a Proof distinguish "not idempotent" from "never converged".
        class Stuck(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("svc", "never clears")]), {}

            def apply(self, inputs):
                return None, {}

        proof = await Idempotence(Reconciler((Stuck(),))).prove()
        self.assertFalse(proof.stable)
        self.assertEqual(proof.churned, ())                                    # apply did nothing - not a churn
        self.assertEqual([item.message for item in proof.residual], ["never clears"])

    def test_a_minted_proof_cannot_be_falsified_in_place(self):
        # The verdict is a RECORD: tuple channels behind read-only properties, so neither clearing the
        # churn nor reassigning a channel can flip an unstable proof to stable after it was minted.
        proof = Proof([DriftItem("cache", "rebuilt again")], [])
        self.assertFalse(proof.stable)
        with self.assertRaises(AttributeError):
            proof.churned = ()
        with self.assertRaises(AttributeError):
            proof.residual = ()

    async def test_a_proof_is_truthy_exactly_when_stable(self):
        self.assertTrue(await Idempotence(Reconciler((Fixable(),))).prove())

        class Churner(Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}

            def apply(self, inputs):
                return [DriftItem("cache", "rebuilt again")], {}

        self.assertFalse(await Idempotence(Reconciler((Churner(),))).prove())

    async def test_proof_repr_shows_the_verdict_and_both_channels(self):
        proof = await Idempotence(Reconciler((Fixable(),))).prove()
        self.assertIn("stable=True", repr(proof))
        self.assertIn("churned=()", repr(proof))
        self.assertIn("residual=()", repr(proof))

    async def test_the_harness_is_open_for_a_stricter_check(self):
        # Idempotence is the open base now the twin collapsed onto it. A custom harness subclasses it,
        # inherits the wrapped reconciler and the shared _verdict rule, then shapes its own proving protocol.
        class TripleCheck(Idempotence):
            # A stricter harness. Converge twice, then judge the THIRD converge instead of the second.
            async def prove(self) -> Proof:
                await self._reconciler.converge()
                await self._reconciler.converge()
                return self._verdict(await self._reconciler.converge())

        self.assertTrue(issubclass(TripleCheck, Idempotence))
        proof = await TripleCheck(Reconciler((Fixable(),))).prove()
        self.assertTrue(proof.stable)


class AsyncApplyIdempotenceTests(unittest.IsolatedAsyncioTestCase):
    """The same guarantee for a step whose apply() genuinely awaits I/O: the harness proves stability and
    catches churn identically, the async apply is just another coroutine the engine drives."""

    class _AsyncFix(Step):
        def __init__(self) -> None:
            self.__done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

        def assess(self, inputs):
            return Assessment(deviation=[] if self.__done[0] else [DriftItem("svc", "needs io")]), {}

        async def apply(self, inputs):
            await asyncio.sleep(0)
            self.__done[0] = True

            return None, {}
    async def test_an_idempotent_async_reconciler_proves_stable(self):
        proof = await Idempotence(Reconciler((self._AsyncFix(),))).prove()
        self.assertTrue(proof.stable)
        self.assertEqual(proof.churned, ())

    async def test_a_churning_async_apply_is_caught(self):
        class _AsyncChurner(Step):
            def assess(self, inputs):
                return Assessment(deviation=[]), {}   # always clean

            async def apply(self, inputs):
                await asyncio.sleep(0)
                return [DriftItem("cache", "rebuilt again")], {}   # yet works every converge

        proof = await Idempotence(Reconciler((_AsyncChurner(),))).prove()
        self.assertFalse(proof.stable)
        self.assertEqual([item.message for item in proof.churned], ["rebuilt again"])
