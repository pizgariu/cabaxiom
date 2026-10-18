"""Choosing the CONVERGENCE shape - how many apply -> re-probe passes one converge() runs and when to stop.

Convergence is the axis that answers "how many passes?". The kernel ships three built-ins and an open base
for your own and this program walks all four on worlds picked to show exactly where they differ.

    Once        one pass, no loop (the default - not shown here, it is the trivial case).
    Fixpoint    loop until the residual SET stops changing (or revisits a state - an oscillation) or a
                ceiling is hit. Optionally paced by a Backoff so a stalled pass becomes a retry.
    Shrinking   loop only while the residual keeps getting SMALLER (by count). Stop the instant a pass
                buys no ground. For a strictly reducible world, where a pass that fixes nothing is spinning.
    BaseLooping the open base under Fixpoint and Shrinking. Subclass it, implement deciding(), inherit the
                whole bounded loop. Act 4 builds a custom convergence on it.

The one lesson: Fixpoint measures progress by whether the SET changed, Shrinking by whether the COUNT fell.
On a world that CHURNS (swaps one problem for another without shrinking), they diverge sharply.

Run it:

    python examples/convergence_shapes.py

Expected stdout: Shrinking draining a backlog to empty, the churn world spun to the ceiling by Fixpoint but
cut short by Shrinking, a Linear-paced stall settling and a custom Patient convergence tolerating a plateau.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Assessment, BaseLooping, DriftItem, Fixpoint, Journal, Linear, Reconciler, Shrinking, Step
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, BaseLooping, DriftItem, Fixpoint, Journal, Linear, Reconciler, Shrinking, Step


class Drain(Step):
    """Reports one drift per still-open item and closes a BATCH per apply(), so the residual COUNT strictly
    falls each productive pass - the reducible world Shrinking is built for."""

    def __init__(self, total: int, batch: int):
        self.open = set(range(total))
        self.batch = batch

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem(f"item-{index}", "open") for index in sorted(self.open)]), {}

    def apply(self, inputs):
        closing = sorted(self.open)[: self.batch]
        self.open.difference_update(closing)
        return [DriftItem(f"item-{index}", "closed") for index in closing] or None, {}


class Churn(Step):
    """Each apply() closes one gap but opens the next, so the residual COUNT never falls - it CHURNS. The
    world that separates the loop shapes: Fixpoint sees the SET change and runs to its ceiling. Shrinking
    sees the COUNT hold and stops at once."""

    def __init__(self) -> None:
        self.frontier = [0]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem(f"gap-{self.frontier[0]}", "open")]), {}

    def apply(self, inputs):
        closed = self.frontier[0]
        self.frontier[0] += 1
        return [DriftItem(f"gap-{closed}", "closed")], {}


class Settling(Step):
    """Waits on external state. apply() does nothing, drift() clears only once the world has been re-probed
    `patience` times. The case a Backoff is for - a stalled pass paced and retried, not treated as terminal."""

    def __init__(self, patience: int):
        # NOT named `expects`. The declaration slots are read off the instance, so a domain attribute
        # shadowing one would BE a declaration - and the Graph refuses the wrong shape loudly.
        self.patience = patience
        self.probes = [0]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        self.probes[0] += 1
        return Assessment(deviation=[] if self.probes[0] > self.patience else [DriftItem("svc", "external state settling")]), {}

    def apply(self, inputs):
        return None, {}


class Patient(BaseLooping):
    """A CUSTOM convergence on the BaseLooping seam. Keep going while the residual shrinks but tolerate up
    to `patience` consecutive passes that buy no ground before giving up - a plateau might be temporary. The
    stateful cousin of Shrinking. Its per-run stall counter lives in the closure deciding() hands back, so a
    second converge() starts clean instead of inheriting a stale count. Implement deciding(), inherit the loop."""

    def __init__(self, patience: int = 2, max_passes: int = 10):
        super().__init__(max_passes)
        self.__patience = patience

    def deciding(self):
        stalls = 0

        def decide(before, after):
            nonlocal stalls
            if len(after) < len(before):   # ground bought: reset the patience streak and continue
                stalls = 0
                return False, 0.0
            stalls += 1                     # a pass that bought nothing: spend patience before giving up
            return stalls > self.__patience, 0.0

        return decide


async def passes_of(step: Step, convergence) -> int:
    # Run one converge under the given convergence and report how many apply -> re-probe passes it took,
    # counted off a Journal (one recorded Pass per pass). The residual is printed by the caller.
    journal = Journal()
    await Reconciler((step,), convergence=convergence, observer=journal).converge()
    return len(journal.passes)


async def main() -> None:
    print("Act 1 - Shrinking drains a reducible backlog (count strictly falls to empty)")
    backlog = Drain(total=6, batch=2)
    residual = await Reconciler((backlog,), convergence=Shrinking()).converge()
    print(f"    6 items, 2 per pass -> {len(residual.applied)} closed, residual {'empty' if not residual else residual}")
    assert not backlog.open   # the backlog is DRAINED, not abandoned partway: Shrinking looped to empty
    assert not residual
    print()

    print("Act 2 - the churn world: Fixpoint keeps going, Shrinking stops")
    ceiling = 6
    fixpoint_passes = await passes_of(Churn(), Fixpoint(max_passes=ceiling))
    shrinking_passes = await passes_of(Churn(), Shrinking(max_passes=ceiling))
    print(f"    Fixpoint  ran {fixpoint_passes} passes (set changes every pass -> spun to the ceiling)")
    print(f"    Shrinking ran {shrinking_passes} passes (count never fell -> stopped the moment it plateaued)")

    # The one lesson, made falsifiable. Fixpoint reads a changed SET as progress and never converges on a
    # world that churns, so only the ceiling stops it. Shrinking reads a flat COUNT as a plateau and quits.
    assert fixpoint_passes == ceiling
    assert shrinking_passes < fixpoint_passes
    print()

    print("Act 3 - Linear backoff paces a stall (the gentle ramp between Fixed and Exponential)")
    step, cap = 0.5, 2.0
    ramp = Linear(step=step, cap=cap)
    delays = [ramp.delay(n) for n in range(1, 6)]
    print(f"    Linear(step={step}, cap={cap}) delays: {delays}")
    assert delays == sorted(delays)   # a ramp climbs, it never doubles back
    assert max(delays) <= cap         # and cap is a ceiling on the single longest pause, not a target

    settling = Settling(patience=3)
    paced = await Reconciler(
        (settling,),
        convergence=Fixpoint(max_passes=6, backoff=Linear(step=0.01, cap=0.03)),
    ).converge()
    print(f"    a step waiting on external state settled after {settling.probes[0]} probes, residual "
          f"{'empty' if not paced else paced}")
    # A stall is a WAIT, not a verdict. The step's drift only clears once it has been re-probed past its
    # patience, so an empty residual here means the paced loop outlasted the stall instead of calling it.
    assert settling.probes[0] > settling.patience
    assert not paced
    print()

    print("Act 4 - a custom convergence on the BaseLooping seam: Patient tolerates a plateau")
    spans = {}
    for patience in (0, 2):
        spans[patience] = await passes_of(Churn(), Patient(patience=patience, max_passes=8))
        print(f"    Patient(patience={patience}) ran {spans[patience]} passes on the churn world "
              f"({'like Shrinking' if patience == 0 else 'spends its patience before giving up'})")

    # The seam delivered. With no patience the custom shape reproduces Shrinking exactly and each unit
    # of patience buys one more plateau pass before it gives up. Nothing else about the loop was written.
    assert spans[0] == shrinking_passes
    assert spans[2] == spans[0] + 2


if __name__ == "__main__":
    asyncio.run(main())
