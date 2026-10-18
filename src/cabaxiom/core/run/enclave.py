"""Enclave. A whole Reconciler participating in a parent run as ONE Step - reconciliation made fractal."""
from collections.abc import Mapping
from typing import cast, final, override

from ..declaration.drift import Artifacts, Assessment, FlowAssessment, FlowOutcome
from ..declaration.step import Step
from ..record.ledger import Reading
from ..record.records import Residual
from .reconciler import Reconciler

# The Step surface and the reconciler surface already align verb for verb (assess + a write and a
# teardown), so a Reconciler is a Step minus this adapter - and this module is the adapter, sitting on
# top of both with a one-way dependency arrow.


@final
class Unpublished(ValueError):
    """Raised when an Enclave's published key cannot be exported. Nothing inside produced it or two
    inner steps both claim it.

    A NAMED type rather than a bare ValueError, because the two reasons deserve different retry money.
    The casualty case (an inner failure explains the missing key) can genuinely come good on a retry -
    the inner stack is idempotent, so re-converging it re-runs only what failed. The static case (a
    typo, a step that never returns that key) never comes good, so the shipped Retry would re-converge
    the whole inner stack once per attempt of the budget before the operator hears about it - safe, not
    free. A custom `retryable(step, attempt, error)` can tell this type apart and decline to pace it,
    without matching message text.

    WHERE it surfaces differs by side. The difference is catchability itself. Raised from apply(), it rides
    the write fan, so FailFast re-raises it BARE and a flat `except Unpublished` works at the converge
    call site. Raised from assess(), it rides the PROBE fan, which gathers a wave's broken reads into one
    ExceptionGroup - so on the read side it arrives inside "N of the wave's reads failed" and only
    `except*` reaches it by type. That is the read contract for every broken read, not an exception made
    for this one."""


