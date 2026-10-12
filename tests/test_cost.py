"""The deterministic cost gate - what a run COSTS, counted in operations rather than measured in seconds.

bench/stress.py measures time and reads growth back out of it, which is the right tool for a sweep a human
runs and reads. It cannot be a gate. A ceiling in seconds passes on a fast laptop and fails on a loaded CI
box, so the number nobody dares assert is the number nobody defends. Until now not one cost in this kernel
was pinned anywhere. Nothing watched for the regression that makes a converge quadratic in its steps or
resolves every declared name twice or charges a clean run for the failure machinery. None of those changes a
residual, so every correctness test in this suite would stay green while a control plane carrying a thousand
steps got slower every release.

So this file counts the work instead of timing it. Every number here is an exact count of how many times the
kernel entered a seam it already publishes, taken over a declaration of KNOWN shape. That makes each
assertion a fact about the algorithm rather than about the machine, so it means the same thing everywhere and
can be asserted as an equality.

What the counts are read through and why each seam was chosen.
  - the step verbs, counted by the steps this file wrote, which is the only place that sees a re-entry
  - the Observer hooks, where the kernel says began, dispatching, stepped, produced, acted, remained and
    pruned out loud, so a pass count and a per-unit count need no private read
  - the Addressing lookup, injected as a Vocabulary of counting rows, which counts literally how many times
    the graph was asked to resolve a declared name

Wall time stays informational and lives in bench/COST-BASELINE.md beside these counts, with the interpreter
and the machine it was read on. The counts are the gate.
"""
import asyncio
import unittest

from cabaxiom import (
    Addressing,
    Assessment,
    Authority,
    DriftItem,
    EdgeKind,
    Fixpoint,
    Graph,
    Kahn,
    Local,
    Logging,
    Observer,
    OnError,
    Only,
    Parallel,
    Permit,
    Reconciler,
    Retry,
    Skip,
    Step,
    Supervised,
    ThreadDispatcher,
    Vocabulary,
    Write,
)
from cabaxiom.vocabulary import Roster


class _Counts:
    """How many times a run entered each step verb, kept beside the steps because a Step freezes after
    construction. One tally is shared by every step of a declaration, so 200 applies over 200 steps is one
    apply each and 400 would be the finding."""

    def __init__(self) -> None:
        self.assess = 0
        self.apply = 0
        self.prune = 0


class _Verbs(Step):
    """A step that counts every entry into its own three verbs and does nothing else.

    `settles_after` is how many applies it takes before the read comes back clean, zero for a step already in
    desired state - which is what lets ONE step serve both the fixed-cost gates (a clean world, one pass) and
    the pass-count gates (a world that comes good over several). `produces` names the one artifact key a step
    hands its dependents, so the data-flow's own cost can be counted as payload keys mounted."""

    def __init__(self, counts: _Counts, produces: str | None = None, settles_after: int = 0):
        self._counts = counts
        self._produces = produces
        # A mutable cell rather than an int. A step is frozen after construction, so the countdown advances by
        # mutating a held list, which is the sanctioned form for a value that changes across passes.
        self._left = [settles_after]

    def assess(self, inputs):
        self._counts.assess += 1
        # The message carries the remaining count, so two passes never read as one unchanged residual and a
        # Fixpoint's stall detector cannot end the loop before the work is done.
        return Assessment(deviation=() if not self._left[0] else (DriftItem("cost", f"{self._left[0]} left"),)), {}

    def apply(self, inputs):
        self._counts.apply += 1
        if self._left[0]:
            self._left[0] -= 1
        return None, {} if self._produces is None else {self._produces: 1}

    def prune(self, inputs):
        self._counts.prune += 1
        return None, {}


class _Leased(_Verbs):
    """A step that declares one capacity - the control for the authority count. A step with no `leases` must
    cost no ask, so this is what proves the counter can see one at all."""

    leases = (Permit("cost", 4),)


class _Fuse(Step):
    """The one broken step of the failure declarations, so the blame walk has something real to fan over."""

    def apply(self, inputs):
        raise RuntimeError("hard I/O failure")


class _Named(Step):
    """A step that counts the reads of its own name. Every sentence the kernel writes about a step goes
    through Step.named, which reads `identifier` first, so a hook that names a step is a hook that touched it."""

    def __init__(self) -> None:
        self.reads = [0]

    @property
    def identifier(self) -> str | None:
        self.reads[0] += 1
        return None


