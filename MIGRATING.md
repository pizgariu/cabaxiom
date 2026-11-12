# Migrating to 1.0.0

1.0.0 freezes the front door. This page is what an upgrade needs and nothing else.

## What the freeze covers

**The forty-three names `cabaxiom` exports.** They will not move, change signature or change meaning inside
the 1.x line. That is the whole promise and it is meant to be boring.

```python
import cabaxiom
cabaxiom.__all__          # the frozen surface, forty-three names
```

**What a name carries is frozen with it.** The public methods, properties and constructor keywords of a
frozen class keep their names, their parameters and their defaults. A minor may add a method or a keyword
with a default. It never takes one away. A contract test holds every one of them to the shape 1.0.0 shipped.

**A frozen verb can hand back a layer type.** `Reconciler.explain()` answers an `Explanation` and
`foresee()` a `Casualty`, both from `cabaxiom.core.record`. The verb is frozen. What the object it returns
exposes carries its layer's promise, the same as a name you import from there. So does a layer type a frozen
constructor accepts, such as a custom `Ordering` handed to `Reconciler`.

**A bug fix is not a change of meaning.** A fix that makes a frozen name do what its documentation already
says ships in a patch under `### Fixed`. Changing what the documentation says waits for 2.0.0.

They fall in four groups. What you DECLARE (`Step` and the shapes a hook hands back), what you RUN (the
`Reconciler` and its axes), what you READ (the records a run answers with) and what you CATCH (the refusal
vocabulary).

## What the freeze does NOT cover

`cabaxiom.core` and `cabaxiom.laboratory` stay importable and stay documented. They are **not** part of the
1.x promise. A name there can move, change or be renamed in a minor.

This is deliberate rather than a hedge. The kernel has about a hundred and sixty public names and freezing
all of them for years would mean either never improving them or cutting a major every time one moved. So the
door carries the contract and the layers carry the rest. A name graduates to the door when it has earned the
promise, which is what the 1.1 through 1.5 minors are for.

**If you depend on a layer name, pin a minor.** `cabaxiom>=1.0,<1.1` is honest about what you are standing
on. If you think a name belongs on the door, that is worth an issue - the first three arrived that way,
because the kernel's own first client needed them.

## Coming from 0.7.1

0.7.1 is the last release before the freeze. Its door carried fifty-nine names.

- **40 are still on the door**, unchanged.
- **19 moved one import deeper.** The table below.
- **3 are new on the door** - `Cancellation`, `Reading` and `Vocabulary`. That is additive and needs nothing
  from you.

Every one of the nineteen answers when you reach for it. `from cabaxiom import Enclave` does not fail with a
bare "cannot import name" - it tells you the line to type. So the fastest migration is to run your suite and
follow the sentences.

| was | write |
|---|---|
| `Clean` | `from cabaxiom.core.run import Clean` |
| `Cutover` | `from cabaxiom.core.run import Cutover` |
| `Enclave` | `from cabaxiom.core.run import Enclave` |
| `Enclosure` | `from cabaxiom.core.run import Enclosure` |
| `Every` | `from cabaxiom.core.declaration import Every` |
| `Fanout` | `from cabaxiom.core.run import Fanout` |
| `Flow` | `from cabaxiom.core.run import Flow` |
| `Itinerary` | `from cabaxiom.core.run import Itinerary` |
| `Journal` | `from cabaxiom.core.record import Journal` |
| `Only` | `from cabaxiom.core.plan import Only` |
| `Permit` | `from cabaxiom.core.declaration import Permit` |
| `RemoteDispatcher` | `from cabaxiom.core.run import RemoteDispatcher` |
| `Skip` | `from cabaxiom.core.plan import Skip` |
| `Stable` | `from cabaxiom.core.run import Stable` |
| `Succession` | `from cabaxiom.core.plan import Succession` |
| `ThreadDispatcher` | `from cabaxiom.core.run import ThreadDispatcher` |
| `Transition` | `from cabaxiom.core.run import Transition` |
| `WithTag` | `from cabaxiom.core.plan import WithTag` |
| `WithoutTag` | `from cabaxiom.core.plan import WithoutTag` |

## Coming from an older release

The door was wider before 0.7.0 narrowed it the first time. 0.4.2 carried fifty-four names.

- **20 are still on the door**, unchanged.
- **31 moved one import deeper.** Everything below.
- **3 were replaced.** Also below, with what to write instead.
- **23 names are new on the door**, which is additive and needs nothing from you.

Every one of those answers the same way, so the suite and the sentences still do the work.

