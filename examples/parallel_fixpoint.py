"""Provision a small dependency graph with ThreadDispatcher and settle it with Fixpoint.

The graph models bringing up a tiny service stack:

    Network
      |-- Database
      |-- Cache
             \\-- AppServers   (after Database and Cache)

Kahn resolves that into three waves:

    wave 0: Network
    wave 1: Database, Cache      <- mutually independent, so ThreadDispatcher fans them across threads
    wave 2: AppServers

Two behaviours are on show at once:

  ThreadDispatcher   runs the steps inside a wave on worker threads, with a barrier between
                     waves so Network is fully up before Database and Cache start and both of
                     those are up before AppServers. The example records which worker thread
                     handled each resource to make the fan-out visible.

  Fixpoint convergence  repeats the apply -> re-probe cycle until the residual stops changing.
                     AppServers brings up one replica per pass (a stand-in for a controller that
                     nudges reality one step toward desired each reconcile), so it needs several
                     passes to reach its desired replica count. Fixpoint keeps going until the
                     re-probe comes back clean.

An empty residual at the end is the proof the whole stack reached desired state, checked by
re-probing and `applied` is the running record of every change made across all passes.

Run it:

    python examples/parallel_fixpoint.py

Expected stdout - the resolved waves, evidence that Database and Cache ran on pool worker
threads (not the main thread), a converge that took several Fixpoint passes with an empty
residual and a clean idempotent second converge.
"""

import asyncio
import sys
import threading
import time
from pathlib import Path

try:
    from cabaxiom import Assessment, DriftItem, Fixpoint, Graph, Kahn, Reconciler, Step, ThreadDispatcher
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, DriftItem, Fixpoint, Graph, Kahn, Reconciler, Step, ThreadDispatcher


class Cluster:
    """The shared world the steps reconcile against. Guarded by a lock because ThreadDispatcher runs
    the steps within a wave on different threads at the same time."""

    def __init__(self):
        self._lock = threading.Lock()
        self.ready: set[str] = set()   # single-shot resources that are provisioned
        self.replicas = 0              # app-server replicas brought up so far
        self.worker: dict[str, str] = {}  # resource name -> the thread that provisioned it

    def bring_up(self, name: str) -> None:
        with self._lock:
            self.ready.add(name)
            self.worker[name] = threading.current_thread().name

    def is_ready(self, name: str) -> bool:
        with self._lock:
            return name in self.ready

    def scale_once(self) -> int:
        with self._lock:
            self.replicas += 1
            self.worker["AppServers"] = threading.current_thread().name
            return self.replicas


class _Resource(Step):
    """A single-shot resource - provisioned once, ready forever after."""

    name = "?"

    def __init__(self, cluster: Cluster):
        self.cluster = cluster

    def assess(self, inputs):
        if self.cluster.is_ready(self.name):
            return Assessment(deviation=[]), {}
        return Assessment(deviation=[DriftItem(self.name, "resource is not provisioned")]), {}

    def apply(self, inputs):
        if self.cluster.is_ready(self.name):
            return None, {}
        time.sleep(0.05)  # stand in for real provisioning latency, so the fan-out overlaps
        self.cluster.bring_up(self.name)
        return [DriftItem(self.name, "provisioned")], {}


class Network(_Resource):
    name = "Network"


class Database(_Resource):
    name = "Database"
    expects = (Network,)


class Cache(_Resource):
    name = "Cache"
    expects = (Network,)


class AppServers(Step):
    """Brings up one replica per pass until it reaches the desired count. This is what makes
    Fixpoint loop. A single apply() makes partial progress, so the re-probe stays dirty until
    enough passes have run."""

    expects = (Database, Cache)

    def __init__(self, cluster: Cluster, desired_replicas: int):
        self.cluster = cluster
        self.desired = desired_replicas

    def assess(self, inputs):
        have = self.cluster.replicas
        if have < self.desired:
            return Assessment(deviation=[DriftItem("AppServers", f"{have}/{self.desired} replicas up")]), {}
        return Assessment(deviation=[]), {}

    def apply(self, inputs):
        if self.cluster.replicas >= self.desired:
            return None, {}
        now = self.cluster.scale_once()
        return [DriftItem("AppServers", f"scaled up to {now} replica(s)")], {}


def report(residual) -> None:
    print(f"  applied this run: {len(residual.applied)} change(s)")
    for item in residual.applied:
        print(f"    + {item}")
    if residual:
        print("  residual (still wrong):")
        for item in residual:
            print(f"    ! {item}")
    else:
        print("  residual: empty -> whole stack verified by re-probe")


async def main() -> None:
    cluster = Cluster()
    desired_replicas = 3

    # Supplied scrambled to show the ordering does the sequencing, not the caller.
    steps = [
        AppServers(cluster, desired_replicas),
        Cache(cluster),
        Network(cluster),
        Database(cluster),
    ]

    print("Resolved waves (Kahn):")
    supplied = tuple(steps)
    waves = [tuple(step.__class__.__name__ for step in wave) for wave in Kahn().waves(Graph(supplied))]
    for index, names in enumerate(waves):
        print(f"    wave {index}: {', '.join(names)}")
    # Three waves out of a scrambled list. Database and Cache share one because neither declared the
    # other and that shared wave is the only thing ThreadDispatcher is allowed to fan.
    assert waves[0] == ("Network",)
    assert set(waves[1]) == {"Database", "Cache"}
    assert waves[2] == ("AppServers",)
    print()

    # ThreadDispatcher fans each wave across worker threads via asyncio.to_thread, so a blocking
    # provisioning step rides the async engine without pinning the event loop - the 4.0 bridge for a
    # synchronous domain. Fixpoint loops apply -> re-probe until the residual settles or the ceiling is hit.
    reconciler = Reconciler(
        steps,
        Kahn(),
        mode=ThreadDispatcher(),
        convergence=Fixpoint(max_passes=10),
    )

    print("Initial drift:")
    for item in await reconciler.assess():
        print(f"    - {item}")
    print()

    print("Converge (ThreadDispatcher, Fixpoint convergence):")
    first = await reconciler.converge()
    report(first)
    # AppServers moves one replica per apply(), so a single pass CANNOT reach the desired count.
    # An empty residual here is Fixpoint having looped apply -> re-probe until the world caught up.
    assert not first
    assert cluster.replicas == desired_replicas
    print()

    print("Second converge (should be a clean no-op):")
    again = await reconciler.converge()
    report(again)
    assert not again.applied            # a settled stack is not re-provisioned and not over-scaled
    assert cluster.replicas == desired_replicas
    print()

    main_thread = threading.current_thread().name
    print("Fan-out evidence (which thread provisioned each wave-1 resource):")
    for name in ("Database", "Cache"):
        worker = cluster.worker.get(name, "?")
        off_main = "off the main thread" if worker != main_thread else "on the main thread"
        print(f"    {name:<9} -> {worker} ({off_main})")

    # Fanned, not merely permitted to fan. Both wave-1 resources were provisioned by pool workers, so the
    # concurrency is a fact about this run and not a promise made by the executor's docstring.
    assert cluster.worker["Database"] != main_thread
    assert cluster.worker["Cache"] != main_thread


if __name__ == "__main__":
    asyncio.run(main())
