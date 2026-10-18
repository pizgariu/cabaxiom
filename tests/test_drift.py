"""DriftItem value object - name and message access, repr, slots guard and str form."""
import unittest
from dataclasses import dataclass

from cabaxiom import Artifacts, Assessment, DriftItem, Reconciler, Step
from cabaxiom.core.declaration.drift import FlowAssessment, FlowOutcome


class DriftItemTests(unittest.TestCase):
    def test_exposes_name_and_message(self):
        d = DriftItem("n", "f")
        self.assertEqual((d.name, d.message), ("n", "f"))

    def test_repr(self):
        self.assertEqual(repr(DriftItem("n", "f")), "DriftItem('n', 'f')")

    def test_slots_forbid_stray_attributes(self):
        d = DriftItem("n", "f")
        with self.assertRaises(AttributeError):
            d.extra = 1  # __slots__ has no __dict__

    def test_frozen_a_field_cannot_be_reassigned(self):
        # DriftItem hashes by value, so a value already sitting in a set must not change under it - the
        # fields are read-only properties, so a caller that wants a different item constructs one.
        d = DriftItem("n", "f")
        with self.assertRaises(AttributeError):
            d.name = "other"
        with self.assertRaises(AttributeError):
            d.message = "other"

    def test_str_renders_name_and_message(self):
        self.assertEqual(str(DriftItem("a", "b")), "a: b")

    def test_equality_is_by_value_over_the_two_contract_fields(self):
        # A caller can assert a drift list against expected items, not identities.
        self.assertEqual(DriftItem("n", "f"), DriftItem("n", "f"))
        self.assertNotEqual(DriftItem("n", "f"), DriftItem("n", "other"))
        self.assertNotEqual(DriftItem("n", "f"), DriftItem("other", "f"))

    def test_equal_items_hash_alike(self):
        # Value equality pairs with value hashing, so items work in sets and as dict keys.
        self.assertEqual(hash(DriftItem("n", "f")), hash(DriftItem("n", "f")))
        self.assertEqual({DriftItem("n", "f"), DriftItem("n", "f")}, {DriftItem("n", "f")})

    def test_another_carrier_is_not_equal_by_structure(self):
        # The Drift protocol is structural for READING. Equality stays within DriftItem, so a foreign
        # carrier with the same fields falls back to Python's default and compares unequal.
        class Carrier:
            name = "n"
            message = "f"

        self.assertNotEqual(DriftItem("n", "f"), Carrier())


class DriftContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_frozen_dataclass_carrier_satisfies_the_protocol_end_to_end(self):
        # The protocol declares name/message as READ-ONLY properties, so the most natural domain carriers -
        # a frozen dataclass here - are legal Drift. A step returning its OWN carrier type (a domain list,
        # not list[Drift]) flows through assess(), converge() and the residual untouched.
        @dataclass(frozen=True)
        class Finding:
            name: str
            message: str

        class Domain(Step):
            def __init__(self) -> None:
                self.__fixed = [False]   # a cell, since the frozen Step forbids reassigning an attribute

            def assess(self, inputs: Artifacts) -> FlowAssessment:
                deviation = [] if self.__fixed[0] else [Finding("svc", "wrong mode")]
                return Assessment(deviation=deviation), {}

            def apply(self, inputs: Artifacts) -> FlowOutcome:
                self.__fixed[0] = True
                return [Finding("svc", "mode corrected")], {}

        residual = await Reconciler((Domain(),)).converge()
        self.assertEqual(residual, [])
        self.assertEqual([(c.name, c.message) for c in residual.applied], [("svc", "mode corrected")])
