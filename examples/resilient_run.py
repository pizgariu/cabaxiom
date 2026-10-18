"""Push on through failures, block what depends on them, retry the transient and watch it live.

Three resilience axes at once, on a small deploy graph:

    Migrate            (fails permanently)
      \\-- Api          (after Migrate)
             \\-- Smoke  (after Api)
    Cache              (independent, fails twice then recovers)
    Metrics           (independent, clean)

  OnError.BestEffort   a failing step does not abort the run. It is recorded as `step failed`
                       drift and its transitive dependents are BLOCKED - reported as
                       `step blocked` rather than run against state nobody put there. Independent
                       steps still run, which is the partial progress BestEffort exists for.

  Retry(3)             each write gets up to three attempts, paced by a Backoff. Cache recovers
                       on its third try. Migrate exhausts all three and only then counts as failed.

  Observer             two at once, composed with Chorus. A live observer prints each unit as it
                       settles (stepped) and each spent attempt (retried) and a Journal records
                       the whole run as data for inspection afterward.

Run it:

    python examples/resilient_run.py

Expected stdout - a live trace of attempts and settled steps, then the residual - Cache and
Metrics applied, Migrate failed, Api and Smoke blocked - and the Journal's record of the pass.
All in memory. The Backoff is zero so it runs instantly.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import (
        Assessment,
        Chorus,
        DriftItem,
        Fixed,
        Journal,
        Observer,
        OnError,
        Parallel,
        Reconciler,
        Retry,
        Step,
    )
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import (
        Assessment,
        Chorus,
        DriftItem,
        Fixed,
        Journal,
        Observer,
        OnError,
        Parallel,
        Reconciler,
        Retry,
        Step,
    )


class Deploy(Step):
    def __init__(self, name: str):
        self.name = name
        self.done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.done[0] else [DriftItem(self.name, "not deployed")]), {}

    def apply(self, inputs):
        self.done[0] = True
        return [DriftItem(self.name, "deployed")], {}


class Migrate(Deploy):
    def apply(self, inputs):
        raise RuntimeError("migration failed")  # permanent: exhausts its retries


        return None, {}
class Api(Deploy):
    expects = (Migrate,)


class Smoke(Deploy):
    expects = (Api,)


class Cache(Deploy):
    def __init__(self, name: str):
        super().__init__(name)
        self.tries = [0]   # a cell, since the frozen Step forbids reassigning an attribute

    def apply(self, inputs):
        self.tries[0] += 1
        if self.tries[0] < 3:
            raise RuntimeError(f"cache warm-up not ready (try {self.tries[0]})")  # transient
        return super().apply(inputs)


class Metrics(Deploy):
    pass


class Live(Observer):
    """Prints the unit-level hooks as they fire, so the run is watchable while it happens."""

    def stepped(self, step, changes, error) -> None:
        if error is not None:
            print(f"    x {step.__class__.__name__}: failed with {error.__class__.__name__}")
        else:
            made = ", ".join(str(c) for c in (changes or [])) or "no change"
            print(f"    . {step.__class__.__name__}: {made}")

    def retried(self, step, attempt, error) -> None:
        print(f"    ~ {step.__class__.__name__}: attempt {attempt} failed ({error}), retrying")


async def main() -> None:
    journal = Journal()
    migrate, api, smoke = Migrate("migrate"), Api("api"), Smoke("smoke")
    cache, metrics = Cache("cache"), Metrics("metrics")
    steps = [migrate, api, smoke, cache, metrics]
    reconciler = Reconciler(
        steps,
        mode=Parallel(OnError.BestEffort),
        retry=Retry(3, backoff=Fixed(0)),           # zero backoff keeps the example instant
        observer=Chorus(Live(), journal),           # trace live AND record as data
    )

    print("Live trace:")
    residual = await reconciler.converge()
    print()

    failed = [i for i in residual if "step failed" in i.message]
    blocked = [i for i in residual if "step blocked" in i.message]
    print(f"applied (partial progress): {[str(i) for i in residual.applied]}")
    print(f"failed:  {[str(i) for i in failed]}")
    print(f"blocked: {[str(i) for i in blocked]}")

    # Retry(3): Cache's third attempt is the one that stuck, so the transient really was ridden out and
    # not just tolerated. Migrate raises every time, so it spent the same three and only then counted.
    assert cache.tries[0] == 3

    # BestEffort, both halves. Independent work still landed, which is the partial progress it exists
    # for. The migration's dependents did NOT run - blocked is a REFUSAL to act on state nobody put
    # there, not a failure of their own and `done` staying False is what says so.
    assert {item.name for item in failed} == {"Migrate"}
    assert {item.name for item in blocked} == {"Api", "Smoke"}
    assert cache.done[0] and metrics.done[0]
    assert not api.done[0] and not smoke.done[0]
    print()

    print("Journal (the run recorded as data):")
    for n, entry in enumerate(journal.passes):
        print(f"    pass {n}: applied={[str(i) for i in entry.applied]} residual={[str(i) for i in entry.residual]}")

    # The Journal is the run, not a paraphrase of it. Its last pass carries the very residual converge()
    # handed back, so an assertion made against the record is an assertion about the run.
    assert journal.passes[-1].residual == tuple(residual)
    assert journal.passes[-1].applied == residual.applied


if __name__ == "__main__":
    asyncio.run(main())
