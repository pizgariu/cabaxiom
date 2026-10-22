"""Convergence strategies for how many times to repeat apply -> re-probe. Once, Fixpoint (loop to a settled set), Shrinking (loop while the residual keeps getting smaller), Budget (loop while there is time left on the clock), plus the Backoff family that paces Fixpoint's retries (Fixed, Exponential, Linear, Fibonacci, Jitter)."""
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from typing import final, override

from ..declaration.drift import Drift
from ..declaration.errors import Misconfigured

# WHAT A LOOPING STRATEGY DECIDES AFTER EACH PASS, named so the seam stops spelling a positional pair.
# The bool says whether the loop is done, the float how long to pause before the next pass when it is
# not. deciding() hands back a closure that answers one per pass. Every shipped strategy plus any
# domain-written one signs the same shape. PUBLIC because deciding() is a seam on an open base.
type Decision = tuple[bool, float]


class Convergence(ABC):
    """Strategy for how many times to repeat the apply -> re-probe cycle.

    The policy is a generator. It YIELDS the seconds to wait before the next pass (0.0 for none),
    RECEIVES that pass's residual Drift back through send() and RETURNS the final residual. The
    reconcilers drive it, sync or async, so the policy is written once and neither path duplicates it.
    """
    @abstractmethod
    def passes(self) -> Generator[float, list[Drift], list[Drift]]:
        ...


@final
class Once(Convergence):
    """Run exactly one apply -> re-probe cycle."""
    @override
    def passes(self) -> Generator[float, list[Drift], list[Drift]]:
        return (yield 0.0)   # one pass, no wait, return its residual


class Backoff(ABC):
    """How long to pause before a retry, as a function of how many times in a row it has stalled.

    Fixpoint stops the moment a pass leaves the residual unchanged, reading it as settled or stuck.
    That is right for an in-process convergence, where re-probing at once cannot change the answer.
    It is wrong for a step whose drift clears only once some external state catches up (a rollout
    finishing, a cache expiring, a queue draining). There the same drift now can be gone in a moment.
    Hand Fixpoint a Backoff and an unchanged pass no longer ends the loop. Fixpoint waits, then
    retries, still bounded by max_passes, giving the world time to settle. Retry paces a single
    step's write attempts with the same vocabulary. delay() is the pure policy, the seconds to
    pause before retrying the nth consecutive stall (1 on the first). wait() is the blocking form
    built on it, used by the sync write path (Retry) on the calling thread. Fixpoint does not call
    wait(). It yields delay() to whoever drives it, so the sync reconciler blocks on that pause while
    an async one awaits the event loop's own sleep instead, so a pause never blocks the coroutines
    sharing the loop.
    """
    @abstractmethod
    def delay(self, stalled: int) -> float:
        ...

    def wait(self, stalled: int) -> None:
        time.sleep(self.delay(stalled))


@final
class Fixed(Backoff):
    """Pause the same number of seconds before every retry, however long the stall has run."""
    def __init__(self, seconds: float):
        if seconds < 0:
            raise Misconfigured(f"Fixed backoff seconds must be >= 0, got {seconds}")
        self.__seconds = seconds

    @override
    def delay(self, stalled: int) -> float:
        return self.__seconds


@final
class Exponential(Backoff):
    """Double the pause on each consecutive stall, from base up to cap seconds.

    The nth stall pauses base * 2 ** (n - 1), clamped to cap, so a loop that keeps meeting the
    same drift steps back further each time instead of re-probing at full tilt. cap bounds the
    single longest pause, the consumer's own ceiling (max_passes, attempts) bounds how many there
    can be.
    """
    def __init__(self, base: float, cap: float):
        if base < 0:
            raise Misconfigured(f"Exponential backoff base must be >= 0, got {base}")
        if cap < base:
            raise Misconfigured(f"Exponential backoff cap must be >= base, got cap={cap}, base={base}")
        self.__base = base
        self.__cap = cap

    @override
    def delay(self, stalled: int) -> float:
        return float(min(self.__base * 2 ** (stalled - 1), self.__cap))