class _Tally(Observer):
    """Every hook the kernel fires, counted - the run's own trace read as an operation count.

    The pass hooks (began, acted, remained, pruned) say how many CYCLES a run took, while the unit hooks
    (dispatching, stepped, produced, retried) say how much work each cycle admitted. `mounted` sums the
    payload keys the write side handed out, since dispatching carries the very mapping a step is about to
    read, which makes the data-flow's cost countable without instrumenting a step.

    The counts live in a dict and are read back through fired(), because a counter named after its hook would
    have to shadow the hook that increments it."""

    _HOOKS = ("began", "dispatching", "stepped", "produced", "acted", "remained", "retried", "pruned")

    def __init__(self) -> None:
        self.__counts = dict.fromkeys(_Tally._HOOKS, 0)
        self.mounted = 0

    def fired(self, *hooks: str) -> tuple[int, ...]:
        # The counts of the named hooks, in the order asked. A tuple, so one assertion reads as the sentence it
        # is checking, so a typo raises here instead of quietly comparing nothing.
        return tuple(self.__counts[hook] for hook in hooks)

    def began(self) -> None:
        self.__counts["began"] += 1

    def dispatching(self, step, inputs) -> None:
        self.__counts["dispatching"] += 1
        self.mounted += len(inputs)

    def stepped(self, step, changes, error) -> None:
        self.__counts["stepped"] += 1

    def produced(self, step, artifacts) -> None:
        self.__counts["produced"] += 1

    def acted(self, applied) -> None:
        self.__counts["acted"] += 1

    def remained(self, residual) -> None:
        self.__counts["remained"] += 1

    def retried(self, step, attempt, error) -> None:
        self.__counts["retried"] += 1

    def pruned(self, residual) -> None:
        self.__counts["pruned"] += 1


class _Lookups:
    """How many declared names a derivation resolved and how many steps those names reached.

    Two numbers rather than one, because they answer different questions. `names` is how often the graph was
    ASKED, which is a fact about the declaration's size. `reached` is how many steps the answers landed on,
    which is the derived edge count. A resolution that grew with the square of the run shows up as names
    following reached instead of holding to the declaration."""

    def __init__(self) -> None:
        self.names = 0
        self.reached = 0


class _Metered(Addressing):
    """One Addressing with a counter around its lookup, delegating everything else to the real one.

    This is the seam the cost question is actually about - how many times the graph is asked to resolve a name
    - and it is injectable, since the Vocabulary a run speaks is an axis like every other. Delegation rather
    than a reimplementation, so what is measured is the shipped lookup and the counter cannot change the thing
    it counts."""

    def __init__(self, inner: Addressing, lookups: _Lookups):
        self.__inner = inner
        self.__lookups = lookups

    @property
    def takes(self) -> str:
        return self.__inner.takes

    @property
    def stray(self) -> str:
        return self.__inner.stray

    @property
    def noun(self) -> str:
        return self.__inner.noun

    @property
    def vow(self) -> str:
        return self.__inner.vow

    @property
    def indirect(self) -> bool:
        return self.__inner.indirect

    def admits(self, name):
        return self.__inner.admits(name)

    def found(self, name, instances, providers):
        matched = self.__inner.found(name, instances, providers)
        self.__lookups.names += 1
        self.__lookups.reached += len(matched)
        return matched

    def shown(self, names, labels):
        return self.__inner.shown(names, labels)

    def spoken(self, name):
        return self.__inner.spoken(name)

    def absent(self, named):
        return self.__inner.absent(named)


class _Language:
    """The SHIPPED vocabulary with a counter around every lookup, row for row.

    Rebuilt rather than reduced, so a metered run speaks the same eight edge kinds an ordinary one does and no
    count below is a count of a smaller language. The wrappers are shared per addressing because a Vocabulary
    refuses counterparts that do not share one - `expects` and `requires` are twins over the same lookup - and
    that validation is part of what keeps this harness honest."""

    @staticmethod
    def metered(lookups: _Lookups) -> Vocabulary:
        wrappers: dict[Addressing, Addressing] = {}
        rows = []
        for kind in Vocabulary.shipped():
            if kind.addressing not in wrappers:
                wrappers[kind.addressing] = _Metered(kind.addressing, lookups)
            rows.append(EdgeKind(kind.slot, wrappers[kind.addressing], hard=kind.hard,
                                 counterpart=kind.counterpart, colour=kind.colour, precedes=kind.precedes))
        return Vocabulary(*rows)


