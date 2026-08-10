"""Compatibility shims kept dependency-free: `override` from the standard library on 3.12+, a transparent no-op below it."""
import sys
from collections.abc import Callable
from typing import TypeVar

_F = TypeVar("_F", bound=Callable[..., object])

if sys.version_info >= (3, 12):
    from typing import override
else:  # pragma: no cover
    def override(func: _F) -> _F:
        # Below 3.12 typing.override does not exist. A no-op keeps the decorator dependency-free at
        # runtime, while the static check runs under mypy targeting 3.12 (see [tool.mypy] python_version).
        return func

__all__ = ["override"]