@final
class Linear(Backoff):
    """Grow the pause by a fixed step each consecutive stall, up to cap. The nth stall pauses
    min(step * stalled, cap).

    The gentle middle between Fixed (one flat pause however long the stall runs) and Exponential
    (doubling, which reaches a long pause in a few stalls). A ramp that climbs one step at a time
    suits a world expected to settle steadily, where doubling would overshoot the wait and a flat
    pause would under-wait a longer stall. cap bounds the single longest pause, the consumer's own
    ceiling (max_passes, attempts) bounds how many there can be.
    """
    def __init__(self, step: float, cap: float):
        if step < 0:
            raise Misconfigured(f"Linear backoff step must be >= 0, got {step}")
        if cap < step:
            raise Misconfigured(f"Linear backoff cap must be >= step, got cap={cap}, step={step}")
        self.__step = step
        self.__cap = cap

    @override
    def delay(self, stalled: int) -> float:
        return float(min(self.__step * stalled, self.__cap))


@final
class Fibonacci(Backoff):
    """Ramp the pause by the Fibonacci sequence, base * (1, 2, 3, 5, 8, 13, ...), up to cap.

    The middle ground between Linear and Exponential, provably in the middle rather than merely
    between them in spirit. Every term is the sum of the two before it, so against the same step the
    nth pause is never shorter than Linear's step * n and never longer than Exponential's
    base * 2 ** (n - 1). It opens exactly where both neighbours open, base then twice base, holds
    level with Linear for a third stall, then pulls ahead.

    That gap is the whole point. Exponential(base=1, cap=8) is sitting on its cap by the fourth stall
    and every retry after that is the same flat pause, which is Fixed wearing a ramp's name. Fibonacci
    reaches that cap a stall later and the stalls in between still say something, so a world that
    clearly needs more time than a fixed step buys gets it without a doubling overshooting the wait.
    cap bounds the single longest pause, the consumer's own ceiling (max_passes, attempts) bounds how
    many there can be.
    """
    def __init__(self, base: float, cap: float):
        if base < 0:
            raise Misconfigured(f"Fibonacci backoff base must be >= 0, got {base}")
        if cap < base:
            raise Misconfigured(f"Fibonacci backoff cap must be >= base, got cap={cap}, base={base}")
        self.__base = base
        self.__cap = cap

    @override
    def delay(self, stalled: int) -> float:
        # The sequence is generated in place rather than memoised. Two terms carried and one addition
        # per stall, so a Backoff that lives as long as the process cannot accumulate a table. `current` walks
        # 1, 2, 3, 5, 8, the sequence with its duplicate leading 1 dropped, so the first stall pauses
        # base instead of pausing the same length twice and wasting a retry on a ramp that has not
        # moved. Once the ramp has met the cap, further terms cannot change the answer, so the walk
        # stops there. That early exit is what keeps an O(n) sequence O(1) in the steady state, so it
        # is why a large stall count costs nothing here.
        previous, current = 1, 1
        for _ in range(stalled - 1):
            if self.__base * current >= self.__cap:
                break
            previous, current = current, previous + current
        return float(min(self.__base * current, self.__cap))


@final
class Jitter(Backoff):
    """Full jitter over a wrapped Backoff. Each pause is a uniform random draw in [0, backoff.delay(n)].

    Retrying on a fixed schedule synchronises every client that stalled together, so they retry in lockstep
    and collide again, a thundering herd. Spreading each pause across [0, the underlying delay] scatters them,
    the standard defence. Jitter decorates any Backoff (Fixed, Exponential) rather than replacing it, so the
    wrapped policy still sets the ceiling and the jitter only spreads beneath it. The RNG is injected (a
    random.Random) and defaults to a fresh one, so a test can seed it and pin the draw.
    """
    def __init__(self, backoff: Backoff, *, rng: random.Random | None = None):
        self.__backoff = backoff
        self.__rng = rng or random.Random()

    @override
    def delay(self, stalled: int) -> float:
        return self.__rng.uniform(0.0, self.__backoff.delay(stalled))


