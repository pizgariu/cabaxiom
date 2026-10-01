"""Step - one reconciliation concern that owns its desired state, with reactive and unified hooks."""
from abc import ABC, ABCMeta
from collections.abc import AsyncIterator, Iterable
from typing import Any, final, override

from .drift import (
    Artifacts,
    Assessment,
    AsyncFlowAssessment,
    AsyncFlowOutcome,
    Drift,
    DriftItem,
    FlowAssessment,
    FlowOutcome,
)
from .errors import Identity, Malformed
from .lease import Permit
from .vocabulary import Vocabulary


class _Sealed(ABCMeta):
    """The freeze's clock. Construction runs whole, THEN the instance seals - one object.__setattr__
    in the metaclass's __call__, after the outermost __init__ has returned.

    A metaclass rather than an __init__ wrapper, for two reasons that were both bugs first. A wrapper
    installed per subclass sealed at the WRONG level - a derived __init__ calling super().__init__()
    was sealed by the super call and crashed on its own next assignment - so it needed a re-entrancy
    flag to find the outermost frame. __call__ IS the outermost frame, so the flag retires. And the
    wrapper occupied cls.__dict__["__init__"] at class-definition time, which made a later @dataclass
    decorator skip generating its own - a dataclass Step with a constructor field crashed on
    object.__init__ instead of taking the argument. The metaclass touches no __init__ at all, so the
    dataclass form works and every subclass keeps exactly the constructor it wrote."""

    @override
    def __call__(cls, *args: Any, **kwargs: Any) -> Any:
        instance = super().__call__(*args, **kwargs)
        object.__setattr__(instance, "_Step__frozen", True)
        return instance


