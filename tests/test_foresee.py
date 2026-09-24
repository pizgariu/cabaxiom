"""foresee() - what one step's failure would cost, read before anything runs."""
import unittest

from cabaxiom import Parallel, Pipeline, Reconciler, Step, Unresolvable
from cabaxiom.ordering import Components


class Db(Step):
    provides = frozenset({"storage"})

    async def assess(self):
        return self.verified()


class Spare(Step):
    provides = frozenset({"storage"})

    async def assess(self):
        return self.verified()


class Cache(Step):
    async def assess(self):
        return self.verified()


class Api(Step):
    expects = (Cache,)
    demands = ("storage",)

    async def assess(self):
        return self.verified()


class Cdn(Step):
    expects = (Api,)

    async def assess(self):
        return self.verified()


class TheForecastComesOffTheDerivationTests(unittest.TestCase):
    """It is not a simulation. `blocked` is the Graph's own fallout() walk, the same one a targeted run
    inverts to build its closure, so a forecast that disagreed with the derivation would be a
    contradiction rather than a bug."""

    def test_a_failure_reaches_its_transitive_dependents_and_not_itself(self):
        db, cache, api, cdn = Db(), Cache(), Api(), Cdn()
        told = Reconciler((db, cache, api, cdn)).foresee(db)
        self.assertEqual(told.blocked, ("Api", "Cdn"))    # Cdn only through Api
        self.assertFalse(told.contained)
        self.assertTrue(told)                             # truthy, because it IS a finding
        self.assertEqual(str(told), "Db would fail, blocking Api, Cdn")

    def test_a_leaf_failing_costs_the_run_nothing_else(self):
        db, cache, api, cdn = Db(), Cache(), Api(), Cdn()
        told = Reconciler((db, cache, api, cdn)).foresee(cdn)
        self.assertEqual(told.blocked, ())
        self.assertTrue(told.contained)
        self.assertFalse(told)                            # falsy when there is no finding
        self.assertEqual(str(told), "Cdn would fail alone")

    def test_the_forecast_agrees_with_only_s_closure_read_the_other_way(self):
        # The two walks are one walk with the direction as a parameter, so they have to be each other's
        # mirror. If B stands in the fallout of A, then A stands in the closure Only(B) would keep.
        from cabaxiom import Only
        held = {"Db": Db, "Cache": Cache, "Api": Api, "Cdn": Cdn}
        steps = (Db(), Cache(), Api(), Cdn())
        run = Reconciler(steps)
        for step in steps:
            for hurt in run.foresee(step).blocked:
                kept = Reconciler(tuple(type(one)() for one in steps), scope=Only(held[hurt])).explain()
                self.assertIn(Step.named(step), [name for group in kept.groups for name in group],
                              f"{hurt} says it depends on {Step.named(step)}, yet Only({hurt}) dropped it")


class TheFailFastAnswerIsAboutPositionNotEdgesTests(unittest.TestCase):
    """FailFast stops the run where it stands, so what survives depends on the shape the dispatcher
    walks rather than on what depends on what."""

    def test_a_strictly_later_group_is_skipped_and_the_failure_s_own_group_settles(self):
        db, cache, api, cdn = Db(), Cache(), Api(), Cdn()
        told = Reconciler((db, cache, api, cdn), dispatcher=Parallel()).foresee(db)
        self.assertEqual(told.settling, ("Cache",))       # admitted in the same wave, already in flight
        self.assertEqual(told.skipped, ("Api", "Cdn"))

    def test_the_same_failure_reads_differently_under_a_chain_shape(self):
        db, cache, api, cdn = Db(), Cache(), Api(), Cdn()
        told = Reconciler((db, cache, api, cdn), Components(), dispatcher=Pipeline()).foresee(db)
        self.assertEqual(told.blocked, ("Api", "Cdn"))    # the derivation does not care about the shape
        self.assertEqual(told.skipped, ())                # one chain holds everything, nothing is later


class StarvationIsASeverityNoteTests(unittest.TestCase):
    """It names the capabilities this step is the ONLY present provider of. Everything wanting one is
    already blocked, yet a future declaration written against a starved capability fails differently."""

    def test_a_sole_provider_starves_its_capability(self):
        db, cache, api = Db(), Cache(), Api()
        self.assertEqual(Reconciler((db, cache, api)).foresee(db).starves, ("storage",))

    def test_a_second_provider_means_nothing_starves(self):
        db, spare, api = Db(), Spare(), Api()
        cache = Cache()
        self.assertEqual(Reconciler((db, spare, cache, api)).foresee(db).starves, ())

    def test_a_step_providing_nothing_starves_nothing(self):
        db, cache, api = Db(), Cache(), Api()
        self.assertEqual(Reconciler((db, cache, api)).foresee(api).starves, ())


class AForecastIsAboutTheRunThatWasResolvedTests(unittest.TestCase):

    def test_a_step_outside_the_run_is_refused(self):
        db, cache, api = Db(), Cache(), Api()
        with self.assertRaises(Unresolvable) as ctx:
            Reconciler((db, cache, api)).foresee(Cdn())
        self.assertIn("not in this run", str(ctx.exception))

    def test_a_step_the_scope_dropped_is_outside_the_run_too(self):
        from cabaxiom import Skip
        db, cache, api, cdn = Db(), Cache(), Api(), Cdn()
        run = Reconciler((db, cache, api, cdn), scope=Skip(Cdn))
        with self.assertRaises(Unresolvable):
            run.foresee(cdn)