class Enclave(Step):
    """A whole reconciler joining a parent run as ONE Step, the composition thesis closing on itself.

    A sub-stack with its own ordering, dispatcher, convergence, retries and observer becomes a single step
    the parent orders with `expects` / `requires` like any other, so stacks nest and one top-level converge()
    returns one residual - and Idempotence.prove() on the parent certifies the whole tree. One flavour now
    that the engine is async native. Every verb awaits its inner counterpart on the caller's loop.

    The one load-bearing rule lives in apply(). It returns the inner converge's APPLIED channel, never the
    residual. A naive adapter returning the Residual would poison the parent's applied channel with
    still-wrong items - silently breaking Proof.churned. The inner residual needs no smuggling. The
    parent's re-assessment calls assess(), which delegates to the sub-stack, so what is still wrong inside
    surfaces honestly and "empty means verified" stays true across every level. FailFast inside the enclave
    propagates out to meet the PARENT dispatcher's own OnError policy, so prune() composes for free - both
    levels tear down in reverse.

    The parent's artifacts are not threaded inward. A sub-stack is an independent run with its own
    data-flow, so the enclave reads the world through its inner reconciler rather than through what the
    parent's siblings produced. And it publishes nothing back up the artifacts channel UNLESS ASKED:
    `publishes=("dataset_uri",)` names the keys this enclave exports to the parent's data-flow, an explicit
    contract like a module's exports, with the empty default keeping the boundary sealed exactly as it
    always was. An exported key joins the parent's payloads like any sibling's, the parent's own
    collision guard included - and it crosses on BOTH verbs with two honest fates. On apply() it is a
    PROMISE. After a clean converge the key must exist, so a hole is refused (see `Unpublished`). On
    assess() it is a PHOTOGRAPH. A world not built yet has no key to show, so a hole is exported as
    absence while the inner deviation says why - EXCEPT on a clean reading, where absence is refused,
    because a photograph of a converged world that lacks a promised key is a typo or a producer whose
    assess forgot to mirror its artifacts, never the world's fault. A parent consumer of a published key
    therefore tolerates absence in any assess that can see a dirty world and may rely on presence
    exactly when the reading is otherwise clean."""

    def __init__(self, reconciler: Reconciler, publishes: tuple[str, ...] = ()):
        # The vet runs FIRST, before anything is stored (the guard-before-store precedent). The classic
        # forgotten comma makes a bare string iterate into characters, while a non-string key could never
        # match an artifact. The frozen-Step seal then makes the declaration immutable for free, which
        # matters here - publishes is read at apply and assess time alike, so a slot that stayed
        # assignable could change between two passes of one run.
        declared = cast(object, publishes)   # vetted as the untyped value a caller may actually hand over
        if not isinstance(declared, tuple):
            entry = repr(declared) if isinstance(declared, str) else None
            hint = f" A single key still needs a trailing comma - write publishes=({entry},)." if entry else ""
            raise TypeError(f"Enclave.publishes must be a tuple of artifact keys, got {declared.__class__.__name__}.{hint}")
        for key in declared:
            if not isinstance(key, str):
                raise TypeError(
                    f"Enclave publishes {key!r}, which is not an artifact key. A published key is the string "
                    f"under which a step inside returns the value in its artifacts."
                )
        self._reconciler = reconciler
        self.__publishes = publishes

    @override
    async def assess(self, inputs: Artifacts) -> FlowAssessment:
        # The parent's re-assessment sees the WHOLE sub-stack's deviation as this one step's deviation,
        # which is what keeps "empty means verified" true across a nested tree.
        #
        # ALL FOUR CHANNELS CROSS, not just deviation. They used to stop here. The first real consumer
        # of a nested run found it within an hour - a check suite holding a git-hooks reconciler needs the
        # inner run's ADVICE, so dropping it made the enclave lossy in the one direction nothing would
        # ever notice, since advice is precisely what a green run still has to say. There is no double
        # count to fear either way: the inner steps are not in the parent's graph, so the parent aggregates
        # this enclave's four channels exactly once. The published keys cross here too, as the GLIMPSE.
        reading = await self._reconciler.assess()
        return Assessment(deviation=reading, plan=reading.plan, advisory=reading.advisory,
                          footprint=reading.footprint), self.__glimpsed(reading)

    @override
    async def apply(self, inputs: Artifacts) -> FlowOutcome:
        # Converge the whole sub-stack as this step's one write. Return the APPLIED channel, never the
        # residual (see the class docstring). What remains wrong inside surfaces through the parent's
        # re-assessment. The exported keys ride out as this step's own artifacts.
        residual = await self._reconciler.converge()
        return residual.applied, self.__exported(residual)

    @override
    async def prune(self, inputs: Artifacts) -> FlowOutcome:
        # Tear the sub-stack down (its own reverse order) and hand its surviving residue to the parent,
        # which is collecting exactly that. What survived this step's teardown. Nothing is exported on the
        # way down - the teardown walks the inverse partition, so a parent dependent already ran before
        # this enclave was pruned, so there is nobody left to read a key.
        return await self._reconciler.prune(), {}

    def __claimants(self, key: str, produced: Mapping[Step, Artifacts]) -> list[Step]:
        # The producer scan, spoken ONCE for both verbs. Who claims a published key, in the INNER
        # DECLARATION order read off the inner run's own graph, so every refusal sentence is a function
        # of the world and not of the strategy that walked it.
        return [step for step in self._reconciler._graph.steps if key in produced.get(step, {})]

    def __collision(self, key: str, producers: list[Step]) -> Unpublished:
        # The one fate both verbs share. The boundary is ONE consumer of each published key, so two inner
        # producers are refused exactly as the Ledger's own mount refuses a colliding payload.
        first, second = producers[0], producers[1]
        named = f"two {Step.named(first)} instances" if Step.named(first) == Step.named(second) else f"{Step.named(first)} and {Step.named(second)}"
        return Unpublished(
            f"Enclave publishes `{key}` and {named} both produce it. The boundary is one consumer "
            f"of that key, so the collision is refused exactly as the Ledger's own mount refuses "
            f"one. Namespace the keys inside or publish the one that means it."
        )

    def __glimpsed(self, reading: Reading) -> Artifacts:
        # The read-side crossing, the photograph to __exported's promise. A key nobody produced is
        # SKIPPED while the reading is dirty - the world is not built yet, so the deviation beside the
        # hole is what keeps the parent's proof honest, so absence and deviation travel together BY
        # CONSTRUCTION. On a CLEAN reading the same hole is refused. A photograph of a converged world
        # that lacks a promised key is a typo, a producer whose assess forgot to mirror its artifacts
        # (artifacts are level-triggered, a function of the world) or a lazy read - never the world's
        # fault, so skipping it would mint a clean proof over a broken promise.
        if not self.__publishes:
            return {}
        produced = reading.produced
        glimpsed: Artifacts = {}
        for key in self.__publishes:
            producers = self.__claimants(key, produced)
            if not producers:
                if reading:
                    continue
                raise Unpublished(
                    f"Enclave publishes `{key}` and a clean reading shows no producer for it. A clean "
                    f"reading claims the world converged and artifacts are level-triggered - a function "
                    f"of the world, not of the work - so the key had to be in the photograph. Either no "
                    f"step inside returns it from assess (mirror what apply produces) or nothing inside "
                    f"produces it at all."
                )
            if len(producers) > 1:
                raise self.__collision(key, producers)
            glimpsed[key] = produced[producers[0]][key]
        return glimpsed

    def __exported(self, residual: Residual) -> Artifacts:
        # The write-side boundary crossing. Every published key, found among what the inner run's final
        # pass produced, in the order the export list declares them - the claimant scan above, with the
        # PROMISE fates. A hole after a converge is refused, quoting the inner record when a casualty
        # explains it and naming the promise when nothing does.
        if not self.__publishes:
            return {}
        produced = residual.produced
        exported: Artifacts = {}
        for key in self.__publishes:
            producers = self.__claimants(key, produced)
            if not producers:
                if residual.failures:
                    told = ", ".join(item.message for item in residual.failures)
                    raise Unpublished(
                        f"Enclave publishes `{key}` and nothing inside produced it this run. The run "
                        f"recorded inside: {told}. A published key is the enclave's promise to the parent, "
                        f"so the promise breaks loudly instead of exporting silence."
                    )
                raise Unpublished(
                    f"Enclave publishes `{key}` yet no step inside produces it. A published key is the "
                    f"enclave's promise to the parent, in the spirit of `demands` - it cannot be checked at "
                    f"resolution, because only a run shows what a step returns, so it is checked here, on "
                    f"every write."
                )
            if len(producers) > 1:
                raise self.__collision(key, producers)
            exported[key] = produced[producers[0]][key]
        return exported
