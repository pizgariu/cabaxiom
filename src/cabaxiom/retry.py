"""Retry - per-step attempts for the write phase, paced by a Backoff, spent before the OnError policy."""
import asyncio
import inspect
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import final, override

from .cancellation import Deferred
from .convergence import Backoff
from .drift import Artifacts, AsyncFlowOutcome, FlowOutcome
from .errors import Misconfigured
from .observer import Observer
from .step import Step


class BaseRetry(ABC):
    """The attempt engine of the retry axis - how many tries a single step's write (apply or prune) gets
    before its failure counts, with WHETHER a given failure earns the next try left abstract as `retryable`.

    The Reconciler calls the injected retry on the write callable before handing it to the dispatcher, so
    the attempts are spent inside the dispatcher's own unit of work, with no dispatcher aware of them - the
    exceptions are the decorators that MOVE the write, which hand the relocation to the carrier through
    Write.relay and get this same budget laid back around it (the thread bridge, the wire, the chaos axis). A
    failure reaches the OnError policy only once every attempt is spent, so retry layers UNDER the error
    policy: FailFast aborts on a step that failed all its tries, BestEffort records exactly one residual
    entry for it. Only the writes are wrapped. The read (assess) stays single-try, since the re-assessment
    is the proof of the run and a probe that needs retrying is reporting something worth seeing. An
    optional Backoff paces the attempts, the same Fixed and Exponential that pace Fixpoint passes. Retry(1)
    is the neutral single try that wraps nothing.

    A Cancelled raised by a step is never retried: it is a BaseException, so the attempt loop's own
    `except Exception` structurally cannot catch it - the abort propagates with no branch spent asking. The
    pacing awaits the event loop's own sleep off the pure delay(), never blocking a wave-mate, now that the
    engine is async native and the write is always awaited on the caller's loop.

    A REAL FAILURE ALREADY SEEN OUTRANKS A LATER DENIAL. It is the one cut-through this loop overrules.
    The permit is asked per attempt, so a pool that fills between two tries denies a later attempt of a write
    an earlier attempt already ran and broke - and a deferral says the write never ran, which is no longer
    available to describe that step. So the loop remembers the failure it caught and re-raises THAT when a
    Deferred escapes a later attempt of the same write. The LATEST one where two attempts broke differently,
    because it is the state the world was last left in, so a reader should not have to measure to find out. A denial with nothing broken behind it is untouched,
    which is what keeps a full pool a report rather than an abort under the default policy. A Skew is
    untouched too, since a write that may have LANDED is the more dangerous fact of the two.

    Built like every other engine-and-seam family, BaseLooping being the nearest kin: the attempt loop (the
    shared budget, the Cancelled cut-through) lives HERE and the entry point is final, so a policy cannot
    break the machinery it rides. The shipped @final leaf is Retry, which retries every failure. Subclass
    THIS base to retry only some (a transient ConnectionError, say) so a permanent failure reaches the
    OnError policy at once or to give a step its OWN budget by declining once its share is spent, which is
    how one injected retry serves a run whose steps do not deserve the same number of tries. The pace stays
    global, since one Backoff is shared by every attempt this retry paces.
    """

    def __init__(self, attempts: int, *, backoff: Backoff | None = None):
        if attempts < 1:
            raise Misconfigured(f"{self.__class__.__name__} attempts must be >= 1, got {attempts}")
        self.__attempts = attempts
        self.__backoff = backoff

    @abstractmethod
    def retryable(self, step: Step, attempt: int, error: Exception) -> bool:
        # The seam - is this write failure worth another try? Asked between attempts, never about a
        # Cancelled (a BaseException cannot enter the attempt loops' except at all).
        #
        # The three arguments are exactly the triple Observer.retried announces, in the same order, because
        # they are the same event asked and told: WHICH step failed, how many of its attempts have gone and
        # what it raised. That is what lets one retry serve a whole run without one budget having to fit
        # every step - declining at `attempt` caps the spend for THIS step alone and no pause is paid for
        # the attempt that was cut, since the decline re-raises before the backoff. Construct the retry with
        # the largest budget any step should have and let the seam spend less where less is right.
        ...

    @final
    def __call__(self, do: Callable[[Step, Artifacts], AsyncFlowOutcome], *,
                 observer: Observer | None = None) -> Callable[[Step, Artifacts], AsyncFlowOutcome]:
        # Wrap the per-step write callable in the attempt loop and hand back the wrapped form. The neutral
        # single try hands back do itself, so the default costs nothing. do carries the data-flow contract:
        # it takes the step and the inputs its prerequisites produced, then returns an outcome that is
        # awaited when the step handed back a coroutine and taken as-is otherwise.
        #
        # It takes the OBSERVER, not one hook plucked off it. Every other axis that announces something
        # takes the whole trace - the dispatcher does, with its Ledger firing stepped() through it - and this
        # one used to be handed `observer.retried` by the reconciler instead, which put the knowledge of
        # WHICH hook a retry fires in the composer rather than in the retry. Resolved once here.
        watching = observer or Observer()
        if self.__attempts == 1:
            return do

        async def retrying(step: Step, inputs: Artifacts) -> FlowOutcome:
            # One async loop, because the engine is one colour now. A write that raises synchronously on
            # the call (a connection setup dying before the coroutine is even built) and one that raises on
            # await both land in the same try and spend one attempt, so neither escapes the budget, the
            # retried hook or the pacing.
            #
            # `broke` is the real failure this write has ALREADY suffered, remembered across the attempts
            # for the one cut-through this loop is allowed to overrule, while the outer clause below is where
            # that is spent. It is not a spare copy of the last error - nothing else reads it.
            broke: Exception | None = None
            try:
                for stalled in range(1, self.__attempts):
                    try:
                        return await self.__settle(do(step, inputs))
                    except Exception as error:
                        broke = error   # this write HAS run and HAS broken, whatever a later attempt says
                        self.__caught(step, stalled, error, watching)   # cut through or announce the spend
                        await self.__rest(stalled)                      # then await the backoff, if any
                return await self.__settle(do(step, inputs))   # the last try, its failure propagates to OnError
            except Deferred:
                # A POOL THAT FILLED BETWEEN TWO ATTEMPTS MUST NOT ERASE WHAT THE STEP ALREADY DID. The
                # permit is asked per attempt, deliberately, so a later attempt can be denied one the first
                # attempt held - and Deferred is a BaseException, so it sails past the `except Exception`
                # above and became the step's whole fate. Both clauses of the sentence it carries were then
                # false. "The apply did not run" - it ran. "Nothing broke and nothing changed" - it broke,
                # and may have half-written before it did. So a denial may only describe a write that never
                # ran. Here one has, which is the narrow case this clause is for.
                #
                # With no earlier failure the denial is the honest fate and is re-raised untouched, which is
                # what keeps a momentarily full pool reporting a deferral under FailFast instead of aborting
                # the run. Only Deferred is overruled, never Skew - a skew means the write may have LANDED,
                # and that is the more dangerous fact of the two, so it keeps its own precedence. The
                # deferral is dropped from the chain rather than kept as context, because a traceback
                # closing on "nothing broke and nothing changed" beside the thing that broke is the same
                # lie in a longer form.
                if broke is None:
                    raise
                raise broke from None

        return retrying

    def __caught(self, step: Step, stalled: int, error: Exception, watching: Observer) -> None:
        # The failure handling the attempt loop leans on. A failure retryable() declines cuts through by
        # re-raising, so no further attempt is spent and no backoff is paced. Otherwise the spend is
        # announced before the loop awaits its pace, so a stalled run says why it waits. A Cancelled never
        # reaches here AT ALL: it is a BaseException, so the loop's `except Exception` cannot catch it - the
        # abort cut-through stopped being a branch and became structure.
        if not self.retryable(step, stalled, error):
            raise error
        watching.retried(step, stalled, error)

    async def __rest(self, stalled: int) -> None:
        # The pause between tries, if any, awaited on the event loop's own sleep off the pure delay(),
        # never blocking a wave-mate. `stalled` counts the consecutive failures so far, the same stall
        # count Fixpoint hands its backoff, so Retry and Fixpoint speak one vocabulary.
        if self.__backoff is not None:
            await asyncio.sleep(self.__backoff.delay(stalled))

    @staticmethod
    async def __settle(outcome: AsyncFlowOutcome) -> FlowOutcome:
        # One attempt's outcome - awaited when the step handed back a coroutine, taken as-is otherwise. A
        # step that answered the first call with a coroutine is free to answer a retry with a plain tuple -
        # the write contract allows both.
        if inspect.isawaitable(outcome):
            return await outcome
        return outcome


@final
class Retry(BaseRetry):
    """The shipped retry policy. Every failure earns the next attempt, until the budget is spent.

    Retrying everything is the honest default for a write whose failures are usually transient, which is
    why the family's ready leaf carries it: Retry(3) works as handed, while Retry(1) is the neutral single
    try the Reconciler resolves when none is injected. A failure that should NOT be paced through attempts
    that cannot help it - a permanent error, a step past its own share of the budget - is a policy, where a
    policy is a BaseRetry subclass saying so in retryable()."""

    def __init__(self, attempts: int, *, backoff: Backoff | None = None):
        # Declared rather than inherited, forwarding without adding a thing. The leaf is what a caller
        # actually writes - `Retry(3)`, `Retry(1, backoff=Jitter(Fixed(0.2)))` - so its whole surface reads
        # here instead of only in the base, where a reader arriving at the shipped policy has to go looking
        # for the arguments it takes. The budget guard stays in one place, above.
        super().__init__(attempts, backoff=backoff)

    @override
    def retryable(self, step: Step, attempt: int, error: Exception) -> bool:
        return True