class _Hashes:
    """How many hashes were taken of a probe. A frozenset membership costs exactly one and a list walk costs
    none, which is what makes ZERO the finding here rather than the success."""

    def __init__(self) -> None:
        self.taken = 0


class _Weighed:
    """A stand-in for a step inside a Roster, counting every hash taken of it.

    It is not a Step and cannot be. A Step may not define __hash__ (its identity IS the kernel's dependency
    addressing, so the contract refuses one where it is written) and it does not need to be either - a Roster
    reads its held items through hash and identity alone, which is the whole question this probe asks."""

    def __init__(self, hashes: _Hashes):
        self.__hashes = hashes

    def __hash__(self) -> int:
        self.__hashes.taken += 1
        return id(self)


class _Loud(list):
    """A residual that counts being READ, so a hook doing nothing can be told from a hook doing something
    cheap. Reading it at all is the cost being measured, which is why length and iteration both count."""

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def __len__(self) -> int:
        self.reads += 1
        return super().__len__()

    def __iter__(self):
        self.reads += 1
        return super().__iter__()


class _Granting(Authority):
    """An authority that grants everything and counts being asked. Written from the port rather than wrapped
    around Local, because what is under test is how often the seam is ENTERED and nothing at all about a
    pool."""

    def __init__(self) -> None:
        self.acquired = 0
        self.released = 0

    def acquire(self, permit, holder):
        self.acquired += 1
        return True

    def release(self, permit, holder):
        self.released += 1


class _Nothing:
    """The plainest write callable there is, for the identity checks that prove a neutral axis wraps nothing.
    It has to be a real callable and it has to do nothing, so that what is under test is the wrapper or its
    absence."""

    @staticmethod
    def write(step, inputs):
        return None, {}


class _Inversion:
    """Whether a run's Graph has built its dependents map yet.

    It reads a private, deliberately, in one place so the mangled name is spelled once. The claim under
    test IS about a private - the inversion is built on the first ask and cached, so no public read can tell
    "never built" from "built and empty", where a public read that could would already be the eager build this
    gate exists to refuse."""

    @staticmethod
    def built(reconciler: Reconciler) -> bool:
        return reconciler._graph._Graph__inverted is not None


class _Shapes:
    """The declarations the gates are measured over, built by INSTANCE edges so a graph of a thousand nodes
    costs a thousand objects rather than a thousand classes.

    Each shape says what it builds in vertices and declared names, with every gate below asserting those numbers
    before it asserts a cost - a cost attributed to the wrong graph reads exactly like a real one, which is the
    guard bench/stress.py already keeps for its own shapes."""

    @staticmethod
    def independent(count: int, counts: _Counts) -> tuple[Step, ...]:
        # No edges at all. One wave of `count` steps, the shape the fixed-cost claim is about.
        return tuple(_Verbs(counts) for _ in range(count))

    @staticmethod
    def chain(count: int, counts: _Counts, *, slot: str = "uses", produces: bool = False) -> tuple[Step, ...]:
        # The deepest graph there is - `count` steps in one line, `count - 1` declared names, one per edge. The
        # slot is a parameter because a hard name costs a second resolution where a soft one does not.
        made = [_Verbs(counts, produces=f"key{index}" if produces else None) for index in range(count)]
        for index, later in enumerate(made[1:]):
            setattr(later, slot, (made[index],))
        return tuple(made)

    @staticmethod
    def fan(count: int, counts: _Counts) -> tuple[Step, ...]:
        # The widest graph there is - one root named by `count - 1` leaves. Where a square would hide, since
        # every leaf names the same one step.
        root = _Verbs(counts)
        made = [root]
        for _ in range(count - 1):
            leaf = _Verbs(counts)
            leaf.uses = (root,)
            made.append(leaf)
        return tuple(made)

    @staticmethod
    def layered(width: int, layers: int, span: int, counts: _Counts) -> tuple[Step, ...]:
        # Wide AND deep, the shape a real declaration takes. `width * layers` vertices and
        # `(layers - 1) * width * span` declared names, each naming one instance from the layer above.
        made: list[Step] = []
        previous: list[Step] = []
        for _ in range(layers):
            current = [_Verbs(counts) for _ in range(width)]
            for position, step in enumerate(current):
                if previous:
                    step.uses = tuple(previous[(position + offset) % len(previous)] for offset in range(span))
            made.extend(current)
            previous = current
        return tuple(made)

    @staticmethod
    def replicas(count: int) -> tuple[Step, ...]:
        # The quadratic case, where the point is WHERE it lives. `count` consumers each name ONE class against
        # `count` present instances of it, so the declaration holds `count` names while the derivation lands
        # `count * count` edges. The blowup is declared, not computed.
        class Replica(Step):
            pass

        class Consumer(Step):
            expects = (Replica,)

        return tuple([Replica() for _ in range(count)] + [Consumer() for _ in range(count)])

    @staticmethod
    def hanging(on: tuple[Step, ...], count: int, counts: _Counts) -> tuple[Step, ...]:
        # `count` steps that all name the same prerequisites - the shape a blame walk fans over, plus the one
        # where a record written per culprit EDGE instead of per blocked step squares.
        made = []
        for _ in range(count):
            step = _Verbs(counts)
            step.uses = on
            made.append(step)
        return tuple(made)


