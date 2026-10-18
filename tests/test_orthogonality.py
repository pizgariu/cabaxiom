"""The cross-product harness. A random declaration crossed with a random AXIS CONFIGURATION, so the ten
injected axes are proved to decide HOW a run happens and never WHAT it leaves behind.

The suite had two halves that never met. test_equivalence.py compares three dispatchers over ONE
hand-written declaration with every other axis defaulted, while test_properties.py generates random DAGs and
then drives them with the defaults only. Both bugs this family has shipped lived exactly in that gap -
ThreadDispatcher under Retry(n larger than 1) handed asyncio.to_thread an unawaited coroutine so apply()
never ran at all. ThreadDispatcher.probe mangled an async read the same way one release later - because
no test had ever put two CHOSEN axes in one Reconciler. This file crosses them.

The strongest line in the file is the world assertion. It is read off the mutable object the steps share,
not off anything the run says about itself, because both bugs above reported every channel perfectly and
left an EMPTY WORLD behind.
"""
import asyncio
import inspect
import itertools
import logging
import threading
import unittest
from types import MappingProxyType
from typing import NamedTuple

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from cabaxiom import (
    DFS,
    AllOf,
    AnyOf,
    Assessment,
    Authority,
    Budget,
    Cancellation,
    Cancelled,
    Ceiling,
    Chains,
    Charter,
    Chorus,
    Components,
    Deadline,
    Dispatcher,
    DriftItem,
    Every,
    Exponential,
    Fibonacci,
    Fixed,
    Fixpoint,
    Flag,
    Jitter,
    Journal,
    Kahn,
    Ledger,
    Linear,
    Local,
    Logging,
    Majority,
    Observer,
    Once,
    OnError,
    Only,
    Overlap,
    Parallel,
    Permit,
    Priority,
    Quorum,
    Reading,
    Reconciler,
    Retry,
    RunMode,
    Shrinking,
    Some,
    Step,
    Supervised,
    ThreadDispatcher,
    Timing,
    Walk,
    Warrant,
    WithEveryTag,
    WithTag,
)
from cabaxiom.laboratory import ChaosDispatcher, Sabotage


class _Custom(Dispatcher):
    """The shared half of the two custom dispatchers below - their READ fan, which is identical.

    Both walk their groups one step at a time on the read side, so the probe lives here once instead of
    twice. Never instantiated (it declares no `overlaps`, which the dispatcher base refuses at construction
    for exactly that reason) and it holds no shape of its own - each leaf composes its own arranger and
    answers for it."""

    async def probe(self, groups, graph, read, cancellation, observer):
        # Mounted through the Ledger's one merge, exactly as the wave fan does it, so the read side and the
        # write side cannot disagree about what a step is handed - and the reads are taken in resolved order,
        # so the deviations flatten as they do everywhere else. The read ANNOUNCES each step through
        # dispatching, as every shipped dispatcher does, which is what keeps the trace orthogonal. This
        # harness exists to prove every dispatcher tells the observer the same story, so a custom one that
        # stayed silent on the read side would be telling a shorter one.
        produced = {}
        found = {"deviation": [], "plan": [], "advisory": [], "footprint": []}
        for leg in groups:
            for step in leg:
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                mounted = Ledger.mounted(step, graph.dependencies(step), produced)
                observer.dispatching(step, MappingProxyType(mounted))
                answer = read(step, mounted)
                assessment, artifacts = await answer if inspect.isawaitable(answer) else answer
                produced[step] = artifacts
                for channel, items in found.items():
                    items.extend(getattr(assessment, channel))
        return Reading(found["deviation"], produced, found["plan"], found["advisory"], found["footprint"])


class _Serial(_Custom):
    """A serial dispatcher composing the public Walk arranger, because without one two axes are
    unreachable and the cross-product would be a claim about eight.

    The Waves arranger REFUSES an Ordering that yields no waves, while DFS, Priority and Components all fall
    back to one flat group - so every shipped dispatcher can only ever be handed Kahn, so the arranger
    axis has no second value at all inside the kernel. This is the trivial custom dispatcher the Walk
    docstring points at, walking its legs one step at a time through the ONE Ledger, so it inherits the
    kernel's whole failure semantics and its data-flow rather than re-deriving either. It asks blocked()
    per step instead of admit() per wave, which is the correct gate for a shape where a dependency may
    share a group with its dependent."""

    overlaps = Overlap.NEITHER

    def __init__(self, on_error=OnError.FailFast):
        super().__init__(on_error)

    async def execute(self, groups, graph, do, cancellation, observer):
        attempt = self._attempt(do)
        ledger = self._ledger(groups, observer, graph)
        for leg in groups:
            for step in leg:
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                if ledger.blocked(step):
                    continue
                mounted = ledger.assemble(step)
                observer.dispatching(step, MappingProxyType(mounted))
                ledger.record(*await attempt((step, mounted)))
        return ledger.outcome()


class _Chained(_Custom):
    """A dispatcher that really RUNS the Chains arranger - each chain in series, the chains concurrently.

    Chains is the third shipped shape and NOTHING had ever walked one. It builds a ChainsPartition, that
    partition's placement rule is verified, so the only dispatcher in the tree that composed it (the chain
    runner in test_pipeline) has stub verbs that never execute - so an entire arranger was shaped, guarded
    and never driven. This drives it, which is what puts a third value on the arranger axis and makes the
    shape's ACROSS overlap a fact rather than a declaration.

    Serial within a chain and concurrent between them is the exact mirror of a wave, so it is the one shape
    where a step may sit in the same group as its own prerequisite. That is why it records as it walks
    rather than gathering at the end - a dependent inside a chain has to read what the step before it
    produced, so a gathered chain would mount an empty payload."""

    overlaps = Overlap.ACROSS

    def __init__(self, on_error=OnError.FailFast):
        super().__init__(on_error)

    async def execute(self, groups, graph, do, cancellation, observer):
        attempt = self._attempt(do)
        ledger = self._ledger(groups, observer, graph)

        async def chain(legs):
            for step in legs:
                if cancellation.cancelled():
                    raise Cancelled.by(cancellation)
                if ledger.blocked(step):
                    continue
                mounted = ledger.assemble(step)
                observer.dispatching(step, MappingProxyType(mounted))
                ledger.record(*await attempt((step, mounted)))

        async with asyncio.TaskGroup() as group:
            for legs in groups:
                group.create_task(chain(legs))
        return ledger.outcome()


class _World:
    """The mutable ground truth the generated steps share and the only place per-run state may live.

    A Step seals when construction ends, so nothing a run learns may accumulate on `self`. Every node
    holds this object instead, minted fresh for every axis configuration, because a second
    configuration handed the first one's world would start from an already-written state and prove
    nothing.

    The counter is an itertools.count, not an integer field. ThreadDispatcher runs a whole wave of applies
    on worker threads at once, where next() on a count is one C call where `self.at += 1` is a read, an add
    and a write. A lost tick there would make the edge assertion lie about the very thing it exists to
    check."""

    def __init__(self):
        self.written = {}    # THE ground truth - what the steps actually did to the world they share
        self.spans = {}      # node name -> one (entered, left) pair per COMPLETED apply
        self.broken = set()  # the one failure the transient node is allowed per run
        self.__clock = itertools.count(1)

    def tick(self):
        return next(self.__clock)