### Moved

| was | write | since |
|---|---|---|
| `AllOf` | `from cabaxiom.core.declaration import AllOf` | 0.7.0 |
| `AnyOf` | `from cabaxiom.core.declaration import AnyOf` | 0.7.0 |
| `Backoff` | `from cabaxiom.core.run import Backoff` | 0.7.0 |
| `BaseDispatcher` | `from cabaxiom.core.run import BaseDispatcher` | 0.7.0 |
| `Chains` | `from cabaxiom.core.plan import Chains` | 0.7.0 |
| `Chorus` | `from cabaxiom.core.record import Chorus` | 0.7.0 |
| `Clean` | `from cabaxiom.core.run import Clean` | 1.0.0 |
| `Components` | `from cabaxiom.core.plan import Components` | 0.7.0 |
| `Convergence` | `from cabaxiom.core.run import Convergence` | 0.7.0 |
| `DFS` | `from cabaxiom.core.plan import DFS` | 0.7.0 |
| `Dispatcher` | `from cabaxiom.core.run import Dispatcher` | 0.7.0 |
| `Every` | `from cabaxiom.core.declaration import Every` | 1.0.0 |
| `Explanation` | `from cabaxiom.core.record import Explanation` | 0.7.0 |
| `Jitter` | `from cabaxiom.core.run import Jitter` | 0.7.0 |
| `Majority` | `from cabaxiom.core.declaration import Majority` | 0.7.0 |
| `Most` | `from cabaxiom.core.declaration import Most` | 0.7.0 |
| `Once` | `from cabaxiom.core.run import Once` | 0.7.0 |
| `Only` | `from cabaxiom.core.plan import Only` | 1.0.0 |
| `Ordering` | `from cabaxiom.core.plan import Ordering` | 0.7.0 |
| `Partition` | `from cabaxiom.core.plan import Partition` | 0.7.0 |
| `Placement` | `from cabaxiom.core.plan import Placement` | 0.7.0 |
| `Priority` | `from cabaxiom.core.plan import Priority` | 0.7.0 |
| `Quorum` | `from cabaxiom.core.declaration import Quorum` | 0.7.0 |
| `Rule` | `from cabaxiom.core.declaration import Rule` | 0.7.0 |
| `Scope` | `from cabaxiom.core.plan import Scope` | 0.7.0 |
| `Settle` | `from cabaxiom.core.run import Settle` | 0.7.0 |
| `Skip` | `from cabaxiom.core.plan import Skip` | 1.0.0 |
| `Some` | `from cabaxiom.core.declaration import Some` | 0.7.0 |
| `Stable` | `from cabaxiom.core.run import Stable` | 1.0.0 |
| `ThreadDispatcher` | `from cabaxiom.core.run import ThreadDispatcher` | 1.0.0 |
| `Write` | `from cabaxiom.core.run import Write` | 0.7.0 |

### Replaced

| was | what to write instead |
|---|---|
| `Levels` | the partition is WavesPartition since the plan layer split. Write `from cabaxiom.core.plan import WavesPartition` |
| `Outcome` | a write answers FlowOutcome or AsyncFlowOutcome, which gained the artifacts half - a hook hands back `(changes, artifacts)` rather than changes alone. Both are on the front door |
| `Pipeline` | running independent chains at once is the Flow run mode. A step starts the moment its own prerequisites settle, so one chain never waits on another. Write `Reconciler(..., mode=Flow())`, importing Flow from cabaxiom.core.run |

## Behaviour, not just names

Four windows changed how the kernel behaves. A name that survived can still answer differently, so each
window's `### BC break` section in [CHANGELOG.md](CHANGELOG.md) is the full list.

- **0.5.0** - eight breaks. The declaration vocabulary became data and the dependency slot was renamed from
  `after` to `expects`. A class still declaring `after` is refused by name rather than ignored.
- **0.6.0** - nine breaks. The four read verbs became one `assess()` answering a `Reading`. Every hook
  takes `inputs` and a write answers `(changes, artifacts)` rather than changes alone.
- **0.7.0** - six breaks. The package became four layers, the door narrowed the first time and the three
  strategy families answer a named verb instead of `__call__`.
- **1.0.0** - nine breaks. A hook's reply in the wrong shape is refused where it comes back, a bare string
  in a label slot is refused and a class edge naming a base class reaches its subclasses now, so a run can
  gain waves.

## The shortest path

```
pip install --upgrade cabaxiom
pytest                       # follow the refusals, they name the line to type
```

A refusal that does not tell you what to write is a defect here. Report it.