class Step(ABC, metaclass=_Sealed):
    """One reconciliation concern that owns its desired state.

    assess() and apply() default to no-ops (not abstract), so a probe-only step overrides just
    assess(), a cleanup-only step just apply(). The kernel adds nothing domain-shaped here. Mode,
    registry and progress belong in a caller-side Step subclass.

    A STEP IS A DECLARATION, NOT A SESSION. Instances freeze the moment construction ends. What a
    step IS was decided when it was written. Everything it learns at runtime travels as artifacts
    through the run instead of accumulating on `self`. That is one rule bought three ways - a step
    cannot smuggle hidden state between passes (the class of bug the kernel refuses everywhere else),
    two passes over one step read the same declaration and a frozen step serialises, which is what
    lets a dispatcher hand it to a worker that does not share this process.

    The hook types are deliberately wide, so a domain override is never fighting the kernel. The
    read returns a FlowAssessment and the writes a FlowOutcome, both Sequence-based (list is
    invariant, so a domain's own list[MyDrift] would fail a list-typed override) and both admitting
    a coroutine - `async def apply()` and `async def assess()` are legal, typed overrides, awaited
    on the caller's event loop. A plain sync override is equally legal and is bridged by the
    dispatcher that runs it.
    """

    # --- THE CONTRACT ---

    # 1. BY CLASS
    # Step CLASSES this step expects to be ready before it runs. Soft edge - trusts the world if absent.
    # Class default, overridable per instance (self.expects = (Other,)).
    expects: tuple[type["Step"], ...] = ()

    # The HARD companion of `expects`. It demands the class is present in the run, raising if it is absent.
    requires: tuple[type["Step"], ...] = ()

    # Step CLASSES this step prepares the ground for. A soft, reversed edge - this step runs BEFORE the match.
    prepares: tuple[type["Step"], ...] = ()

    # The HARD companion of `prepares`. It runs before the match and mandates the match is in the run.
    mandates: tuple[type["Step"], ...] = ()

    # 2. BY LABEL (Capabilities)
    # Capabilities this step comes after, SOFTLY. Fanned to every present provider.
    wants: tuple[str, ...] = ()

    # The HARD companion of `wants`. It raises at resolution if no step provides the capability.
    demands: tuple[str, ...] = ()

    # Capabilities this step PROVIDES. Opaque labels decoupling dependencies from concrete classes.
    provides: frozenset[str] = frozenset()

    # Resources this step CONTENDS for. Opaque labels grouping steps that may never run concurrently.
    # This is a shape constraint, not a dependency edge.
    contends: frozenset[str] = frozenset()

    # 3. BY INSTANCE
    # Specific Step INSTANCES this step comes after, SOFTLY. Resolved alongside `expects`.
    uses: tuple["Step", ...] = ()

    # The HARD companion of `uses`. It demands that specific instance is in the run.
    needs: tuple["Step", ...] = ()

    # 4. DATA FLOW
    # Artifact keys this step PUTS in the dict its hooks return. The DATA plane, not the dependency plane -
    # declaring a key creates no edge and changes no order, because a step may well come after another for
    # reasons that carry no payload at all. What it buys is the guard below.
    produces: frozenset[str] = frozenset()

    # Artifact keys this step READS out of the `inputs` it is handed. Declaring them turns a silent runtime
    # hole into a refusal at resolution. The Ledger mounts a payload from a step's DIRECT prerequisites, so
    # a key nothing upstream produces arrives as an absent entry. The hook improvises on a default and the
    # run reports clean against a world assembled from nothing. `demand()` refuses that the moment
    # membership is final, which is where the dependency plane already refuses an absent `requires`.
    consumes: frozenset[str] = frozenset()

    # 5. METADATA
    # Opaque labels grouping this step along an axis orthogonal to its type (e.g., "prod", "destructive").
    tags: frozenset[str] = frozenset()

    # Capacities this step needs before it WRITES, granted by an injected Authority and re-asked per
    # attempt. Unlike `contends`, which is a seating rule inside one resolved partition in one process,
    # a Permit is a pool held outside every run, so two coordinators ask the same authority. A denial is a
    # reading rather than a wait - see cabaxiom.lease for why blocking was refused.
    leases: tuple["Permit", ...] = ()

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Vet the declaration CONTAINERS at class-definition time, the earliest and clearest place to
        # catch the classic forgotten comma - `expects = (Reactor)` is the class Reactor, not a one-tuple,
        # and would otherwise blow up deep in the kernel with a cryptic message. Each class-level edge slot
        # must be a tuple and `provides` must be a set of labels, never a string (a bare string iterates
        # into single characters - the silent kind of wrong). Element TYPES are checked later, per instance,
        # by the Graph's construction guard, which also covers the instance-level `uses` and `provides`.
        super().__init_subclass__(**kwargs)

        # THE FREEZE itself lives on the metaclass (_Sealed seals after the outermost construction),
        # so this hook carries no wrapper. It neither touches __init__ - which is what lets @dataclass
        # generate one - nor needs to find the outermost frame, because __call__ IS that frame.

        # IDENTITY IS THE DEPENDENCY CURRENCY, stated here because this is where it is enforced. Every
        # structure the kernel derives is keyed by step INSTANCE - `uses` names instances, the Graph's
        # tables hash them, a Transition's leaver set and a Succession's survivors match them - so two
        # steps that compare equal would silently collapse into ONE graph node and the run would be
        # refused blaming an Ordering that did nothing wrong. A hand-written __eq__ or __hash__ is
        # therefore refused where it is written. A decorator that rewrites them AFTER class creation
        # (dataclass with eq=True) escapes this hook, so the Graph re-checks at construction - the same
        # two-guard doctrine the declaration containers already follow.
        for dunder in ("__eq__", "__hash__"):
            if dunder in cls.__dict__ and cls.__dict__[dunder] is not None:
                raise Malformed(
                    f"{cls.__name__} defines {dunder}. A Step's identity IS the kernel's dependency "
                    f"addressing, so every derived structure is keyed by instance and value equality collapses "
                    f"two steps into one graph node. Put the value semantics on a field object instead, "
                    f"and let the step be the one thing that stays itself."
                )
        # (the container walk below reads the VOCABULARY, so a grown edge kind is vetted here with no
        # edit - the seventh enumeration site the registry retired, found by measuring, not by grep)
        for kind in Vocabulary.shipped():
            value = getattr(cls, kind.slot, ())   # a slot the class never mentions defaults clean
            if isinstance(value, tuple):
                continue
            entry = value.__name__ if isinstance(value, type) else repr(value) if isinstance(value, str) else None
            hint = f" A single entry still needs a trailing comma - write {kind.slot} = ({entry},)." if entry else ""
            raise Malformed(f"{cls.__name__}.{kind.slot} must be a tuple, got {value.__class__.__name__}.{hint}")
        for slot, noun in (("provides", "capability labels"), ("contends", "resource labels"),
                           ("produces", "artifact keys"), ("consumes", "artifact keys")):
            declared = getattr(cls, slot)
            if isinstance(declared, str):
                raise Malformed(
                    f"{cls.__name__}.{slot} must be a set of {noun}, got the string {declared!r}. "
                    f"Wrap it - {slot} = frozenset({{{declared!r}}})."
                )

    # The declaration slots stay assignable after construction, because they are DECLARATIONS, not runtime
    # state. Every docstring above promises a slot is "overridable per instance". A run reads them once
    # when the Reconciler resolves, before anything executes - so setting `step.uses = (other,)` on a built
    # step is configuration a worker would receive intact, never state hidden mid-run. Everything else is
    # sealed.
    _SLOTS = frozenset({
        "expects", "requires", "prepares", "mandates",
        "wants", "demands", "provides", "contends", "leases",
        "uses", "needs", "tags", "produces", "consumes"
    })

    @staticmethod
    def labelled(steps: Iterable["Step"]) -> dict["Step", str]:
        """Per-instance run labels for a set of steps, in the order given. A kind's first instance keeps the
        bare type name and later ones are numbered (`Directory`, `Directory#2`), so a duplicate-free set
        reads exactly as type names while two instances of one kind never collide into one name.

        ONE home, on the class that owns what a step IS, because these labels are read ACROSS citizens. An
        Indictment names the accused, an Explanation names the run, a Casualty marks it, a Severance paths
        it and a Diagram paints it. Minted separately they diverged - the reconciler tallied in RUN order
        and an isolation in SUPPLIED order, so the same string meant a different step in each. An
        operator painting an indictment's accused onto a drawing reddened the innocent one. Order is the
        caller's, because it is the only thing that legitimately differs. Pass the steps in the order the
        reader will see them."""
        tally: dict[str, int] = {}
        labels: dict["Step", str] = {}
        for step in steps:
            name = Step.named(step)
            count = tally[name] = tally.get(name, 0) + 1
            labels[step] = name if count == 1 else f"{name}#{count}"
        return labels

    @property
    def identifier(self) -> str | None:
        """What this step calls ITSELF. None means it is named by its kind, which is what a class-shaped step is.

        The seam exists for steps a HUMAN did not write. A class name identifies a step perfectly while every
        step in a run is a distinct class, which is the shape a hand-written declaration takes. It stops
        identifying anything the moment a run holds five instances of one generic class - a graph assembled
        from data, a step minted per row, a fan built in a loop - because then every sentence about any of
        them reads the same, while `#2` says only that the labeller met it second."""
        return None

    @staticmethod
    def paired(previous: Iterable["Step"], desired: Iterable["Step"]) -> dict["Step", "Step"]:
        """Which step of DESIRED continues which step of PREVIOUS. The correspondence two declarations have
        across a change. This is its ONE home, because two citizens read it and a delta that disagreed
        with the teardown it precedes would be worse than no delta at all.

        Keyed by the DESIRED step, since every reader walks the successor and asks what each of its steps used
        to be. A desired step absent from the map is a JOINER and a previous step absent from the values is a
        LEAVER, which is the whole difference a stateless transition needs.

        Two steps correspond when they are the SAME OBJECT or when both name themselves and the names agree.
        Object identity is the older rule and stays the fallback, so every declaration written before identifiers
        existed pairs exactly as it always did. An identifier is what makes an answer possible AT ALL for a
        declaration assembled from data, where the successor is a fresh object on every build and instance
        identity has nothing left to compare.

        WHAT THIS ANSWERS AND WHAT IT REFUSES TO JUDGE. An unnamed step rebuilt as a fresh object cannot be
        recognised. That reads here exactly as a step that genuinely left, because from two declarations
        alone THE TWO ARE THE SAME PICTURE. A full swap of one kind for another instance of it is an ordinary
        transition (blue for green, one directory for the next) and refusing it to catch a rebuild would break
        the commoner case to guard the rarer one. So this answers the correspondence and nothing more. The
        suspicion is raised where a reader asks for an opinion rather than an action, in Rift.estranged.
        Only an ambiguity that cannot be anything but a mistake is refused below."""
        previous, desired = tuple(previous), tuple(desired)
        Step.__solitary(previous, "previous")
        Step.__solitary(desired, "desired")
        named = {step.identifier: step for step in previous if step.identifier is not None}
        held = set(previous)
        paired: dict["Step", "Step"] = {}
        for step in desired:
            if step in held:
                paired[step] = step
            elif step.identifier is not None and step.identifier in named:
                paired[step] = named[step.identifier]
        return paired

    @staticmethod
    def __solitary(declaration: tuple["Step", ...], side: str) -> None:
        # An identifier is a NAME, so it identifies one step within one declaration the way a class name
        # identifies one class within a module. Two steps answering the same name make the correspondence
        # above ambiguous. An ambiguous pairing would silently pick whichever came second.
        seen: dict[str, "Step"] = {}
        for step in declaration:
            identifier = step.identifier
            if identifier is None:
                continue
            if identifier in seen:
                raise Identity(
                    f"Two steps in the {side} declaration both call themselves {identifier!r} "
                    f"({seen[identifier].__class__.__name__} and {step.__class__.__name__}), so nothing can say "
                    f"which one a successor continues. An identifier names a step across runs, so it is unique "
                    f"within a declaration."
                )
            seen[identifier] = step

    @staticmethod
    def named(step: "Step") -> str:
        """One step's name, ignoring the run. Its own if it declares one, its kind's otherwise.

        The singular sibling of labelled() and the ONE home for the question "what do I call this step in a
        sentence". It exists because the answer was previously spelled `step.__class__.__name__` at every
        site that wrote a sentence, which is how the Ledger came to say `Directory` for two different steps
        while a Diagram of the same run said `Directory` and `Directory#2`.

        Every sentence in the kernel reads it. The Ledger's fates and blocks, the Graph's declaration
        refusals, the shape guards in Partition and Arranger, the Ordering's cycle path, the logging
        Observer plus the reprs of Match, Stamp and Shift. One site deliberately does NOT - the refusal
        for two instances that compare EQUAL names the CLASS, because that message diagnoses a bad
        __eq__ and the fix is a class-level one."""
        return step.identifier or step.__class__.__name__

    def __setattr__(self, key: str, value: Any) -> None:
        # The freeze's teeth. Construction assigns freely, the metaclass seals the instance the moment
        # it ends. After that only a declaration slot may still be set - anything else is
        # refused with the reason and the sanctioned channel. Runtime state is not banned, it is ROUTED:
        # artifacts travel with the run, where two passes cannot read each other's leftovers and a worker
        # on another machine reads exactly what this one would.
        if getattr(self, "_Step__frozen", False) and key not in Step._SLOTS:
            raise TypeError(
                f"{self.__class__.__name__} is frozen. A step is a declaration, so mutating one after "
                f"construction is how state hides between passes. A declaration slot ({', '.join(sorted(Step._SLOTS))}) "
                f"stays settable. For anything else, hand runtime state to the run - return it as artifacts, "
                f"and read what your dependencies produced from `inputs`."
            )
        super().__setattr__(key, value)

    async def watch(self) -> AsyncIterator[None]:
        # The empty event source. A step that overrides nothing never announces its world, so a watch()
        # loop over it converges once and then sleeps. The yield below exists only to make this function
        # an async GENERATOR - the loop body running would break the contract, so the line is excluded
        # from the coverage gate rather than pretended reachable.
        _nothing: tuple[None, ...] = ()
        for _never in _nothing:
            yield _never   # pragma: no cover - the empty source's whole point

    def assess(self, inputs: Artifacts) -> AsyncFlowAssessment:
        return self.verified()

    def apply(self, inputs: Artifacts) -> AsyncFlowOutcome:
        return self.unchanged()

    def prune(self, inputs: Artifacts) -> AsyncFlowOutcome:
        return self.unchanged()

    # --- WHAT A HOOK HANDS BACK ---
    #
    # Four named constructors for the two return shapes above, so a hook states what it FOUND or what it
    # DID instead of assembling the record that carries the answer. The ceremony they replace was the most
    # repeated line in this repository - a record, a keyword, a list, an item and a trailing empty dict,
    # spelled 176 times, to say "nothing is out of desired state".
    #
    # They are METHODS on the declaration rather than helpers beside it. That is the whole point. A
    # subclass inherits them, so `return self.verified()` needs no import at all and a first declaration
    # never has to meet Assessment or DriftItem to say a file is missing. Those two are the kernel's
    # CARRIERS. A carrier is not the first thing a domain should have to learn. They stay public and
    # unchanged for the caller who wants to build one by hand - the two sites in this repository that set
    # more than one Assessment channel do exactly that. A fluent builder for two sites out of a hundred
    # and sixty-six would be machinery bought for nobody.

    @final
    def verified(self, *, produced: Artifacts | None = None) -> FlowAssessment:
        """A read that found nothing out of desired state - the kernel's founding sentence, in one call.

        EMPTY MEANS VERIFIED is the axiom this whole engine rests on, so the way to say it is one word and
        not a record with an empty channel in it. `produced` carries what this read wrote to the data plane
        for its dependents. It defaults to nothing, because the overwhelming majority of reads produce
        none - a step that declares `produces` passes them here."""
        return Assessment(), produced or {}

    @final
    def drifted(self, *found: str | Drift, produced: Artifacts | None = None) -> FlowAssessment:
        """A read that found something out of desired state, named by this step unless told otherwise.

        A bare string is THIS step's own report and is named through named(), because the name written at
        those call sites was overwhelmingly `self.__class__.__name__` - a declaration that already knows
        what it is called should not be asked for it a second time. Asking is how one run came to say
        `Directory` for two different steps. Pass a Drift instead wherever the subject is not the step and
        pass several to report several.

        Found nothing? Then this returns exactly what verified() does, which is not a loophole but the
        axiom holding. A hook that spreads a computed sequence in here says the truth at both lengths."""
        return Assessment(deviation=self.__reported(found)), produced or {}

    @final
    def unchanged(self, *, produced: Artifacts | None = None) -> FlowOutcome:
        """A write that ran and had nothing to change - the clean no-op, the commonest write there is.

        Distinct from a write that never ran, which is a Deferred and not a return value at all. This one
        reached the world, looked and found it already right."""
        return None, produced or {}

    @final
    def changed(self, *made: str | Drift, produced: Artifacts | None = None) -> FlowOutcome:
        """A write that changed something, named by this step unless told otherwise - drifted()'s twin.

        Same naming rule, same spread rule. Reporting nothing lands where unchanged() does, since the
        kernel already reads a write's report as `changes or ()` and has never told the two apart."""
        return self.__reported(made), produced or {}

    def __reported(self, told: tuple[str | Drift, ...]) -> tuple[Drift, ...]:
        # The one place a bare message becomes a carrier. Anything that is not a string is already a Drift
        # and passes through untouched, which is what keeps a domain's own richer item first-class here -
        # the kernel reads a drift through two fields and never cares which class exposed them.
        return tuple(DriftItem(Step.named(self), one) if isinstance(one, str) else one for one in told)
