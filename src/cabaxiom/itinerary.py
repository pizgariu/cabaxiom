"""Itinerary. A world walked through a PATH of declarations, one proof-gated Transition per hop - the staged rollout as a value with its rollback for free."""
from collections.abc import Iterable, Sequence
from itertools import pairwise
from typing import final

from .cancellation import Cancellation
from .convergence import Convergence
from .dispatcher import RunMode
from .observer import Observer
from .ordering import Ordering
from .retry import BaseRetry
from .step import Step
from .transition import Cutover, Transition
from .vocabulary import Vocabulary


@final
class Passage:
    """The verdict of one walk. A Cutover per hop attempted, in path order.

    The walk stops AT the first unclean leg, so every leg before the last is clean by construction and
    the tail says everything. `arrived` is true exactly when the last attempted leg is clean - nothing
    stopped the walk, so every hop ran and the world stands at the path's end. `reached` is the index of
    the waypoint the world verifiably stands at. The count of clean legs, with 0 meaning it never
    verifiably left the path's start (which the walk assumed, not proved). A Passage is truthy exactly
    when arrived, so it reads as the assertion it is."""
    __slots__ = ("__legs",)

    def __init__(self, legs: Sequence[Cutover]):
        # A RECORD, like every verdict the kernel mints. The legs are captured as a tuple behind a
        # read-only property, so a walk cannot be rewritten after the world took it.
        self.__legs = tuple(legs)

    @property
    def legs(self) -> tuple[Cutover, ...]:
        return self.__legs

    @property
    def arrived(self) -> bool:
        # The walk only stops early on an unclean Cutover, so a clean tail means the whole path ran.
        return bool(self.__legs) and self.__legs[-1].clean

    @property
    def reached(self) -> int:
        # The clean legs are a prefix (the walk's stop rule), so counting them names the waypoint index.
        return sum(1 for leg in self.__legs if leg.clean)

    def __bool__(self) -> bool:
        return self.arrived

    def __repr__(self) -> str:
        return f"Passage(arrived={self.arrived}, reached={self.reached}, legs={len(self.legs)})"


@final
class Itinerary:
    """A world walked through a PATH of declarations, one proof-gated Transition per hop. The whole staged
    rollout - baseline, canary, fleet - expressed as a value the caller holds, exactly as a single
    Transition holds its two declarations. No tool with a state file can express this, because none holds
    the path between declarations as anything but bookkeeping.

    converge() is a coroutine now that the engine is async native. It walks hop by hop and advances only on
    a clean Cutover, so the world never leaves a waypoint it cannot prove it reached. Re-running RESUMES for
    free. Settled hops read clean and no-op through the level-triggered loop, so the walk picks up wherever
    the world really stands. And reversed(itinerary) is the same value walked back - the rollback needs zero
    extra declarations, because the caller's waypoints already contain every intermediate world.

    Waypoints share step INSTANCES for the steps that persist between them. The kernel's dependency
    addressing is instance identity, so a persisting step re-declared as a fresh instance reads as a leaver
    plus a joiner - torn down and rebuilt across the hop instead of carried through it."""

    def __init__(self, waypoints: Iterable[Iterable[Step]], ordering: Ordering | None = None, *,
                 mode: RunMode | None = None, convergence: Convergence | None = None,
                 cancellation: Cancellation | None = None, observer: Observer | None = None,
                 retry: BaseRetry | None = None, vocabulary: Vocabulary | None = None):
        # The knobs are kept whole beside the stations: __reversed__ re-plots the same path backwards with
        # the same strategy set, with every hop sharing them exactly as Transition shares its own (one
        # dispatcher instance across every hop - its pool is lock-guarded for that kind of sharing).
        self._stations = self.__plotted(waypoints)
        self.__ordering = ordering
        self.__mode = mode
        self.__convergence = convergence
        self.__cancellation = cancellation
        self.__observer = observer
        self.__retry = retry
        self.__vocabulary = vocabulary
        self.__hops = tuple(
            Transition(previous, desired, ordering, mode=mode, convergence=convergence,
                       cancellation=cancellation, observer=observer, retry=retry, vocabulary=vocabulary)
            for previous, desired in pairwise(self._stations)
        )

    @staticmethod
    def __plotted(waypoints: Iterable[Iterable[Step]]) -> tuple[tuple[Step, ...], ...]:
        # Materialise the path once and guard it. A path IS its hops, so a single declaration has none.
        # The EMPTY declaration is a legal waypoint and the idiom for the path's far ends - start from ()
        # to build from scratch (the first hop prunes nothing and converges the first world), end at ()
        # for a full teardown - which is exactly what keeps reversal symmetric.
        stations = tuple(tuple(waypoint) for waypoint in waypoints)
        if len(stations) < 2:
            raise ValueError(
                f"Itinerary needs at least two waypoints, got {len(stations)} - a path is its hops, so "
                f"one declaration has none. Start from the empty declaration () to build from scratch."
            )
        return stations

    async def converge(self) -> Passage:
        # Walk the hops in path order, keep each leg's Cutover and stop AT the first unclean one. The
        # world stands where it last proved arrival, so the Passage's tail says exactly where that is.
        legs: list[Cutover] = []
        for hop in self.__hops:
            legs.append(await hop.converge())
            if not legs[-1].clean:
                break
        return Passage(legs)

    def __reversed__(self) -> "Itinerary":
        # The same value walked back. Stations reversed, knobs identical. A rollback from a partial walk
        # needs no bookkeeping of where the world stopped - the hops above the standing waypoint read clean
        # and no-op, level-triggered, until the walk meets the world where it really is.
        return Itinerary(tuple(reversed(self._stations)), self.__ordering, mode=self.__mode,
                         convergence=self.__convergence, cancellation=self.__cancellation,
                         observer=self.__observer, retry=self.__retry, vocabulary=self.__vocabulary)

