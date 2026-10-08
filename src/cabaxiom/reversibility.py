"""Reversibility. Prove the converge -> prune round trip returns the world to its FIRST OBSERVED reading - the certificate that "undo" is not a lie."""
from collections import Counter
from collections.abc import Sequence
from typing import final

from .drift import Drift
from .reconciler import Reconciler


@final
class Roundtrip:
    """The verdict of a reversibility check, over three channels. What the converge left WRONG, what the
    prune left BEHIND and what still DIFFERS from the world as first observed. Each channel is named for
    the promise it guards and holds the counter-evidence - empty means the promise held.

    `built` is the converge's residual. Empty when the desired world was verifiably reached, since a round
    trip that never arrived proves nothing about the way back. `erased` is the prune's surviving residue:
    empty when everything the steps own is reported gone. `restored` is the difference between the opening
    and the closing drift readings. Empty when the world reads exactly as it did before the kernel ever
    touched it, which is what "undo" means. That channel is deliberately a comparison against the OPENING
    reading, never against emptiness - after a teardown drift() reads the built world as missing again, so
    emptiness would be the wrong bar - and it is what catches the failures the other two cannot. A prune
    that CLAIMS a clean teardown while the artifact still stands. A run that tore down a world
    somebody else had built.

    `reversible` is true only when all three are empty. The run arrived, erased its own footprint and
    left the world reading as first observed. A Roundtrip is truthy exactly when reversible, so it reads
    as the assertion it is."""
    __slots__ = ("__built", "__erased", "__restored")

    def __init__(self, built: Sequence[Drift], erased: Sequence[Drift], restored: Sequence[Drift]):
        # A RECORD, like every verdict the kernel mints. The channels are captured as tuples behind
        # read-only properties, so a caller cannot falsify the certificate in place after it was minted.
        self.__built = tuple(built)
        self.__erased = tuple(erased)
        self.__restored = tuple(restored)

    @property
    def built(self) -> tuple[Drift, ...]:
        return self.__built

    @property
    def erased(self) -> tuple[Drift, ...]:
        return self.__erased

    @property
    def restored(self) -> tuple[Drift, ...]:
        return self.__restored

    @property
    def reversible(self) -> bool:
        return not self.built and not self.erased and not self.restored

    def __bool__(self) -> bool:
        return self.reversible

    def __repr__(self) -> str:
        return (f"Roundtrip(reversible={self.reversible}, built={self.built!r}, "
                f"erased={self.erased!r}, restored={self.restored!r})")


# NOT @final for the same reason Idempotence is not. A harness that walks the round trip more than
# once subclasses this and closes through the shared _verdict, as tests/test_reversibility.py does.
class Reversibility:
    """Proves a Reconciler's round trip restores the world, wrapping one (has-a, like Idempotence). The
    round-trip twin of Idempotence. Where an idempotence check proves a second converge is a clean no-op,
    this proves the whole converge -> prune round trip returns the world to its first observed reading.

    prove() is a coroutine, since the engine is async native. It holds the OPENING assess reading as a
    value, awaits converge, prune and a closing assess, then returns a Roundtrip - the certificate that
    building and tearing down left the world exactly as first observed. The opening reading is a local
    value inside one prove() call, so the kernel still keeps no state and the whole check works through
    Enclaves for free - one Roundtrip certifies a fractal tree.

    Every leg runs even when an earlier channel is already dirty. The three promises are independent
    evidence, so a verdict that stopped early could not say which of them broke. The certificate is
    honest in both directions - a prune that claims clean while its artifact stands fails `restored` even
    though `erased` reads empty, while a run that tore down a world somebody ELSE had built fails `restored`
    from the other side. For ephemeral test environments, sandboxes and canaries. The proof that "undo" is
    not a lie, minted instead of trusted."""

    def __init__(self, reconciler: Reconciler):
        self._reconciler = reconciler

    @staticmethod
    def __differs(opening: Sequence[Drift], closing: Sequence[Drift]) -> list[Drift]:
        # The restoration rule compares the two readings as (name, message) multisets, so the answer
        # holds every item UNBALANCED between them, from whichever side carries the surplus. An opening
        # item missing at closing means the run left something satisfied that was not (a footprint left
        # standing reads as no-longer-missing). A closing item absent at opening means it broke or tore
        # down something that was fine. Either way the world no longer reads as first observed.
        return (Reversibility.__surplus(opening, closing)
                + Reversibility.__surplus(closing, opening))

    @staticmethod
    def __surplus(kept: Sequence[Drift], against: Sequence[Drift]) -> list[Drift]:
        # The items of `kept` that `against` cannot match, with multiplicity. Two identical readings on
        # one side and one on the other yield exactly one item of evidence, in `kept`'s own order.
        budget: Counter[tuple[str, str]] = Counter((item.name, item.message) for item in kept)
        budget.subtract((item.name, item.message) for item in against)
        excess: list[Drift] = []
        for item in kept:
            pair = (item.name, item.message)
            if budget[pair] > 0:
                budget[pair] -= 1
                excess.append(item)
        return excess

    @staticmethod
    def _verdict(built: Sequence[Drift], erased: Sequence[Drift],
                 opening: Sequence[Drift], closing: Sequence[Drift]) -> Roundtrip:
        # The closing rule. The converge's residual, the prune's residue and the two readings folded
        # through __differs, so the Roundtrip says WHICH promise broke - or that none did.
        return Roundtrip(built, erased, Reversibility.__differs(opening, closing))

    async def prove(self) -> Roundtrip:
        # The round trip, observed at both ends - read, build, tear down, read again - then the shared
        # _verdict folds the four values into the three-channel certificate.
        opening = await self._reconciler.assess()
        built = await self._reconciler.converge()
        erased = await self._reconciler.prune()
        return self._verdict(built, erased, opening, await self._reconciler.assess())

