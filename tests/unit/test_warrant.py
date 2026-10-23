"""Policy read before the first write, plus a refusal that is a verdict rather than an exception.

A run can be correct and still be a catastrophe. A declaration that says one table where somebody meant
fifty converges perfectly, proves itself and reports clean, because a reconciler answers whether the world
matches the declaration and never whether the declaration was sane.

The load-bearing decision is that a veto is NOT raised. Raising would land a policy refusal in the channel a
caller catches a broken socket in, so a formal decision not to start would be told apart from a crash by
exception type alone - and this kernel already ruled on that when it built `halt()`, which exists "precisely
so a non-failure stop stops impersonating a failure". These pin the verdict at every place it shows.
"""
import unittest

from cabaxiom import Assessment, DriftItem, OnError, Parallel, Reconciler, Step, Supervised, ThreadDispatcher
from cabaxiom.core.record import Ceiling, Charter, Observer, Reading, Warrant
from cabaxiom.laboratory import ChaosDispatcher, Idempotence, Sabotage


class Owning(Step):
    """Owns a declared number of things, so a footprint bound has something to count."""

    def __init__(self, owns: int, *, dirty: bool = True) -> None:
        self._owns = owns
        self._dirty = dirty
        self._writes: list[int] = []

    @property
    def identifier(self) -> str:
        return "owning"

    @property
    def writes(self) -> int:
        return len(self._writes)

    def assess(self, inputs):
        return Assessment(
            deviation=[DriftItem("owning", "not settled")] if self._dirty and not self._writes else [],
            plan=[DriftItem("owning", "would write")] if self._dirty else [],
            advisory=[DriftItem("owning", "worth a look")],
            footprint=[DriftItem(f"thing-{n}", "would be removed") for n in range(self._owns)],
        ), {}

    def apply(self, inputs):
        if self._writes:
            return None, {}
        self._writes.append(1)
        return [DriftItem("owning", "wrote")], {}


class Standing(Owning):
    """Owning's teardown half. It records that its own prune ran, so a refused teardown is measured by what
    happened to the world rather than by what the run says about itself - which is the only reading a run
    that reported beautifully and tore everything down cannot fake."""

    def __init__(self, owns: int, *, dirty: bool = True) -> None:
        super().__init__(owns, dirty=dirty)
        self._torn: list[int] = []

    @property
    def torn(self) -> int:
        return len(self._torn)

    def prune(self, inputs):
        self._torn.append(1)
        return None, {}


class _Always(Warrant):
    """Refuses everything, with a reason, so the verdict's shape can be asserted without a policy."""

    def assent(self, reading: Reading):
        return [DriftItem("always", "this gate refuses every run")]


class ReadingCarriesFourChannelsTests(unittest.IsolatedAsyncioTestCase):
    """The probe kept the deviations and dropped the other three, so three quarters of what every step
    computed was thrown away inside the fan that asked for it. A gate that judges scale needs all four and
    "refuse when more than five things would be torn down" is a question about the footprint that cannot be
    asked of the deviations."""

    async def test_all_four_channels_reach_the_reading(self):
        reading = await Reconciler((Owning(3),)).assess()
        self.assertEqual([item.message for item in reading], ["not settled"])
        self.assertEqual([item.message for item in reading.plan], ["would write"])
        self.assertEqual([item.message for item in reading.advisory], ["worth a look"])
        self.assertEqual(len(reading.footprint), 3)

    async def test_the_sequence_view_is_still_only_the_deviations(self):
        # Additive, so every existing caller that iterated a Reading sees exactly what it saw before.
        reading = await Reconciler((Owning(9),)).assess()
        self.assertEqual(len(list(reading)), 1)
        self.assertEqual(len(reading), 1)


class VetoIsAVerdictTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_refused_run_writes_nothing_and_reports_why(self):
        step = Owning(50)
        residual = await Reconciler((step,), warrant=Ceiling(footprint=5)).converge()
        self.assertNotEqual(residual, [])                  # a refused run is not verified
        self.assertEqual(list(residual.failures), [])      # and nothing broke
        self.assertEqual(list(residual.applied), [])       # and nothing changed
        self.assertEqual(step.writes, 0)
        self.assertIn("50 footprint findings", residual.vetoed[0].message)
        self.assertIn("bounded at 5", residual.vetoed[0].message)

    async def test_a_veto_never_raises(self):
        # THE decision. A caller's try/except around converge is for broken sockets, not for policy.
        residual = await Reconciler((Owning(1),), warrant=_Always()).converge()
        self.assertEqual([item.message for item in residual.vetoed], ["this gate refuses every run"])

    async def test_the_reasons_ride_in_the_sequence_view_too(self):
        # Otherwise a gate that refused a world already in desired state would report an empty residual,
        # which reads as verified success for a run that deliberately did nothing.
        residual = await Reconciler((Owning(1, dirty=False),), warrant=_Always()).converge()
        self.assertNotEqual(residual, [])
        self.assertIn("refuses every run", " ".join(item.message for item in residual))

    async def test_a_permitted_run_converges_exactly_as_it_would_have(self):
        step = Owning(2)
        residual = await Reconciler((step,), warrant=Ceiling(footprint=10)).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.writes, 1)
        self.assertEqual(list(residual.vetoed), [])

    async def test_a_run_with_no_warrant_takes_no_leading_probe(self):
        # The neutral default has to cost nothing, not merely behave the same. A step counts its reads.
        reads = []

        class Counting(Step):
            def assess(self, inputs):
                reads.append(1)
                return Assessment(), {}

            def apply(self, inputs):
                return None, {}

        await Reconciler((Counting(),)).converge()
        self.assertEqual(len(reads), 1)          # the re-probe only
        reads.clear()
        await Reconciler((Counting(),), warrant=Ceiling(footprint=99)).converge()
        self.assertEqual(len(reads), 2)          # the gate's leading read, then the re-probe

    async def test_the_veto_channel_is_empty_on_every_ordinary_run(self):
        for warrant in (None, Ceiling(footprint=99), Charter()):
            with self.subTest(warrant=type(warrant).__name__):
                residual = await Reconciler((Owning(1),), warrant=warrant).converge()
                self.assertEqual(list(residual.vetoed), [])


