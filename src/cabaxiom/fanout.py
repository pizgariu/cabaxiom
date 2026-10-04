"""Fanout. One step per discovered thing, from a declaration nobody could write in advance."""
from abc import abstractmethod
from typing import cast, final, override

from .drift import Artifacts, Assessment, FlowAssessment, FlowOutcome
from .reconciler import Reconciler
from .step import Step


class Fanout(Step):
    """A step that lists a world, declares a graph over what it found, then converges that graph as its one write.

    The shape every reconciler eventually needs and none of them can write down. A declaration names the
    concerns. A concern over FIFTY buckets, twelve tenants or however many rows a table holds today is
    one concern in the source and fifty in the world. Written flat it collapses into a single step that
    loops inside itself, so everything the kernel offers dies at that boundary. Fifty findings become one
    sentence, a retry paces the whole batch instead of the one cursed item, the residual carries the batch
    rather than the failure. A bucket that appeared since the last pass is invisible until somebody
    edits the source.

    A fanout keeps all of it by having a graph of its own. `explore()` answers a whole `Reconciler` built
    over what it just listed, rebuilt on every verb, with the three verbs here wiring it to the parent. Each
    discovered thing is its own step, so it is its own finding under its own name, it gets its own `Retry`,
    and only what is still wrong stays in the residual. Growth between passes needs no edit at all, which
    is the level-triggered doctrine paying for itself - the next pass lists the world again and the new
    thing joins the run.

    THE INNER GRAPH IS REBUILT WHOLE, never mutated. That is what keeps the proofs. Mid-run minting was
    refused because a living graph that grows is a graph whose ordering, partition and coverage were all
    verified against a world that no longer exists. Here every pass holds a complete immutable derivation,
    so `Idempotence.prove()` on the PARENT certifies the whole tree, second converge writing nothing.

    Why this is not an `Enclave`. An enclave takes a reconciler that is already built, resolved once at
    construction and walked by `Enclosure` on that basis, which is exactly what a per-pass graph cannot be.
    And an enclave exports named keys, a boundary that refuses two inner producers of one key, while a map
    has N producers of one key by definition. So the two are siblings rather than parent and child. Static
    composition is an `Enclave`, dynamic composition is a `Fanout`, so both are one step to the parent.

    The load-bearing rule is ENFORCED here rather than documented. `apply()` returns the inner converge's
    APPLIED channel and never its residual, because a residual handed up would poison the parent's applied
    channel with still-wrong items and silently break `Proof.churned`. Hand-rolled fan-outs get this wrong,
    and the mistake reads as success. The verbs are `final`, so a subclass writes the discovery and cannot
    reach the wiring. What is still wrong inside surfaces through the parent's own re-assessment, which
    calls `assess()`, which lists the world afresh and reads the whole sub-stack. Empty still means verified.

    The parent's artifacts reach the seam. An enclave threads nothing inward, since its inner run is
    independent by the time anyone holds it, yet a fan's declaration is BUILT during the parent's run and a
    sibling's output is often the thing that says what to list. Nothing crosses back up. A step that means
    to publish is an `Enclave`, while a fan of N producers has no single value to name.

    Two costs, both stated because neither is hidden anywhere else. The listing runs once per verb, so a
    converge that takes three passes lists the world six times, which is the price of asking rather than
    remembering. And `Enclosure` cannot see inside a fanout, because there is nothing to see until a verb
    runs. It says so out loud instead of walking past.
    """

    @abstractmethod
    async def explore(self, inputs: Artifacts) -> Reconciler:
        """Answer a reconciler over the world as it is RIGHT NOW. Built fresh, used once, never kept.

        This is where the listing goes. A fan cannot be written in advance because the thing it fans over is
        a fact about the world at the moment somebody asks, so the I/O belongs in a verb, which is where this
        project says I/O belongs. A constructor that awaited a listing would turn a declaration into a
        session, so a graph derived at import time would describe last week.

        Read `inputs` for what the parent's siblings produced. That is the whole reason the seam takes them,
        and it is the one thing a static enclave cannot do.

        Called once per verb, so once per pass, with the answer dropped when the verb returns. Nothing
        about it may outlive the call. The freeze already refuses stashing it on `self`, which is the same
        rule this seam exists to satisfy rather than a separate one."""
        raise NotImplementedError

    @final
    @override
    async def assess(self, inputs: Artifacts) -> FlowAssessment:
        # The whole sub-stack's deviation IS this step's deviation, the enclave contract unchanged, so it
        # is what keeps "empty means verified" true through a level whose shape is decided at read time.
        return Assessment(deviation=await (await self.__explored(inputs)).assess()), {}

    @final
    @override
    async def apply(self, inputs: Artifacts) -> FlowOutcome:
        # Converge the discovered graph as this step's one write, then hand up the APPLIED channel. See the
        # class docstring for why the residual must not travel and why this method is closed.
        return (await (await self.__explored(inputs)).converge()).applied, {}

    @final
    @override
    async def prune(self, inputs: Artifacts) -> FlowOutcome:
        # Tear down what is there NOW rather than what was there when the run started, which is the only
        # honest answer a teardown of a discovered world can give. The inner reconciler walks its own
        # inverse partition, so both levels come down in reverse and the parent collects the residue.
        return await (await self.__explored(inputs)).prune(), {}

    async def __explored(self, inputs: Artifacts) -> Reconciler:
        # The seam's answer, vetted ONCE for all three verbs. Both refusals here fire on the first pass of
        # the first run and neither ever comes good on a retry, the static case `Unpublished` argues about
        # at more length.
        answered = cast(object, await self.explore(inputs))   # vetted as the untyped value a caller may actually hand over
        if not isinstance(answered, Reconciler):
            raise TypeError(
                f"{Step.named(self)}.explore must answer a Reconciler over what it found, got "
                f"{answered.__class__.__name__}. A fanout composes a whole inner run rather than a list of "
                f"steps, so the discovery chooses the inner ordering, dispatcher, retry and observer too."
            )
        # noinspection PyProtectedMember
        if self in answered._graph.steps:
            raise ValueError(
                f"{Step.named(self)}.explore answers a graph containing the fanout itself, so assessing it "
                f"would list the world again to assess it again, without end. A fan is the boundary around "
                f"its discoveries and never one of them. Building the inner graph from a registry that "
                f"holds this step is the usual way in."
            )
        return answered

