"""Bring up a service mesh concurrently, then bound a hung dependency with a Deadline.

The kernel is async to the bone. converge() and the reads are coroutines run on the caller's event loop.
A step whose apply() and assess() are coroutines closes its gap over the network without blocking the
loop it shares and a plain sync step still runs inline. This example uses asyncio.sleep to stand in for
that I/O.

Part 1 - concurrent bring-up. Four services with a dependency graph:

    Gateway
      |-- Auth        (after Gateway)
      |-- Catalog     (after Gateway)
             \\-- Checkout   (after Auth and Catalog)

The default Parallel dispatcher awaits each dependency wave with asyncio.gather, so Auth and Catalog boot
concurrently (a single wave), barred before and after by their dependency edges. Both the writes AND the
re-probe reads are coroutines, awaited on the caller's loop.

Part 2 - a hung dependency. One service's apply() never returns (an unresponsive socket). Under the plain
Parallel that would block the wave forever, so Supervised is used instead. It polls the injected Deadline
while the wave is in flight and cancels the hung coroutine when the budget elapses, raising Cancelled. The
deadline stays enforceable even against an apply() that hangs.

Run it:

    python examples/async_service_mesh.py

Expected stdout - the four services boot (Auth and Catalog concurrently), the converge returns an empty
residual verified by an awaited re-probe, a second converge is a clean no-op and then the hung-dependency
run is aborted by the Deadline with a Cancelled the example catches and reports. No external services are
touched. All I/O is a simulated asyncio.sleep.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Assessment, Cancelled, Deadline, DriftItem, Reconciler, Step, Supervised
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, Cancelled, Deadline, DriftItem, Reconciler, Step, Supervised


class Service(Step):
    """A service that boots by awaiting its I/O. assess() reads liveness (also over I/O), apply() boots it.
    Liveness lives in a cell, since the frozen Step forbids reassigning an attribute between passes."""

    def __init__(self, name: str, log: list):
        self.name = name
        self.log = log
        self.__up = [False]

    async def assess(self, inputs):
        await asyncio.sleep(0)  # a real liveness probe would be a network round-trip
        return Assessment(deviation=[] if self.__up[0] else [DriftItem(self.name, "service is down")]), {}

    async def apply(self, inputs):
        if self.__up[0]:
            return None, {}
        self.log.append(f"{self.name}-start")
        await asyncio.sleep(0.02)  # stand-in for the boot I/O
        self.__up[0] = True
        self.log.append(f"{self.name}-ready")
        return [DriftItem(self.name, "booted")], {}


def report(residual) -> None:
    changed = ", ".join(str(item) for item in residual.applied) or "nothing"
    print(f"  applied: {changed}")
    print("  residual: empty -> mesh verified by an awaited re-probe" if not residual
          else f"  residual: {[str(i) for i in residual]}")


async def bring_up() -> None:
    log: list = []

    class Gateway(Service):
        pass

    class Auth(Service):
        expects = (Gateway,)

    class Catalog(Service):
        expects = (Gateway,)

    class Checkout(Service):
        expects = (Auth, Catalog)

    # Handed in scrambled. Kahn resolves the waves and Parallel fans each on the loop.
    steps = [Checkout("checkout", log), Auth("auth", log), Gateway("gateway", log), Catalog("catalog", log)]
    reconciler = Reconciler(steps)

    print("Part 1: concurrent bring-up")
    booted = await reconciler.converge()
    report(booted)
    # Auth and Catalog share one wave, so both start before either finishes - concurrency, not sequence.
    ended_auth = log.index("auth-ready")
    started_catalog = log.index("catalog-start")
    concurrent = started_catalog < ended_auth
    print(f"  boot order: {log}")
    print(f"  auth and catalog booted concurrently: {concurrent}")

    assert not booted                              # up and the re-probe that says so was awaited too
    assert concurrent                              # one gather, two coroutines in flight
    assert log.index("gateway-ready") < started_catalog                  # the bar BEFORE the wave held
    assert max(ended_auth, log.index("catalog-ready")) < log.index("checkout-start")   # and the one after

    print("Second converge (clean no-op):")
    settled = await reconciler.converge()
    report(settled)
    assert not settled.applied   # nothing to write, so nothing written: the loop did not re-boot the mesh


async def bound_a_hang() -> None:
    print()
    print("Part 2: a hung dependency, bounded by a Deadline via Supervised")

    class Wedged(Step):
        def assess(self, inputs):
            return Assessment(deviation=[DriftItem("wedged", "never comes up")]), {}

        async def apply(self, inputs):
            await asyncio.Event().wait()  # an unresponsive socket: this never returns
            return None, {}

    reconciler = Reconciler(
        (Wedged(),),
        mode=Supervised(poll=0.01),   # polls the cancellation while the wave is in flight
        cancellation=Deadline(0.05),        # the budget the hung apply() must not outlast
    )
    aborted = None
    try:
        await reconciler.converge()
    except Cancelled as abort:
        aborted = abort
        print(f"  aborted as expected: {abort}")
        print("  the Deadline stayed enforceable even though apply() hung")

    # The whole point of Part 2: without this the example would still exit 0 if converge() simply
    # returned, which is exactly the failure mode (a budget nobody enforces) it exists to rule out.
    assert aborted is not None


async def main() -> None:
    await bring_up()
    await bound_a_hang()


if __name__ == "__main__":
    asyncio.run(main())

