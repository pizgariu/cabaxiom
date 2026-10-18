"""Reconciler. Resolves Steps once, then assesses the world or converges and self-verifies - one
engine, async native, woken by events instead of driven by a polling loop."""
import asyncio
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from typing import cast, final

from .cancellation import Cancellation
from .convergence import Convergence, Once
from .dispatcher import Parallel, RunMode, Write
from .drift import Artifacts, Drift
from .graph import Graph
from .lease import Authority
from .ledger import Reading, Statement
from .observer import Observer
from .ordering import Kahn, Ordering
from .records import Casualty, Explanation, Residual
from .retry import BaseRetry, Retry
from .scope import Scope
from .step import Step
from .vocabulary import Vocabulary
from .warrant import Warrant


@final
class Reconciler:
    """Resolves an explicit, ordered set of Steps once, then either assesses the world (read-only) or
    converges actual -> desired (idempotent) and self-verifies by re-assessing for the residual.

    ONE engine, one colour. The sync and async families used to mirror each other verb for verb. The
    mirror was the maintenance. Every fix landed twice or drifted. The engine is async native now - a step
    with blocking I/O rides ThreadDispatcher, which bridges it onto the loop, so the sync DOMAIN is still
    served while the sync ENGINE is gone. converge() is awaited, so the event loop is the one thing a
    consumer must bring.

    No registry, no auto-discovery, no capability probing. The kernel takes the steps it is handed.
    Ordering is an injected strategy (Kahn by default). The self-verifying converge is the core and
    watch() is the standing form of it - woken by the steps' own event sources instead of a timer.
    """

    def __init__(self, steps: Iterable[Step], ordering: Ordering | None = None, *,
                 scope: Scope | None = None, mode: RunMode | None = None,
                 convergence: Convergence | None = None, cancellation: Cancellation | None = None,
                 observer: Observer | None = None, retry: BaseRetry | None = None,
                 vocabulary: Vocabulary | None = None, authority: Authority | None = None,
                 warrant: Warrant | None = None):
        scope = scope or Scope()
        ordering = ordering or Kahn()

        mode = mode or Parallel()
        self._convergence = convergence or Once()
        self._cancellation = cancellation or Cancellation()
        self._observer = observer or Observer()
        self._retry = retry or Retry(1)   # the neutral single try, which wraps nothing
        # None means no capacity is asked for, so the write path wraps nothing at all - the same
        # zero-cost neutral the retry takes. A run whose steps declare no `leases` sees no difference
        # either way, so the axis is invisible until somebody wants it.
        self._authority = authority
        # None means no gate, so neither write verb takes the leading probe - so the axis costs nothing
        # at all until somebody asks for it, which is the same neutral every other axis ships. BOTH write
        # verbs ask it, converge before the first wave and prune before the first teardown, because a
        # destructive-scale policy is a question about the one verb that destroys anything.
        self._warrant = warrant

        # The world is derived ONCE, over the full membership and the one vocabulary - construction vets
        # every declaration. The scope then narrows the DERIVATION itself. Select() is Graph in, Graph out,
        # so the language cannot fork on the way through - it rides inside the one object being narrowed,
        # and the second Vocabulary.shipped() a forgotten keyword used to summon has nowhere left to
        # appear. The dispatcher resolves the final, scoped graph into the run shape it will walk.
        self._graph = scope.select(Graph(tuple(steps), Vocabulary.shipped() if vocabulary is None else vocabulary))
        self._partition = mode.resolve(ordering, self._graph)
        # The WORKER, not the mode. A RunMode is a constructor-time citizen - it pairs a shape with a
        # worker, vouches the pairing and resolves the partition - and every one of those jobs is done by
        # this line. What the run keeps is what it walks with, the partition and the dispatcher, so holding
        # the mode was holding a spent validator and paying a two-hop chain for its worker on every verb.
        self._dispatcher = mode.dispatcher

    def explain(self) -> Explanation:
        # The structural read (returns an Explanation, not Drift). What the injected Ordering resolved and
        # the dispatcher will walk, as per-instance labels in run order, the resolved edges behind that
        # order (read off the run's own Graph, so every edge kind is present by construction, capabilities
        # included) plus the declarations that produced them. Reads the same resolved partition and Graph
        # every other verb uses, so it explains the actual run and re-resolves nothing.
        ordered = tuple(step for group in self._partition for step in group)
        labels = self.__labelled()
        groups = tuple(tuple(labels[step] for step in group) for group in self._partition)
        # Every landed arrow with the slot that produced it, straight off the Graph's per-name view and
        # ORIENTED here by the kind's own direction. A `precedes` declaration lands with the declarer on
        # the prerequisite side, so the (dependent, prerequisite, slot) contract holds for every kind and
        # no consumer re-derives a direction the vocabulary owns - the lesson Enclosure already paid for.
        # The resolved dependency mapping is a projection of these, so the picture and the edge list
        # cannot tell two different stories about one run.
        arrows = tuple(
            (labels[reached], labels[step], matched.slot) if matched.kind.precedes
            else (labels[step], labels[reached], matched.slot)
            for step in ordered
            for matched in self._graph.matching(step)
            for reached in matched.matched
        )
        # The declaration mappings, one per vocabulary slot and driven BY the vocabulary. How a declared
        # name reads on the page is the ADDRESSING's business (by class reads as the class name, by label
        # as its label, an instance by its per-instance run label, present ones only), so the next edge
        # kind arrives here with no new code. `provides` and `contends` ride along as the declarations the
        # vocabulary does not drive - sets of opaque labels rather than addressings over steps, sorted, the
        # declarations being sets. `contends` is NOT an edge kind and never becomes one, so it contributes
        # no arrow and the drawing stays a picture of the declaration.
        declared = {
            kind.slot: tuple(
                (labels[step], seen)
                for step in ordered
                if (seen := kind.addressing.shown(getattr(step, kind.slot, ()), labels))
            )
            for kind in self._graph.vocabulary
        }
        declared["provides"] = tuple(
            (labels[step], tuple(sorted(step.provides))) for step in ordered if step.provides)
        declared["contends"] = tuple(
            (labels[step], tuple(sorted(step.contends))) for step in ordered if step.contends)

        return Explanation(groups, shape=self._partition.placement.grouping, arrows=arrows, declared=declared, vocabulary=tuple(self._graph.vocabulary))

    def foresee(self, step: Step) -> Casualty:
        # The counterfactual structural read, explain()'s twin. If THIS step failed, what would the run
        # lose? Reads the same resolved partition and Graph every other verb uses, touches nothing and
        # runs nothing.
        #
        # The BestEffort answer is the Graph's fallout(), which is not a lookalike of the blame walk but
        # literally the one the Ledger runs, so a forecast that disagreed with the handling would be a
        # contradiction rather than a bug. The Halt answer is split, because Halt gates by RUN POSITION
        # and not by edges. A strictly later group cannot start once the run stands still, while the
        # failure's own group is indeterminate - a fanning dispatcher admitted it whole, so it settles.
        labels = self.__labelled()
        if step not in labels:
            raise ValueError(
                f"{Step.named(step)} is not in this run, so there is nothing to foresee about it."
            )
        struck = self._graph.fallout((step,))
        blocked = tuple(labels[other] for other in labels if other in struck and other is not step)
        position = next(index for index, group in enumerate(self._partition) if step in group)
        skipped = tuple(labels[other] for group in self._partition.groups[position + 1:] for other in group)
        settling = tuple(labels[other] for other in self._partition.groups[position] if other is not step)
        offered: dict[str, int] = {}
        for other in labels:
            for capability in other.provides:
                offered[capability] = offered.get(capability, 0) + 1
        starves = tuple(sorted(capability for capability in step.provides if offered[capability] == 1))
        return Casualty(labels[step], blocked, skipped, settling, starves)

    def __labelled(self) -> dict[Step, str]:
        # The run's per-instance labels, in RUN order - minted by the one shared labeller, since these
        # names are read across citizens (an Indictment names the accused, this names the run, a Casualty
        # marks it, a Diagram paints it) and a second tally over a different order made one string mean
        # two different steps. Shared by BOTH structural reads here, because explain() and foresee()
        # describing the same run must name the same step the same way.
        return Step.labelled(step for group in self._partition for step in group)

    def __settled(self, statement: Statement, applied: list[Drift], reprobe: Sequence[Drift]) -> list[Drift]:
        # The tail of a converge pass. It takes the dispatcher's Statement whole rather than making the
        # caller unpack it. The fresh re-assessment arrives already awaited,
        # what apply() changed is routed to the applied channel and kept OUT of the residual so an empty
        # list stays verified-success, then the residual is this run's failures plus that re-assessment.
        # `applied` accumulates on the caller's own coroutine across passes (never in a dispatcher's
        # workers), so it stays race-free and in resolved order.
        #
        # Each hook is handed a TUPLE. An Observer is a trace, so a trace must not be able to rewrite what
        # it traces - the residual IS this kernel's proof, so an observer that appended to the list it was
        # shown once made a verified-clean run come back dirty. A Chorus relayed the same object to
        # every member so one could alter what a later one saw. A tuple does not merely discard the
        # mutation the way a copy did - it refuses it, with the Sequence annotation saying so up front.
        applied.extend(statement.returns)
        self._observer.acted(statement.returns)
        # Deferrals ride into the residual beside the failures and stay a SEPARATE argument the whole way,
        # so no sentence between the pool and the report can rename a full queue into a broken step. A run
        # whose only trouble is exhausted capacity is not clean, which is what this line says.
        residual = [*statement.failures, *statement.deferred, *reprobe]
        self._observer.remained(tuple(residual))
        return residual

    async def assess(self) -> Reading:
        # THE read fan. Every step's assess() over the resolved partition, deviations flattened in run
        # order. One verb where four used to fan separately, because the four always read the same world
        # - the record each step returns still carries the plan, the advice and the footprint apart and
        # this fan surfaces the deviation channel, the one converge() re-probes for its proof. The
        # Reading is a Sequence of exactly those deviations, so every list-shaped caller reads it as
        # before - and carries what each assess PRODUCED beside them, the read's own data-flow.
        return await self._dispatcher.probe(self._partition.groups, self._graph, lambda step, inputs: step.assess(inputs), self._cancellation, self._observer)

    async def __refused(self) -> tuple[Reading, tuple[Drift, ...]] | None:
        # THE GATE, asked once and before anything is written. The ONE home BOTH write verbs ask it from -
        # so a refusal cannot come to mean one thing to a converge and another to a teardown. It answers the
        # reading it judged beside the reasons or None when the run may proceed. The verdict each verb then
        # mints is its own, because the two residuals are made of different channels and are announced through
        # different hooks.
        #
        # Only when a warrant was injected, so a run without one takes no leading probe and pays nothing,
        # which is the neutral-by-default rule every axis in this kernel follows. The reading is the whole
        # world as it stands, all four channels, which is what lets a policy judge scale rather than guess it.
        #
        # IT IS HANDED OVER WHOLE FOR EITHER VERB. That is a decision rather than an omission. assent() is
        # opaque about which channel it weighed, so a reconciler narrowing the reading per verb would be
        # forging a record the probe never answered - and Reading's own contract is that it is total over the
        # run or not minted at all. A gate handed a hollowed channel cannot be told apart from one that never
        # looked. So a Ceiling bounding the deviations refuses a teardown too, reading as the policy it
        # is - a world that never reached its declaration is a world whose teardown would destroy what nobody
        # built.
        if self._warrant is None:
            return None
        reading = await self.assess()
        refused = tuple(self._warrant.assent(reading))
        return (reading, refused) if refused else None

    async def converge(self) -> Residual:
        # Apply every step and re-assess for what is STILL out of desired state. The returned residual is
        # the proof it worked, `applied` the record of what changed.
        #
        # CQS. A command returning its own outcome (this run's failures + a fresh re-assessment + applied),
        # none reconstructible by a later read. Splitting into a query would need a persistent store to
        # read the post-state back, which this kernel deliberately lacks. Persistence is a consumer
        # concern. The injected Convergence strategy decides how many times to repeat the apply ->
        # re-assess cycle: Once (default) runs it a single time, Fixpoint loops until the residual
        # settles, for steps that only come good once an earlier step's apply() has cleared the way.
        if (verdict := await self.__refused()) is not None:
            reading, refused = verdict
            # A REFUSAL IS A VERDICT. Nothing was applied, so the applied channel is empty and the
            # failures channel is empty too, because nothing broke. The reasons ride in the residual
            # BESIDE what the probe found, which keeps "empty means verified" honest - a refused run
            # really did not reach its declaration - and they ride in their own channel so no caller
            # reads a policy decision as a crash. The deviations are the channel THIS residual is made
            # of, which is the rule the teardown's own verdict follows with its own channel.
            #
            # The empty applied channel is ANNOUNCED as well as returned. That is not ceremony. A
            # trace closes one pass by pairing acted with remained (Journal buffers what acted said and
            # writes it out when remained arrives), so a path firing only the second half leaves the
            # previous run's buffer standing - and one Journal reused across a written run and then a
            # refused one recorded the writes of the first as the refusal's own. Firing both halves is
            # what makes "nothing was applied" true in the trace and not only in the record. began()
            # stays deliberately unfired, because no pass began and Timing opens its span on it.
            self._observer.acted(())
            self._observer.remained(tuple([*refused, *reading]))
            return Residual.refused(refused, beside=reading, produced=reading.produced)

        applied: list[Drift] = []
        told: list[Drift] = []              # the failures of the LAST cycle, for the minted channel
        latest: list[Drift] | None = None   # the flat list that cycle handed the policy, for the identity check
        held: Mapping[Step, Artifacts] = {}   # the LAST cycle's produced map, a photograph retaken per pass

        # The run's write, verb spoken. A Write is the retry-wrapped callable every dispatcher calls as
        # before, plus the verb a transport needs in its envelope and the relay() that rebuilds the whole
        # stack around a relocated hook. Built here because only the reconciler knows which write this is.
        do = Write(self._retry, self._observer, lambda step, inputs: step.apply(inputs), "apply", self._authority)

        async def cycle() -> list[Drift]:
            nonlocal latest, held
            self._observer.began()
            statement = await self._dispatcher.execute(self._partition.groups, self._graph, do, self._cancellation, self._observer)
            held = statement.produced
            told[:] = statement.failures
            # Bound to a local as well as to the nonlocal, because the nonlocal is declared
            # list[Drift] | None for its pre-first-pass state and a reader should not have to do the
            # narrowing in their head to see what this hands back.
            latest = settled = self.__settled(statement, applied, await self.assess())
            return settled

        # The convergence policy lives once in passes(). It yields the wait before each pass, the cycle
        # runs and sends back its residual, while StopIteration carries the final residual out.
        passes = self._convergence.passes()
        try:
            wait = next(passes)
            while True:
                if wait:
                    await asyncio.sleep(wait)
                wait = passes.send(await cycle())
        except StopIteration as done:
            # The failures channel is honest only for the residual the policy actually returned from its
            # last cycle - a custom passes() synthesizing some other list gets an empty channel rather
            # than a guessed one, so the view stays exactly what the policy answered.
            flat = cast(list[Drift], done.value)
            return Residual.converged(flat, failures=told if flat is latest else (), applied=applied, produced=held if flat is latest else None)

    async def prune(self) -> Residual:
        # The deletion half, the mirror of converge. Run every step's prune() in REVERSE resolved order
        # (tear a dependent down before the thing it depends on) through the same dispatcher, so the
        # teardown inherits the whole failure semantics without a second engine.
        #
        # THE GATE, on the verb it was built for. Ceiling's own words are that a footprint bound
        # refuses "a run that would tear down more than five things", so prune is the only verb that tears
        # anything down - yet the gate sat in converge alone, so the one question the footprint channel exists
        # to ask could not be asked of the one verb it is about. It cost nothing to notice, because nothing in
        # the suite composed a warrant with a teardown.
        #
        # THE LEADING PROBE IS TAKEN WHILE THE WORLD STILL STANDS, which is why a read before a teardown is
        # coherent at all. Residual.pruned says why the read is deliberately NOT re-run afterwards - it measures
        # deviation from a world that should EXIST, so it would report a successful teardown as everything
        # being missing - and that objection is about a reading taken AFTER the removal. It does not touch
        # this one, which reads the standing world and whose footprint channel is precisely the question a
        # destructive-scale policy asks.
        if (verdict := await self.__refused()) is not None:
            reading, refused = verdict
            # A REFUSED TEARDOWN SURVIVED ENTIRELY, so this residual means what survived - so the reasons
            # ride beside the FOOTPRINT, the channel that says what a teardown would have removed and
            # therefore names exactly what is still standing. Converge's veto rides its reasons beside the
            # deviations by the same rule, each verb carrying the channel its own residual is made of. The
            # deviations would be a category error here, naming a converge's finding inside a survival proof,
            # and an empty residue channel would leave a caller no reading of the world its probe paid for.
            # Nothing was torn down and nothing broke, so the failures channel stays empty exactly as it does
            # for a refused converge. pruned() is fired because it is the teardown's own closing hook -
            # a trace that recorded every teardown but the refused one would be the same lie the converge
            # veto's unpaired hooks already were.
            residual = Residual.refused(refused, beside=reading.footprint, produced=reading.produced)
            self._observer.pruned(tuple(residual))
            return residual

        do = Write(self._retry, self._observer, lambda step, inputs: step.prune(inputs), "prune", self._authority)
        statement = await self._dispatcher.execute(self._partition.inverse(), self._graph, do, self._cancellation, self._observer)
        # The verdict says why no read follows the teardown. The observer hook is fired here because it is
        # the teardown's own closing hook, on the refused path and the run path alike.
        residual = Residual.pruned(statement)
        self._observer.pruned(tuple(residual))
        return residual

    async def watch(self) -> AsyncIterator[Residual]:
        # The standing converge, woken by the world instead of a timer. Each step's watch() is monitored
        # concurrently, a yield from any of them queues one wake, with every wake answered by a full
        # converge - level-triggered to the bone. The wake carries no payload and is never trusted as a
        # report, the re-assessment that follows is still the only truth, so a spurious wake costs one
        # clean pass and a missed one is caught by the next. The first converge runs unconditionally,
        # because a watcher that starts on a drifted world should not wait for the world to move again
        # before saying so.
        yield await self.converge()

        queue: asyncio.Queue[Step] = asyncio.Queue()

        async def _monitor(step: Step) -> None:
            try:
                async for _ in step.watch():
                    await queue.put(step)
            except asyncio.CancelledError:
                pass

        tasks = [asyncio.create_task(_monitor(step)) for step in self._graph.steps]

        try:
            while True:
                await queue.get()
                # Coalesce a burst. Ten wakes queued during one converge are one drifted world. Ten
                # converges over it would be nine no-ops paid at full price. Draining here is what makes
                # a wake mean "look again", never "look once per event".
                while not queue.empty():
                    queue.get_nowait()

                if self._cancellation.cancelled():
                    break

                yield await self.converge()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

