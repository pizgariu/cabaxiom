"""Capacity across processes, declared on a step and granted by an injected authority.

The axis `contends` could never be. Contention is mutual exclusion of ONE inside one resolved partition in
one process, derived statically from a placement rule, so a pool of eight is inexpressible and two
coordinators share no exclusion at all. A limit that spans processes is a different plane, held OUTSIDE
every run, which is what this is.

THE AUTHORITY IS A PORT, so the kernel keeps its promise. `Local` ships and counts in memory, which is what
lets the suite and the examples run offline, while Redis or etcd or a database row is an adapter somebody
writes in fifteen lines. The kernel imports nothing.

A DENIAL IS A READING, NEVER A WAIT. Blocking on a token was refused because a step suspended on a queue
holds its dispatcher slot while the Cancellation cannot fire, so a Deadline would bound the work and not
the waiting. A step whose permit was unavailable did not run, is therefore not settled and says so in the
residual through `Deferred`. The next pass asks again, which is the level-triggered answer to everything.
"""
from abc import ABC, abstractmethod
from typing import NamedTuple, final, override


@final
class Permit(NamedTuple):
    """One named capacity a step needs before it writes.

    The name addresses a pool the authority owns, never a resource the kernel knows about, so two steps in
    two processes naming `"snowflake_api"` are asking the same authority the same question. The capacity
    rides here rather than in the authority's configuration because the DECLARATION is where a reader of a
    step learns what it needs, while a limit kept somewhere else is a limit nobody sees while reading the
    code that depends on it. An authority is free to clamp it lower and a sane one will."""

    name: str
    capacity: int


class Authority(ABC):
    """Who grants a permit. The seam a distributed limit is actually enforced at.

    `acquire` answers True when the holder now owns one of the pool's slots and False when it does not,
    and it NEVER waits - a waiting authority would reintroduce exactly the suspended step this axis exists
    to avoid. `release` returns a slot and must tolerate being called for a holder that never held one,
    because a run that aborted between the two is the ordinary case rather than the exception."""

    @abstractmethod
    def acquire(self, permit: Permit, holder: str) -> bool:
        # Grant or refuse, immediately. Answer False rather than blocking.
        ...

    @abstractmethod
    def release(self, permit: Permit, holder: str) -> None:
        # Return the slot. Idempotent, because an abort can land between acquire and release.
        ...


@final
class Local(Authority):
    """An in-process authority, which is the honest default and a real one for a single coordinator.

    It exists so the kernel ships something that works with no network, the way every axis here ships a
    neutral implementation - `Retry(1)`, a silent `Observer`, `Parallel`. It is NOT a distributed limit and
    says so, because a local counter presented as a global one is the lie this whole axis was created to
    replace. Two coordinators each holding their own `Local` grant each other's slots freely."""

    def __init__(self) -> None:
        self.__held: dict[str, set[str]] = {}

    @override
    def acquire(self, permit: Permit, holder: str) -> bool:
        holders = self.__held.setdefault(permit.name, set())
        if holder in holders:
            return True   # already ours, so a re-acquire inside one attempt is not a second slot
        if len(holders) >= permit.capacity:
            return False
        holders.add(holder)
        return True

    @override
    def release(self, permit: Permit, holder: str) -> None:
        self.__held.get(permit.name, set()).discard(holder)

    def held(self, name: str) -> int:
        # Published for a test and for an operator, because a pool nobody can read is a pool nobody trusts.
        return len(self.__held.get(name, set()))