class BaseLooping(Convergence, ABC):
    """Shared skeleton for the multi-pass convergences (Fixpoint, Shrinking). Prime one pass, then loop
    up to max_passes, stopping the moment the residual is clean or the subclass's per-run decision says
    so. The open base a custom looping convergence stands on - implement deciding() and inherit the whole
    bounded loop.

    The two built-ins differ only in that decision and in the state it carries: Fixpoint remembers every
    residual it has seen (to catch an oscillation) and how long it has stalled (to pace a backoff).
    Shrinking carries nothing, comparing only adjacent sizes. That state must be FRESH per run - one
    Convergence instance drives many converge() calls - so the subclass hands back a NEW decision each run
    through deciding(), keeping any memory in the returned closure rather than on self, where a second
    converge() would inherit it. max_passes is the hard ceiling that guarantees termination for both.
    """

    def __init__(self, max_passes: int = 10):
        if max_passes < 1:
            raise Misconfigured(f"{self.__class__.__name__} max_passes must be >= 1, got {max_passes}")
        self._max_passes = max_passes

    @final
    @override
    def passes(self) -> Generator[float, list[Drift], list[Drift]]:
        # The loop, written once and driven by converge(), which awaits the pauses it yields:
        # prime the first pass, then for each further pass stop on a clean residual or on the subclass's
        # verdict. deciding() is asked once per run for a fresh decision, so any cross-pass memory it keeps
        # stays local to this generator, never on self where a second converge() would inherit it.
        decide = self.deciding()
        opening = self.opening()
        residual = yield opening
        wait = opening
        for _ in range(self._max_passes - 1):
            if not residual:
                break  # converged clean
            before = residual
            residual = yield wait
            stop, wait = decide(before, residual)
            if stop:
                break
        return residual

    def opening(self) -> float:
        # The pause before a pass there is no verdict for yet. The very first one plus the one right after
        # it, since a decision needs two residuals to compare and cannot exist before the second pass has
        # been asked for. Zero by default, which is right for a convergence that reacts to what it sees -
        # Fixpoint cannot know it has stalled until it has stalled. Override it for a pace that is a
        # PROPERTY of the world rather than a reaction to it, a poll interval against an eventually
        # consistent store being the case that matters. Re-probing immediately there reads state that has
        # not caught up and manufactures a residual which is not really there.
        return 0.0

    @abstractmethod
    def deciding(self) -> Callable[[list[Drift], list[Drift]], Decision]:
        # Return a FRESH decision for one run. Given the residual BEFORE a pass and the one AFTER it,
        # answer (stop?, the seconds to wait before the next pass). A stateful policy (an oscillation
        # memory, a stall streak) keeps its state in the returned closure, so every run starts clean.
        ...


