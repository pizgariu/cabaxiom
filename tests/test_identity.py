"""Identity is the dependency currency, so a step a dict cannot tell apart is refused."""
import unittest
from dataclasses import dataclass

from cabaxiom import Malformed, Step


class TheGuardTests(unittest.TestCase):

    def test_a_hand_written_equality_is_refused_at_class_definition(self):
        with self.assertRaises(Malformed) as refused:
            class Loose(Step):
                def __eq__(self, other):
                    return True

        self.assertIn("addressed by identity", str(refused.exception))

    def test_a_hand_written_hash_is_refused_too(self):
        with self.assertRaises(Malformed):
            class Loose(Step):
                def __hash__(self):
                    return 0

    def test_a_dataclass_step_is_refused_at_first_construction(self):
        # A decorator runs AFTER the class body, so the subclass hook has already been and gone by the
        # time @dataclass installs its generated __eq__. Construction is the first moment the finished
        # class exists, which is why the guard is asked twice.
        @dataclass
        class Configured(Step):
            path: str

        with self.assertRaises(Malformed) as refused:
            Configured("/etc/app.conf")
        self.assertIn("eq=False", str(refused.exception))

    def test_the_refusal_names_the_fix_rather_than_only_the_problem(self):
        @dataclass
        class Configured(Step):
            path: str

        with self.assertRaises(Malformed) as refused:
            Configured("/etc/app.conf")
        self.assertIn("@dataclass(eq=False)", str(refused.exception))


class TheSanctionedShapeTests(unittest.TestCase):

    def test_a_dataclass_step_with_eq_off_keeps_its_constructor_and_its_identity(self):
        @dataclass(eq=False)
        class Configured(Step):
            path: str

        first, second = Configured("/etc/app.conf"), Configured("/etc/app.conf")
        self.assertEqual(first.path, "/etc/app.conf")
        self.assertNotEqual(first, second)          # alike, still two steps
        self.assertEqual(len({first, second}), 2)   # which is what keeps them two nodes

    def test_an_ordinary_step_is_addressable_without_saying_anything(self):
        class Plain(Step):
            pass

        self.assertEqual(len({Plain(), Plain()}), 2)


class TheSealIsNotOnlyForStepTests(unittest.TestCase):
    """The construction half of the guard reaches for Step's own check through a mangled name, so it has
    to cope with a class that carries no such check. That is why it is a getattr and not a call."""

    def test_a_class_built_on_the_metaclass_alone_is_sealed_with_no_guard_to_run(self):
        from cabaxiom.step import _Sealed

        class Bare(metaclass=_Sealed):
            pass

        self.assertIsNone(getattr(Bare, "_Step__addressable", None))
        self.assertIsInstance(Bare(), Bare)
