"""The Assessment: one read of the world in four named channels, frozen once it is minted."""
import unittest

from cabaxiom import Assessment, DriftItem


class AssessmentTests(unittest.TestCase):

    def test_an_empty_reading_is_empty_on_every_channel(self):
        # The default a step that overrides nothing answers with, and the shape "empty means verified"
        # rests on. All four, not just deviation, because a silent step advises nothing either.
        reading = Assessment()
        self.assertEqual((list(reading.deviation), list(reading.plan)), ([], []))
        self.assertEqual((list(reading.advisory), list(reading.footprint)), ([], []))

    def test_each_channel_carries_what_it_was_given(self):
        found, intended = DriftItem("cfg", "missing"), DriftItem("cfg", "would write it")
        advice, held = DriftItem("cfg", "an older format still parses"), DriftItem("cfg", "/etc/app.conf")
        reading = Assessment(deviation=[found], plan=[intended], advisory=[advice], footprint=[held])
        self.assertEqual(list(reading.deviation), [found])
        self.assertEqual(list(reading.plan), [intended])
        self.assertEqual(list(reading.advisory), [advice])
        self.assertEqual(list(reading.footprint), [held])

    def test_a_channel_takes_any_drift_carrier_and_not_only_DriftItem(self):
        # The protocol is two fields wide on purpose, so a domain's own richer item is first-class here.
        class Mine:
            name, message = "mine", "and the kernel reads two fields of it"

        self.assertEqual(list(Assessment(deviation=[Mine()]).deviation)[0].name, "mine")

    def test_a_reading_cannot_be_rewritten_by_the_hand_that_received_it(self):
        # A verdict that the receiver can edit is not a verdict. Frozen, like every record the kernel mints.
        reading = Assessment(deviation=[DriftItem("cfg", "missing")])
        with self.assertRaises(Exception):
            reading.deviation = []                                        # type: ignore[misc]