@final
class Fixpoint(BaseLooping):
    """Repeat the apply -> re-probe cycle until the residual stops changing, starts REPEATING or
    max_passes is reached.

    Some steps only reach desired state once an earlier step's apply() has made room. One pass
    clears what it can, the next clears what the first unblocked and so on. Settling is by value.
    two residuals are equal when their (name, message) multisets match, so the loop stops as soon
    as a pass changes nothing (converged clean or genuinely stuck). max_passes is the hard ceiling
    that guarantees termination even when a step never settles.

    A stall compares a pass to the one before it. An oscillation is subtler - the residual keeps
    changing but cycles through states it has already visited (A, B, A, B, ...), so no two adjacent
    passes ever match and a stall never fires. Fixpoint remembers every residual state it has seen,
    so returning to any earlier one is caught as a loop and ends the run at once, instead of spinning
    to max_passes. Unlike a stall, an oscillation is always terminal. A backoff cannot rescue a
    deterministic A<->B loop the way it can drift that is only waiting on external state.

    An optional backoff changes what an unchanged (stalled) pass means. Without one it is terminal.
    With one it becomes a paced retry: Fixpoint waits (growing the wait as stalls repeat) and
    re-probes again, up to max_passes, for drift that clears only once external state catches up.
    See Backoff.
    """

    def __init__(self, max_passes: int = 10, *, backoff: Backoff | None = None):
        super().__init__(max_passes)
        self.__backoff = backoff

    @override
    def deciding(self) -> Callable[[list[Drift], list[Drift]], Decision]:
        # Fresh per run. `seen` catches an oscillation (a residual state visited before), `stalled` paces
        # the optional backoff. Both live in this closure, so a second converge() starts clean. Settling is
        # by value. Two residuals are equal when their (name, message) multisets match.
        seen: set[tuple[tuple[str, str], ...]] = set()   # every residual state visited, to catch a loop
        stalled = 0

        def decide(before: list[Drift], after: list[Drift]) -> Decision:
            nonlocal stalled
            previous = tuple(sorted((item.name, item.message) for item in before))
            current = tuple(sorted((item.name, item.message) for item in after))
            seen.add(previous)
            if current == previous:
            # The pass changed nothing - settled or stuck. Terminal, unless a backoff turns it into a
                # paced retry for drift that is only waiting on external state to catch up.
                if self.__backoff is None:
                    return True, 0.0
                stalled += 1
                return False, self.__backoff.delay(stalled)
            if current in seen:
                # The residual changed but returned to a state visited earlier - an oscillation, not
                # progress. A deterministic loop that will never converge, one a backoff cannot rescue,
                # so it is always terminal - stop now instead of spinning to max_passes.
                return True, 0.0
            stalled = 0   # a genuinely new state: progress, so a later stall backs off from scratch
            return False, 0.0

        return decide


@final
class Shrinking(BaseLooping):
    """Repeat the apply -> re-probe cycle only while the residual keeps SHRINKING: stop the moment a
    pass fails to reduce the drift COUNT (a plateau or a growth), the moment it reaches clean or at
    max_passes.

    Fixpoint stops when the residual SET stops changing (or revisits a state it has seen). Shrinking
    stops when it stops making measurable headway, counted by size. The two suit different worlds.
    Fixpoint fits drift that settles by CHURNING - a pass swaps one drift for another on the way down,
    the set keeps changing, so only equality means done. Shrinking fits a strictly REDUCIBLE world,
    where every productive pass removes at least one item and a pass that removes nothing is spinning:
    the churn Fixpoint waits through (the set changes, the count holds) ends the loop here, at the first
    pass that buys no ground. A residual that GREW is terminal too - progress went backwards, so another
    pass cannot be trusted to recover it. max_passes is the hard ceiling that guarantees termination.

    There is no backoff knob, unlike Fixpoint. Here a plateau IS the stop condition, so there is nothing
    to pace through. A world that only settles once external state catches up (the same count lingering
    until it clears) wants Fixpoint with a Backoff, not this.
    """
    @override
    def deciding(self) -> Callable[[list[Drift], list[Drift]], Decision]:
        # Stateless. Compare only adjacent sizes. No wait is ever asked for (0.0), since Shrinking MEASURES
        # progress, it does not pace retries - a plateau ends the run rather than being waited through,
        # which is Fixpoint-with-a-Backoff's job. Stop when a pass buys no ground (the count held or grew).
        def decide(before: list[Drift], after: list[Drift]) -> Decision:
            return len(after) >= len(before), 0.0

        return decide


