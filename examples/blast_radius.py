"""Ask what a failure would cost BEFORE you run it, then watch the run agree.

Every other read in this kernel describes what a run will do. `foresee()` describes what it would LOSE
if one step failed, which is the question you actually have before pressing the button on a risky step.

The reason to trust the answer is not that the forecast is careful. It is that `blocked` comes from
`Graph.fallout()` and the `Ledger` blames a real failure by walking that same `fallout()`. The forecast
and the handling are one walk with two callers, so this example can print the prediction, run the fleet
for real and diff the two - which is exactly what it does.

Halt is reported in two channels on purpose, because Halt gates by run POSITION and not by edges:

  skipped   every step in a strictly later wave. Once the run stands still, the engine never starts these.
  settling  the failure's OWN wave. Indeterminate by shape and this engine resolves it one way. The wave
            was admitted whole and in flight when the failure landed, so its members settle, never skip.

Folding those into one number would be a promise the kernel does not make, so they are reported apart.

Run it:

    python examples/blast_radius.py

Expected stdout - the forecast for a risky step and for a linchpin, then a real BestEffort run whose
blocked set matches the forecast exactly, then the Halt reading showing the guaranteed skips holding while
the failure's own wave settles rather than skips. The "world" is an in-memory set of live names.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Assessment, DriftItem, OnError, Parallel, Reconciler, Step
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, DriftItem, OnError, Parallel, Reconciler, Step

world: set[str] = set()


class Service(Step):
    """A service whose existence is a name in a shared in-memory `world` set."""

    name = "service"

    def assess(self, inputs):
        return Assessment(deviation=[] if self.name in world else [DriftItem(self.name, "not up")]), {}

    def apply(self, inputs):
        if self.name in world:
            return None, {}
        world.add(self.name)
        return [DriftItem(self.name, "brought up")], {}


class Network(Service):
    name = "network"


class Database(Service):
    name = "database"
    expects = (Network,)
    provides = frozenset({"database"})


class Migration(Service):
    """The risky one. Schema migrations are where a converge actually tends to die."""

    name = "migration"
    wants = ("database",)

    def apply(self, inputs):
        raise RuntimeError("constraint violation on users.email")


        return None, {}
class Cache(Service):
    """Independent of the migration but resolved into the SAME group by the ordering, which is what
    makes the two Halt channels different rather than academic."""

    name = "cache"
    expects = (Database,)


class Api(Service):
    name = "api"
    expects = (Migration,)


class Worker(Service):
    name = "worker"
    expects = (Migration,)


class Metrics(Service):
    """Independent of the whole chain, which is the interesting part of a blast radius."""

    name = "metrics"


def fleet(executor):
    steps = (Network(), Database(), Migration(), Cache(), Api(), Worker(), Metrics())
    reconciler = Reconciler(steps, mode=executor)
    found = {step.__class__.__name__: step for step in steps}
    return reconciler, found


async def main() -> None:
    reconciler, steps = fleet(Parallel(OnError.BestEffort))

    print("THE RUN, in resolved order")
    print(f"    {reconciler.explain()}\n")

    print("BEFORE anything runs - what would each failure cost?")
    for name in ("Migration", "Database", "Metrics"):
        casualty = reconciler.foresee(steps[name])
        verdict = "takes nobody with it" if casualty.contained else f"blocks {list(casualty.blocked)}"
        starves = f", sole provider of {list(casualty.starves)}" if casualty.starves else ""
        print(f"    {casualty.failed:<10} {verdict}{starves}")
    print()

    # --- the forecast, then the reality ------------------------------------------------------------
    forecast = reconciler.foresee(steps["Migration"])
    print("NOW RUN IT FOR REAL - the migration fails, BestEffort collects")
    residual = await reconciler.converge()
    recorded = sorted(item.name for item in residual if "step blocked" in item.message)
    failed = [item.name for item in residual if "step failed" in item.message]

    print(f"    failed : {failed}")
    print(f"    forecast blocked: {sorted(forecast.blocked)}")
    print(f"    ACTUAL   blocked: {recorded}")
    print(f"    identical: {sorted(forecast.blocked) == recorded}"
          "   (one fallout() walk, two callers - they cannot disagree)")
    print(f"    world: {sorted(world)}   (metrics came up, nothing downstream did)\n")

    # --- the two Halt channels and why they are two ----------------------------------------------
    print("UNDER HALT - the same failure, read by run POSITION instead of by edges")
    halted, halted_steps = fleet(Parallel(OnError.Halt))
    halt = halted.foresee(halted_steps["Migration"])
    print(f"    guaranteed skipped: {list(halt.skipped)}")
    print(f"    indeterminate     : {list(halt.settling)}   (the failure's own wave)")

    world.clear()
    halt_residual = await halted.converge()
    halt_skipped = {item.name for item in halt_residual if "step skipped" in item.message}
    print(f"    the run skipped      : {sorted(halt_skipped)}")
    print(f"    the guarantee held   : {set(halt.skipped) <= halt_skipped}")
    print(f"    settling members ran : {set(halt.settling) & halt_skipped == set()}   (the fan admitted the whole wave)")
    print("    The wave was in flight when the migration failed, so its members settled rather than skipped.")
    print("    Reporting that group as skipped would be a promise the shape does not make.")

    assert sorted(forecast.blocked) == recorded == ["Api", "Worker"]
    assert set(halt.skipped) <= halt_skipped               # the guarantee: strictly later waves skip
    assert set(halt.settling) & halt_skipped == set()      # the maybe resolved to "settled", never skipped
    assert reconciler.foresee(steps["Metrics"]).contained

    print("\nA forecast you can check against the run that follows it, in the same script.")


if __name__ == "__main__":
    asyncio.run(main())
