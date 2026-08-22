"""The drift contract - one thing found out of desired state, read through a two-field protocol,
and the shapes a hook hands back over it."""
from collections.abc import Awaitable, Sequence
from dataclasses import dataclass
from typing import Protocol, final


class Drift(Protocol):
    # One thing found out of desired state. These two fields are the entire contract a drift exposes,
    # so any domain item satisfies the kernel just by structurally exposing them. Richer payload stays
    # private to the domain item. Read by duck typing, never isinstance-tested: the Protocol names the
    # boundary, it does not gate at runtime.
    name: str     # the subject that drifted (a config file, an env var, a service)
    message: str  # human-readable one-liner: what is wrong


@final
class DriftItem:
    # The kernel's concrete default Drift, for domains with no carrier of their own. A domain with a
    # richer item just exposes name + message on it and uses that instead.
    __slots__ = ("name", "message")

    def __init__(self, name: str, message: str):
        self.name = name
        self.message = message

    def __repr__(self) -> str:
        return f"DriftItem({self.name!r}, {self.message!r})"

    def __str__(self) -> str:
        return f"{self.name}: {self.message}"


@final
@dataclass(frozen=True)
class Assessment:
    """One read of the world, whole - the deviation, the plan, the advice and the footprint in a single
    frozen record, where four separate hooks used to each pay their own probe for a slice of the same
    reading.

    The four channels keep four meanings apart instead of blurring them into one list. `deviation` is what
    is out of desired state, and an empty one is the whole proof a run offers. `plan` is what a converge
    WOULD do. `advisory` is what deserves attention in a system that already MEETS desired state, which is
    exactly why it is not deviation - advice must never dirty a proof. `footprint` is what this step owns,
    read in teardown order.

    Frozen, like every verdict this kernel mints, so a reading cannot be rewritten by the hand that
    received it. Every channel defaults to empty, so a step answering about one of them writes one
    keyword and says nothing it does not mean."""

    deviation: Sequence[Drift] = ()
    plan: Sequence[Drift] = ()
    advisory: Sequence[Drift] = ()
    footprint: Sequence[Drift] = ()


# What a WRITE hands back: what it changed, or None for a clean no-op. A Sequence and deliberately not a
# list, because list is INVARIANT - a domain writing the obviously correct `def apply(self) -> list[MyDrift]`
# was a mypy --strict error on an override, since list[MyDrift] is not a list[Drift]. Sequence is covariant
# and read-only, so it takes the domain's own list without the domain knowing why it now type-checks.
Changes = Sequence[Drift] | None

# The same, admitting a coroutine, so `async def apply()` is a legal typed override rather than a special
# case the executor has to be told about.
Outcome = Changes | Awaitable[Changes]
