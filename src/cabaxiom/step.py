"""Step - one reconciliation concern that owns its desired state, with read/apply/prune hooks."""
from abc import ABC
from typing import final

from .drift import Assessment, Changes, Drift, DriftItem, Outcome


class Step(ABC):
    """One reconciliation concern that owns its desired state.

    drift() and apply() default to no-ops (not abstract), so a probe-only step
    overrides just drift(), a cleanup-only step just apply(). The kernel adds
    nothing domain-shaped here: mode, registry, and progress belong in a
    caller-side Step subclass.
    """

    # Step classes (not instances) that must converge before this one. Reconciler orders on it.
    after: tuple[type["Step"], ...] = ()

    @staticmethod
    def named(step: "Step") -> str:
        # One step's name, ignoring the run: its kind's, since a step declares no identity of its own.
        # The ONE home for the question "what do I call this step in a sentence". It was spelled
        # type(step).__name__ at eight separate sites before this, which costs nothing until one of them
        # drifts - and the sites that drift are exactly the ones a person reads, a failure message and a
        # drawing of the run. A step that wants a name of its own is a later problem, and it will be
        # solved here rather than at eight call sites.
        return type(step).__name__

    def drift(self) -> list[Drift]:
        # Read-only, never mutates. [] means already in desired state. Any deviation belongs here,
        # even one apply() cannot fix. A finding about a system that already meets desired state is
        # advice, not drift - route it to audit().
        return []

    def plan(self) -> list[Drift]:
        # Dry-run preview of the actions apply() would take, without mutating. Where drift() is the
        # deviation (what is wrong), plan() is the intended action. Defaults to drift() since for a
        # fixable step the deviation is the work. Override when they diverge.
        return self.drift()

    def audit(self) -> list[Drift]:
        # Advisory findings about a step that is already in desired state (a stale runtime behind a
        # correct config, a better mode the domain chooses not to force). Read-only, never mutates.
        # [] means nothing to advise. Not defaulted to drift() like plan(): advice is what remains
        # when there is no deviation, so echoing drift here would report every deviation twice. If
        # apply() could fix it, it is drift, not advice.
        return []

    def footprint(self) -> list[Drift]:
        # What this step owns that a teardown would remove: the preview an uninstall shows before
        # pruning, in the same (name, message) shape as every other read. Read-only, never mutates.
        # [] means owns nothing worth listing. What ownership means is the domain's business.
        return []

    def apply(self) -> Outcome:
        # Idempotent converge toward desired state. The return type is a Sequence and admits a coroutine,
        # so a domain's own `-> list[MyDrift]` and its `async def apply()` are both legal typed overrides. Re-running a satisfied step is a no-op. May
        # return what it changed this run (name + message), which converge() collects on its applied
        # channel. None (the default, and every no-op) contributes nothing.
        return None

    def prune(self) -> Changes:
        # The deletion half of apply(): remove what this step owns, and return what survived (its
        # residue) so Reconciler.prune() self-verifies the teardown. [] means clean. Reconciler runs
        # it in reverse order (a dependent down before what it depends on).
        return []

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
