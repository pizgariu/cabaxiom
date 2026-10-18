"""What is the SMALLEST thing that breaks it? Both benches delta-debug and they shrink opposite axes.

Isolation holds the world still and shrinks the DECLARATION, asking which step the stack cannot take. A
Siege holds the declaration still and shrinks the FAULT SET, asking which failure it cannot take. What
either hands back is a reproducer and never a root cause. Both say so in their own words - no smaller
set reproduces this is a far weaker claim than this is the reason, where only one of them is true."""

from .isolation import Charge, Churn, Indictment, Isolation, Stall
from .siege import Breach, Siege

__all__ = [
    "Charge",
    "Churn",
    "Indictment",
    "Isolation",
    "Stall",
    "Breach",
    "Siege",
]