class _Node(Step):
    """The shared body of every generated node - level-triggered and honest about its own run order.

    assess() reads the world the step holds, so a written node re-probes clean and a converge under
    Fixpoint(3) settles after the pass that wrote instead of writing three times. That is what makes the
    applied channel a count of CHANGES rather than a count of passes.

    apply() stamps the sequence number it entered on and the one it left on, stamping them ONLY once the
    write has completed - so the transient node's lost first attempt leaves no span, every node ends with
    exactly one span per pass, so the edge comparison can index the two lists against each other."""

    seeded = None   # what the world already holds for this node before the run starts
    # Carried by EVERY node, so the neutral scopes have a tag to select the whole membership by. A scope
    # that selects everything is the only kind that belongs in an equivalence set, since without a tag the
    # tag-shaped scopes could not be reached at all.
    tags = frozenset({"every", "node"})

    def __init__(self, world, name, tokens=()):
        self._world = world
        self._name = name
        self._tokens = tokens   # the artifact keys this node's producing prerequisites owe it

    def assess(self, inputs):
        # All four channels answered, not just the deviation. A Ceiling judges scale per channel and a
        # Charter is handed the whole Reading, so a node that answered one channel would let both warrants
        # pass by having nothing to weigh.
        return Assessment(deviation=self._deviation(), plan=[DriftItem(self._name, "would write")],
                          footprint=[DriftItem(self._name, "owned")]), {}

    def _deviation(self):
        return [] if self._name in self._world.written else [DriftItem(self._name, "absent")]

    def apply(self, inputs):
        entered = self._world.tick()
        outcome = self._write(inputs)
        self._world.spans[self._name].append((entered, self._world.tick()))
        return outcome

    def prune(self, inputs):
        # The teardown twin, so ONE generated declaration drives both write verbs. It removes exactly its
        # own mark, which makes "the world is empty afterwards" the absolute reading for a prune the way
        # "the world holds every writer's mark" is the absolute reading for a converge.
        self._world.written.pop(self._name, None)
        return None, self._produce()

    def _write(self, inputs):
        # A node already at desired state reports NOTHING. A no-op that still reported would turn the
        # applied bag into a pass counter, so Once and Fixpoint(3) would disagree by design.
        if self._name in self._world.written:
            return None, self._produce()
        self._world.written[self._name] = "created"
        return [DriftItem(self._name, "created")], self._produce()

    def _produce(self):
        return {}


class _Drifts(_Node):
    """The ordinary case - drifted until written, settled for good afterwards. The base's own behaviour,
    named so the character table reads as six characters rather than five and a default."""


class _Settled(_Node):
    """Already at desired state before the run, so its apply must be a no-op.

    The world carries its mark from the mint and nothing may overwrite it. A run that re-wrote a settled
    node shows up twice - the value turns from `settled` into `created` and the applied bag grows an entry
    nobody asked for."""

    seeded = "settled"


class _Produces(_Node):
    """Hands an artifact to its dependents, on EVERY pass and not only on the pass that wrote.

    The produced map is a photograph of the last pass rather than an accumulator, so a producer that
    answered its token once and then went quiet would starve a reader in pass two while the run still
    reported clean."""

    def _produce(self):
        return {f"{self._name}/token": self._name}


class _Reads(_Node):
    """Reads what its producing prerequisites handed it and refuses to pretend when the payload is absent.

    The data-flow is the half of a run no reported channel can vouch for, so this node raises rather than
    shrugging. A missing token means the ordering, the shape or the mounting lost an artifact, where a raise
    turns that into a red test where a quiet no-op would turn it into a green one."""

    def _write(self, inputs):
        owed = tuple(token for token in self._tokens if token not in inputs)
        if owed:
            raise RuntimeError(f"{self._name} was handed {sorted(inputs)} and its prerequisites owed it {sorted(owed)}")
        return super()._write(inputs)


class _Reports(_Node):
    """Report-only, so the residual is legitimately non-empty and the comparison covers a dirty outcome as
    well as a clean one. Nothing the kernel can do clears it and its apply writes nothing at all."""

    def _deviation(self):
        return [DriftItem(self._name, "still wrong")]

    def _write(self, inputs):
        return None, {}


class _Transient(_Node):
    """Loses its FIRST attempt of the run and then behaves, which is what gives the retry axis something to
    be an axis about.

    Deterministic on purpose. This is the trap the whole file turns on. A node that failed at random
    would make two axis configurations legitimately disagree and the comparison would flap, so the one
    permitted failure is spent against the world - fresh per configuration - and never against a coin."""

    def _write(self, inputs):
        if self._name not in self._world.broken:
            self._world.broken.add(self._name)
            raise RuntimeError(f"{self._name} lost its first attempt of the run")
        return super()._write(inputs)


class _Awaits(_Node):
    """The other COLOUR. Every verb wears `async def`, which is the legal typed override the whole
    dispatcher family claims to tolerate on both sides of the run.

    THE TABLE HAD NO ASYNC NODE AT ALL. The history says exactly why that mattered. The second bug this
    family shipped was ThreadDispatcher.probe handing an async assess() back unawaited, while the first was
    the write side of the same mistake - so a generator whose every node is synchronous is thin in precisely
    the place both failures lived. A blocking node reaches to_thread and returns its outcome directly, never
    touching the bridge's await, so only an async one proves the bridge carries both colours."""

    async def assess(self, inputs):
        await asyncio.sleep(0)   # a real suspension, so the step genuinely leaves and re-enters the loop
        return _Node.assess(self, inputs)

    async def apply(self, inputs):
        await asyncio.sleep(0)
        return _Node.apply(self, inputs)

    async def prune(self, inputs):
        await asyncio.sleep(0)
        return _Node.prune(self, inputs)


class _AwaitsProducing(_Awaits):
    """An async node that also hands an artifact down, so the data-flow crosses a suspension point rather
    than only ever being produced and read inside one synchronous call."""

    def _produce(self):
        return {f"{self._name}/token": self._name}


class _HalfAwaits(_Node):
    """One verb each colour on ONE step, because a wrapper that assumes a step is uniformly one colour
    passes a table where every node is consistent. Its read suspends and its write does not."""

    async def assess(self, inputs):
        await asyncio.sleep(0)
        return _Node.assess(self, inputs)


# The character table. Every node draws one of these rather than every node being identical, because a DAG
# of six clones exercises the ordering and nothing else.
_CHARACTERS = {
    "drifts": _Drifts,
    "settled": _Settled,
    "produces": _Produces,
    "reads": _Reads,
    "reports": _Reports,
    "transient": _Transient,
    "awaits": _Awaits,
    "awaits-produces": _AwaitsProducing,
    "half-awaits": _HalfAwaits,
}

# The characters whose apply MUST have left a mark in the world by the time the run ends.
_WRITES = ("drifts", "produces", "reads", "transient", "awaits", "awaits-produces", "half-awaits")

# The characters that hand an artifact to their dependents, whichever colour they wear.
_PRODUCERS = ("produces", "awaits-produces")

# The widest DAG generated, with the pool sized to match it. A permit pool as wide as the largest wave a
# declaration can fan is what keeps a PERMISSIVE authority permissive - one slot short and the axis would
# quietly become a second cancellation, denying a write and changing the outcome it is here not to change.
_MAX_NODES = 6
_LEASES = (Permit("orthogonality", _MAX_NODES),)
# The consenting Ceiling's bound, set to the widest reading a declaration can answer rather than to
# something comfortably enormous. Every node answers exactly one footprint item, so this consents to every
# generated declaration and refuses the first one that grows past the table - a bound nobody could reach is
# a bound that proves the channel is counted at all.
_CEILING = _MAX_NODES

