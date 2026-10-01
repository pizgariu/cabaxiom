"""Policy read before the first write, plus a refusal that is a VERDICT rather than an exception.

A run can be correct and still be a catastrophe. A declaration that says one table where somebody meant
fifty converges perfectly, proves itself and reports clean, because a reconciler answers whether the world
matches the declaration and never whether the declaration was sane. That question needs asking somewhere,
and the only place it can be asked usefully is BEFORE the first wave, on a reading of the world rather than
on the wreckage.

THE SEVENTH AXIS, built like the six before it. An Ordering, a Dispatcher, a Convergence, a Cancellation, an
Observer and a Retry are all injected strategies with a neutral default. This is another. A run with no
warrant behaves exactly as it always did and pays nothing - not even the leading probe, which only happens
when somebody asks for a gate.

A REFUSAL IS NOT AN EXCEPTION. That is the load-bearing decision. Raising would land a policy refusal in
the same channel a caller catches a broken socket in, so a formal decision not to start would be told apart
from a crash by exception type alone. This kernel already ruled on exactly that, in the Ledger's own words -
`halt()` exists "precisely so a non-failure stop stops impersonating a failure". A veto is a non-failure
stop. So it lands in the record. The reasons go into the residual, which keeps "empty means verified" true
because a refused run genuinely did not reach its declaration. They land in a channel of their own, so nobody
reads a refusal as a failure or as ordinary drift.
"""
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import final, override

from .drift import Drift, DriftItem
from .errors import Misconfigured
from .ledger import Reading


class Warrant(ABC):
    """Whether a run may write, asked once with the whole reading in hand.

    `assent` answers the REASONS to refuse, so an empty answer is consent. Reasons rather than a boolean,
    because a gate that can only say no is a gate an operator swears at - the refusal has to survive being
    read at three in the morning by somebody who did not write the policy.

    It is handed the whole `Reading`, which is why that record grew its other three channels. The deviations
    say what is out of desired state, the plan says what a converge would do, the advisory says what deserves
    attention in a world that already matches, while the footprint says what a teardown would remove. A
    destructive-scale policy is a question about the footprint and cannot be asked of the deviations."""

    @abstractmethod
    def assent(self, reading: Reading) -> Sequence[Drift]:
        # Empty means the run may proceed. Anything else refuses it and says why.
        ...


@final
class Charter(Warrant):
    """Several warrants as one, in declared order, with EVERY one asked.

    The Chorus precedent. Asking them all rather than stopping at the first refusal is deliberate, because a
    caller who has to fix three policy violations wants three sentences, not one and then another run to find
    the next. Empty composes to consent, so `Charter()` is the neutral gate."""

    def __init__(self, *warrants: Warrant) -> None:
        self.__warrants = warrants

    @override
    def assent(self, reading: Reading) -> Sequence[Drift]:
        return [reason for warrant in self.__warrants for reason in warrant.assent(reading)]


@final
class Ceiling(Warrant):
    """Refuse a run whose scale exceeds what was declared safe, counted per channel.

    The shipped policy and the one every comparable tool sells as an add-on. `Ceiling(footprint=5)` refuses
    a run that would tear down more than five things, which is the guard for the afternoon somebody's
    declaration says one table and means fifty. None means that channel is unbounded, so a Ceiling that names
    nothing consents to everything, so every bound has to be chosen rather than inherited.

    It counts FINDINGS and not steps, because a step that owns forty files answers forty footprint items and
    the danger is in the forty."""

    def __init__(self, *, deviation: int | None = None, plan: int | None = None,
                 advisory: int | None = None, footprint: int | None = None) -> None:
        for name, bound in (("deviation", deviation), ("plan", plan), ("advisory", advisory), ("footprint", footprint)):
            if bound is not None and bound < 0:
                raise Misconfigured(f"Ceiling's {name} bound must be zero or more, got {bound}. Zero refuses any finding on that channel. None leaves it unbounded.")
        self.__bounds = {"deviation": deviation, "plan": plan, "advisory": advisory, "footprint": footprint}

    @override
    def assent(self, reading: Reading) -> Sequence[Drift]:
        counted = {"deviation": len(reading), "plan": len(reading.plan),
                   "advisory": len(reading.advisory), "footprint": len(reading.footprint)}
        refused: list[Drift] = []
        for channel, bound in self.__bounds.items():
            if bound is not None and counted[channel] > bound:
                refused.append(DriftItem(
                    f"Ceiling.{channel}",
                    f"the reading answers {counted[channel]} {channel} findings and this run is bounded at "
                    f"{bound}, so nothing was written. Raise the bound if the scale is intended or narrow "
                    f"the declaration with a Scope if it is not."
                ))
        return refused

