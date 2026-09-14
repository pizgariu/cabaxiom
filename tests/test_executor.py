"""Serial and Parallel execution semantics - FailFast vs BestEffort, per-wave fan-out."""
import asyncio
import unittest

from cabaxiom import (
    DFS,
    Dispatcher,
    DriftItem,
    Kahn,
    Levels,
    OnError,
    Ordering,
    Parallel,
    Reconciler,
    Serial,
    Step,
)
from support import A, B, Boom, C, X, Y, Z


class ExecutorTests(unittest.TestCase):
    """The injected Dispatcher - Serial (default) and Parallel, plus the OnError failure policy."""

    def test_serial_is_the_default_and_fails_fast(self):
        # No dispatcher -> Serial(FailFast), so an apply() exception aborts the whole converge.
        with self.assertRaises(RuntimeError):
            asyncio.run(Reconciler((Boom(),)).converge())

    def test_best_effort_collects_failures_as_residual_drift(self):
        # BestEffort catches the exception, records it as Drift and keeps applying the rest.
        log = []

        class Ok(Step):
            def apply(self) -> None:
                log.append("ok")

        residual = asyncio.run(Reconciler((Boom(), Ok()), dispatcher=Serial(OnError.BestEffort)).converge())
        self.assertEqual(log, ["ok"])                 # sibling still ran after Boom blew up
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    def test_parallel_preserves_dependency_order_across_levels(self):
        # The level barrier keeps every Step.expects edge even while fanning each level out.
        log = []
        asyncio.run(Reconciler((C(log), A(log), B(log)), Kahn(), dispatcher=Parallel()).converge())
        self.assertEqual(log, ["A", "B", "C"])

    def test_parallel_runs_every_independent_step(self):
        # One level of independents. Order within is unspecified, yet all must run.
        log = []
        asyncio.run(Reconciler((X(log), Y(log), Z(log)), Kahn(), dispatcher=Parallel()).converge())
        self.assertEqual(sorted(log), ["X", "Y", "Z"])

    def test_parallel_failfast_reraises_on_the_calling_thread(self):
        with self.assertRaises(RuntimeError):
            asyncio.run(Reconciler((Boom(),), Kahn(), dispatcher=Parallel()).converge())

    def test_parallel_best_effort_collects_failures(self):
        residual = asyncio.run(Reconciler((Boom(),), Kahn(), dispatcher=Parallel(OnError.BestEffort)).converge())
        self.assertEqual(len(residual), 1)
        self.assertIn("step failed", residual[0].message)

    def test_reconciler_rejects_parallel_with_a_flat_only_ordering(self):
        # DFS yields no real levels (one-wave fallback), so Parallel would ignore expects= -> refuse at build.
        with self.assertRaises(ValueError) as ctx:
            Reconciler((A([]),), DFS(), dispatcher=Parallel())
        self.assertIn("Parallel", str(ctx.exception))

    def test_the_wave_shape_and_guard_live_in_arrange_on_any_executor(self):
        # No capability flag. Each dispatcher owns its shape via arrange(). A custom dispatcher that builds a
        # wave partition and verifies it rejects a flat-only Ordering (the one-wave fallback fails
        # verify on dependent steps) and accepts real Kahn waves - tied to arrange(), not to
        # the Parallel class.
        class WaveExecutor(Dispatcher):
            def arrange(self, ordering, steps):
                waves = Levels(ordering.levels(steps))
                waves.verify()
                return waves

            async def probe(self, groups, read):
                return [read(step) for group in groups for step in group]

            async def execute(self, groups, do, cancellation):
                return [], []

        with self.assertRaises(ValueError):
            Reconciler((A([]), B([])), DFS(), dispatcher=WaveExecutor())   # DFS one-wave fallback: B beside dep A
        Reconciler((A([]), B([])), Kahn(), dispatcher=WaveExecutor())      # Kahn splits A then B - independent

    def test_guard_rejects_a_custom_ordering_whose_waves_violate_after(self):
        # A level-aware Ordering that overrides levels() but returns one wave of DEPENDENT steps passes the
        # capability check, yet a fanning dispatcher would run them together and ignore after=. The structural
        # invariant catches the mis-split at construction.
        class OneBigWave(Ordering):
            def __call__(self, steps):
                return steps

            def levels(self, steps):
                return (tuple(steps),)   # everything in one wave, dependencies be damned

        with self.assertRaises(ValueError):
            Reconciler((A([]), B([])), OneBigWave(), dispatcher=Parallel())   # B is after A, same wave

    def test_dfs_with_serial_is_allowed(self):
        # DFS is serial-only and serial is fine - it still resolves the chain.
        log = []
        asyncio.run(Reconciler((C(log), A(log), B(log)), DFS(), dispatcher=Serial()).converge())
        self.assertEqual(log, ["A", "B", "C"])




    def test_parallel_routes_what_apply_returns_to_the_applied_channel(self):
        # A step whose apply() returns what it changed. The dispatcher hands those back as its returns list,
        # and converge routes them to the applied channel, keeping them out of the residual.
        class Applied(Step):
            def apply(self):
                return [DriftItem("svc", "created")]

        residual = asyncio.run(Reconciler((Applied(),), Kahn(), dispatcher=Parallel()).converge())
        self.assertEqual(residual, [])                                       # nothing still wrong
        self.assertEqual([item.message for item in residual.applied], ["created"])
