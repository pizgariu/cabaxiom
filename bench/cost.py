"""Read the deterministic cost gate's numbers back out and time the same runs for the record.

tests/test_cost.py ASSERTS the counts. This prints them, beside the wall time this machine took to produce
them - the number a gate must never assert and the number a human still wants to see once. Run it when a
change is meant to make the kernel cheaper or when the baseline is being refreshed on new hardware.

    python3 bench/cost.py                the counts, the timings and the growth
    python3 bench/cost.py --deep         the scaling sweep an order of magnitude larger
    python3 bench/cost.py --json out.json the readings as data

It imports its instruments FROM the test, deliberately. The baseline is then produced by the very counters
the gate asserts, so a recorded number and a gated number cannot drift apart - the failure mode of every
benchmark that keeps its own copy of the harness it measures.

Where stress.py fits. That one fits measured TIME against each documented complexity claim and reports the
exponent, which is the right instrument for asking whether an operation outgrew its claim. This one counts
OPERATIONS for the run as a whole, which is the instrument a gate can be written against. They answer
different questions and neither replaces the other.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import json
import platform
import sys
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, NamedTuple, final

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT / "tests"))

from test_cost import (  # noqa: E402
    _Counts,
    _Inversion,
    _Language,
    _Lookups,
    _Shapes,
    _Tally,
)

from cabaxiom import Graph, Reconciler  # noqa: E402


@final
class Timed(NamedTuple):
    """One declaration, counted and timed. The counts are the gate's own numbers, the seconds are this
    machine's."""
    label: str
    vertices: int
    edges: int
    resolve: float
    converge: float
    prune: float