# The logger the Logging observer on the axis writes to. It is NOT the kernel's default "cabaxiom" one.
# Logging emits a WARNING per retried attempt and this file's transient node earns one on nearly every
# example - so pointed at the default name a single run pushes thousands of lines into whatever logging tree
# the host has configured, while pytest only hides them because its own capture happens to be in the way.
# Handing over a ready Logger is the seam Logging documents for exactly this, so propagate stays off and
# nothing reaches a root handler either. The observer is still fully exercised - it formats and emits every
# hook, the records just land in a sink instead of on somebody's terminal.
_QUIET = logging.getLogger(f"{__name__}.observed")
_QUIET.addHandler(logging.NullHandler())
_QUIET.propagate = False


class _Declaration:
    """One generated declaration plus the minting discipline every configuration depends on.

    MINTED FRESH per configuration, the CLASSES included. `expects` addresses step classes and the Graph
    keys its rosters by exact type, so each node needs a class of its own - and a second configuration
    handed the first one's instances would read a world that had already been written, which is the
    discipline test_equivalence._declaration already keeps by hand."""

    def __init__(self, edges, characters):
        self.edges = edges
        self.characters = characters

    @property
    def writing(self):
        # The nodes whose mark in the world is the absolute reading, not a relative one.
        return tuple(f"S{index}" for index, character in enumerate(self.characters) if character in _WRITES)

    @property
    def presettled(self):
        # The nodes the world already satisfied, whose mark must survive the run exactly as it was.
        return tuple(f"S{index}" for index, character in enumerate(self.characters) if character == "settled")

    @property
    def classes(self):
        # The classes the LAST mint built, for the scopes that address step types. A scope naming a class
        # from an earlier mint would name a type with no step in the run, which the scope family refuses at
        # construction - so this is read straight after the mint it belongs to and never cached across one.
        return self.__minted

    def mint(self):
        world = _World()
        classes = []
        for index, deps in enumerate(self.edges):
            base = _CHARACTERS[self.characters[index]]
            classes.append(type(f"S{index}", (base,), {
                "expects": tuple(classes[dep] for dep in deps),
                "leases": _LEASES,
            }))
        steps = []
        for index, minted in enumerate(classes):
            name = f"S{index}"
            world.spans[name] = []
            if minted.seeded is not None:
                world.written[name] = minted.seeded
            owed = tuple(f"S{dep}/token" for dep in self.edges[index] if self.characters[dep] in _PRODUCERS)
            steps.append(minted(world, name, owed))
        self.__minted = tuple(classes)
        return tuple(steps), world


class _Axes(NamedTuple):
    """One point of the axis cross-product, as DATA.

    Hypothesis prints the drawn value when an example fails, so the minimal reproduction has to read as a
    line somebody can paste rather than as a row of object reprs. _Configured turns this into the live
    strategy objects, fresh every time."""

    runner: str
    ordering: str
    convergence: str
    passes: int
    attempts: int
    paced: str
    observer: str
    warrant: str
    authority: str
    on_error: str
    cancellation: str
    scope: str


class _Ticks:
    """A scripted monotonic clock, so a Budget spends an exact number of passes instead of racing a real
    one. Budget reads the clock once to fix its end and once per loop decision, so answering zero for the
    first `passes` reads and something enormous afterwards buys exactly `passes` passes."""

    def __init__(self, passes):
        self.__passes = passes
        self.__reads = 0

    def __call__(self):
        self.__reads += 1
        return 0.0 if self.__reads <= self.__passes else 1000.0


class _Consents(Warrant):
    """A warrant that READS every channel of the reading and then consents.

    An empty Charter consents by vacuity, which proves the composite relays nothing because it has nobody to
    relay to. This one is a real member with a real opinion and it touches all four channels, so a Charter
    holding several of them proves the reading reaches each member whole."""

    def assent(self, reading):
        # Reading all four is the point. A member handed a Reading that had lost its plan or its footprint on
        # the way through the composite would be indistinguishable from one that never looked.
        assert len(reading) >= 0 and len(reading.plan) >= 0
        assert len(reading.advisory) >= 0 and len(reading.footprint) >= 0
        return ()


class _Configured:
    """One drawn _Axes turned into live objects, with the Reconciler built over them.

    Everything is built FRESH here, the dispatchers included, because two configurations sharing a
    Deadline or a Local would let one run's state decide another's - which is the trap Deadline documents
    about itself."""

    _POLICIES = {"failfast": OnError.FailFast, "besteffort": OnError.BestEffort, "halt": OnError.Halt}
    _ORDERINGS = {"kahn": Kahn, "dfs": DFS, "priority": Priority, "components": Components}
    # Every shipped pace, each neutral at zero seconds. A backoff cannot change an outcome and CAN change
    # which frame a stall is counted in, so the whole family belongs on the axis while none of it may cost
    # the suite a real pause.
    _PACES = {
        "none": lambda: None,
        "fixed": lambda: Fixed(0.0),
        "exponential": lambda: Exponential(0.0, 0.0),
        "linear": lambda: Linear(0.0, 0.0),
        "fibonacci": lambda: Fibonacci(0.0, 0.0),
        "jitter": lambda: Jitter(Fixed(0.0)),
    }

    def __init__(self, axes, classes=()):
        self._axes = axes
        self._classes = classes   # the run's own step classes, for the scopes that address types

    def reconciler(self, steps):
        axes = self._axes
        return Reconciler(
            steps, self.__ordering(),
            mode=self.__mode(),
            convergence=self.__convergence(),
            retry=Retry(axes.attempts, backoff=self._PACES[axes.paced]()),
            cancellation=self.__cancellation(),
            observer=self.__observer(),
            warrant=self.__warrant(),
            authority=Local() if axes.authority == "local" else None,
            scope=self.__scope(),
        )

    def __ordering(self):
        chosen = self._axes.ordering
        if chosen == "priority":
            # A DOMAIN key, not the default class name, so the injected-key seam is on the axis too. The
            # reversed name is a deliberately different order from the default's and still a total one.
            return Priority(key=lambda step_class: step_class.__name__[::-1])
        return self._ORDERINGS[chosen]()

    def __mode(self):
        policy = self._POLICIES[self._axes.on_error]
        return {
            "parallel": lambda: Parallel(policy),
            "supervised": lambda: Supervised(policy),
            "threaded": lambda: ThreadDispatcher(Parallel(policy)),
            "threaded-supervised": lambda: ThreadDispatcher(Supervised(policy)),
            "chaos": lambda: ChaosDispatcher(Parallel(policy), Sabotage()),
            # The chaos decorator INSIDE the bridge, which is the order that keeps the bridge (see
            # DecoratorOrderKeepsTheBridge, where the order is pinned and the other one explained).
            "threaded-chaos": lambda: ThreadDispatcher(ChaosDispatcher(Parallel(policy), Sabotage())),
            "serial": lambda: RunMode(Walk(), _Serial(policy)),
            "threaded-serial": lambda: ThreadDispatcher(RunMode(Walk(), _Serial(policy))),
            "chaos-serial": lambda: ChaosDispatcher(RunMode(Walk(), _Serial(policy)), Sabotage()),
            "chained": lambda: RunMode(Chains(), _Chained(policy)),
            "threaded-chained": lambda: ThreadDispatcher(RunMode(Chains(), _Chained(policy))),
        }[self._axes.runner]()

    def __convergence(self):
        axes = self._axes
        return {
            "once": lambda: Once(),
            "fixpoint": lambda: Fixpoint(max_passes=axes.passes),
            "fixpoint-paced": lambda: Fixpoint(max_passes=axes.passes, backoff=Fixed(0.0)),
            "shrinking": lambda: Shrinking(max_passes=axes.passes),
            "budget": lambda: Budget(1.0, clock=_Ticks(axes.passes)),
            "budget-paced": lambda: Budget(1.0, backoff=Fixed(0.0), clock=_Ticks(axes.passes)),
        }[axes.convergence]()

    def __cancellation(self):
        # Every one of these is UNTRIPPED, which is what keeps the axis about how a run is watched rather
        # than about whether it finished. A firing cancellation has its own class below.
        return {
            "base": lambda: Cancellation(),
            "flag": lambda: Flag(),
            "deadline": lambda: Deadline(60.0),          # a budget no unit test can spend
            "allof": lambda: AllOf(Flag(), Flag()),      # needs both and neither ever fires
            "anyof": lambda: AnyOf(Flag(), Flag()),      # fires on either, so it is the strictest neutral
            "majority": lambda: Majority(Flag(), Flag(), Flag()),
            # A Quorum inside a Quorum, since the composite claims to nest and nothing nested one under a run.
            "nested": lambda: Quorum(AnyOf(Flag()), Quorum(Flag(), rule=Every()), rule=Some()),
        }[self._axes.cancellation]()

    def __observer(self):
        return {
            "silent": lambda: Observer(),
            "journal": lambda: Journal(),
            # A Chorus of four with a Chorus inside it, so the relay and the nesting are both on the axis -
            # and Timing takes a lock per unit hook while Logging formats per pass, which is the pairing an
            # observer axis is actually about.
            "chorus": lambda: Chorus(Journal(), Timing(), Logging(_QUIET), Chorus(Journal())),
        }[self._axes.observer]()

    def __warrant(self):
        return {
            "none": lambda: None,
            "charter": lambda: Charter(),      # no member, so it composes to consent
            "ceiling": lambda: Ceiling(),      # every channel unbounded, so it consents to everything
            # A Charter of SEVERAL real consenting members, nested, each of which reads the whole Reading.
            # An empty Charter consents by vacuity and proves nothing about relaying a reading to members.
            "charter-of-several": lambda: Charter(_Consents(), Ceiling(footprint=_CEILING), Charter(_Consents())),
        }[self._axes.warrant]()

    def __scope(self):
        # NEUTRAL scopes only. That is the whole reason the axis can be here. Scope narrows MEMBERSHIP,
        # so a narrowing scope legitimately converges less and cannot sit in a set asserting one outcome -
        # but a scope that selects the ENTIRE membership must leave the outcome alone, as each of these does
        # it by a different mechanism (by type, by any tag, by every tag) over a rebuilt Graph. That rebuild
        # is the thing worth crossing, since it is a second derivation the run then walks.
        if not self._classes:
            return None   # the empty declaration, where every named scope is ill-defined by construction
        return {
            "none": lambda: None,
            "only-every-class": lambda: Only(*self._classes),
            "with-tag": lambda: WithTag("every"),
            "with-every-tag": lambda: WithEveryTag("every", "node"),
        }[self._axes.scope]()