class ConvergeCostTests(unittest.IsolatedAsyncioTestCase):
    """One converge over N independent steps enters each verb a FIXED number of times per step and fires the
    pass hooks a fixed number of times for the whole run, both independent of N.

    The bug class is anything that grows per step where it should grow per pass - a re-probe taken per step
    instead of per cycle, a payload re-assembled per dependency, a convergence that spends a second pass over a
    world that already came good. A converge over 200 steps that enters a verb 400 times is quadratic in
    disguise, yet not one of those defects changes a residual, so nothing else in this suite would see them."""

    async def test_one_converge_enters_each_verb_once_per_step(self):
        counts, watch = _Counts(), _Tally()
        residual = await Reconciler(_Shapes.independent(200, counts), observer=watch).converge()
        self.assertEqual(residual, [])
        # ONE write and ONE proving read per step. The read is the re-probe that verifies the pass, so there is
        # no leading probe because no warrant was injected.
        self.assertEqual((counts.apply, counts.assess), (200, 200))
        # The pass hooks fire once for the whole cycle, however many steps that cycle holds.
        self.assertEqual(watch.fired("began", "acted", "remained"), (1, 1, 1))
        # The unit hooks fire once per admitted step and nothing was attempted twice - except dispatching,
        # which announces BOTH phases, so a converge (one write pass plus the proving read) fires it twice
        # per step. stepped and produced stay the write's alone, which is what keeps lineage attributable.
        self.assertEqual(watch.fired("dispatching", "stepped", "produced"), (400, 200, 200))
        self.assertEqual(watch.fired("retried", "pruned"), (0, 0))

    async def test_the_cost_per_step_does_not_move_when_the_declaration_doubles(self):
        # The scaling half of the claim. Doubling the steps must double the totals and leave the per-step
        # quotient exactly where it was - a cost that crept from 2.0 to 2.5 per step would still satisfy an
        # assertion written as an inequality, so both are asserted as equalities.
        per_step, per_run = {}, {}
        for size in (100, 200, 400):
            counts, watch = _Counts(), _Tally()
            await Reconciler(_Shapes.independent(size, counts), observer=watch).converge()
            self.assertEqual(counts.apply + counts.assess, 2 * size)
            per_step[size] = ((counts.apply + counts.assess) / size, sum(watch.fired("dispatching", "stepped", "produced")) / size)
            per_run[size] = watch.fired("began", "acted", "remained")
        self.assertEqual(set(per_step.values()), {(2.0, 4.0)})   # 2 dispatching (both phases) + 1 stepped + 1 produced
        self.assertEqual(set(per_run.values()), {(1, 1, 1)})

    async def test_a_chain_mounts_one_payload_key_per_declared_edge(self):
        # The data-flow's own cost. Every step produces one key and every dependent reads exactly what its own
        # prerequisite produced, so the payload the write side mounts is the DECLARED EDGES and never the run's
        # whole artifact store - which is the shape that would turn a deep chain into a quadratic copy.
        counts, watch = _Counts(), _Tally()
        residual = await Reconciler(_Shapes.chain(40, counts, produces=True), observer=watch).converge()
        self.assertEqual(residual, [])
        self.assertEqual(watch.fired("dispatching"), (80,))   # announced on the write and on the proving read
        self.assertEqual(watch.mounted, 39)

    async def test_a_teardown_pays_one_prune_per_step_and_takes_no_read_at_all(self):
        # The prune twin, whose cost is deliberately NOT the converge's. A teardown is not re-probed - the
        # read measures deviation from the should-exist state, so it would report everything as missing - so
        # zero reads is the documented design rather than a gap, so this is what would notice a teardown that
        # quietly grew one.
        counts, watch = _Counts(), _Tally()
        residual = await Reconciler(_Shapes.independent(50, counts), observer=watch).prune()
        self.assertEqual(residual, [])
        self.assertEqual((counts.prune, counts.assess, counts.apply), (50, 0, 0))
        self.assertEqual(watch.fired("pruned", "began", "acted", "remained"), (1, 0, 0, 0))
        self.assertEqual(watch.fired("dispatching", "stepped", "produced"), (50, 50, 50))

    async def test_fixpoint_spends_one_pass_per_unit_of_work_and_none_proving_it(self):
        # How many passes the convergence takes, pinned. Two steps that each need three applies cost exactly
        # three cycles - the third pass's own re-probe is the proof, so no fourth pass is spent confirming it.
        counts, watch = _Counts(), _Tally()
        staged = (_Verbs(counts, settles_after=3), _Verbs(counts, settles_after=3))
        residual = await Reconciler(staged, convergence=Fixpoint(), observer=watch).converge()
        self.assertEqual(residual, [])
        self.assertEqual(watch.fired("began", "acted", "remained"), (3, 3, 3))
        self.assertEqual((counts.apply, counts.assess), (6, 6))

    async def test_fixpoint_over_a_world_that_is_already_clean_costs_exactly_one_pass(self):
        # The looping convergence's neutral cost. A clean first pass ends the loop, so Fixpoint costs what Once
        # costs on a world with nothing to do - and a second pass here would silently double the price of every
        # already-converged run in production, since the residual would be identical either way.
        counts, watch = _Counts(), _Tally()
        residual = await Reconciler(_Shapes.independent(20, counts), convergence=Fixpoint(max_passes=10),
                                    observer=watch).converge()
        self.assertEqual(residual, [])
        self.assertEqual(watch.fired("began", "acted", "remained"), (1, 1, 1))
        self.assertEqual((counts.apply, counts.assess), (20, 20))