@final
class Cost:
    """The baseline harness. Counts first, because they are the contract, then the seconds they took."""

    # How many times, per step, a converge enters a verb and fires a unit hook. The numbers tests/test_cost.py
    # asserts, restated here so the printed report says what it is checking rather than only what it measured.
    WRITES_PER_STEP = 1
    READS_PER_STEP = 1
    UNIT_HOOKS_PER_STEP = 3
    PASS_HOOKS_PER_CYCLE = 3

    def __init__(self, *, deep: bool = False, rounds: int = 3):
        self.__deep = deep
        self.__rounds = rounds

    def spans(self) -> tuple[int, ...]:
        # Doubling layer counts over a fixed width, so V and E double together and a quadratic has nowhere to
        # hide. The deep sweep is the same shape an order of magnitude up.
        return (128, 256, 512, 1024) if self.__deep else (16, 32, 64, 128, 256)

    @staticmethod
    def __best(work: Callable[[], Coroutine[Any, Any, object]], rounds: int) -> float:
        # Best of n, as stress.py takes it - the fastest run is the one least polluted by whatever else the
        # machine was doing. A benchmark that reports the noise reports the machine.
        best = float("inf")
        for _ in range(rounds):
            gc.collect()
            started = time.perf_counter()
            asyncio.run(work())
            best = min(best, time.perf_counter() - started)
        return best

    def counted(self) -> dict[str, object]:
        # THE GATE'S NUMBERS, read off one run of each shape. Every line here is asserted by a test, so a
        # number that surprises a reader is a number to go and read the assertion for.
        counts, watch, lookups = _Counts(), _Tally(), _Lookups()
        steps = _Shapes.independent(200, counts)
        run = Reconciler(steps, observer=watch)
        residual = asyncio.run(run.converge())
        converge = {
            "steps": len(steps), "applies": counts.apply, "reads": counts.assess,
            "pass hooks (began, acted, remained)": list(watch.fired("began", "acted", "remained")),
            "unit hooks (dispatching, stepped, produced)": list(watch.fired("dispatching", "stepped", "produced")),
            "retried": watch.fired("retried")[0], "residual": len(residual),
            "dependents map built": _Inversion.built(run),
        }

        counts, watch = _Counts(), _Tally()
        torn = asyncio.run(Reconciler(_Shapes.independent(200, counts), observer=watch).prune())
        teardown = {"steps": 200, "prunes": counts.prune, "reads": counts.assess,
                    "pruned hook": watch.fired("pruned")[0], "survivors": len(torn)}

        resolution: dict[str, object] = {}
        for label, steps, promised in (("chain 200", _Shapes.chain(200, _Counts()), 199),
                                       ("fan 200", _Shapes.fan(200, _Counts()), 199),
                                       ("replicas 100+100", _Shapes.replicas(100), 100)):
            lookups = _Lookups()
            graph = Graph(steps, _Language.metered(lookups))
            edges = sum(len(graph.dependencies(step)) for step in graph.steps)
            resolution[label] = {"names asked": lookups.names, "steps reached": lookups.reached,
                                 "derived edges": edges, "names promised": promised}
        return {"converge": converge, "teardown": teardown, "resolution": resolution}

    def timed(self) -> list[Timed]:
        # The same shapes, timed. Resolution, converge and teardown separately, because they are three
        # different costs and a single total hides which one moved.
        readings: list[Timed] = []
        for layers in self.spans():
            counts = _Counts()
            steps = _Shapes.layered(32, layers, 2, counts)
            gc.collect()
            started = time.perf_counter()
            run = Reconciler(steps)
            resolved = time.perf_counter() - started
            edges = sum(len(run._graph.dependencies(step)) for step in run._graph.steps)
            converged = self.__best(run.converge, self.__rounds)
            pruned = self.__best(run.prune, self.__rounds)
            readings.append(Timed(f"layered 32x{layers}", len(steps), edges, resolved, converged, pruned))
            print(f"  {readings[-1].label:<18} V={len(steps):>6} E={edges:>7} "
                  f"resolve={resolved * 1000:>7.1f} ms converge={converged * 1000:>7.1f} ms")
        return readings

    def dense(self) -> list[Timed]:
        # The other direction - hold the vertices and grow the declared edges, so the edge term is read on its
        # own. A derivation quadratic in the fan shows here and nowhere else.
        readings: list[Timed] = []
        for span in (1, 2, 4, 8, 16):
            counts = _Counts()
            steps = _Shapes.layered(32, 64, span, counts)
            gc.collect()
            started = time.perf_counter()
            run = Reconciler(steps)
            resolved = time.perf_counter() - started
            edges = sum(len(run._graph.dependencies(step)) for step in run._graph.steps)
            converged = self.__best(run.converge, self.__rounds)
            readings.append(Timed(f"span {span}", len(steps), edges, resolved, converged, 0.0))
            print(f"  span {span:<14} V={len(steps):>6} E={edges:>7} "
                  f"resolve={resolved * 1000:>7.1f} ms converge={converged * 1000:>7.1f} ms")
        return readings

    @staticmethod
    def inversion() -> list[dict[str, object]]:
        # What the Ledger's inversion costs on a DENSE graph and what the cache saves. The gate proves the
        # laziness and the caching. Only a clock can say what they are worth, so this is where that lives.
        readings: list[dict[str, object]] = []
        for size in (100, 200, 400):
            steps = _Shapes.replicas(size)
            graph = Graph(steps)
            edges = sum(len(graph.dependencies(step)) for step in graph.steps)
            gc.collect()
            started = time.perf_counter()
            graph.dependents(steps[0])
            first = time.perf_counter() - started
            started = time.perf_counter()
            graph.dependents(steps[0])
            again = time.perf_counter() - started
            readings.append({"replicas": size, "edges": edges, "first ask ms": round(first * 1000, 4),
                             "cached ask ms": round(again * 1000, 5)})
            print(f"  replicas {size}+{size:<8} E={edges:>7} first={first * 1000:>7.3f} ms "
                  f"cached={again * 1000:>7.4f} ms")
        return readings

    @staticmethod
    def largest() -> dict[str, object]:
        # One run at the size the kernel is meant to carry, end to end.
        counts, watch = _Counts(), _Tally()
        steps = _Shapes.layered(50, 100, 3, counts)
        gc.collect()
        started = time.perf_counter()
        run = Reconciler(steps, observer=watch)
        resolved = time.perf_counter() - started
        edges = sum(len(run._graph.dependencies(step)) for step in run._graph.steps)
        started = time.perf_counter()
        residual = asyncio.run(run.converge())
        converged = time.perf_counter() - started
        print(f"  V={len(steps)} E={edges} resolve={resolved * 1000:.1f} ms "
              f"converge={converged * 1000:.1f} ms residual={len(residual)} applies={counts.apply}")
        return {"vertices": len(steps), "edges": edges, "resolve ms": round(resolved * 1000, 1),
                "converge ms": round(converged * 1000, 1), "applies": counts.apply,
                "reads": counts.assess, "residual": len(residual),
                "unit hooks": list(watch.fired("dispatching", "stepped", "produced"))}

    @staticmethod
    def growth(readings: list[Timed]) -> None:
        # Adjacent ratios, printed beside the size ratio they should be tracking. Nothing is judged here - the
        # gate does the judging, in counts. This is for a human deciding whether to go and look.
        print(f"\n{'shape':<18}{'size x':>9}{'resolve x':>11}{'converge x':>12}{'us per V+E':>13}")
        for earlier, later in zip(readings, readings[1:]):
            units = (later.vertices + later.edges) / (earlier.vertices + earlier.edges)
            print(f"{later.label:<18}{units:>9.2f}{later.resolve / earlier.resolve:>11.2f}"
                  f"{later.converge / earlier.converge:>12.2f}"
                  f"{later.converge / (later.vertices + later.edges) * 1e6:>13.2f}")

    @classmethod
    def cli(cls, argv: list[str]) -> int:
        parsed = argparse.ArgumentParser(description="Read the cost gate's counts and time the same runs.")
        parsed.add_argument("--deep", action="store_true", help="an order of magnitude larger")
        parsed.add_argument("--rounds", type=int, default=3, help="timed repeats, best of (default 3)")
        parsed.add_argument("--json", type=Path, default=None, help="write the readings as data")
        args = parsed.parse_args(argv)

        cost = cls(deep=args.deep, rounds=args.rounds)
        print(f"cabaxiom cost baseline, {platform.python_implementation()} {platform.python_version()} on "
              f"{platform.system()} {platform.machine()}, best of {args.rounds}")
        print(f"one write and one read per step, {cls.UNIT_HOOKS_PER_STEP} unit hooks per step, "
              f"{cls.PASS_HOOKS_PER_CYCLE} pass hooks per cycle - the gate's claim, asserted in "
              f"tests/test_cost.py")

        print("\nCOUNTED (the gate)")
        counted = cost.counted()
        print(json.dumps(counted, indent=1))

        print("\nTIMED, doubling V and E together")
        scaled = cost.timed()
        cost.growth(scaled)

        print("\nTIMED, holding V and growing E")
        dense = cost.dense()

        print("\nTHE LEDGER INVERSION on a dense graph, first ask against the cached one")
        inverted = cost.inversion()

        print("\nONE LARGE RUN")
        largest = cost.largest()

        if args.json is not None:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps({
                "interpreter": platform.python_version(),
                "platform": f"{platform.system()} {platform.machine()}",
                "counted": counted,
                "scaled": [reading._asdict() for reading in scaled],
                "dense": [reading._asdict() for reading in dense],
                "inversion": inverted,
                "largest": largest,
            }, indent=1), encoding="utf-8")
            print(f"\nwritten -> {args.json}")
        print("\nwall time is informational. The counts above are the gate - see bench/COST-BASELINE.md")
        return 0


if __name__ == "__main__":
    raise SystemExit(Cost.cli(sys.argv[1:]))