# The runners split by SHAPE, because the shape decides which orderings are legal. A wave-shaped dispatcher
# can only be handed Kahn (see _Serial), a walk-shaped one takes all four and a chain-shaped one needs the
# only Ordering that yields chains at all.
_WAVE_RUNNERS = ("parallel", "supervised", "threaded", "threaded-supervised", "chaos", "threaded-chaos")
_WALK_RUNNERS = ("serial", "threaded-serial", "chaos-serial")
_CHAIN_RUNNERS = ("chained", "threaded-chained")

# The reference configuration, every axis at its neutral value bar the retry. Retry(1) is out of the
# equivalence set on purpose (see AxisOrthogonality), so the reference spends two attempts like the rest.
_BASELINE = _Axes("parallel", "kahn", "once", 1, 2, "none", "silent", "none", "none", "failfast", "base", "none")


@st.composite
def declarations(draw, max_nodes=_MAX_NODES):
    # A random DAG, acyclic by construction the way test_properties builds one - node i may depend on any
    # subset of {0..i-1} - crossed with a per-node character, so no two nodes have to behave alike.
    nodes = draw(st.integers(min_value=0, max_value=max_nodes))
    edges = []
    for index in range(nodes):
        edges.append(tuple(sorted(draw(st.sets(st.integers(min_value=0, max_value=index - 1))) if index else set())))
    return tuple(edges), tuple(draw(st.sampled_from(tuple(_CHARACTERS))) for _ in range(nodes))


@st.composite
def configurations(draw):
    # One point of the cross-product. The SHAPE is drawn first and the ordering is drawn against it, not
    # beside it, because each fanning arranger refuses an Ordering that yields no groups of its own kind -
    # Waves refuses everything but Kahn, while Chains refuses everything but Components. Drawing the shape as
    # its own coin rather than reading it off a runner sampled from all eleven is what keeps the flat
    # orderings and the chain shape from being rare - measured at nine draws in four hundred the other way
    # round, which is not an axis, it is an anecdote.
    shape = draw(st.sampled_from(("waves", "walk", "chains")))
    if shape == "waves":
        runner, ordering = draw(st.sampled_from(_WAVE_RUNNERS)), "kahn"
    elif shape == "walk":
        runner = draw(st.sampled_from(_WALK_RUNNERS))
        ordering = draw(st.sampled_from(("kahn", "dfs", "priority", "components")))
    else:
        # Components is the ONE shipped Ordering that yields chains, so the chain shape has exactly one
        # legal partner and the pairing is a fact rather than a draw.
        runner, ordering = draw(st.sampled_from(_CHAIN_RUNNERS)), "components"
    return _Axes(
        runner=runner,
        ordering=ordering,
        convergence=draw(st.sampled_from(("once", "fixpoint", "fixpoint-paced", "shrinking", "budget", "budget-paced"))),
        passes=draw(st.integers(min_value=1, max_value=3)),
        attempts=draw(st.integers(min_value=2, max_value=3)),
        paced=draw(st.sampled_from(tuple(_Configured._PACES))),
        observer=draw(st.sampled_from(("silent", "journal", "chorus"))),
        warrant=draw(st.sampled_from(("none", "charter", "ceiling", "charter-of-several"))),
        authority=draw(st.sampled_from(("none", "local"))),
        on_error=draw(st.sampled_from(("failfast", "besteffort", "halt"))),
        cancellation=draw(st.sampled_from(("base", "flag", "deadline", "allof", "anyof", "majority", "nested"))),
        scope=draw(st.sampled_from(("none", "only-every-class", "with-tag", "with-every-tag"))),
    )


class _Outcome:
    """What ONE configuration left behind, reduced to the things no axis may change.

    Bags, not sequences, for everything the run REPORTS - which unit of a wave settles first is the
    dispatcher's own business and legitimately differs - and a plain mapping for the world, which is the
    one channel a run that reported beautifully and did nothing cannot fake."""

    def __init__(self, world, residual):
        self.world = dict(world.written)
        self.spans = {name: tuple(runs) for name, runs in world.spans.items()}
        self.residual = self.bagged(residual)
        self.applied = self.bagged(residual.applied)
        self.failures = self.bagged(residual.failures)
        self.produced = tuple(sorted(
            (Step.named(step), tuple(sorted(artifacts.items()))) for step, artifacts in residual.produced.items()))

    @staticmethod
    def bagged(items):
        # Sorted rather than a Counter so a failure prints readably, the habit test_equivalence keeps.
        return sorted((item.name, item.message) for item in items)