class ResolutionCostTests(unittest.TestCase):
    """Resolution is linear in the nodes plus the DECLARED edges, with every declared name resolved once.

    The counter is the vocabulary's own lookup, so each number below is literally how many times the graph was
    asked to resolve a name. The bug class is a resolution that grows with the square of the run, which this
    kernel has already shipped once - a class Roster answered membership by walking its list, where a chain of
    one class turned the whole derivation quadratic, a hundred seconds on 200000 steps against a third of one
    for the ordering it fed."""

    def test_a_chain_asks_once_per_declared_name(self):
        for size in (50, 100, 200):
            with self.subTest(steps=size):
                lookups = _Lookups()
                graph = Graph(_Shapes.chain(size, _Counts()), _Language.metered(lookups))
                edges = sum(len(graph.dependencies(step)) for step in graph.steps)
                self.assertEqual(edges, size - 1)          # the shape built what it promised
                self.assertEqual(lookups.names, size - 1)  # one ask per declared name, none of them twice
                self.assertEqual(lookups.reached, edges)   # every ask landed on exactly one step

    def test_a_fan_costs_its_declared_edges_and_not_its_square(self):
        # A fan is where a square hides, because one root is named by everybody. The asks and the reach both
        # follow the declaration, so resolving the widest graph costs what resolving the deepest one costs.
        for size in (50, 100, 200):
            with self.subTest(steps=size):
                lookups = _Lookups()
                graph = Graph(_Shapes.fan(size, _Counts()), _Language.metered(lookups))
                edges = sum(len(graph.dependencies(step)) for step in graph.steps)
                self.assertEqual(edges, size - 1)
                self.assertEqual((lookups.names, lookups.reached), (size - 1, size - 1))

    def test_a_class_fan_pays_for_the_declaration_and_not_for_the_walk(self):
        # `expects` names a CLASS, so one name reaches every present instance of it. Doubling this declaration
        # doubles the asks and QUADRUPLES the edges, which is the correct answer and the pin that says where the
        # quadratic lives. A derivation that re-asked per edge would show its asks following the edges instead.
        for size, edges in ((10, 100), (20, 400)):
            with self.subTest(replicas=size):
                lookups = _Lookups()
                graph = Graph(_Shapes.replicas(size), _Language.metered(lookups))
                self.assertEqual(sum(len(graph.dependencies(step)) for step in graph.steps), edges)
                self.assertEqual(lookups.names, size)
                self.assertEqual(lookups.reached, edges)

    def test_a_hard_name_is_resolved_twice_and_a_soft_name_once(self):
        # The presence guard is a SECOND resolution by design. The derivation is total (an absent name is a dead
        # end, never an error), so `needs` is re-asked by demand() once membership is final. Two asks per hard
        # name is the price of that guard, pinned so it stays two and does not become one per Ordering verb.
        for slot, asked in (("uses", 9), ("needs", 18)):
            with self.subTest(slot=slot):
                lookups = _Lookups()
                Reconciler(_Shapes.chain(10, _Counts(), slot=slot), Kahn(), vocabulary=_Language.metered(lookups))
                self.assertEqual(lookups.names, asked)

    def test_resolving_a_run_asks_each_name_once_and_no_later_phase_asks_again(self):
        # Construction runs the scope, the derivation, the presence guard, Kahn's waves, the contention seating,
        # the coverage guard and the placement verification. Every one of those reads the DERIVED edges, so the
        # whole resolution costs exactly the declaration's soft names - the same count the bare derivation cost
        # above, which is what says no later phase re-resolves anything.
        lookups = _Lookups()
        Reconciler(_Shapes.chain(100, _Counts()), Kahn(), vocabulary=_Language.metered(lookups))
        self.assertEqual((lookups.names, lookups.reached), (99, 99))

    def test_a_narrowing_scope_pays_a_second_derivation_over_what_it_kept(self):
        # A cost that is real, by design, worth a number so nobody makes it three. A targeted scope cannot
        # know its closure before the edges exist, so Only derives the whole world, walks the closure and
        # re-derives over the steps it kept - 9 names asked twice for a chain of 10 that keeps every step. It is
        # pinned at TWO because a third derivation is what a future scope composed of scopes would cost and
        # that would be paid by every run rather than noticed by anybody.
        lookups = _Lookups()
        Reconciler(_Shapes.chain(10, _Counts()), Kahn(), scope=Only(_Verbs), vocabulary=_Language.metered(lookups))
        self.assertEqual(lookups.names, 18)
        # A scope that keeps nothing of the chain re-derives nothing of it, so the second derivation is charged
        # for the KEPT set and not for the handed one.
        lookups = _Lookups()
        Reconciler((*_Shapes.chain(10, _Counts()), _Leased(_Counts())), Kahn(), scope=Skip(_Verbs),
                   vocabulary=_Language.metered(lookups))
        self.assertEqual(lookups.names, 9)

    def test_a_structural_read_re_resolves_every_name_and_keeps_nothing(self):
        # explain() is the per-NAME read, documented as keeping nothing at all - the misses it
        # surfaces are re-derived from the tables the derivation already holds. So it costs one full resolution
        # per call, which is the honest price of a read a run may never take. This is the number that says
        # a caller drawing a picture in a loop is paying for it each time.
        lookups = _Lookups()
        run = Reconciler(_Shapes.chain(10, _Counts()), Kahn(), vocabulary=_Language.metered(lookups))
        self.assertEqual(lookups.names, 9)
        run.explain()
        self.assertEqual(lookups.names, 18)
        run.explain()
        self.assertEqual(lookups.names, 27)

    def test_class_membership_is_answered_by_an_index_rather_than_by_a_walk(self):
        # The quadratic this kernel already shipped and fixed, guarded where it actually lived. An instance name
        # is resolved by asking the class Roster whether it holds that instance, where a Roster that answers by
        # walking its list is invisible to every count above - the asks stay linear while each one starts
        # costing the run. A hash per probe is the index answering. Zero hashes would mean the walk is back.
        for size in (100, 400):
            with self.subTest(held=size):
                hashes = _Hashes()
                held = [_Weighed(hashes) for _ in range(size)]
                roster = Roster(held)
                self.assertEqual(hashes.taken, size)   # the index built once, one hash per held item
                hashes.taken = 0
                self.assertIn(held[0], roster)
                self.assertIn(held[-1], roster)
                self.assertNotIn(_Weighed(hashes), roster)
                self.assertEqual(hashes.taken, 3)      # three probes, three hashes, whatever the size


