"""A hook's reply is believed only in the shape the Ledger reads. Anything else is refused with the step's name.

Every local dispatcher unpacked the reply bare, so a hook that fell off the end gave CPython's `cannot unpack`
with no step named and a write returning a string spread it into the applied channel letter by letter."""
import unittest

from cabaxiom import Assessment, DriftItem, OnError, Parallel, Reconciler, Retry, Serial, Step


class _Drifts(Step):
    def assess(self, inputs):
        return Assessment(deviation=[DriftItem("mode", "slow")]), {}


class WriteShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_string_no_longer_spreads_into_the_applied_channel(self):
        class Spread(_Drifts):
            def apply(self, inputs):
                return ("set to fast", {})

        residual = await Reconciler((Spread(),), mode=Serial(on_error=OnError.BestEffort)).converge()
        self.assertEqual(residual.applied, ())
        self.assertIn("Spread handed back ('set to fast', {}) from its write", residual.failures[0].message)

    async def test_a_write_that_returns_nothing_is_refused_by_name(self):
        class Forgets(_Drifts):
            def apply(self, inputs):
                pass

        with self.assertRaises(TypeError) as refused:
            await Reconciler((Forgets(),)).converge()
        self.assertIn("Forgets handed back None from its write", str(refused.exception))

    async def test_none_is_a_legal_write_result(self):
        class Quiet(_Drifts):
            def apply(self, inputs):
                return None, {}

        residual = await Reconciler((Quiet(),), mode=Serial(on_error=OnError.BestEffort)).converge()
        self.assertEqual(list(residual.failures), [])

    async def test_artifacts_that_are_not_a_mapping_are_refused(self):
        class Loose(_Drifts):
            def apply(self, inputs):
                return [DriftItem("mode", "fast")], "not a mapping"

        with self.assertRaises(TypeError) as refused:
            await Reconciler((Loose(),)).converge()
        self.assertIn("a pair of (result, artifacts) with a mapping of artifacts", str(refused.exception))

    async def test_a_shape_refusal_costs_no_retry(self):
        # The vet sits outside BaseRetry.around, so a misshapen reply is not a failure worth spending an
        # attempt on. A hook that cannot answer in the shape will not answer differently the third time.
        calls = []

        class Spread(_Drifts):
            def apply(self, inputs):
                calls.append(1)
                return ("set to fast", {})

        with self.assertRaises(TypeError):
            await Reconciler((Spread(),), retry=Retry(3)).converge()
        self.assertEqual(len(calls), 1)

    async def test_a_hostile_repr_is_quoted_rather_than_raised_through(self):
        # The whole reply is quoted, so it is the TUPLE's repr that runs and raises here. A raise inside a
        # refusal sentence would turn a shape refusal into an unrelated failure the retry would then spend on.
        class Hostile:
            def __repr__(self):
                raise ValueError("no words")

        class Rude(_Drifts):
            def apply(self, inputs):
                return Hostile(), {}

        with self.assertRaises(TypeError) as refused:
            await Reconciler((Rude(),)).converge()
        self.assertIn("<tuple whose repr raised ValueError>", str(refused.exception))


class ReadShapeTests(unittest.IsolatedAsyncioTestCase):
    async def test_an_assess_that_falls_off_the_end_is_named_inside_the_group(self):
        class Falls(Step):
            def assess(self, inputs):
                pass

        with self.assertRaises(ExceptionGroup) as refused:
            await Reconciler((Falls(),), mode=Parallel()).converge()
        inner = refused.exception.exceptions[0]
        self.assertIsInstance(inner, TypeError)
        self.assertIn("Falls handed back None from its assess", str(inner))

    async def test_serial_refuses_a_bare_list_where_an_assessment_is_due(self):
        class Bare(Step):
            def assess(self, inputs):
                return [], {}

        with self.assertRaises(TypeError) as refused:
            await Reconciler((Bare(),), mode=Serial()).converge()
        self.assertIn("an Assessment as the result of an assess", str(refused.exception))

    async def test_an_assess_answering_a_bare_assessment_is_refused(self):
        class Bare(Step):
            def assess(self, inputs):
                return Assessment(deviation=[])

        with self.assertRaises(ExceptionGroup) as refused:
            await Reconciler((Bare(),), mode=Parallel()).converge()
        self.assertIn("a pair of (result, artifacts)", str(refused.exception.exceptions[0]))
