"""Step - one reconciliation concern that owns its desired state, with read/apply/prune hooks."""
from abc import ABC, ABCMeta
from typing import Any, final

from ._compat import override
from .drift import Assessment, Changes, Drift, DriftItem, Outcome


class _Sealed(ABCMeta):
    """The freeze's clock. Construction runs whole, THEN the instance seals - one object.__setattr__ in
    the metaclass's __call__, after the outermost __init__ has returned.

    A metaclass rather than an __init__ wrapper, and the clock is the whole reason. A wrapper installed
    per subclass seals at the WRONG level: a derived __init__ calling super().__init__() would be sealed
    by the super call and crash on its own next assignment, so it would need a re-entrancy flag to find
    the outermost frame. __call__ IS the outermost frame. A wrapper would also occupy
    cls.__dict__["__init__"] at class-definition time, which makes a later @dataclass decorator skip
    generating its own - so a dataclass Step with a constructor field would crash on object.__init__
    instead of taking its argument. The metaclass touches no __init__ at all."""

    @override
    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        instance = super().__call__(*args, **kwargs)
        object.__setattr__(instance, "_Step__frozen", True)
        return instance


class Step(ABC, metaclass=_Sealed):
    """One reconciliation concern that owns its desired state.

    drift() and apply() default to no-ops (not abstract), so a probe-only step
    overrides just drift(), a cleanup-only step just apply(). The kernel adds
    nothing domain-shaped here: mode, registry, and progress belong in a
    caller-side Step subclass.
    """

    # The declaration slots a caller may still set on a constructed step. `after` is configuration the
    # run reads once before anything executes, so setting it late changes the plan and never the state
    # a pass carries into the next one.
    _SLOTS = frozenset({"after"})

    # Step classes (not instances) that must converge before this one. Reconciler orders on it.
    after: tuple[type["Step"], ...] = ()

    def __setattr__(self, key: str, value: Any) -> None:
        # The freeze's teeth. Construction assigns freely, the metaclass seals the instance the moment it
        # ends, and after that only a declaration slot may still be set - anything else is refused with
        # the reason and the sanctioned channel.
        #
        # A STEP IS A DECLARATION, NOT A SESSION. What a step IS was decided when it was written, so two
        # passes over one step must read the same declaration. State accumulating on self between passes
        # is the hidden-state class of bug this kernel refuses everywhere else, and it is also what stops
        # a step being handed to a worker that does not share this process.
        if getattr(self, "_Step__frozen", False) and key not in Step._SLOTS:
            raise TypeError(
                f"{type(self).__name__} is frozen. A step is a declaration, and mutating one after "
                f"construction is how state hides between passes. A declaration slot "
                f"({', '.join(sorted(Step._SLOTS))}) stays settable. For anything else, keep the value in "
                f"__init__ or hand it back from the hook that computed it."
            )
        super().__setattr__(key, value)

    @staticmethod
    def named(step: "Step") -> str:
        # One step's name, ignoring the run: its kind's, since a step declares no identity of its own.
        # The ONE home for the question "what do I call this step in a sentence". It was spelled
        # type(step).__name__ at eight separate sites before this, which costs nothing until one of them
        # drifts - and the sites that drift are exactly the ones a person reads, a failure message and a
        # drawing of the run. A step that wants a name of its own is a later problem, and it will be
        # solved here rather than at eight call sites.
        return type(step).__name__

    def assess(self) -> Assessment:
        # ONE read of the world, answering four questions from a single probe. It used to be four hooks -
        # drift, plan, audit and footprint - and a step with an expensive probe paid for it four times over
        # while nothing forced the four answers to describe the same moment of the world.
        #
        # deviation  what is out of desired state. Empty is the whole proof this kernel offers, and a
        #            deviation apply() cannot fix still belongs here, since a report-only step keeps it in
        #            the residual.
        # plan       what a converge WOULD do. Deliberately NOT defaulted to deviation any more - a channel
        #            that echoes another cannot be told from one somebody meant, so a step whose plan IS its
        #            deviation now says Assessment(deviation=found, plan=found) and says it on purpose.
        # advisory   what deserves attention in a system that already MEETS desired state. If apply() could
        #            fix it, it is deviation and not advice.
        # footprint  what this step owns that a teardown would remove.
        #
        # Read-only, always. Never mutates.
        return self.verified()

    def apply(self) -> Outcome:
        # Idempotent converge toward desired state. The return type is a Sequence and admits a coroutine,
        # so a domain's own `-> list[MyDrift]` and its `async def apply()` are both legal typed overrides. Re-running a satisfied step is a no-op. May
        # return what it changed this run (name + message), which converge() collects on its applied
        # channel. None (the default, and every no-op) contributes nothing.
        return self.unchanged()

    def prune(self) -> Changes:
        # The deletion half of apply(): remove what this step owns, and return what survived (its
        # residue) so Reconciler.prune() self-verifies the teardown. [] means clean. Reconciler runs
        # it in reverse order (a dependent down before what it depends on).
        return self.unchanged()

    # --- WHAT A HOOK HANDS BACK ---
    #
    # Four named constructors for the two return shapes above, so a hook states what it FOUND or what it
    # DID instead of assembling the record that carries the answer.
    #
    # They are METHODS on the declaration rather than helpers beside it, and that is the whole point. A
    # subclass inherits them, so `return self.drifted("config file is missing")` needs no import at all and
    # a first declaration never has to meet Assessment or DriftItem to say a file is missing. Those two are
    # the kernel's CARRIERS, and a carrier is not the first thing a domain should have to learn. Both stay
    # public and unchanged for the caller who wants to build one by hand.

    @final
    def verified(self) -> Assessment:
        """A read that found nothing out of desired state - the kernel's founding sentence, in one call.

        EMPTY MEANS VERIFIED is the axiom this whole engine rests on, so the way to say it is one word
        rather than a record with an empty channel in it."""
        return Assessment()

    @final
    def drifted(self, *found: str | Drift) -> Assessment:
        """A read that found something out of desired state, named by this step unless told otherwise.

        A bare string is THIS step's own report and is named through named(), because the name written at
        such a site is overwhelmingly the step's own kind - a declaration that already knows what it is
        called should not be asked for it a second time. Pass a Drift instead wherever the subject is not
        the step, and pass several to report several.

        Found nothing? Then this returns exactly what verified() does, which is not a loophole but the
        axiom holding - a hook that spreads a computed sequence in here tells the truth at both lengths."""
        return Assessment(deviation=self.__reported(found))

    @final
    def unchanged(self) -> Changes:
        """A write that ran and had nothing to change - the clean no-op, and the commonest write there is."""
        return None

    @final
    def changed(self, *made: str | Drift) -> Changes:
        """A write that changed something, named by this step unless told otherwise - drifted()'s twin."""
        return self.__reported(made)

    def __reported(self, told: tuple[str | Drift, ...]) -> tuple[Drift, ...]:
        # The one place a bare message becomes a carrier. Anything that is not a string is already a Drift
        # and passes through untouched, which keeps a domain's own richer item first-class here - the
        # kernel reads a drift through two fields and never cares which class exposed them.
        return tuple(DriftItem(Step.named(self), one) if isinstance(one, str) else one for one in told)