class TheGateGuardsTheTeardownTests(unittest.IsolatedAsyncioTestCase):
    """The gate guards prune(), which is the verb it was BUILT for.

    THE BUG CLASS. `Ceiling`'s own words are that `footprint=5` refuses "a run that would tear down more than
    five things, which is the guard for the afternoon somebody's declaration says one table and means fifty",
    and `Warrant` explains that "a destructive-scale policy is a question about the footprint and cannot be
    asked of the deviations". prune() is the ONLY verb that tears anything down, yet the gate sat inside
    converge() alone - so a run answering fifty footprint items was refused when it would have WRITTEN and
    permitted when it would have DESTROYED. Nothing in the tree composed a warrant with a teardown, in either
    direction, so no assertion could see it.

    Measured before the fix, one step answering fifty footprint items under `Ceiling(footprint=5)`.

        converge()  vetoed=['Ceiling.footprint']  world={}
        prune()     vetoed=[]                     world={'torn': 'down'}
    """

    def _dispatchers(self):
        # Every in-process shipped dispatcher plus the chaos decorator, because the gate is a leading PROBE
        # and a dispatcher whose probe answered a different reading would refuse differently - or would refuse
        # and tear down anyway, which is the one failure a veto exists to make impossible.
        return (Parallel(), Supervised(), ThreadDispatcher(Parallel()), ChaosDispatcher(Parallel(), Sabotage()))

    async def test_a_footprint_bound_refuses_a_teardown_and_removes_nothing(self):
        step = Standing(50)
        residual = await Reconciler((step,), warrant=Ceiling(footprint=5)).prune()
        self.assertEqual(step.torn, 0)                     # THE ground truth, read off the step
        self.assertEqual([item.name for item in residual.vetoed], ["Ceiling.footprint"])
        self.assertIn("50 footprint findings", residual.vetoed[0].message)
        self.assertEqual(list(residual.failures), [])      # a refusal is not a failure
        self.assertEqual(list(residual.applied), [])       # and a teardown applies nothing either way

    async def test_a_permitted_teardown_tears_down_exactly_as_it_would_have(self):
        step = Standing(2)
        residual = await Reconciler((step,), warrant=Ceiling(footprint=10)).prune()
        self.assertEqual(step.torn, 1)
        self.assertEqual(residual, [])                     # nothing survived, which is a verified teardown
        self.assertEqual(list(residual.vetoed), [])

    async def test_the_refused_teardown_carries_what_survived_beside_the_reason(self):
        # The residue channel of a prune means what SURVIVED, where a refused teardown survived entirely - so
        # the footprint rides there, since that channel says what the teardown would have removed and
        # therefore names exactly what is still standing. The deviations would be a converge's finding
        # smuggled into a survival proof.
        step = Standing(3)
        residual = await Reconciler((step,), warrant=Ceiling(footprint=1)).prune()
        self.assertNotEqual(residual, [])                  # a refused teardown is not a verified one
        self.assertEqual([item.name for item in residual], ["Ceiling.footprint", "thing-0", "thing-1", "thing-2"])
        self.assertEqual(step.torn, 0)

    async def test_a_teardown_with_no_warrant_takes_no_leading_probe(self):
        # The neutral default has to cost NOTHING on this verb too, which for a teardown means zero reads
        # rather than one - prune deliberately never re-probes, so the gate's read is the only one there is.
        reads = []

        class Counting(Step):
            def assess(self, inputs):
                reads.append(1)
                return Assessment(), {}

            def prune(self, inputs):
                return None, {}

        await Reconciler((Counting(),)).prune()
        self.assertEqual(len(reads), 0)
        await Reconciler((Counting(),), warrant=Ceiling(footprint=99)).prune()
        self.assertEqual(len(reads), 1)          # the gate's leading read, no re-probe after it

    async def test_every_channel_bounds_a_teardown_as_it_bounds_a_converge(self):
        # The gate is handed the WHOLE reading for either verb, because assent() is opaque about which channel
        # it weighed and a narrowed reading would be a record the probe never answered. So a bound on any
        # channel refuses both verbs, while a Ceiling on the deviations reads as the policy it is - a world that
        # never reached its declaration is a world whose teardown would destroy what nobody built.
        for channel in ("deviation", "plan", "advisory", "footprint"):
            with self.subTest(channel=channel):
                step = Standing(1)
                residual = await Reconciler((step,), warrant=Ceiling(**{channel: 0})).prune()
                self.assertEqual([item.name for item in residual.vetoed], [f"Ceiling.{channel}"])
                self.assertEqual(step.torn, 0)

    async def test_the_refused_teardown_announces_itself_through_the_teardown_hook(self):
        # pruned() is the teardown's own closing hook, so a trace that recorded every teardown but the refused
        # one would be the same lie the converge veto's unpaired hooks already were. The converge pass hooks
        # stay unfired, because no converge pass happened and Timing opens its span on began.
        seen = []

        class Watching(Observer):
            def began(self):
                seen.append("began")

            def acted(self, applied):
                seen.append(("acted", len(applied)))

            def remained(self, residual):
                seen.append(("remained", len(residual)))

            def pruned(self, residual):
                seen.append(("pruned", len(residual)))

        step = Standing(4)
        await Reconciler((step,), observer=Watching(), warrant=Ceiling(footprint=1)).prune()
        self.assertEqual(seen, [("pruned", 5)])            # the reason plus the four survivors
        self.assertEqual(step.torn, 0)

    async def test_the_produced_map_of_the_gates_own_reading_survives_a_refused_teardown(self):
        # The gate already read the world, so throwing that away would make a refused teardown pay for a probe
        # nobody can see the results of - the same ruling the refused converge keeps.
        class Producing(Step):
            def assess(self, inputs):
                return Assessment(footprint=[DriftItem("p", "owned")]), {"uri": "s3://x"}

            def prune(self, inputs):
                return None, {}

        step = Producing()
        residual = await Reconciler((step,), warrant=Ceiling(footprint=0)).prune()
        self.assertEqual(residual.produced[step], {"uri": "s3://x"})

    async def test_a_refused_teardown_reads_the_same_under_every_dispatcher(self):
        verdicts = []
        for dispatcher in self._dispatchers():
            step = Standing(50)
            residual = await Reconciler((step,), mode=dispatcher, warrant=Ceiling(footprint=5)).prune()
            verdicts.append((type(dispatcher).__name__, step.torn,
                             [(item.name, item.message) for item in residual],
                             [item.name for item in residual.vetoed], residual.failures))
        # Pinned first, so four dispatchers agreeing on nothing cannot pass as four dispatchers agreeing.
        _, torn, residue, vetoed, broke = verdicts[0]
        self.assertEqual(torn, 0)
        self.assertEqual(vetoed, ["Ceiling.footprint"])
        self.assertEqual(len(residue), 51)                 # the reason, beside the fifty that survived
        for name, removed, proof, refused, failures in verdicts:
            with self.subTest(mode=name):
                self.assertEqual(removed, 0)               # nothing was torn down
                self.assertEqual(failures, ())             # a refusal is not a failure
                self.assertEqual(proof, residue)
                self.assertEqual(refused, vetoed)

    async def test_a_teardown_the_gate_permits_is_the_teardown_it_always_was(self):
        for dispatcher in self._dispatchers():
            with self.subTest(mode=type(dispatcher).__name__):
                step = Standing(3)
                residual = await Reconciler((step,), mode=dispatcher, warrant=Charter()).prune()
                self.assertEqual(step.torn, 1)
                self.assertEqual(residual, [])
                self.assertEqual(list(residual.vetoed), [])

    async def test_a_warranted_teardown_now_depends_on_a_read_that_a_teardown_never_needed(self):
        # THE COUPLING THE GATE BOUGHT, pinned as a fact rather than left to be met in an incident. prune()
        # used to reach the world without ever asking assess() anything - __pruned says why the read is
        # deliberately not re-run AFTERWARDS, while before the gate there was no read at all. The gate needs a
        # Reading to judge, a Reading is total over the run or not minted (see Reading's own contract), so a
        # step whose assess RAISES now blocks its own teardown where the same step tore down cleanly with no
        # warrant injected.
        #
        # This is fail-CLOSED and that is defensible - a footprint nobody could count is not a footprint
        # anybody may destroy against - but a teardown is the verb somebody reaches for when the world is
        # already wrong, so it is worth being an assertion rather than a surprise. It arrives as the probe's
        # own group and not as a verdict, which is honest, because what happened is a broken read and not a
        # refusal.
        class Unreadable(Step):
            """A step whose assess dies on a world too broken to read, whose prune works fine. It counts
            into a list because a Step seals when construction ends, the discipline every fixture here keeps."""

            def __init__(self) -> None:
                self._torn: list[int] = []

            @property
            def torn(self) -> int:
                return len(self._torn)

            def assess(self, inputs):
                raise RuntimeError("the world is too broken to read")

            def prune(self, inputs):
                self._torn.append(1)
                return None, {}

        step = Unreadable()
        residual = await Reconciler((step,)).prune()
        self.assertEqual(step.torn, 1)                     # with no warrant the teardown never asks
        self.assertEqual(residual, [])
        step = Unreadable()
        with self.assertRaises(BaseExceptionGroup) as broke:
            await Reconciler((step,), warrant=Ceiling(footprint=99)).prune()
        self.assertEqual(step.torn, 0)                     # and with one, the unreadable world stands
        self.assertIn("reads failed", str(broke.exception))


class CeilingTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_ceiling_that_names_nothing_consents_to_everything(self):
        # Every bound is chosen rather than inherited, so an unconfigured gate is not a silent restriction.
        step = Owning(1000)
        residual = await Reconciler((step,), warrant=Ceiling()).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.writes, 1)

    async def test_each_channel_bounds_independently(self):
        step = Owning(4)
        residual = await Reconciler((step,), warrant=Ceiling(advisory=0)).converge()
        self.assertIn("advisory", residual.vetoed[0].name)

    async def test_every_breached_channel_is_reported_not_just_the_first(self):
        # A caller with three violations wants three sentences, not one and then another run to find the next.
        residual = await Reconciler((Owning(4),), warrant=Ceiling(footprint=1, advisory=0, deviation=0)).converge()
        self.assertEqual(len(residual.vetoed), 3)

    def test_a_negative_bound_is_refused_at_construction(self):
        with self.assertRaises(ValueError) as refused:
            Ceiling(footprint=-1)
        self.assertIn("zero or more", str(refused.exception))

    def test_zero_refuses_any_finding_on_that_channel(self):
        reading = Reading([], None, [], [DriftItem("a", "note")], [])
        self.assertEqual(len(Ceiling(advisory=0).assent(reading)), 1)
        self.assertEqual(len(Ceiling(advisory=1).assent(reading)), 0)


