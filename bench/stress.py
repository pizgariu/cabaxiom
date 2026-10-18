"""Stress the kernel on heavy and huge declarations and check the complexity table is not fiction.

Every row of `docs` and of the technical page claims a cost for one operation. This runs those operations
on generated declarations of several SHAPES, at doubling sizes and reads the growth back out. A claim of
O(V + E) that doubles when the size doubles passes. One that quadruples does not, whatever the docstring
says next to it.

    python3 bench/stress.py                 the default sweep, a minute or so
    python3 bench/stress.py --deep          the same shapes an order of magnitude larger
    python3 bench/stress.py --check         exit non-zero when an operation outgrows its claim
    python3 bench/stress.py --json out.json the readings as data

Nothing here is a ceiling in seconds, so the same run means the same thing on a fast laptop and a slow CI
box. Each operation is scored by fitting its measured time against its OWN claimed cost, over every size
measured and reporting the exponent. 1.00 grows exactly as the claim predicts, 2.00 means the claim is
linear and the code is quadratic in it.

Two things that make the score honest. The cost is a function of what was actually BUILT, not of the size
knob - `replicas` doubles V and quadruples E, so for anything O(V + E) a four-fold time is the correct
answer there and a two-fold time would be the surprise. And the exponent is fitted over all the sizes
rather than taken from the worst adjacent pair, because the worst pair is where the noise lives.
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
import tracemalloc
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from math import log2
from pathlib import Path
from typing import NamedTuple, final, override

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cabaxiom import (  # noqa: E402
    DFS,
    Components,
    Drift,
    Graph,
    Kahn,
    Priority,
    Step,
    Waves,
)


@final
class Census(NamedTuple):
    """What a built declaration actually IS, counted rather than assumed."""
    vertices: int
    edges: int


@final
class Reading(NamedTuple):
    """One shape at one size, measured."""
    shape: str
    size: int
    census: Census
    seconds: dict[str, float]
    peak: int


class Shape(ABC):
    """The open axis of this harness - a FAMILY of declarations, buildable at any size.

    `raised` is concrete and final. It does the one thing a benchmark must never skip - it confronts
    what the generator built with what the generator PROMISED. A stress number attributed to the wrong
    graph is worse than no number at all, because it reads exactly like a real one. Add a shape by
    implementing the two seams and the guard covers it with no edit here."""

    @property
    def named(self) -> str:
        return self.__class__.__name__.lower()

    @final
    def raised(self, size: int) -> tuple[tuple[Step, ...], Graph, Census, float]:
        steps = tuple(self.build(size))
        gc.collect()
        started = time.perf_counter()
        graph = Graph(steps)
        derived = time.perf_counter() - started
        census = Census(len(steps), sum(len(graph.dependencies(step)) for step in graph.steps))
        promised = self.promises(size)
        if census != promised:
            raise SystemExit(f"{self.named} at size {size} promised {promised} and built {census}. "
                             f"Fix the shape - every timing below it would be a measurement of "
                             f"something else.")
        return steps, graph, census, derived

    @abstractmethod
    def build(self, size: int) -> Sequence[Step]:
        # The declaration itself, at this size. Plain steps, plain slots, nothing clever.
        ...

    @abstractmethod
    def promises(self, size: int) -> Census:
        # How many vertices and edges this shape SAYS it produces at this size. The guard checks it.
        ...

    @abstractmethod
    def sizes(self, *, deep: bool) -> tuple[int, ...]:
        # Doubling sizes for this shape. They differ per shape because the shapes cost wildly different
        # amounts per vertex and a sweep that takes an hour is a sweep nobody runs.
        ...


class Node(Step):
    """The cheapest possible step - it declares, it never runs."""

    @override
    def drift(self) -> Sequence[Drift]:
        return ()


@final
class Chain(Shape):
    """N steps in one line, each needing the one before. The deepest graph there is and the shape whose
    every step shares ONE class - which is what makes it the interesting one for instance addressing."""

    @override
    def build(self, size: int) -> Sequence[Step]:
        made = [Node() for _ in range(size)]
        for earlier, later in zip(made, made[1:], strict=False):
            later.needs = (earlier,)
        return made

    @override
    def promises(self, size: int) -> Census:
        return Census(size, size - 1)

    @override
    def sizes(self, *, deep: bool) -> tuple[int, ...]:
        return (8000, 16000, 32000, 64000) if deep else (1000, 2000, 4000, 8000)


@final
class Fan(Shape):
    """One root and N-1 steps needing it. The widest graph there is - one group of N-1 after a group of
    one, so an executor that fans has everything to fan and an ordering has one level to find."""

    @override
    def build(self, size: int) -> Sequence[Step]:
        root = Node()
        made = [root]
        for _ in range(size - 1):
            leaf = Node()
            leaf.needs = (root,)
            made.append(leaf)
        return made

    @override
    def promises(self, size: int) -> Census:
        return Census(size, size - 1)

    @override
    def sizes(self, *, deep: bool) -> tuple[int, ...]:
        return (8000, 16000, 32000, 64000) if deep else (1000, 2000, 4000, 8000)


@final
class Layered(Shape):
    """A realistic middle - layers of independent steps, each step needing `span` steps from the layer
    above it. Wide AND deep, with the edge count a real declaration has rather than a pathological one."""

    def __init__(self, width: int = 40, span: int = 3):
        self.__width = width
        self.__span = span

    @property
    @override
    def named(self) -> str:
        return f"layered({self.__width}x{self.__span})"

    def __layers(self, size: int) -> int:
        return max(1, size // self.__width)

    @override
    def build(self, size: int) -> Sequence[Step]:
        made: list[Step] = []
        previous: list[Step] = []
        for _ in range(self.__layers(size)):
            layer: list[Step] = [Node() for _ in range(self.__width)]
            for position, step in enumerate(layer):
                if previous:
                    step.needs = tuple(previous[(position + offset) % len(previous)]
                                       for offset in range(self.__span))
            made.extend(layer)
            previous = layer
        return made

    @override
    def promises(self, size: int) -> Census:
        layers = self.__layers(size)
        return Census(layers * self.__width, (layers - 1) * self.__width * self.__span)

    @override
    def sizes(self, *, deep: bool) -> tuple[int, ...]:
        return (8000, 16000, 32000, 64000) if deep else (1000, 2000, 4000, 8000)


@final
class Replicas(Shape):
    """The quadratic case the cost section names - n consumers declaring ONE class name, against n present
    instances of it. `expects` fans by class, so n names become n*n edges and the blowup is in the
    DECLARATION, not in the implementation. Here to prove the fan is the cost driver, not the loop."""

    @override
    def build(self, size: int) -> Sequence[Step]:
        half = size // 2

        class Replica(Node):
            pass

        class Consumer(Node):
            expects = (Replica,)

        return [Replica() for _ in range(half)] + [Consumer() for _ in range(half)]

    @override
    def promises(self, size: int) -> Census:
        half = size // 2
        return Census(half * 2, half * half)

    @override
    def sizes(self, *, deep: bool) -> tuple[int, ...]:
        return (500, 1000, 2000, 4000) if deep else (250, 500, 1000, 2000)


@final
class Forest(Shape):
    """Many disjoint chains. Nothing here orders anything against anything else, which is the shape that
    exercises union-find and the per-component sort rather than one long topological order."""

    def __init__(self, length: int = 8):
        self.__length = length

    @property
    @override
    def named(self) -> str:
        return f"forest({self.__length})"

    @override
    def build(self, size: int) -> Sequence[Step]:
        made: list[Step] = []
        for _ in range(size // self.__length):
            tree: list[Step] = [Node() for _ in range(self.__length)]
            for earlier, later in zip(tree, tree[1:], strict=False):
                later.needs = (earlier,)
            made.extend(tree)
        return made

    @override
    def promises(self, size: int) -> Census:
        trees = size // self.__length
        return Census(trees * self.__length, trees * (self.__length - 1))

    @override
    def sizes(self, *, deep: bool) -> tuple[int, ...]:
        return (8000, 16000, 32000, 64000) if deep else (1000, 2000, 4000, 8000)


@final
class Stress:
    """The sweep - every shape at doubling sizes, every claimed operation timed, growth read back out."""

    # Each operation with the cost the docs claim for it, as a function of what was actually BUILT. A
    # doubling of the size is not a doubling of the work. `replicas` doubles V and quadruples E, so for
    # anything O(V + E) a four-fold time is exactly right there and a two-fold time would be the surprise.
    # Comparing against the claim rather than against the size is what makes one ceiling fit every shape.
    MODELS: dict[str, Callable[[Census], float]] = {
        "derive": lambda c: c.vertices + c.edges,
        "demand": lambda c: c.vertices + c.edges,
        "kahn": lambda c: c.vertices + c.edges,
        "dfs": lambda c: c.vertices + c.edges,
        "priority": lambda c: c.vertices * log2(max(2, c.vertices)) + c.edges,
        "components": lambda c: c.vertices + c.edges * log2(max(2, c.vertices)),
        "chains": lambda c: c.vertices + c.edges * log2(max(2, c.vertices)),
        "closure": lambda c: c.vertices + c.edges,
        "fallout": lambda c: c.vertices + c.edges,
        "invert": lambda c: c.vertices + c.edges,
        "arrange": lambda c: c.vertices + c.edges,
        "matching": lambda c: c.vertices + c.edges,
    }

    # How far past its own claim an operation may go before this is a finding rather than a warm cache.
    # It is a multiple of the PREDICTED growth, so it does not move with the machine or with the shape.
    TOLERANCE = 1.30

    # Below this, the timer is what is being read, not the kernel. Both ends of a doubling must clear it
    # or the pair is skipped, which is why the report has blanks in it rather than confident nonsense.
    FLOOR = 0.0020

    SHAPES: tuple[Shape, ...] = (Chain(), Fan(), Layered(), Forest(), Replicas())

    def __init__(self, *, deep: bool = False, rounds: int = 5):
        self.__deep = deep
        self.__rounds = rounds

    @staticmethod
    def __timed(work: Callable[[], object], rounds: int) -> float:
        # The BEST of n, not the mean. The fastest run is the one least polluted by whatever else the
        # machine was doing. A benchmark that reports the noise reports the machine, not the kernel.
        best = float("inf")
        for _ in range(rounds):
            gc.collect()
            started = time.perf_counter()
            work()
            best = min(best, time.perf_counter() - started)
        return best

    def __read(self, shape: Shape, size: int) -> Reading:
        steps, graph, census, derived = shape.raised(size)
        seeds = (steps[0], steps[len(steps) // 2], steps[-1])
        fresh = Graph(steps)   # a graph whose inversion is not built yet, for the one-off inversion cost
        seconds = {
            "derive": min(derived, self.__timed(lambda: Graph(steps), self.__rounds - 1)),
            "demand": self.__timed(graph.demand, self.__rounds),
            "kahn": self.__timed(lambda: Kahn().waves(graph), self.__rounds),
            "dfs": self.__timed(lambda: DFS()(graph), self.__rounds),
            "priority": self.__timed(lambda: Priority()(graph), self.__rounds),
            "components": self.__timed(graph.components, self.__rounds),
            "chains": self.__timed(lambda: Components().chains(graph), self.__rounds),
            "closure": self.__timed(lambda: graph.closure(seeds), self.__rounds),
            "invert": self.__timed(lambda: fresh.dependents(steps[0]), 1),
            "fallout": self.__timed(lambda: graph.fallout(seeds), self.__rounds),
            "arrange": self.__timed(lambda: Waves().arrange(Kahn(), graph), self.__rounds),
            "matching": self.__timed(lambda: [graph.matching(step) for step in steps], self.__rounds),
        }
        gc.collect()
        tracemalloc.start()
        held = Graph(steps)
        peak = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        del held
        return Reading(shape.named, size, census, seconds, peak)

    def sweep(self) -> list[Reading]:
        readings: list[Reading] = []
        for shape in self.SHAPES:
            for size in shape.sizes(deep=self.__deep):
                print(f"  {shape.named} at {size} ...", end="", flush=True)
                reading = self.__read(shape, size)
                print(f" V={reading.census.vertices} E={reading.census.edges} "
                      f"derive={reading.seconds['derive'] * 1000:.1f} ms")
                readings.append(reading)
        return readings

    def growth(self, readings: Sequence[Reading]) -> dict[str, dict[str, float]]:
        # Per shape, per operation - the EXPONENT of the measured time against its own claimed cost, fitted
        # by least squares over every size measured. 1.00 means it grows exactly as the claim predicts,
        # 2.00 means the claim is linear and the code is quadratic in it.
        #
        # A fit over all the sizes rather than the worst adjacent pair, because the worst pair is where the
        # noise lives. On this machine a fan whose real growth is 1.9x per doubling all the way to 16000
        # produced a single 2.56x pair and a harness that shouts about that is a harness nobody believes
        # the day it is right. A slope needs every point to lean the same way before it moves.
        exponents: dict[str, dict[str, float]] = {}
        by_shape: dict[str, list[Reading]] = {}
        for reading in readings:
            by_shape.setdefault(reading.shape, []).append(reading)
        for shape, taken in by_shape.items():
            fitted: dict[str, float] = {}
            for operation in self.MODELS:
                points = [(log2(self.MODELS[operation](one.census)), log2(one.seconds[operation]))
                          for one in taken if one.seconds[operation] >= self.FLOOR]
                if len(points) < 3:   # two points are a line through two points, not evidence of a trend
                    continue
                fitted[operation] = self.__slope(points)
            exponents[shape] = fitted
        return exponents

    @staticmethod
    def __slope(points: Sequence[tuple[float, float]]) -> float:
        # Least squares on log-log, which is the whole trick. A power law becomes a straight line and its
        # exponent becomes the slope. Written out rather than imported, because a stress harness that needs
        # a dependency to say whether the kernel needs no dependencies is a poor argument.
        many = len(points)
        mean_x = sum(x for x, _ in points) / many
        mean_y = sum(y for _, y in points) / many
        spread = sum((x - mean_x) ** 2 for x, _ in points)
        if spread == 0.0:
            return 1.0
        return sum((x - mean_x) * (y - mean_y) for x, y in points) / spread

    def report(self, readings: Sequence[Reading]) -> list[str]:
        broken: list[str] = []
        operations = list(self.MODELS)
        print("\nMEASURED, milliseconds")
        print(f"{'shape':<18}{'V':>8}{'E':>10}" + "".join(f"{name:>11}" for name in operations))
        print("-" * (36 + 11 * len(operations)))
        for reading in readings:
            row = "".join(f"{reading.seconds[name] * 1000:>11.2f}" for name in operations)
            print(f"{reading.shape:<18}{reading.census.vertices:>8}{reading.census.edges:>10}{row}")

        print("\nEXPONENT of measured time against its own claimed cost (1.00 = exactly as claimed)")
        print(f"{'shape':<18}{'':>18}" + "".join(f"{name:>11}" for name in operations))
        print("-" * (36 + 11 * len(operations)))
        for shape, overruns in self.growth(readings).items():
            cells = []
            for name in operations:
                overrun = overruns.get(name)
                if overrun is None:
                    cells.append(f"{'.':>11}")
                    continue
                over = overrun > self.TOLERANCE
                cells.append(f"{('!' if over else '') + f'{overrun:.2f}':>11}")
                if over:
                    broken.append(f"{shape}.{name} grows as its claim to the power {overrun:.2f}")
            print(f"{shape:<18}{'':>18}" + "".join(cells))
        print(f"{'':<18}{'':>18}" + "".join(f"{'.':>11}" for _ in operations)
              + "   <- a dot is too fast or too few points to fit, not a pass")

        print("\nPEAK MEMORY of Graph()")
        for reading in readings:
            print(f"  {reading.shape:<18}{reading.census.vertices:>8} vertices "
                  f"{reading.census.edges:>8} edges  {reading.peak / 1024:>9.0f} KiB  "
                  f"{reading.peak / max(1, reading.census.vertices + reading.census.edges):>7.0f} B per V+E")
        return broken

    @classmethod
    def cliff(cls) -> None:
        """Where DFS stops and why it is not where anybody expects.

        The recursion is not bounded by the chain's LENGTH. It is bounded by how much of the chain is
        still uncoloured when the root loop reaches a step, which is a fact about the order the steps were
        SUPPLIED in. Same declaration, two orders, two completely different ceilings."""
        print("\nDFS recursion cliff (same chain, two supply orders)")
        limit = sys.getrecursionlimit()
        print(f"  sys.getrecursionlimit() = {limit}")
        for order, arrange in (("root first", lambda made: made),
                               ("tail first", lambda made: list(reversed(made)))):
            survived, died = 0, 0
            for length in (limit // 2, limit, limit * 4, limit * 40):
                made = [Node() for _ in range(length)]
                for earlier, later in zip(made, made[1:], strict=False):
                    later.needs = (earlier,)
                try:
                    DFS()(Graph(arrange(made)))
                except RecursionError:
                    died = length
                    break
                survived = length
            print(f"  {order:<12} walked {survived} steps"
                  + (f", died at {died}" if died else ", never hit the limit"))

    @classmethod
    def cli(cls, argv: Sequence[str]) -> int:
        parsed = argparse.ArgumentParser(description="Stress the kernel on heavy and huge graphs.")
        parsed.add_argument("--deep", action="store_true", help="an order of magnitude larger")
        parsed.add_argument("--check", action="store_true", help="exit non-zero on a broken growth claim")
        parsed.add_argument("--rounds", type=int, default=5, help="timed repeats, best of (default 3)")
        parsed.add_argument("--json", type=Path, default=None, help="write the readings as data")
        args = parsed.parse_args(argv)

        print(f"cabaxiom stress sweep, {'deep' if args.deep else 'default'}, best of {args.rounds}")
        stress = cls(deep=args.deep, rounds=args.rounds)
        readings = stress.sweep()
        broken = stress.report(readings)
        cls.cliff()

        if args.json is not None:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(
                [{"shape": r.shape, "size": r.size, "vertices": r.census.vertices,
                  "edges": r.census.edges, "peak_bytes": r.peak,
                  "milliseconds": {name: round(seconds * 1000, 4) for name, seconds in r.seconds.items()}}
                 for r in readings], indent=1), encoding="utf-8")
            print(f"\nwritten -> {args.json}")

        if broken:
            print(f"\n{len(broken)} growth claim(s) broken:")
            for line in broken:
                print(f"  {line}")
            return 1 if args.check else 0
        print("\nevery operation grew within the ratio its complexity allows")
        return 0


if __name__ == "__main__":
    raise SystemExit(Stress.cli(sys.argv[1:]))