class FailureMachineryCostTests(unittest.IsolatedAsyncioTestCase):
    """A clean run pays NOTHING for the failure machinery, while a broken one pays once per blocked step rather
    than once per edge into it.

    The Graph's inversion is documented as lazy - built on the first dependents() ask, which a clean run never
    asks. That claim is load-bearing prose and nothing watched it, so an edit that inverted the edges in the
    constructor would pass every test in this suite while charging every clean run for machinery it does not
    use. The blame count is the same claim from the other side. A step downstream of two failures is ONE
    blocked step naming both, where a record written per culprit edge would grow with the product of the
    failures and the fallout."""

    async def test_a_clean_run_never_builds_the_dependents_map(self):
        counts = _Counts()
        run = Reconciler(_Shapes.chain(20, counts))
        residual = await run.converge()
        # Asserted first, so "nothing was built" cannot pass because nothing ran.
        self.assertEqual((residual, list(residual.failures)), ([], []))
        self.assertEqual((counts.apply, counts.assess), (20, 20))
        self.assertFalse(_Inversion.built(run))

    async def test_a_failed_run_builds_the_inversion_once_and_keeps_it(self):
        # The other half. Otherwise the test above passes forever against a Graph whose inversion had been deleted
        # outright. A failure asks, so the map exists - and it is built ONCE, which the identity of two answers
        # proves without a private read.
        counts = _Counts()
        fuse = _Fuse()
        run = Reconciler((fuse, *_Shapes.hanging((fuse,), 12, counts)), mode=Parallel(OnError.BestEffort))
        await run.converge()
        self.assertTrue(_Inversion.built(run))
        self.assertIs(run._graph.dependents(fuse), run._graph.dependents(fuse))
        self.assertEqual(counts.apply, 0)   # every dependent was blocked, so none of them wrote

    async def test_a_blocked_step_is_recorded_once_however_many_failures_reach_it(self):
        # Twenty steps each naming BOTH failures. One drift per blocked step, naming its culprits in declaration
        # order, is 22 items. One drift per culprit edge would be 42, where on a denser fan the two diverge by the
        # product rather than by a constant.
        counts = _Counts()
        first, second = _Fuse(), _Fuse()
        residual = await Reconciler((first, second, *_Shapes.hanging((first, second), 20, counts)),
                                    mode=Parallel(OnError.BestEffort)).converge()
        failed = [item for item in residual.failures if "step failed" in item.message]
        blocked = [item for item in residual.failures if "step blocked" in item.message]
        self.assertEqual((len(failed), len(blocked)), (2, 20))
        self.assertEqual(len(residual.failures), 22)
        self.assertEqual(counts.apply, 0)