@final
class Budget(Convergence):
    """Repeat the apply -> re-probe cycle while there is time left on the clock, then return whatever is
    still drifting. The complement to Fixpoint's max_passes - a bound in SECONDS rather than in passes.

    A maintenance window is the bound a run is actually given. "Twenty minutes on Sunday night" is a fact
    about the world, "ten passes" is a guess at how many passes fit inside it, so the guess is wrong in
    both directions - a fast fleet stops with the window half spent, a slow one is still going when it
    shuts. Budget takes the number the operator already has and spends exactly that.

    It stands BESIDE BaseLooping rather than under it, for the base's own guarantee. That
    loop is `for _ in range(max_passes - 1)` and the count IS the termination proof it publishes to every
    subclass. A Budget underneath would have to name a pass ceiling it does not have. Either the ceiling
    is real, so the run is bounded by whichever of the window and the count runs out first, which is the
    conjunction rather than the complement or a sentinel large enough never to fire, which voids
    the guarantee for everyone else standing on that base. So the loop is written once more here, a
    handful of lines, with the guarantee restated honestly instead of inherited falsely. Budget terminates
    because the clock advances, which is what monotonic means. Hand it a frozen clock and it will not
    terminate. That is the price of trading a count for a duration, paid in the open.

    What it refuses and why.
    - It refuses a zero-pass run. ONE pass always happens, before the clock is consulted at all, however
      small the window. A budget computed from a schedule can arrive at zero or a hair above it, where a
      Convergence that answered by doing nothing would hand back a clean-looking residual for a world
      nobody had looked at, which is the one lie the residual must never tell. A budget of zero degrades
      to Once, not to nothing. A negative budget is a caller bug rather than a policy and is refused at
      construction, as Deadline and max_passes refuse theirs.
    - It refuses to bound the pass already in flight. The window governs when the loop DECIDES to go
      again, so a pass that overruns it overruns it. A Convergence can only decline to ask for more work,
      never interrupt work under way. Where the window is HARD, pair this with cancellation=Deadline,
      which cuts BETWEEN the units of work inside a pass and reports by raising Cancelled. The two are
      not the same tool wearing different hats: Budget returns a residual for a world that got as far as
      it got, Deadline raises and leaves the caller to ask what happened, while a run wanting both a soft
      target and a hard stop wants both objects.
    - It refuses to read the residual for anything but emptiness. A stall is not terminal here, unlike
      Fixpoint's, because the case Budget exists for is drift that clears only once external state
      catches up, where the same drift now can be gone in a moment. That is also why the optional Backoff
      earns its keep. Without one the loop re-probes as fast as the machine allows and spends the whole
      window hammering. It paces by the number of passes already taken, there being no stall streak here
      to count.

    The clock starts inside passes(), which is asked for once per converge(), so the window is FRESH for
    every run. Deadline cannot manage that and documents the trap, which is why the same Budget instance
    is safe across a watch() loop's repeated converges where the same Deadline is not. The clock is injected (any
    callable answering seconds that only ever grow) and defaults to time.monotonic, so a test scripts it
    and pins every decision without sleeping through a single one.
    """

    def __init__(self, seconds: float, *, backoff: Backoff | None = None, clock: Callable[[], float] = time.monotonic):
        if seconds < 0:
            raise Misconfigured(f"Budget seconds must be >= 0, got {seconds}")
        self.__seconds = seconds
        self.__backoff = backoff
        self.__clock = clock

    @override
    def passes(self) -> Generator[float, list[Drift], list[Drift]]:
        # The generator frame IS the per-run state, so there is nothing to reset between converge()
        # calls and no need for the closure BaseLooping hands its subclasses. passes() is asked for a
        # fresh one each run. Reading the clock HERE and not at construction is what keeps the latency
        # between declaring the policy and running it off the operator's window.
        ends = self.__clock() + self.__seconds
        residual = yield 0.0        # the one pass every budget buys, taken before the clock is consulted
        taken = 1
        while residual and self.__clock() < ends:
            # Clean stops the loop the way it stops every other convergence, time stops it the way only
            # this one does. The pause is not trimmed to fit what is left. A truncated wait re-probes
            # state that has not caught up and manufactures a residual which is not really there, the
            # trap BaseLooping.opening() names, so the window is allowed to overrun by one pace instead.
            pause = 0.0 if self.__backoff is None else self.__backoff.delay(taken)
            residual = yield pause
            taken += 1
        return residual
