"""The named refusals - three unrelated bases, every one still catchable as what it replaced."""
import unittest

from cabaxiom import (
    Cycle,
    Deadline,
    Fixpoint,
    Malformed,
    Misconfigured,
    Reconciler,
    Retry,
    Stable,
    Step,
    Unresolvable,
)


class NothingConnectsThemTests(unittest.TestCase):

    def test_the_three_bases_share_no_ancestor_a_caller_could_catch(self):
        # The decision worth arguing for. A caller who wants to hear about a malformed declaration has no
        # business being handed a misconfigured axis, where a common parent would let one except swallow both.
        shared = (set(Malformed.__mro__) & set(Unresolvable.__mro__) & set(Misconfigured.__mro__))
        self.assertEqual(shared - {object, BaseException, Exception}, set())

    def test_each_still_answers_to_the_builtin_it_replaces(self):
        # So nothing written against the previous release breaks. The finer answer is opt-in.
        self.assertTrue(issubclass(Malformed, TypeError))
        self.assertTrue(issubclass(Unresolvable, ValueError))
        self.assertTrue(issubclass(Misconfigured, ValueError))
        self.assertTrue(issubclass(Cycle, Unresolvable))


class TheAxesRefuseByNameTests(unittest.TestCase):

    def test_an_axis_handed_a_value_outside_its_domain_is_misconfigured(self):
        # Nothing about the steps is wrong here, which is exactly why it is not Unresolvable.
        for build in (lambda: Retry(0), lambda: Deadline(-1), lambda: Fixpoint(0), lambda: Stable(1)):
            with self.subTest(axis=build):
                with self.assertRaises(Misconfigured):
                    build()

    def test_an_old_except_ValueError_still_catches_every_one(self):
        with self.assertRaises(ValueError):
            Retry(0)


class TheRunRefusesByNameTests(unittest.TestCase):

    def test_a_loop_in_the_edges_is_a_Cycle(self):
        class Left(Step):
            pass

        class Right(Step):
            after = (Left,)

        Left.after = (Right,)
        try:
            with self.assertRaises(Cycle):
                Reconciler((Left(), Right()))
        finally:
            Left.after = ()

    def test_a_cycle_is_still_a_ValueError_to_anyone_who_only_knows_that(self):
        class Left(Step):
            pass

        class Right(Step):
            after = (Left,)

        Left.after = (Right,)
        try:
            with self.assertRaises(ValueError):
                Reconciler((Left(), Right()))
        finally:
            Left.after = ()
