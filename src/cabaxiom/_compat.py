"""Compatibility shims kept dependency-free: `override` from the standard library on 3.12+, a transparent no-op below it."""
import sys
from collections.abc import Callable
from typing import TypeVar

_F = TypeVar("_F", bound=Callable[..., object])

# BOTH SIDES excluded, not one. Exactly one branch runs on any given interpreter, so whichever side
# carries the pragma alone, the other is uncovered on the versions that take it - which is how a suite
# reporting 100% on 3.13 reported 99% on 3.10 and 3.11 and failed the gate there.
if sys.version_info >= (3, 12):  # pragma: no cover
    from typing import override
else:  # pragma: no cover
    def override(func: _F) -> _F:
        # Below 3.12 typing.override does not exist. A no-op keeps the decorator dependency-free at
        # runtime, while the static check runs under mypy targeting 3.12 (see [tool.mypy] python_version).
        return func

__all__ = ["override"]
