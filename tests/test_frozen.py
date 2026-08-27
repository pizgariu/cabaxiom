"""A step is a declaration, not a session - and the CLOCK that makes the freeze land at the right moment."""
import unittest
from dataclasses import dataclass

from cabaxiom import Step


class FreezeTests(unittest.TestCase):

    def test_a_constructed_step_refuses_a_later_assignment(self):
        class Counter(Step):
            def __init__(self):
                self.seen = 0

        step = Counter()
        with self.assertRaises(TypeError) as refused:
            step.seen = 1
        self.assertIn("Counter is frozen", str(refused.exception))

    def test_the_refusal_names_the_sanctioned_channel(self):
        # A refusal that says only no is a refusal a reader has to guess their way out of.
        class Quiet(Step):
            pass

        with self.assertRaises(TypeError) as refused:
            Quiet().whatever = 1
        self.assertIn("state hides between passes", str(refused.exception))

    def test_a_declaration_slot_stays_settable(self):
        # `after` is configuration a run reads once before anything executes, so setting it late changes
        # the plan and never the state one pass carries into the next.
        class First(Step):
            pass

        class Second(Step):
            pass

        step = Second()
        step.after = (First,)
        self.assertEqual(step.after, (First,))

    def test_a_container_made_in_init_is_still_mutable(self):
        # The freeze refuses REBINDING, not the state a declaration legitimately holds. A step that must
        # remember something across passes keeps it in a container it made at construction.
        class Tally(Step):
            def __init__(self):
                self.runs = []

            def apply(self):
                self.runs.append("once")
                return self.unchanged()

        step = Tally()
        step.apply()
        step.apply()
        self.assertEqual(step.runs, ["once", "once"])


class TheClockTests(unittest.TestCase):
    """WHEN the seal lands, which is where the two obvious implementations of this go wrong."""

    def test_a_dataclass_step_still_takes_its_constructor_field(self):
        # An __init__ wrapper installed at class-definition time occupies cls.__dict__["__init__"], which
        # makes @dataclass skip generating its own - and the step then crashes on object.__init__ instead
        # of taking its argument. The metaclass touches no __init__ at all, so this works.
        @dataclass
        class Configured(Step):
            path: str

        self.assertEqual(Configured("/etc/app.conf").path, "/etc/app.conf")

    def test_a_dataclass_step_is_frozen_all_the_same(self):
        @dataclass
        class Configured(Step):
            path: str

        with self.assertRaises(TypeError):
            Configured("/etc/app.conf").path = "/tmp/other"

    def test_a_derived_init_calling_super_is_not_sealed_by_the_super_call(self):
        # The failure a per-subclass wrapper has without a re-entrancy flag: super().__init__() returns,
        # the wrapper seals, and the derived __init__ crashes on its very next line. __call__ is the
        # outermost frame, so there is no inner frame to seal at.
        class Base(Step):
            def __init__(self):
                self.base = 1

        class Derived(Base):
            def __init__(self):
                super().__init__()
                self.derived = 2

        step = Derived()
        self.assertEqual((step.base, step.derived), (1, 2))
