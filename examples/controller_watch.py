"""React to a moving world with watch() - a standing converge woken by events, not a timer.

converge() closes the gap once. watch() keeps it closed. Each Step can expose an async watch() that
yields whenever its OWN world may have moved - a file event, a queue message, a webhook - and the engine
answers every wake with a FULL re-converge, yielding the residual. Level-triggered to the bone. A wake
carries no payload and is never trusted as a report, the re-assessment that follows is the only truth, so
a spurious wake costs one clean pass and a missed one is caught by the next.

When the loop should STOP is the caller's to decide - watch() runs until the caller breaks out of the
async for. A Settle is the reusable judge for that decision, driven by the caller across passes:

  Clean       stop on the first clean pass
  Stable(k)   stop only after k CONSECUTIVE clean passes

The difference is the whole point on a flapping world. This example models a service whose world an
external timeline breaks and then repairs - each change a "look again" event its watch() yields. Clean
declares victory on the opening clean pass, before the break has landed. Stable(2) keeps watching, sees
the break, sees the repair and stops only once the world has held clean twice running.

Run it:

    python examples/controller_watch.py

Expected stdout: Clean stops after a single pass. Stable(2) rides out the break and stops on two clean
passes back to back, having cost strictly more passes - the price of the guarantee. No external
resources. The world's timeline is simulated in memory.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Assessment, Clean, DriftItem, Reconciler, Stable, Step
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, Clean, DriftItem, Reconciler, Stable, Step


class FlappingService(Step):
    """A service repaired from OUTSIDE, not by this run. apply() is a no-op probe, so the residual reports
    the world's health honestly each pass. Its watch() plays the world's timeline - a sequence of health
    states, each yielded as a "look again" event - so the demo is deterministic with no real clock."""

    def __init__(self, timeline: list[bool]) -> None:
        self.__world = {"healthy": timeline[0]}
        self.__events = timeline[1:]   # each later state is delivered on its own wake

    async def watch(self):
        for healthy in self.__events:
            await asyncio.sleep(0.001)   # stands in for the wait on a real event source
            self.__world["healthy"] = healthy
            yield

    def assess(self, inputs):
        drift = [] if self.__world["healthy"] else [DriftItem("service", "knocked out")]
        return Assessment(deviation=drift), {}

    def apply(self, inputs):
        return None, {}   # the world heals on its own timeline, the reconciler observes and reports


async def watch_until(label: str, settle, timeline: list[bool]) -> list[bool]:
    print(f"{label}:")
    judge = settle.watch()
    next(judge)   # prime the stop condition before any pass has run
    observed: list[bool] = []

    async for residual in Reconciler((FlappingService(timeline),)).watch():
        clean = not residual
        observed.append(clean)
        shown = "clean" if clean else f"drift: {[str(item) for item in residual]}"
        print(f"    pass {len(observed)}: {shown}")
        if judge.send(residual) or len(observed) >= 10:   # the cap guards against a world that never holds
            break

    print(f"  stopped after {len(observed)} pass(es)\n")
    return observed


async def main() -> None:
    # healthy, then a break, then a repair that holds. Clean stops on the opening clean pass, before the
    # break ever lands, so it never learns the world was about to flap.
    timeline = [True, False, True, True]
    eager = await watch_until("Clean (stops on the first clean pass)", Clean(), timeline)
    assert eager == [True]   # one clean observation was the whole of its evidence

    # Stable(2) keeps watching, weathers the break and stops only on two clean passes in a row.
    patient = await watch_until("Stable(2) (needs two consecutive clean passes)", Stable(2), timeline)
    assert False in patient          # it stayed long enough to SEE the break Clean had already missed
    assert patient[-2:] == [True, True]   # and stopped only on two clean observations back to back
    assert len(patient) > len(eager)      # which cost it strictly more passes, the price of the guarantee


if __name__ == "__main__":
    asyncio.run(main())