class AxisOrthogonality(unittest.IsolatedAsyncioTestCase):
    """Ten axes, ONE outcome. A declaration whose steps are level-triggered has exactly one correct
    result, while the axes choose the order, the concurrency, the pacing and the number of passes - never
    the result.

    THE BUG CLASS. Every failure this family has shipped was a PAIR of axes nobody had put in one
    Reconciler. ThreadDispatcher under Retry(n larger than 1) handed asyncio.to_thread an unawaited
    coroutine, so apply() never ran and the run reported clean over an empty world. ThreadDispatcher.probe
    mangled an async read the same way. Neither could have survived the world comparison below, which is
    read off the object the steps mutate rather than off anything the run says about itself.

    WHAT IS IN and why each one only changes HOW. Ordering (all four, reached through the shape that can
    take them, plus Priority with an injected domain key as well as its default). Dispatcher (Parallel,
    Supervised, ThreadDispatcher over any of them, the chaos decorator with a no-op adversary both inside
    and outside the bridge, the serial walk and the chain runner). Arranger (all three - Waves, Walk and
    Chains, each through the dispatcher that composes it). Colour (a synchronous node, an async node and a
    node wearing one colour per verb, because both shipped bugs were an async hook a wrapper mangled).
    Convergence (Once, Fixpoint with and without a pace, Shrinking, Budget on a scripted clock, paced and
    not). Retry (two and three attempts, against every shipped Backoff at zero seconds). A neutral
    cancellation that never fires (the base, an untripped Flag, a Deadline of a minute, plus the Some, Every
    and Most composites, one of them nested). An observer (silent, Journal and a Chorus of four with a
    Chorus inside it). A consenting warrant (an empty Charter, an unbounded Ceiling and a Charter of
    several real members that each read the whole Reading). A permissive authority (Local against a pool
    wide enough for every ask). A NEUTRAL scope, one per mechanism - by type, by any tag, by every tag -
    each of which selects the entire membership and so may not change a thing while still making the run
    walk a rebuilt Graph. And the error policy, all three, which is legitimate here because the one failure
    in the declaration is spent inside the retry and never reaches a policy at all.

    WHAT IS OUT, where each exclusion is a real outcome difference rather than a convenience. A NARROWING
    scope, because a narrowed run legitimately does less - only the scopes that select everything are here.
    A vetoing warrant, a denying authority and a firing cancellation each stop the run short - and each gets
    a class of its own below, because each is an invariant in its own right. An authority whose capacity
    BINDS is out for a subtler reason worth naming - a pool of one against a wave of three is granted three
    times over by a dispatcher whose write never suspends and twice deferred by one that does, so a binding
    capacity makes those two axes genuinely non-orthogonal, so the pool is sized to the widest wave
    instead. RemoteDispatcher pickles the step, so what a step may hold is a different question and a
    different builder's. And Retry(1) is out for the sharpest reason of the lot - the declaration contains a
    node that loses its first attempt, so a single-attempt run genuinely ends with a failed step and a
    smaller world. OneAttemptIsNotEnough below proves that boundary is real rather than assumed."""

    @settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.differing_executors])
    @given(declarations(), st.lists(configurations(), min_size=2, max_size=4))
    def test_every_axis_configuration_reaches_the_same_outcome(self, declared, drawn):
        # Hypothesis drives this synchronously, so each converge - a coroutine - runs to completion under
        # asyncio.run, the habit test_properties and test_stateful already keep. The configuration rides in
        # every message rather than in a subTest, because subTest reporting is disabled under @given anyway
        # and Hypothesis is the thing that shrinks and prints the falsifying example.
        plan = _Declaration(*declared)
        readings = [(axes, asyncio.run(self._settled(plan, axes))) for axes in (_BASELINE, *drawn)]
        reference = readings[0][1]
        for axes, outcome in readings:
            told = f"under {axes}"
            self.assertEqual(outcome.world, reference.world, told)         # 1, THE ground truth
            self.assertEqual(outcome.residual, reference.residual, told)   # 2, the proof set as a bag
            self.assertEqual(outcome.applied, reference.applied, told)     # 3, what the run says it changed
            self.assertEqual(outcome.produced, reference.produced, told)   # and the data-flow photograph
            self.assertEqual(outcome.failures, [], told)                   # nothing here fails past its retry
            self._ordered(plan, outcome, told)                             # 4, every declared edge
        # The ABSOLUTE reading. Three configurations agreeing on an empty world would satisfy every
        # comparison above and prove nothing at all, which is exactly how the thread bridge shipped broken.
        for name in plan.writing:
            self.assertEqual(reference.world.get(name), "created", f"{name} reported but wrote nothing")
        for name in plan.presettled:
            self.assertEqual(reference.world.get(name), "settled", f"{name} was already settled and was rewritten")

    async def _settled(self, plan, axes):
        # Steps minted fresh for THIS configuration, so it starts from an unwritten world. The classes are
        # read straight off that mint, because a scope addressing types has to name THIS run's classes.
        steps, world = plan.mint()
        return _Outcome(world, await _Configured(axes, plan.classes).reconciler(steps).converge())

    def _ordered(self, plan, outcome, told):
        # Every declared edge, pass by pass. A prerequisite's apply must have LEFT before its dependent's
        # ENTERED, which is the one thing a fanning dispatcher can get wrong while every reported channel
        # still comes out right. The two span lists index against each other because a node records a span
        # only when its write completed, so no lost attempt shifts the pairing.
        counted = {len(runs) for runs in outcome.spans.values()}
        if not counted:
            return   # the empty declaration, which is a legal DAG and has nothing to order
        self.assertEqual(len(counted), 1, f"the nodes disagree about how many passes ran over them {told}")
        for index, deps in enumerate(plan.edges):
            for dep in deps:
                for (_, left), (entered, _) in zip(outcome.spans[f"S{dep}"], outcome.spans[f"S{index}"]):
                    self.assertLess(left, entered, f"S{dep} had not finished when S{index} started {told}")


class TeardownOrthogonality(unittest.IsolatedAsyncioTestCase):
    """The SECOND write verb, crossed with the axes at all. prune() is converge's mirror and the whole
    cross-product above drives only converge, so half the write surface had never met a chosen axis.

    THE BUG CLASS is the one this family keeps shipping - a layer laid at the wrong depth by a decorator.
    Both write verbs reach the world through their own Write carrier, built one per phase, so a wrapper that
    gets the layering right for apply and wrong for prune would be invisible to every converge-shaped
    assertion in the tree. The thread bridge's own fix had to be verified on both verbs for exactly that
    reason, by hand, on one hand-written step.

    The absolute reading is the mirror of the converge one. Each node's prune removes exactly its own mark,
    so a teardown of the whole membership must leave an EMPTY world - and the world is FILLED first, so an
    empty result is a fact about the teardown rather than about what it started from."""

    @settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.differing_executors])
    @given(declarations(), st.lists(configurations(), min_size=2, max_size=3))
    def test_every_axis_configuration_tears_the_same_world_down(self, declared, drawn):
        plan = _Declaration(*declared)
        readings = []
        for axes in (_BASELINE, *drawn):
            steps, world = plan.mint()
            for name in plan.writing:
                world.written[name] = "created"
            residual = asyncio.run(_Configured(axes, plan.classes).reconciler(steps).prune())
            readings.append((axes, dict(world.written), _Outcome.bagged(residual.failures)))
        _, reference, broke = readings[0]
        for axes, left, failures in readings:
            told = f"under {axes}"
            self.assertEqual(left, reference, told)     # what the teardown actually removed
            self.assertEqual(failures, broke, told)     # and what it says broke on the way down
        # The ABSOLUTE reading, so configurations agreeing on a world nobody touched cannot pass as agreement.
        self.assertEqual(reference, {}, "a teardown of the whole membership left a mark behind")
        self.assertEqual(broke, [], "nothing in this declaration fails a teardown")


