"""foresee() - the counterfactual structural read. If THIS step failed, what would the run lose? The
answer is the Graph's fallout(), the same walk the Ledger runs when it actually blames a failure, so the
forecast and the handling cannot disagree."""
import unittest

from cabaxiom import OnError, Parallel, Reconciler, Step


class Network(Step):
    def apply(self, inputs):
        raise RuntimeError("boom")


class Db(Step):
    expects = (Network,)


class Api(Step):
    expects = (Db,)


class Cache(Step):
    expects = (Db,)


class Unrelated(Step):
    pass


def _fleet(executor):
    reconciler = Reconciler((Network(), Db(), Api(), Cache(), Unrelated()), mode=executor)
    network = next(step for group in reconciler._partition for step in group
                   if isinstance(step, Network))
    return reconciler, network


class ForecastEqualsHandlingTests(unittest.IsolatedAsyncioTestCase):
    """The load-bearing claim. What foresee() predicts is what the run actually records, because both read
    the one fallout() walk."""

    async def test_the_blocked_forecast_is_exactly_what_best_effort_records(self):
        reconciler, network = _fleet(Parallel(OnError.BestEffort))
        forecast = reconciler.foresee(network)

        residual = await reconciler.converge()
        recorded = sorted(item.name for item in residual if "step blocked" in item.message)
        self.assertEqual(sorted(forecast.blocked), recorded)
        self.assertEqual(recorded, ["Api", "Cache", "Db"])

    async def test_the_fanning_executor_settles_the_group_halt_never_guarantees(self):
        # Halt gates by RUN POSITION, so only a strictly later wave is a guaranteed skip. The failure's own
        # wave is the honest maybe - reporting it as skipped would be a promise the shape does not make. A
        # fanning executor resolves that maybe by admitting the wave, so its group-mates settle rather than
        # skip, which is exactly why the forecast reports them apart from the guaranteed skips.
        reconciler, network = _fleet(Parallel(OnError.Halt))
        forecast = reconciler.foresee(network)

        residual = await reconciler.converge()
        recorded = {item.name for item in residual if "step skipped" in item.message}
        self.assertEqual(set(forecast.settling) & recorded, set())          # they were admitted, so they ran
        self.assertTrue(set(forecast.skipped) <= recorded)


class ForecastShapeTests(unittest.IsolatedAsyncioTestCase):
    """What the reading says and what it refuses to say."""

    def test_a_step_nothing_stands_on_is_contained(self):
        reconciler, _ = _fleet(Parallel())
        spare = next(step for group in reconciler._partition for step in group
                     if isinstance(step, Unrelated))
        forecast = reconciler.foresee(spare)

        self.assertTrue(forecast.contained)
        self.assertFalse(forecast)                     # truthy only when it would take others down
        self.assertEqual(forecast.blocked, ())
        self.assertEqual(forecast.failed, "Unrelated")

    def test_it_names_the_step_and_counts_its_channels(self):
        reconciler, network = _fleet(Parallel())
        self.assertIn("Casualty(Network: blocked=3", repr(reconciler.foresee(network)))

    def test_two_instances_of_one_kind_are_named_apart_exactly_as_explain_names_them(self):
        first, second = Unrelated(), Unrelated()
        reconciler = Reconciler((first, second))
        self.assertEqual(reconciler.foresee(second).failed, "Unrelated#2")
        self.assertEqual(reconciler.explain().groups, (("Unrelated", "Unrelated#2"),))

    def test_a_step_outside_the_run_is_refused(self):
        reconciler = Reconciler((Unrelated(),))
        with self.assertRaises(ValueError) as ctx:
            reconciler.foresee(Network())
        self.assertIn("not in this run", str(ctx.exception))

    def test_a_scope_narrowing_a_step_away_makes_it_unforeseeable(self):
        from cabaxiom import Skip  # noqa: PLC0415 - only this test narrows the run

        spare = Unrelated()
        reconciler = Reconciler((Network(), spare), scope=Skip(Network))
        with self.assertRaises(ValueError):
            reconciler.foresee(Network())
        self.assertTrue(reconciler.foresee(spare).contained)


class StarvationTests(unittest.IsolatedAsyncioTestCase):
    """A severity note, not a further casualty. Everything wanting the capability already depends on its
    provider, so starvation says what a FUTURE declaration would lose, not what this run would."""

    def test_it_names_the_capabilities_this_step_alone_provides(self):
        class Primary(Step):
            def __init__(self) -> None:
                self.provides = frozenset({"database", "cache"})

        class Replica(Step):
            def __init__(self) -> None:
                self.provides = frozenset({"database"})

        class Thirsty(Step):
            demands = ("database",)

        primary = Primary()
        reconciler = Reconciler((primary, Replica(), Thirsty()))
        forecast = reconciler.foresee(primary)

        self.assertEqual(forecast.starves, ("cache",))   # the database still has a replica
        self.assertIn("Thirsty", forecast.blocked)       # and it was already a casualty anyway

    def test_a_step_providing_nothing_starves_nobody(self):
        reconciler, network = _fleet(Parallel())
        self.assertEqual(reconciler.foresee(network).starves, ())
