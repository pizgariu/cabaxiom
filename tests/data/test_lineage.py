"""Lineage - one JSONL line per clean producer, straight off the kernel's produced() seam - the run's own
attribution, never a parallel bookkeeping that could disagree with it."""
import io
import json
import unittest

from battery.data import Lineage

from cabaxiom import OnError, Parallel, Reconciler, Step
from cabaxiom.core.record import Chorus


class Maker(Step):
    def __init__(self, key: str, value: object) -> None:
        self.__key = key
        self.__value = value

    def apply(self, inputs):
        return None, {self.__key: self.__value}


class Boom(Step):
    def apply(self, inputs):
        raise RuntimeError("db down")


class LineageTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_line_per_clean_producer_with_run_style_labels(self):
        sink = io.StringIO()
        await Reconciler((Maker("uri", "s3://a"), Maker("rows", 7), Boom()),
                         observer=Lineage(sink), mode=Parallel(OnError.BestEffort)).converge()
        lines = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual([line["step"] for line in lines], ["Maker", "Maker#2"])   # numbered like every kernel read
        self.assertEqual(lines[0]["artifacts"], {"uri": "s3://a"})
        self.assertEqual(lines[1]["artifacts"], {"rows": 7})
        self.assertTrue(all(line["pass"] == 1 for line in lines))
        self.assertEqual(sum("Boom" in line["step"] for line in lines), 0)   # a failure has nothing to attribute

    async def test_a_label_stays_with_its_instance_across_passes(self):
        sink = io.StringIO()
        first, second = Maker("a", 1), Maker("b", 2)
        reconciler = Reconciler((first, second), observer=Lineage(sink))
        await reconciler.converge()
        await reconciler.converge()
        lines = [json.loads(line) for line in sink.getvalue().splitlines()]
        self.assertEqual([line["pass"] for line in lines], [1, 1, 2, 2])
        self.assertEqual([line["step"] for line in lines], ["Maker", "Maker#2", "Maker", "Maker#2"])

    async def test_a_value_that_does_not_speak_json_is_named_not_crashed_on(self):
        sink = io.StringIO()

        class Handle(Step):
            def apply(self, inputs):
                return None, {"lock": object()}

        await Reconciler((Handle(),), observer=Lineage(sink)).converge()
        line = json.loads(sink.getvalue().splitlines()[0])
        self.assertIn("object object at", line["artifacts"]["lock"])   # the repr, because a lineage that crashes is worse

    async def test_it_composes_with_a_chorus_and_hears_the_teardowns_too(self):
        sink = io.StringIO()

        class Holder(Step):
            def prune(self, inputs):
                return None, {"released": "s3://x"}

        await Reconciler((Holder(),), observer=Chorus(Lineage(sink))).prune()
        line = json.loads(sink.getvalue().splitlines()[0])
        self.assertEqual(line["artifacts"], {"released": "s3://x"})
        self.assertEqual(line["pass"], 0)   # a teardown is not a converge pass, so the trace says so


if __name__ == "__main__":
    unittest.main()