class CharterTests(unittest.IsolatedAsyncioTestCase):
    async def test_it_asks_every_warrant_rather_than_stopping_at_the_first(self):
        residual = await Reconciler((Owning(9),),
                                   warrant=Charter(Ceiling(footprint=1), _Always(), Ceiling(advisory=0))).converge()
        self.assertEqual(len(residual.vetoed), 3)

    async def test_an_empty_charter_is_the_neutral_gate(self):
        step = Owning(3)
        residual = await Reconciler((step,), warrant=Charter()).converge()
        self.assertEqual(residual, [])
        self.assertEqual(step.writes, 1)

    async def test_it_nests(self):
        residual = await Reconciler((Owning(9),),
                                   warrant=Charter(Charter(_Always()), Ceiling(footprint=2))).converge()
        self.assertEqual(len(residual.vetoed), 2)


class VetoMeetsTheCitizensTests(unittest.IsolatedAsyncioTestCase):
    """What a refused run means to the records that read a residual. The answer is that they need no change,
    because a refused residual is honestly non-empty and every one of them already reads that correctly."""

    async def test_idempotence_refuses_to_call_a_vetoed_run_stable(self):
        run = Reconciler((Owning(50),), warrant=Ceiling(footprint=5))
        proof = await Idempotence(run).prove()
        self.assertFalse(proof.stable)

    async def test_a_vetoed_run_under_besteffort_is_still_a_verdict_and_not_a_failure(self):
        residual = await Reconciler((Owning(50),), mode=Parallel(OnError.BestEffort),
                                    warrant=Ceiling(footprint=5)).converge()
        self.assertEqual(list(residual.failures), [])
        self.assertNotEqual(list(residual.vetoed), [])

    async def test_the_produced_map_of_the_gates_own_reading_survives(self):
        # The gate already read the world, so throwing that away would make a refused run pay for a probe
        # nobody can see the results of.
        class Producing(Step):
            def assess(self, inputs):
                return Assessment(deviation=[DriftItem("p", "off")]), {"uri": "s3://x"}

            def apply(self, inputs):
                return None, {}

        step = Producing()
        residual = await Reconciler((step,), warrant=_Always()).converge()
        self.assertEqual(residual.produced[step], {"uri": "s3://x"})