class DispatcherCostTests(unittest.IsolatedAsyncioTestCase):
    """Every shipped dispatcher costs the SAME per step, while composing a retry over one changes that cost by
    nothing on a run where nothing fails.

    This is the cost half of the crossing the suite was missing. ThreadDispatcher composed with Retry(2) once
    NEVER RAN apply() at all - to_thread handed back an unawaited coroutine - and the shipping bug was possible
    because no test had ever put those two objects in one Reconciler. A count of the verb entries is the
    shortest possible statement of that defect. Zero applies is a cost, where a dispatcher that ran a step twice
    to be sure would be the same finding from the other direction."""

    async def test_every_dispatcher_costs_the_same_per_step_with_and_without_a_retry(self):
        readings = {}
        for dispatcher in (Parallel(), Supervised(), ThreadDispatcher(), ThreadDispatcher(Supervised())):
            for attempts in (1, 2):
                counts, watch = _Counts(), _Tally()
                residual = await Reconciler(_Shapes.chain(20, counts, produces=True), mode=dispatcher,
                                            retry=Retry(attempts), observer=watch).converge()
                self.assertEqual(residual, [])
                named = f"{type(dispatcher).__name__} over Retry({attempts})"
                readings[named] = ((counts.apply, counts.assess), watch.fired(*_Tally._HOOKS), watch.mounted)
        # Pinned first, so four dispatchers agreeing on nothing cannot pass as four dispatchers agreeing.
        expected = ((20, 20), (1, 40, 20, 20, 1, 1, 0, 0), 19)   # dispatching announces both phases
        for named, reading in readings.items():
            with self.subTest(mode=named):
                self.assertEqual(reading, expected)