class TraceOrthogonality(unittest.IsolatedAsyncioTestCase):
    """The observer axis sees the SAME EVENTS whichever dispatcher ran the declaration. Everything above
    compares what a run LEFT BEHIND. This compares what it SAID while running.

    THE BUG CLASS is a whole channel no outcome assertion can reach. An observer is the only way a caller
    watches a long run. A dispatcher that skipped dispatching for one step, fired stepped twice for one
    unit or lost produced for a clean write would leave every residual, applied and world assertion in this
    file perfectly intact. The hooks are also where the two granularities meet - the pass hooks fire on the
    caller's coroutine and the unit hooks fire where the run RECORDS - so this pins the Observer docstring's
    own claim that even ThreadDispatcher records on the loop and only the hook itself leaves it.

    A BAG, not a sequence, for the same reason every other comparison here is one. Which unit of a wave
    settles first is the dispatcher's own business and legitimately differs."""

    class _Recorder(Observer):
        """Every hook as data, plus the thread each fired on. A trace that recorded from a worker thread
        would need a lock the kernel says no observer owes a shipped dispatcher."""

        def __init__(self):
            self.events = []
            self.threads = set()

        def __note(self, *event):
            self.events.append(event)
            self.threads.add(threading.get_ident())

        def began(self):
            self.__note("began")

        def acted(self, applied):
            self.__note("acted", len(applied))

        def remained(self, residual):
            self.__note("remained", len(residual))

        def dispatching(self, step, inputs):
            self.__note("dispatching", Step.named(step), tuple(sorted(inputs)))

        def stepped(self, step, changes, error):
            self.__note("stepped", Step.named(step), len(changes or ()), None if error is None else type(error).__name__)

        def produced(self, step, artifacts):
            self.__note("produced", Step.named(step), tuple(sorted(artifacts)))

        def retried(self, step, attempt, error):
            self.__note("retried", Step.named(step), attempt)

        def pruned(self, residual):
            self.__note("pruned", len(residual))

    # One of each character a trace can tell apart - a producer feeding a reader, the node that loses an
    # attempt (so retried is in the stream), a settled no-op and a report-only step.
    _SHAPE = (((), (0,), (1,), (), ()), ("produces", "reads", "transient", "settled", "reports"))

    def _runners(self):
        policy = OnError.FailFast
        return (
            ("Parallel", Parallel(policy), Kahn()),
            ("Supervised", Supervised(policy), Kahn()),
            ("ThreadDispatcher(Parallel)", ThreadDispatcher(Parallel(policy)), Kahn()),
            ("ThreadDispatcher(Supervised)", ThreadDispatcher(Supervised(policy)), Kahn()),
            ("ChaosDispatcher(Parallel)", ChaosDispatcher(Parallel(policy), Sabotage()), Kahn()),
            ("ThreadDispatcher(ChaosDispatcher)", ThreadDispatcher(ChaosDispatcher(Parallel(policy), Sabotage())), Kahn()),
            ("_Serial", RunMode(Walk(), _Serial(policy)), DFS()),
            ("ThreadDispatcher(_Serial)", ThreadDispatcher(RunMode(Walk(), _Serial(policy))), Priority()),
            ("_Chained", RunMode(Chains(), _Chained(policy)), Components()),
            ("ThreadDispatcher(_Chained)", ThreadDispatcher(RunMode(Chains(), _Chained(policy))), Components()),
        )

    async def _traced(self, verb, dispatcher, ordering):
        plan = _Declaration(*self._SHAPE)
        steps, _ = plan.mint()
        recorder = self._Recorder()
        reconciler = Reconciler(steps, ordering, mode=dispatcher, observer=recorder,
                                retry=Retry(2), authority=Local())
        await getattr(reconciler, verb)()
        return sorted(recorder.events), recorder.threads

    async def test_every_dispatcher_tells_the_observer_the_same_story(self):
        for verb in ("converge", "prune"):
            reference = None
            for name, dispatcher, ordering in self._runners():
                with self.subTest(verb=verb, mode=name):
                    events, threads = await self._traced(verb, dispatcher, ordering)
                    # Pinned first, so ten dispatchers agreeing on nothing cannot pass as ten agreeing.
                    self.assertGreater(len(events), 5, "the trace is too short to be comparing anything")
                    self.assertEqual(threads, {threading.get_ident()},
                                     "a hook fired off the caller's thread, which is a lock the kernel says "
                                     "no observer owes a shipped dispatcher")
                    if reference is None:
                        reference = events
                    self.assertEqual(events, reference)

    async def test_the_converge_trace_holds_every_hook_the_kernel_ships(self):
        # The reference stream itself, so the comparison above compares something KNOWN rather than whatever
        # the first runner happened to emit.
        events, _ = await self._traced("converge", Parallel(), Kahn())
        fired = {event[0] for event in events}
        self.assertEqual(fired, {"began", "acted", "remained", "dispatching", "stepped", "produced", "retried"})
        self.assertEqual(sum(1 for event in events if event[0] == "dispatching"), 10)   # 5 steps, announced on the write and on the proving read
        self.assertEqual(sum(1 for event in events if event[0] == "retried"), 1)


class ARefusalIsNotAPass(unittest.IsolatedAsyncioTestCase):
    """A refused run applied NOTHING and it has to say so through the observer as well as in the record.

    THE BUG CLASS, one that was live in the tree. The gate inside converge() returns before any pass
    happens, yet it fired remained() without ever firing acted() - so the two halves a trace pairs to close
    one pass arrived unmatched. Journal buffers what acted said and writes it out when remained arrives,
    which means ONE Journal reused across a written run and then a refused one recorded the FIRST run's
    changes as the refusal's own. The residual said the applied channel was empty and the trace said a change
    had landed, about the same run. Nothing in the tree crossed the warrant axis with the observer axis, so
    no assertion could see it - test_warrant.py never builds an observer and test_observer.py never builds a
    warrant.

    The kernel's own words are what it broke. Journal says "acted always precedes remained within a pass",
    and converge's own veto comment says "Nothing was applied, so the applied channel is empty"."""

    class _Refuses(Warrant):
        """A warrant that always refuses, so the gate is reached without leaning on a channel's count."""

        def assent(self, reading):
            return [DriftItem("gate", "refused")]

    async def _converged(self, observer, warrant=None):
        plan = _Declaration(((),), ("drifts",))
        steps, world = plan.mint()
        residual = await Reconciler(steps, observer=observer, warrant=warrant).converge()
        return dict(world.written), residual

    async def test_a_journal_reused_across_a_veto_does_not_inherit_the_last_run_s_writes(self):
        journal = Journal()
        wrote, _ = await self._converged(journal)
        self.assertEqual(wrote, {"S0": "created"})                       # the first run really did write
        self.assertEqual([item.name for item in journal.passes[0].applied], ["S0"])
        refused, residual = await self._converged(journal, self._Refuses())
        self.assertEqual(refused, {})                                    # the refused run wrote nothing
        self.assertEqual(residual.applied, ())                           # and the record says so
        self.assertEqual(journal.passes[-1].applied, (),
                         "the trace credited a refused run with the previous run's writes")
        self.assertEqual([item.name for item in journal.passes[-1].residual], ["gate", "S0"])

    async def test_the_veto_fires_the_hooks_that_describe_an_outcome_and_not_the_one_that_opens_work(self):
        # began() must stay unfired. That is not cosmetic. Timing opens a Span on began, so firing it
        # would mint a measured pass for a run that never ran one.
        seen = []

        class Watching(Observer):
            """The three pass hooks in the order they fired, so the ABSENCE of began is asserted rather
            than assumed from a Timing span that happens to be empty."""

            def began(self):
                seen.append("began")

            def acted(self, applied):
                seen.append(("acted", len(applied)))

            def remained(self, residual):
                seen.append(("remained", len(residual)))

        timing = Timing()
        await self._converged(Chorus(Watching(), timing), self._Refuses())
        self.assertEqual(seen, [("acted", 0), ("remained", 2)])
        self.assertEqual(timing.passes, ())
        self.assertEqual(timing.elapsed, 0.0)


