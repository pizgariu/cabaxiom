"""Provision a small dependency graph with the Parallel dispatcher and settle it with Fixpoint.

The graph models bringing up a tiny service stack:

    Network
      |-- Database
      |-- Cache
             \\-- AppServers   (expects Database and Cache)

Kahn resolves that into three waves:

    wave 0: Network
    wave 1: Database, Cache      <- mutually independent, so Parallel fans them concurrently
    wave 2: AppServers

Two behaviours are on show at once:

  Parallel dispatcher  gathers the steps inside a wave on the event loop, with a barrier between
                     waves so Network is fully up before Database and Cache start and both of
                     those are up before AppServers. The example records which thread ran each
                     provision to show the whole fan-out stays on the caller's thread.

  Fixpoint convergence  repeats the apply -> re-probe cycle until the residual stops changing.
                     AppServers brings up one replica per pass (a stand-in for a controller that
                     nudges reality one step toward desired each reconcile), so it needs several
                     passes to reach its desired replica count. Fixpoint keeps going until the
                     re-probe comes back clean.

An empty residual at the end is the proof the whole stack reached desired state, checked by
re-probing, while `applied` is the running record of every change made across all passes.

Run it:

    python examples/parallel_fixpoint.py

Expected stdout - the resolved waves, evidence that every provision stayed on the caller's
thread while the wave fanned on the event loop, a converge that took several Fixpoint passes
with an empty residual and a clean idempotent second converge.
"""
import asyncio
import sys
import threading
import time
from pathlib import Path

try:
    from cabaxiom import DriftItem, Fixpoint, Graph, Kahn, Parallel, Reconciler, Step
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import DriftItem, Fixpoint, Graph, Kahn, Parallel, Reconciler, Step


class Cluster:
    """The shared world the steps reconcile against. Guarded by a lock because Parallel runs
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

    def drift(self) -> list[DriftItem]:
        if self.cluster.is_ready(self.name):
            return []
        return [DriftItem(self.name, "resource is not provisioned")]

    def apply(self) -> list[DriftItem] | None:
        if self.cluster.is_ready(self.name):
            return None
        time.sleep(0.05)  # stand in for real provisioning latency, so the fan-out overlaps
        self.cluster.bring_up(self.name)
        return [DriftItem(self.name, "provisioned")]


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

    def drift(self) -> list[DriftItem]:
        have = self.cluster.replicas
        if have < self.desired:
            return [DriftItem("AppServers", f"{have}/{self.desired} replicas up")]
        return []

    def apply(self) -> list[DriftItem] | None:
        if self.cluster.replicas >= self.desired:
            return None
        now = self.cluster.scale_once()
        return [DriftItem("AppServers", f"scaled up to {now} replica(s)")]


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


def main() -> None:
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
    for index, wave in enumerate(Kahn().levels(Graph(tuple(steps)))):
        names = ", ".join(type(step).__name__ for step in wave)
        print(f"    wave {index}: {names}")
    print()

    # Parallel gathers each dependency wave on the event loop and bars between waves, so Step.expects
    # still holds under concurrency. Fixpoint loops apply -> re-probe until the residual settles or the
    # ceiling is hit.
    dispatcher = Parallel()
    reconciler = Reconciler(
        steps,
        Kahn(),
        dispatcher=dispatcher,
        convergence=Fixpoint(max_passes=10),
    )

    print("Initial plan:")
    for item in asyncio.run(reconciler.plan()):
        print(f"    - {item}")
    print()

    print("Converge (Parallel dispatcher, Fixpoint convergence):")
    report(asyncio.run(reconciler.converge()))
    print()

    print("Second converge (should be a clean no-op):")
    report(asyncio.run(reconciler.converge()))
    print()

    main_thread = threading.current_thread().name
    print("Fan-out evidence (which thread provisioned each wave-1 resource):")
    for name in ("Database", "Cache"):
        worker = cluster.worker.get(name, "?")
        off_main = "off the main thread" if worker != main_thread else "on the main thread"
        print(f"    {name:<9} -> {worker} ({off_main})")


if __name__ == "__main__":
    main()