class NeutralAxisCostTests(unittest.IsolatedAsyncioTestCase):
    """The neutral value of an axis COSTS NOTHING rather than merely behaving the same.

    Retry(1) hands the write callable straight back, a run with no authority gets the raw call with no permit
    layer around it, an authority is never asked about a step that declares no lease, while the silent Observer
    does not even read what it is handed. The bug class is a neutral that quietly becomes a wrapper - invisible
    to every behavioural test in this suite, visible only as a slower run, exactly the shape the thread
    bridge got wrong once when it threaded the retry-wrapped callable instead of the raw one.

    The fourth neutral, a run with no warrant taking no leading probe, is already pinned by counting a step's
    reads in tests/test_warrant.py and is deliberately not repeated here."""

    def test_the_neutral_retry_wraps_nothing(self):
        write = _Nothing.write
        self.assertIs(Retry(1)(write), write)
        self.assertIsNot(Retry(2)(write), write)

    def test_no_authority_wraps_no_permit(self):
        write = _Nothing.write
        self.assertIs(Write(Retry(1), Observer(), write, "apply").raw, write)
        # And the layer does appear when somebody asks for it. Otherwise the identity above proves nothing.
        self.assertIsNot(Write(Retry(1), Observer(), write, "apply", Local()).raw, write)

    async def test_an_authority_is_never_asked_about_a_step_that_declares_no_lease(self):
        counts, authority = _Counts(), _Granting()
        await Reconciler(_Shapes.independent(10, counts), authority=authority).converge()
        self.assertEqual(counts.apply, 10)
        self.assertEqual((authority.acquired, authority.released), (0, 0))
        # The control - one declared capacity is one ask and one release per write, so the counter is not blind.
        counts, authority = _Counts(), _Granting()
        await Reconciler((_Leased(counts), _Leased(counts)), authority=authority).converge()
        self.assertEqual((authority.acquired, authority.released), (2, 2))

    def test_the_silent_observer_does_not_even_read_what_it_is_handed(self):
        # A no-op hook that still counted its residual would pay a length on every pass of every run, where one
        # that named its step would pay an attribute read per unit. Logging is the control, because it DOES
        # read - so zero here is the base observer staying silent rather than the probe being blind.
        silent, spoken = Observer(), Logging()
        residual = _Loud()
        for hook in (silent.acted, silent.remained, silent.pruned):
            hook(residual)
        self.assertEqual(residual.reads, 0)
        for hook in (spoken.acted, spoken.remained, spoken.pruned):
            hook(residual)
        self.assertEqual(residual.reads, 3)

        named = _Named()
        silent.dispatching(named, {})
        silent.stepped(named, None, None)
        silent.produced(named, {})
        silent.retried(named, 1, RuntimeError("nothing"))
        self.assertEqual(named.reads[0], 0)
        spoken.stepped(named, None, None)
        self.assertEqual(named.reads[0], 1)


class LargeGraphCostTests(unittest.IsolatedAsyncioTestCase):
    """One end-to-end run over a graph big enough to be interesting - 1024 steps over 1984 declared edges -
    resolves and converges clean at exactly the cost the fixed-cost gates predict for it.

    Those gates are read on small declarations, where a squared cost is cheap enough to pass unnoticed. This is
    the same arithmetic at a size where a square would take minutes instead of milliseconds, so it is the
    end-to-end proof and the hang guard at once. The bound is around a hundred times the measured cost
    (recorded in bench/COST-BASELINE.md), because a timeout here is only ever meant to catch a run that stopped
    finishing, never to grade the machine it runs on."""

    async def test_a_thousand_step_graph_resolves_and_converges_at_the_pinned_cost(self):
        counts, watch, lookups = _Counts(), _Tally(), _Lookups()
        steps = _Shapes.layered(32, 32, 2, counts)
        self.assertEqual(len(steps), 1024)
        # Resolution first, over the metered language, so the same declaration also reports what deriving it
        # cost - 31 layers of 32 steps naming two prerequisites each, asked once apiece.
        derived = Graph(steps, _Language.metered(lookups))
        self.assertEqual(sum(len(derived.dependencies(step)) for step in derived.steps), 1984)
        self.assertEqual((lookups.names, lookups.reached), (1984, 1984))

        async with asyncio.timeout(60):
            residual = await Reconciler(steps, observer=watch).converge()

        self.assertEqual(residual, [])
        self.assertEqual((counts.apply, counts.assess), (1024, 1024))
        self.assertEqual(watch.fired("began", "acted", "remained"), (1, 1, 1))
        self.assertEqual(watch.fired("dispatching", "stepped", "produced"), (2048, 1024, 1024))   # dispatching announces both phases