class DecoratorOrderKeepsTheBridge(unittest.IsolatedAsyncioTestCase):
    """ThreadDispatcher keeps bridging when ANOTHER decorator is composed inside it, which is the order the
    kernel supports and the one the cross-product above draws as `threaded-chaos`.

    THE BUG CLASS is this file's founding one, seen from the composition side rather than the axis side.
    ChaosDispatcher REBUILDS the write callable, so the Write carrier does not survive it - RemoteDispatcher
    refuses a rebuilt callable out loud for exactly that reason. ThreadDispatcher accepts one silently and
    the whole question is then which layer ends up on the worker thread. With the chaos decorator INSIDE, the
    bridge still holds the carrier, relay() rebuilds the stack around the relocated hook, so a blocking
    write leaves the loop. Nothing about the OUTCOME would change if it did not, which is why this is
    measured by WHERE the write ran rather than by what it returned - the same reason the axis-side pin next
    door is measured that way."""

    class _Records(Step):
        """Reports the thread each write ran on. It declares a lease, because a step asking for no capacity
        never reaches the permit layer and the question this class exists to ask cannot be asked."""

        leases = (Permit("orthogonality", 4),)

        def __init__(self, seen):
            self._seen = seen

        def apply(self, inputs):
            self._seen.append(threading.get_ident())
            return None, {}

        def prune(self, inputs):
            self._seen.append(threading.get_ident())
            return None, {}

    async def test_a_decorator_inside_the_bridge_leaves_the_bridge_intact(self):
        for verb in ("converge", "prune"):
            for axes in ({}, {"retry": Retry(3)}, {"authority": Local()}, {"authority": Local(), "retry": Retry(3)}):
                with self.subTest(verb=verb, axes=sorted(axes)):
                    seen = []
                    awaiting = threading.get_ident()
                    dispatcher = ThreadDispatcher(ChaosDispatcher(Parallel(), Sabotage()))
                    reconciler = Reconciler((self._Records(seen),), mode=dispatcher, **axes)
                    await getattr(reconciler, verb)()
                    # Counted before it is located, because a write that never ran is somewhere other than
                    # here too. That is the exact shape of the first bug this family shipped.
                    self.assertEqual(len(seen), 1, f"the {verb} write ran {len(seen)} times instead of once")
                    self.assertNotIn(awaiting, seen,
                                     f"the {verb} write ran on the event loop with the chaos decorator "
                                     f"composed inside the bridge, so the bridge is gone")


class OneAttemptIsNotEnough(unittest.IsolatedAsyncioTestCase):
    """Why Retry(1) is excluded from the equivalence set, said out loud rather than assumed.

    The generated declaration holds a node that loses its first attempt of the run, which is what makes
    the retry axis an axis at all. A single-attempt run therefore ends with a failed step and a world that
    is genuinely smaller, so Retry(1) changes WHAT happens and cannot sit in a set asserting one outcome.
    This is the boundary, pinned - so the exclusion stays a fact about the kernel and does not quietly
    become a way of dodging a red test."""

    def _transient(self):
        plan = _Declaration(((),), ("transient",))
        return plan.mint()

    async def test_one_attempt_leaves_the_transient_node_failed_and_the_world_empty(self):
        steps, world = self._transient()
        residual = await Reconciler(steps, mode=Parallel(OnError.BestEffort), retry=Retry(1)).converge()
        self.assertEqual(world.written, {})
        self.assertEqual([item.name for item in residual.failures], ["S0"])
        self.assertEqual(residual.applied, ())

    async def test_two_attempts_heal_it_in_the_same_pass(self):
        steps, world = self._transient()
        residual = await Reconciler(steps, mode=Parallel(OnError.BestEffort), retry=Retry(2)).converge()
        self.assertEqual(world.written, {"S0": "created"})
        self.assertEqual(residual.failures, ())
        self.assertEqual(_Outcome.bagged(residual.applied), [("S0", "created")])


class _Across(unittest.IsolatedAsyncioTestCase):
    """The dispatcher set the three excluded axes are compared over. Holds no test of its own - it exists
    so the three classes below compare through ONE definition of "every dispatcher" instead of each
    inventing its own."""

    @staticmethod
    def dispatchers(policy=OnError.FailFast):
        # Every in-process shipped dispatcher plus the serial walk, which is the only way to reach the Walk
        # arranger. RemoteDispatcher is absent for the reason it is absent from the cross-product - its
        # envelope pickles the step, so what a step may hold is a different question.
        return (Parallel(policy), Supervised(policy), ThreadDispatcher(Parallel(policy)),
                ChaosDispatcher(Parallel(policy), Sabotage()), RunMode(Walk(), _Serial(policy)))


class _Gated(Step):
    """One step behind a gate. It drifts and it writes the moment anything lets it."""

    def __init__(self, world):
        self._world = world

    def assess(self, inputs):
        return Assessment(deviation=[DriftItem("gated", "absent")]), {}

    def apply(self, inputs):
        self._world["gated"] = "created"
        return [DriftItem("gated", "created")], {}


class VetoingWarrant(_Across):
    """A warrant that REFUSES is out of the equivalence set because a refused run legitimately did less,
    and that makes it an invariant of its own. The refusal has to be the SAME refusal whichever dispatcher
    was going to walk the run and it has to leave the world alone.

    THE BUG CLASS. The gate is a leading probe INSIDE converge(), so a dispatcher whose probe answered a
    different reading would refuse differently - or would refuse and write anyway, which is the one
    failure a veto exists to make impossible. Nothing before this crossed the warrant axis with the
    dispatcher axis at all."""

    async def test_a_veto_leaves_the_world_untouched_under_every_dispatcher(self):
        verdicts = []
        for dispatcher in self.dispatchers():
            world = {}
            residual = await Reconciler((_Gated(world),), mode=dispatcher,
                                        warrant=Ceiling(deviation=0)).converge()
            verdicts.append((type(dispatcher).__name__, dict(world), _Outcome.bagged(residual),
                             _Outcome.bagged(residual.vetoed), residual.applied, residual.failures))
        # Pinned first, so five dispatchers agreeing on nothing cannot pass as five dispatchers agreeing.
        _, world, residual, vetoed, applied, failures = verdicts[0]
        self.assertEqual(world, {})
        self.assertEqual([name for name, _ in vetoed], ["Ceiling.deviation"])
        self.assertEqual(len(residual), 2)                       # the reason, beside what the probe found
        self.assertIn(("gated", "absent"), residual)
        for name, seen, proof, refused, wrote, broke in verdicts:
            with self.subTest(mode=name):
                self.assertEqual(seen, {})           # nothing was written
                self.assertEqual(wrote, ())          # and nothing claims to have been
                self.assertEqual(broke, ())          # a refusal is not a failure
                self.assertEqual(proof, residual)
                self.assertEqual(refused, vetoed)


class _Denying(Authority):
    """An authority whose pool is permanently empty, so every write is deferred and none is a failure."""

    def acquire(self, permit, holder):
        return False

    def release(self, permit, holder):
        ...


