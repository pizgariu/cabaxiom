"""Does the property hold? Idempotence converges twice and compares the two readings, Reversibility
applies and then prunes and asks whether the world came back to where it started.

Both answer with a frozen verdict rather than a boolean, because the interesting part of a failed proof
is never that it failed - it is WHICH item churned, which a boolean has thrown away."""

from .idempotence import Idempotence, Proof
from .reversibility import Reversibility, Roundtrip

__all__ = [
    "Idempotence",
    "Proof",
    "Reversibility",
    "Roundtrip",
]