class _Held(Step):
    """A step that needs a permit before it writes."""

    leases = (Permit("held", 1),)

    def __init__(self, world):
        self._world = world

    def apply(self, inputs):
        self._world["held"] = "created"
        return [DriftItem("held", "created")], {}


class _Downstream(Step):
    """The dependent, so a denial's BLOCKING clause is exercised beside the deferral itself."""

    expects = (_Held,)
    leases = (Permit("held", 1),)

    def __init__(self, world):
        self._world = world

    def apply(self, inputs):
        self._world["downstream"] = "created"
        return [DriftItem("downstream", "created")], {}


class DenyingAuthority(_Across):
    """An authority that DENIES is out of the equivalence set because a run that never wrote is a
    different outcome - and it carries a rule the kernel states in a comment and nothing generated has
    ever checked. A deferral is reported the SAME WAY under all three OnError policies, because OnError is
    a policy about ERRORS and an exhausted pool is not one.

    THE BUG CLASS is named in that comment. Deferred is a BaseException, so handled below the OnError
    clause a momentarily full pool under the DEFAULT FailFast would abort the run and re-raise out of
    converge - making a capacity limit indistinguishable from a crash for every caller who never chose a
    policy. Crossing the authority axis with the policy axis is what turns that comment into a test."""

    async def test_a_denial_reads_the_same_under_every_dispatcher_and_every_policy(self):
        verdicts = []
        for policy in OnError:
            for dispatcher in self.dispatchers(policy):
                world = {}
                residual = await Reconciler((_Held(world), _Downstream(world)), mode=dispatcher,
                                            authority=_Denying()).converge()
                verdicts.append(((policy.name, type(dispatcher).__name__), dict(world),
                                 _Outcome.bagged(residual), _Outcome.bagged(residual.failures)))
        _, world, residual, failures = verdicts[0]
        self.assertEqual(world, {})
        self.assertEqual(failures, [("_Downstream", "step blocked: prerequisite _Held waited for a permit")])
        self.assertEqual(len(residual), 2)
        self.assertEqual([name for name, _ in residual], ["_Downstream", "_Held"])
        self.assertTrue(next(said for name, said in residual if name == "_Held").startswith("step deferred"))
        for where, seen, proof, broke in verdicts:
            with self.subTest(run=where):
                self.assertEqual(seen, {})
                self.assertEqual(proof, residual)
                self.assertEqual(broke, failures)


class _Trips(Step):
    """Writes, then trips the run's own cancellation - so the abort lands between two waves rather than at
    a moment a test had to guess at."""

    def __init__(self, world, flag):
        self._world = world
        self._flag = flag

    def apply(self, inputs):
        self._world["tripped"] = "created"
        self._flag.cancel()
        return [DriftItem("tripped", "created")], {}


class _Never(Step):
    """The step on the far side of the abort. It must not run, under any dispatcher."""

    expects = (_Trips,)

    def __init__(self, world):
        self._world = world

    def apply(self, inputs):
        self._world["never"] = "created"
        return [DriftItem("never", "created")], {}


class _Aborts(Step):
    """A step that aborts itself, for the question a retry budget must never answer."""

    def apply(self, inputs):
        raise Cancelled("the step aborted itself")


class _Recording(Observer):
    """Keeps the one hook a firing cancellation must never fire."""

    def __init__(self):
        self.retries = []

    def retried(self, step, attempt, error):
        self.retries.append(Step.named(step))


class FiringCancellation(_Across):
    """A cancellation that FIRES is out of the equivalence set because a cut run legitimately did less,
    and what it leaves behind is an invariant of its own. The abort cuts through as ITSELF, the progress
    made before it is real and identical under every dispatcher, with no attempt ever spent on it.

    THE BUG CLASS. Cancelled is a BaseException precisely so a retry loop's `except Exception` cannot
    catch it, where a cut that got retried would spend a whole budget re-running a run somebody stopped -
    which is a pairing of the cancellation axis and the retry axis that nothing generated has crossed."""

    async def test_an_abort_between_waves_keeps_what_landed_under_every_dispatcher(self):
        for dispatcher in self.dispatchers():
            with self.subTest(mode=type(dispatcher).__name__):
                world = {}
                flag = Flag()
                with self.assertRaises(Cancelled) as cut:
                    await Reconciler((_Trips(world, flag), _Never(world)), mode=dispatcher,
                                     cancellation=flag).converge()
                self.assertEqual(world, {"tripped": "created"})   # what landed is RECORDED, not rolled back
                self.assertEqual(str(cut.exception), "Run cancelled by Flag")

    async def test_no_attempt_is_ever_spent_on_an_abort(self):
        for dispatcher in self.dispatchers():
            with self.subTest(mode=type(dispatcher).__name__):
                watching = _Recording()
                with self.assertRaises(Cancelled):
                    await Reconciler((_Aborts(),), mode=dispatcher, retry=Retry(3),
                                     observer=watching).converge()
                self.assertEqual(watching.retries, [])


class ExecutorIsTheDispatchersChoice(unittest.IsolatedAsyncioTestCase):
    """The authority axis says WHO may write. It may not say WHERE the write runs, because that is the
    dispatcher axis's whole answer and two axes deciding one thing is what orthogonality means.

    THE BUG CLASS is this file's own reason for existing, one layer deeper than the outcome. Every axis
    reaches the write through Write, so a wrapper laid there that changes the CALLING CONVENTION silently
    rewrites what a decorating dispatcher is able to do - which is precisely how ThreadDispatcher under
    Retry(n) came to hand asyncio.to_thread an unawaited coroutine. The outcome comparison above cannot
    see this class of defect, because a blocking hook run on the event loop still returns the right
    answer. It just pins the loop while doing it, which is the one thing ThreadDispatcher exists to
    prevent."""

    class _Records(Step):
        """Reports which thread each of its writes actually ran on. It declares a lease, because a step
        that asks for no capacity never reaches the permit wrapper and the question cannot be asked."""

        leases = (Permit("orthogonality", 4),)

        def __init__(self, seen):
            self._seen = seen

        def apply(self, inputs):
            self._seen.append(threading.get_ident())
            return None, {}

        def prune(self, inputs):
            self._seen.append(threading.get_ident())
            return None, {}

    async def _threads(self, verb, **axes):
        # WHICH threads the writes ran on, handed back whole rather than as a verdict. A verdict of "somewhere
        # other than here" is satisfied by a write that never ran at all, which is not a hypothetical -
        # it is exactly what ThreadDispatcher under Retry(n) once did. So the assertion counts the writes
        # before it asks where they happened.
        seen = []
        reconciler = Reconciler((self._Records(seen),), mode=ThreadDispatcher(Parallel()), **axes)
        await getattr(reconciler, verb)()
        return seen

    async def test_the_thread_bridge_holds_whatever_else_is_injected(self):
        for verb in ("converge", "prune"):
            for axes in ({}, {"retry": Retry(3)}, {"authority": Local()}, {"authority": Local(), "retry": Retry(3)}):
                with self.subTest(verb=verb, axes=sorted(axes)):
                    awaiting = threading.get_ident()
                    seen = await self._threads(verb, **axes)
                    self.assertEqual(
                        len(seen), 1,
                        f"the {verb} write ran {len(seen)} times instead of once, so where it ran is not yet the question",
                    )
                    self.assertNotIn(
                        awaiting, seen,
                        f"ThreadDispatcher ran the {verb} write on the event loop, so the blocking bridge "
                        f"the dispatcher axis was chosen for is gone",
                    )
