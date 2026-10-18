# cabaxiom

Declare the state you want. The loop reads the world, finds the gap and closes it. Then it looks again to prove the gap is gone.

[![CI](https://github.com/pizgariu/cabaxiom/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/pizgariu/cabaxiom/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cabaxiom.svg)](https://pypi.org/project/cabaxiom/)
[![Python versions](https://img.shields.io/badge/python-3.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://github.com/pizgariu/cabaxiom)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A reconciliation kernel with no domain baked in and nothing to install alongside it. You describe each concern as a `Step` that reads its own drift and knows how to close it. The kernel resolves the order and runs the steps, then reads reality back. A clean result is verified, not assumed. Pure standard library, zero runtime dependencies.

## Quickstart

```python
import asyncio
from cabaxiom import Reconciler, Step

class CreateConfig(Step):
    ...   # assess() reads the gap, apply() closes it

class InstallHooks(Step):
    expects = (CreateConfig,)

class VerifyHooks(Step):
    expects = (InstallHooks,)

asyncio.run(Reconciler([
    CreateConfig(),
    InstallHooks(),
    VerifyHooks(),
]).converge())
```

That is the whole surface. Steps declare what they depend on, the `Reconciler` resolves the order, applies what is missing and re-probes to prove the result. Everything else in this README - dispatchers, retries, cancellation, the reactive `watch()` loop - is an optional strategy plugged into exactly this loop.

---

## See it work

This is `examples/git_repo_state.py`, printed verbatim. It takes a throwaway git repository from empty to fully configured, in the right order and then proves the result held.

```
Throwaway repository: /tmp/reconciler-git-rf6bona1

Plan (what converge would do, in resolved order):
    - user.name: want 'Reconciler Bot', have unset
    - user.email: want 'bot@example.test', have unset
    - commit.gpgsign: want 'false', have unset
    - HEAD: repository has no commits yet
    - branch:feature/login: local branch is missing

First converge:
  applied this run:
    + user.name: set to 'Reconciler Bot'
    + user.email: set to 'bot@example.test'
    + commit.gpgsign: set to 'false'
    + HEAD: created the initial commit
    + branch:feature/login: created local branch
  residual: empty -> desired state verified by re-probe

Second converge (should be a clean no-op):
  applied this run: nothing
  residual: empty -> desired state verified by re-probe

Direct git inspection:
    user.name = 'Reconciler Bot'
    HEAD      = 13fde42
    branch    = feature/login
```

Three things in that output are the entire idea.

**The plan came out ordered.** The steps were handed in scrambled. A branch cannot exist before there is a commit and a commit needs `user.name` and `user.email` first. Nobody wrote that sequence. The kernel read the dependency graph and produced it - config, then the initial commit, then the branch.

**The first converge did the work that was missing and nothing else.** Every line under "applied this run" is a real mutation of a real repository. Then the kernel probed a second time and found nothing left. That empty residual isn't bookkeeping. The loop went back to git after acting and confirmed reality now matches intent.

**The second converge did nothing and that is the whole point.** Running the identical reconcile again applied zero changes and still verified clean. A no-op is not a wasted pass. It's the property that makes every other pass safe.

---

## What reconciliation actually is

Most code that touches the world is a script - a fixed run of imperative steps that assumes it starts from a known place. Run it twice and it breaks or worse, it quietly does the wrong thing. Reconciliation drops that model. You keep a picture of the **desired** state and repeatedly drag the **actual** state toward it through a short feedback loop:

```
        +------------------------------------------------+
        |                                                |
        v                                                |
   +---------+       +----------+       +---------+      |
   |  WATCH  | ----> | COMPARE  | ----> |   ACT   | -----+
   |  read   |       | actual   |       | close   |
   | actual  |       |   vs     |       |  the    |
   | state   |       | desired  |       |  gap    |
   +---------+       +----------+       +---------+
                          |
                          v
                     the gap here
                    is called DRIFT
```

WATCH reads what is true right now, not what you last left behind. COMPARE holds that against what you declared and computes the difference. That difference is the **drift** - the itemized gap between reality and intent. ACT applies just enough to close it. Then the loop runs again from the top.

A few properties fall straight out of this shape and they are what separate a reconciler from a setup script.

**Drift is expected, not exceptional.** Someone hand-edits a file. A branch gets deleted, a replica dies, config drifts during an incident. A reconciler does not try to prevent any of that. It assumes the world will wander off and treats every deviation as something to fix next pass. It does not raise an alarm.

**It is level-triggered, not edge-triggered.** A trigger does not mean "handle this one event". It means "re-check the whole state against desired, now". You never process a single delta. You ask the same question from scratch, every time. That is why you can miss a signal, double-fire a trigger or run on a plain timer and the answer stays correct.

**That forces idempotency, which is the reward.** Because the same unit of work may run any number of times, doing it twice has to land exactly where doing it once did. A pass that finds nothing to change and does nothing is a first-class outcome, the no-op from the second converge above. A system built this way **self-heals**. It converges toward desired over repeated cycles no matter how it was knocked off course.

If you have used a Kubernetes controller, you have already met this loop. It runs the same idea on your own Steps. For intuition, it is a thermostat that keeps re-reading the room instead of firing the furnace once. Or an immune system that patrols instead of firing once and going quiet. Reconciliation is what resilience gets built on, precisely because everything drifts eventually.

`cabaxiom` is that principle and nothing else, boiled down to a small kernel with no domain vocabulary. It has no idea what a file or a git repo is. You teach it one `Step` at a time.

---

## The building blocks

### `Step` - a unit of desired state

You subclass `Step` and answer one question. What is the gap between the world and what I want? You report that gap as drift and you know how to close it.

```python
from cabaxiom import Step

class Config(Step):
    def __init__(self, key: str, want: str) -> None:
        self.key = key
        self.want = want

    def assess(self, inputs):
        have = read_config(self.key)                  # WATCH
        if have == self.want:                         # COMPARE
            return self.verified()                    # no gap, no drift
        return self.drifted(f"want {self.want!r}, have {have!r}")

    def apply(self, inputs):
        write_config(self.key, self.want)             # ACT
        return self.changed(f"set to {self.want!r}")
```

Four named constructors carry every answer a hook can give. `verified()` and `drifted(...)` for the read, `unchanged()` and `changed(...)` for the write - and a bare message is named after the step itself, so a declaration that already knows what it is called is never asked twice. They are methods on `Step`, which is why the import above is one name long. Nothing here has to meet the records that carry the answer.

`assess()` is WATCH plus COMPARE in one probe and it never mutates. It answers what it found beside the artifacts it produced for its dependents and finding nothing IS the verified answer. `apply()` is ACT and it must be idempotent - it hands back what it changed and its own artifacts, with `unchanged()` for a clean no-op. The kernel calls both. You never write the loop. Those artifacts are the DATA plane and a step may put it under contract - `produces = frozenset({"dsn"})` names the keys it writes, `consumes = frozenset({"dsn"})` the keys it reads and a consumer whose key no prerequisite of it produces is refused at construction. Declaring a key creates no ordering - a step may well come after another for reasons that carry no payload - it only closes the hole where a missing key arrives as an absent entry your hook cannot tell from a real one. The git example at the top is three steps of exactly this shape.

The kernel reads only two fields out of your drift, through the `Drift` protocol - a `name` and a `message`. That is the entire contract. `DriftItem(name, message)` is the ready-made implementation and the constructors above mint one for you whenever you pass a bare message. Hand them your own carrier instead wherever the subject is not the step and it passes through untouched - because the kernel reads nothing else, your domain stays entirely yours.

### `expects` - declare dependencies, get ordering for free

A step names what must run before it with one class attribute:

```python
class InitialCommit(Step):
    expects = (GitConfig,)

class LocalBranch(Step):
    expects = (InitialCommit,)
```

Hand the reconciler these in any order and it sorts them into dependency waves. That is what produced the correct plan in the opening output. A dependency cycle raises `ValueError` at construction and names the steps it could not place. A dependency on a step outside the set you passed is ignored, so a subset still reconciles cleanly.

`expects` relates *kinds*. Every instance of a named class runs first. For a dependency between two *instances* of one class - `Directory("a")` before `Directory("a/b")`, which `expects` cannot express - set `self.uses = (other_step, ...)` on the instance. And when the arrow is easier to write from the other end - a step that must run *before* a class it cannot edit - declare `prepares = (Other,)`, the same edge written the other way around. The kernel resolves all of them together, over one instance-keyed graph.

`expects`, `prepares`, `wants` and `uses` are *soft*. A dependency absent from the run is trusted, not demanded. Each has a hard twin - `requires`, `mandates`, `demands` and `needs` - that orders exactly the same way but raises `ValueError` at resolution when the named class, provider or instance is missing, for the prerequisite a targeted or filtered run must never drop by accident. Orthogonally, a step can carry opaque `tags` (a `frozenset`, class default or per instance) - an environment, a risk class, a subsystem - that the `WithTag` / `WithoutTag` scopes select on, the axis-orthogonal counterpart to `Only` / `Skip`.

Every declaration above orders two steps. One runs, then the other. Sometimes what you need is the opposite - two steps that must never run *at the same time*, in either order, with any gap between them. A migration and a backfill against one database, two jobs against one rate-limited API, anything holding a single build directory. Name the resource in `contends` and the kernel seats them apart:

```python
class Migrate(Step):
    contends = frozenset({"database"})

class Backfill(Step):
    contends = frozenset({"database"})   # never in flight beside Migrate. Either order is fine.
```

**This is not an edge and that is the whole point.** Writing `Backfill.expects = (Migrate,)` would also stop the overlap and it would do it by declaring a dependency that does not exist - so `foresee(Migrate)` would name `Backfill` a casualty of a step it never needed, `Enclosure` would see a boundary that is not there and every drawing would show the arrow. `contends` moves the *seating* and leaves the derivation alone. `explain().arrows` stays empty, because nothing was declared about order.

The run shape honours it the way its own rule requires and it works out which way to move without being told. `Parallel` pushes contenders into different waves, a `Chains` arrangement pulls them into one chain (a chain is serial, so that is where they stop overlapping) and `Serial` never had a problem. A seating that puts two contenders where they would overlap is refused at construction, so a custom `Arranger` is checked rather than trusted.

Because there is no arrow to read, `explain()` carries the reason separately - keyed by resource, since that is what a reader arrives asking about:

```python
explanation = reconciler.explain()

explanation.groups              # (('Migrate', 'Archive'), ('Backfill',))
explanation.arrows              # ()  - nothing was declared about order
explanation.contention          # (('database', ('Migrate', 'Backfill')),
                                #  ('tape', ('Archive', 'Backfill')))
```

That last line is why `Backfill` is alone in the second wave. It contends with `Migrate` over the database and with `Archive` over the tape and those two share the first. A resource only one step names constrains nothing and is left out.

The drawing tells the two apart. A dependency keeps its arrowhead, contention is an undirected dotted link, because putting a head on it would draw exactly the dependency that was so carefully not declared:

```
n0 -->|after| n2          # Migrate runs before Backfill
n0 -.-|database| n1       # Migrate and Archive merely exclude each other
```

### `Reconciler` - the engine

```python
import asyncio
from cabaxiom import Reconciler

reconciler = Reconciler([LocalBranch(...), GitConfig(...), InitialCommit(...)])

drift = asyncio.run(reconciler.assess())        # the ordered gap, no changes made
residual = asyncio.run(reconciler.converge())   # WATCH -> COMPARE -> ACT -> re-probe

if not residual:
    print("verified clean")
```

`converge()` returns a `Residual`, a read-only sequence of whatever gap outlived the run. Empty means the kernel acted, probed again and confirmed reality now matches intent. The changes made along the way live on a separate channel, `residual.applied`, which is what the examples print under "applied this run". Keeping the two apart means "what I fixed" never blurs into "what is still wrong".

### `watch()` - the reactive standing converge

`converge()` is one turn of the crank. `Reconciler.watch()` turns it whenever the world moves, which is what a long-lived reconciler does. It is an async generator. A step exposes its own `watch()` that yields when its world may have changed - a file event, a queue message, a webhook - and the engine answers each wake with a full converge, yielding the residual.

```python
async for residual in reconciler.watch():   # one converge per wake, lazily
    log_gap(residual)
    if judge.send(residual):                 # stop when your own condition is met
        break
```

A wake carries no payload and is never trusted as a report - the re-assessment that follows is the only truth, so a spurious wake costs one clean pass and a missed one is caught by the next. The default `watch()` on a step yields nothing and exits, so a step with no event source is a plain one-shot concern. A domain that genuinely wants a timer wakes on its own clock inside `watch()`.

`watch()` runs until the caller breaks out of the loop - the standing run is yours to stop. A `Settle` is the reusable judge for that. Prime one with `judge = Stable(3).watch(); next(judge)`, then `judge.send(residual)` yields `True` once the condition holds. `Clean` stops on the first clean pass, while `Stable(passes)` waits for that many consecutive clean passes before it calls the world settled, so a resource that flaps clean then dirty again does not fool it.

---

## Choosing behavior

Every axis of behavior is a small object you swap. The defaults resolve to `Kahn`, `Parallel`, `Once` and no cancellation. Pass nothing and you get all four.

| Axis | The question it answers | Default | Alternatives |
| --- | --- | --- | --- |
| **Scope** | Which of the handed steps take part? | `Scope` (everything) | `Only(StepC, ...)` (the targets plus their transitive dependencies), `Skip(StepB, ...)` (all but the named, no cascade); `WithTag(...)` / `WithoutTag(...)` select by `Step.tags` instead of by type |
| **Ordering** | Given the dependency graph (`expects` / `requires` kinds, `prepares` / `mandates` reversed kinds, `wants` / `demands` capabilities against `provides`, `uses` / `needs` instances - each pair soft and hard), in what order do steps run? | `Kahn` (dependency waves) | `DFS` (flat post-order), `Priority(key=...)` (best-first frontier over a key), `Components` (split into independent chains) |
| **Run mode** (`mode=`) | What shape does the run take and how does it actually run? | `Parallel` (fan each wave onto the event loop with `asyncio.gather`, awaiting coroutine steps concurrently) | `Supervised` (polls the cancellation mid-wave so a `Deadline` bounds even a hung `apply()`), `Serial` (one step at a time in resolved order - no concurrency anywhere, for a run you need reproducible above all), `Flow` (barrier-free: a step starts the moment its OWN prerequisites settle rather than when its whole wave does, so one slow step stops holding up everything behind it on a wide, uneven declaration), `ThreadDispatcher` (runs a blocking `apply()` on a worker thread through `asyncio.to_thread`, the bridge for a synchronous domain), `RemoteDispatcher` (ships each unit of work to a worker in another process - an injected transport carries the pickled `(verb, step, inputs)` envelope and `RemoteDispatcher.work()` is the worker half), `ChaosDispatcher` (injects faults to exercise your own failure semantics) |
| **Error policy** | When a step fails, stop or push on? | `OnError.FailFast` | `OnError.BestEffort` (finish the group, collect failures as `step failed` drift and BLOCK the failed step's transitive dependents - each reported as `step blocked: prerequisite X failed`, naming every failure it stands on in declaration order so the sentence does not move with the Ordering instead of converging against state nobody put there); `OnError.Halt` (stop like `FailFast`, report like `BestEffort`: the failure is recorded, in-flight steps settle, every unrun step reports `step skipped` and the run returns its record - applied channel intact - instead of raising) |
| **Retries** | How many tries does one step's write get? | one try | `Retry(attempts, backoff=...)` guards each `apply()` and `prune()`, spending paced attempts (`Fixed` / `Exponential` / `Linear` / `Jitter`) before a failure reaches the error policy; subclass `BaseRetry` and implement `retryable(step, attempt, error)` to retry only some failures or to give a step its own share of the budget |
| **Convergence** | How many apply-then-probe passes per converge? | `Once` (single pass) | `Fixpoint(max_passes=...)` (repeat until the residual stops changing by value, starts repeating a prior state (an oscillation) or a ceiling is hit), optionally paced by a `backoff` (`Fixed`, `Exponential`, `Linear` (a fixed step up to a cap) or `Jitter`, which scatters any backoff's pause to break a thundering herd) that retries an unchanged pass instead of stopping, so drift waiting on external state still clears; `Shrinking(max_passes=...)` instead loops only while the residual keeps getting SMALLER, stopping the moment a pass buys no ground - for a strictly reducible world rather than one that settles by churning |
| **Cancellation** | When should a run abort cooperatively between steps? | `Cancellation` (never aborts) | `Deadline(seconds)` (wall-clock budget), `Flag` (manual switch), the composites `AnyOf` / `AllOf` / `Majority` that nest into a tree or `Quorum(..., rule=...)` with `Some` / `Every` / `Most` or a `Rule` of your own |
| **Observability** | How do you trace a run without instrumenting every step? | none (silent) | an `Observer` with pass hooks (`began` / `acted` / `remained`, plus `pruned` for teardowns) and live unit hooks (`dispatching` as each unit's payload is mounted, `stepped` per settled step, `produced` attributing each clean step's artifacts, `retried` per spent attempt), composed with `Chorus` or recorded as data (a `Pass` per pass) with `Journal` |

Every axis is an open base you can subclass and each carries a seam to implement and inject (`BaseNamed`, `BaseTagged`, `BaseLooping`, `BaseRetry`, `BaseDispatcher`, `BaseFan`). You do not extend a reconciler, you inject into it. The full cut is in [the architecture notes](docs/architecture.md) (`Ordering`, `Dispatcher`, `Convergence`, `Backoff`, `Cancellation`, `Settle`, `Observer`, `Scope`, `BaseRetry` - whose seam `retryable(step, attempt, error)` says which failures earn another try). A run mode PAIRS two things and vouches for the pair. An `Arranger` turns an Ordering into the partition to walk (`Waves`, `Chains`, the serial-safe `Walk` or a shape of your own), a worker walks it and `RunMode.resolve()` builds the shape and then checks that this worker can safely walk the partition that actually came back - at construction, before anything touches your world. You compose your own with `RunMode(MyShape(), MyWorker())` and the worker walks its groups through a `Ledger` (the record of one run - `blocked` / `admit` gate, `record` classifies, `outcome` closes), inheriting the kernel's entire failure semantics - the `Cancelled` cut-through, `FailFast`, `BestEffort` with dependent blocking, the live `stepped` hook - without re-deriving a line of it. The shared bases are public and named `Base*`, following `BaseException` - `BaseDispatcher` behind the workers, `BaseFan` behind the arrangers, `BaseLooping` behind the looping convergences `Fixpoint` and `Shrinking`, `BaseRetry` behind the shipped retry-everything `Retry` and `BaseNamed` / `BaseTagged` behind the scopes.

```python
import asyncio
from cabaxiom import Reconciler, Parallel, Fixpoint, Deadline

reconciler = Reconciler(
    steps,
    mode=Parallel(),
    convergence=Fixpoint(max_passes=10),
    cancellation=Deadline(seconds=30),
)
residual = asyncio.run(reconciler.converge())
```

### Async native - the one engine on your event loop

The kernel is async to the bone. There is no sync twin. Every verb that touches a step is a coroutine - `converge()`, `prune()` and the read `assess()` - so a step whose `apply()` or `assess()` is a coroutine closes its gap over I/O without blocking the coroutines it shares the loop with and a plain sync `apply()` still runs inline. `Parallel` fans each dependency wave with `asyncio.gather` and bars between waves, fanning the re-probe that proves a converge exactly as it fans the writes. It checks the cancellation only between waves, so `Supervised` is its polling sibling. It consults the cancellation while a wave is in flight and cancels the outstanding coroutines when it fires, which is what lets a `Deadline` bound an `apply()` that hangs instead of blocking on it forever. A synchronous, blocking domain rides the same engine through `ThreadDispatcher`, which runs each blocking `apply()` on a worker thread via `asyncio.to_thread` - and a domain with workers on other machines rides it through `RemoteDispatcher`, whose injected transport carries each `(verb, step, inputs)` envelope out and whose books never leave the originals. Two sentences an operator needs before putting anything irreversible behind that wire. The default `Retry(1)` is at-most-once per cycle, while any larger budget over a wire is an opt-in at-least-once - a reply lost on the way home cannot be told apart from an envelope lost on the way out, so retry re-ships and the write lands again, which an idempotent `apply()` absorbs and anything else answers by declining a distinguishable lost-reply error in `retryable()`. And artifacts carry POINTERS, not payloads. `RemoteDispatcher(transport, limit=...)` puts a byte ceiling on both directions, refusing an oversized envelope before it crosses and an oversized reply as the non-retryable `Skew` it is, because the data plane moves the data and the wire moves the words. For a continuous loop, `Reconciler.watch()` drives a converge per wake and the caller applies a `Settle` (`Clean` or `Stable(k)` for k consecutive clean passes) to decide when to stop.

### More than converge

A `Reconciler` reads and writes state through a handful of verbs. Every one but `explain()` fans across the steps in resolved order, reversed for the teardown.

- `assess()` fans every step's own `assess()` across the run and folds the answers into one `Reading`. The reading is the deviations in run order, the channel converge re-probes for its proof. It carries the other three channels beside them - `plan` (what a converge would do), `advisory` (findings about a step already in desired state, kept out of deviation so advice never dirties a proof) and `footprint` (what a teardown would remove).
- `explain()` returns the resolved run structure itself - the waves the dispatcher will walk (labelled per instance, so two steps of one kind read apart), the resolved dependency arrows behind them straight off the run's Graph - every edge kind, capabilities included - and the declarations that produced each arrow. It reads the same resolution every other verb uses, so it shows the actual run.
- `converge()` applies, then re-probes, returning the `Residual`.
- `prune()` is the reverse-order teardown itself, verifying the same way a converge does.
- `watch()` is the reactive standing converge, a converge per wake from the steps' own event sources.

### Proving idempotence

Idempotence is the whole promise. Converge and a second converge on the settled world changes nothing. `Idempotence` proves that instead of trusting it. It wraps a `Reconciler`, converges to desired state, converges once more and returns a `Proof`.

```python
import asyncio

from cabaxiom.laboratory import Idempotence

proof = asyncio.run(Idempotence(reconciler).prove())
assert proof.stable          # the second converge was a clean no-op
```

`proof.churned` is what that second converge's `apply()` reported doing - empty on an idempotent reconciler and the tell of an `apply()` that keeps working even when `assess()` reads clean - which the residual alone hides, being empty whenever the reading is clean. `proof.residual` is what was still wrong after it, empty only when the reconciler actually reached desired state, so a `Proof` says which of the two failures it found.

### Proving reversibility

`converge()` builds and `prune()` tears down - but nothing yet proved the tear-down returned the world to what the run first observed. `Reversibility` mints that certificate. It holds the opening drift reading as a value, converges, prunes, reads again and returns a `Roundtrip`.

```python
import asyncio

from cabaxiom.laboratory import Reversibility

roundtrip = asyncio.run(Reversibility(reconciler).prove())
assert roundtrip.reversible   # arrived, erased its footprint, world reads as first observed
```

The three channels are named for the promises they guard and hold the counter-evidence - `built` (the converge never arrived), `erased` (the prune reported survivors) and `restored` (the closing reading differs from the opening one). The last is the trick no bookkeeping-based destroy can pull off. It compares against the OPENING reading, never against emptiness, so a prune that claims clean while its artifact still stands is convicted and a run that tore down a world somebody else had built is refused honestly. For ephemeral test environments, sandboxes and canaries, the proof that "undo" is not a lie.

### Isolating a failure

When a large stack churns or will not settle, the question is always the same. Which steps, exactly? `Isolation` answers it by delta-debugging the declaration itself - it shrinks the step set to the smallest dependency-closed subset that still shows the failure and returns an `Indictment` naming it.

```python
import asyncio

from cabaxiom.laboratory import Isolation, Stall

indictment = asyncio.run(Isolation(steps, charge=Stall()).isolate())
if indictment:
    print("accused:", ", ".join(indictment.accused))       # the group the failure lives in
    print("dismissed:", ", ".join(indictment.dismissed))   # dropped while the failure persisted
    print("evidence:", indictment.evidence)                # the accused set's own Proof, re-runnable
```

Every candidate subset travels with everything it stands on (the Graph keeps it dependency-closed), so every trial is a legal, runnable world and never a resolution error. The `charge` picks the failure to hunt - `Churn` (an `apply()` that keeps working under a clean drift, the default) or `Stall` (a residual that never clears) and a custom `Charge` reads the trial's `Proof` however your failure looks. Trials are real runs - point an isolation at a rehearsal world, exactly as you would `Idempotence.prove()`, whose protocol each trial runs.

### Besieging a declaration

`Isolation` holds the world still and shrinks the DECLARATION, asking which step breaks the stack. A `Siege` is its twin on the other axis. It holds the declaration still and shrinks the FAULT, asking which failure the stack cannot take. It lays a strike on every step, then lifts them one at a time while the failure keeps showing and returns a `Breach` naming the smallest fault set your declaration cannot absorb.

```python
from cabaxiom.laboratory import Siege, Stall

breach = await Siege(steps, charge=Stall()).lay()
if breach:
    print("cannot take:", ", ".join(breach.breached))   # the smallest fault set that still breaks it
    print("absorbed:", ", ".join(breach.survived))      # the failures the declaration shrugged off
else:
    print("converged under every fault the siege could lay")
```

A falsy `Breach` is the stronger result and the one worth asserting in a suite. The strikes are NAMED rather than rolled (`Targeted`), which is what makes a fault set a value a hunt can halve, re-run and compare - a seeded `Sabotage` makes a random chaos run repeatable, which is what you want while HUNTING for a failure and a `Siege` is what you reach for once you have one and want it minimal. Read a `Breach` as a reproducer and never as a root cause. Where several faults each break the run on their own they are all equally minimal and the lift order decides which one the shrink keeps. Trials are real runs, so lay a siege against a rehearsal world.

### Nesting whole stacks

The Step surface and the reconciler surface align verb for verb and `Enclave` closes the loop. A whole reconciler - its own ordering, executor, convergence, retries - joins a parent run as ONE step.

```python
import asyncio

from cabaxiom import Enclave, Parallel, Reconciler
from cabaxiom.laboratory import Idempotence

database = Reconciler(db_steps, mode=Parallel())    # a whole stack...
application = Reconciler(app_steps)                       # ...and another

class DatabaseStack(Enclave): ...
class ApplicationStack(Enclave):
    expects = (DatabaseStack,)                              # ordered like any step

top = Reconciler((ApplicationStack(application), DatabaseStack(database)))
assert asyncio.run(Idempotence(top).prove())              # one Proof certifies the whole tree
```

Reconciliation is fractal. Stacks nest, one top-level `converge()` returns one residual and what changed inside an enclave rides the parent's `applied` channel while what is still wrong surfaces through the parent's re-probe - so "empty means verified" stays true across every level.

An `Enclave` holds a stack you already built. A `Fanout` builds one **per pass**, over a world it lists in
the moment, which is how a declaration naming one concern answers for however many things exist today.

```python
from cabaxiom import Fanout, Reconciler

class SweepBuckets(Fanout):
    async def explore(self, inputs):                      # the listing goes in a verb, never a constructor
        return Reconciler([Clean(name) for name in await bucket_names()])
```

Each discovered thing is its own step, so it is its own finding under its own name, it spends its own
`Retry` and only what is still wrong stays in the residual. A bucket that appeared since the last pass
joins the next one with no edit to anything - the pass lists the world again. The inner graph is rebuilt
WHOLE rather than mutated, so every pass holds a complete immutable derivation and `Idempotence.prove()`
on the parent still certifies the tree. The three verbs are `final`, because the wiring has one rule that
reads as success when you get it wrong. `apply()` hands up the child's applied channel and never its
residual. The cost is stated plainly - a fan asks the world instead of remembering it, so every pass lists
it twice, once for the write and once for the re-probe that proves the write.

### Proving the nesting is airtight

Fractal nesting has one hazard and it is silent. Each reconciler derives its structure over its OWN steps, so a step inside an enclave that declares `expects=(Network,)` while the `Network` lives in the parent gets a dead end - an absent name is trusted to the world, nothing raises - and the parent orders the enclave only by the enclave's own declarations. The inner step can genuinely run first and neither level's `explain()` can see it, because every read is scoped to one reconciler by design.

```python
from cabaxiom import Enclosure

severance = Enclosure(top).prove()
assert severance.airtight                     # no declared ordering dies at a boundary
for cut in severance.severed:
    print(f"{cut.leaner} leans on {cut.resolver}, so order {cut.boundary} after {cut.against}")
```

`Enclosure` walks the tree and, for every name a step declares, finds the steps that would answer it at OTHER levels - every one, not just the names that matched nothing, because a name answered locally AND a level up is exactly as unguarded on the second one. For each pair it asks the deepest common level whether the resolver's representative already precedes the leaner's. Ordered means the intent survives, since an enclave's `apply()` is the whole inner converge. `severance.inverted` is the sharper subset, where the common level orders the pair the wrong way round.

It is pure structure. Nothing runs, no world is touched and it works over sync and async trees alike. Read `severed` as a suspicion, not an error - an enclave may deliberately trust the outer world to converge on its own schedule - but an empty one is a proof the nesting holds.

### Moving between declarations

A step removed from the desired set just stops being mentioned - and whatever it built would leak forever, since nothing prunes what is no longer declared. `Transition` closes that gap statelessly. The caller still holds the previous declaration, so the difference is computable.

```python
import asyncio

from cabaxiom import Transition

cutover = asyncio.run(Transition(previous_steps, desired_steps).converge())
assert cutover.clean         # the leavers are gone AND the new declaration converged
```

It tears down exactly the steps present before but absent now (the leavers, in their own reverse dependency order, self-verifying like every prune), then converges the desired set - teardown first, so a leaver's port, path or name is free before the new world claims it. The returned `Cutover` carries both proofs - `pruned` (the leavers' surviving residue) and `residual` (the converge outcome).

### Foreseeing a failure

`explain()` says what the run WILL do. `foresee()` says what it would lose if one step failed, which is the question you actually have at 3am, asked before anything runs.

```python
casualty = reconciler.foresee(network)
print(casualty.blocked)     # under BestEffort: everything that would report "step blocked"
print(casualty.skipped)     # under Halt: everything in a later group, guaranteed not to start
print(casualty.settling)    # under Halt: its own group, indeterminate by shape
print(casualty.starves)     # capabilities it is the only present provider of
```

The forecast is not a simulation. `blocked` is the Graph's `fallout()` walk and the `Ledger` blames a real failure by running that same walk, so the two cannot disagree. Halt is reported in two channels on purpose, because Halt gates by run POSITION rather than by edges. A strictly later group can never start, while the failure's own group depends on the shape - a fanning executor admitted it whole so it settles, a serial walk skips only what it had not reached. Folding those into one number would be a promise the kernel does not make.

`starves` is a severity note rather than a further casualty. Everything wanting a capability already depends on its provider, so it is already in `blocked`. What starvation adds is what a FUTURE declaration would lose. A `demands` on a capability nobody else provides raises at resolution and a `wants` simply goes quiet.

### Drawing a run

`Mermaid` and `Dot` render an `Explanation` as source text. Both are handed a run that is already resolved and can reach nothing else, so a rendering bug makes an ugly picture and never a wrong run. Contention is drawn without an arrowhead, since it says neither step may run beside the other while taking no view on which of them goes first.

```python
print(reconciler.explain().mermaid())
```

```
graph LR
    subgraph cluster_0["wave 0"]
        n0["Postgres"]
        n1["Cache"]
    end
    subgraph cluster_1["wave 1"]
        n2["Api"]
    end
    n1 -->|expects| n2
    n0 ==>|demands| n2
```

The arrow says which kind of declaration drew it, so the picture shows at a glance which edges the run would still be correct without. Reach for `Mermaid` or `Dot` from `cabaxiom.core.record` when you want to configure one. `explain().mermaid()` and `explain().dot()` are the shorthand for the default.

---

## Examples

The [`examples/`](examples/) directory holds four runnable, self-contained programs. Each builds a real throwaway resource, converges it, ends with an empty residual and cleans up on the way out. Run any of them with `python examples/<name>.py`.

### Checking a declaration before you run it

`Transition` moves the world. `Succession` reads the same two declarations and tells you what the move does to the STRUCTURE, before anything runs - the only member of the proof family that touches nothing at all, so it belongs in a pre-commit hook or a review, not a sandbox.

```python
from cabaxiom import Succession

rift = Succession(previous_steps, desired_steps).compare()
if rift.torn:                                    # a soft edge lost its whole match set
    for shift in rift.quieted:
        print(f"{shift.step.__class__.__name__}.{shift.slot} no longer resolves")
```

The finding it exists for is the **silent** one. When the only step providing `"database"` leaves, a survivor's `wants` does not fail - it goes quiet and the run simply stops waiting for something. `requires` and `demands` are already loud (`demand()` raises the moment membership is final), so `quieted` is precisely the class nothing else reports and it is the only channel that votes. A `Rift` is truthy exactly when torn.

The other channels read the same delta in the other directions - `materialised` (a name that matched nothing now matches something), `widened` and `narrowed` (a fan-in that grew or thinned but still resolves) and `standing` (every name this declaration leans on the world to have already satisfied). That makes the one read answer three questions:

```python
Succession(previous, desired).compare().quieted        # what a cutover would silence
Succession(ours, (*ours, *theirs)).compare()           # what merging two declarations creates
Succession((), mine).compare().standing                # what my declaration assumes the world provides
```

Survivors are matched by `Step.paired`, the one home `Transition` reads to pick its leavers, so a pre-flight cannot disagree with the move it precedes. A step is recognised by the `ident` it calls itself where it has one and by object identity where it does not, which is what makes a declaration **rebuilt from data** comparable at all while leaving every older declaration matching exactly as it did. When not one step is recognised and both sides hold kinds in common, `rift.estranged` names those kinds and the Rift is torn, because the empty verdict that shape used to produce read as a clean bill over a declaration whose every edge was in fact remade.

### Walking a path of declarations

A staged rollout is just several declarations of one world at growing amplitude - and `Itinerary` expresses the whole path as a value, walked one proof-gated `Transition` per hop.

```python
import asyncio

from cabaxiom import Itinerary

itinerary = Itinerary([(), baseline, canary, fleet])   # start from () to build from scratch
passage = asyncio.run(itinerary.converge())
if not passage:
    print(f"stands at waypoint {passage.reached}")     # proven, not assumed
    rollback = asyncio.run(reversed(itinerary).converge())   # the same value, walked back
```

The walk advances only on a clean `Cutover`, so the world never leaves a waypoint it cannot prove it reached. Re-running the same itinerary resumes for free - settled hops no-op through the level-triggered loop - and `reversed(itinerary)` is the rollback with zero extra declarations, because the waypoints already contain every intermediate world. Waypoints share step instances for the steps that persist between them (identity is the kernel's dependency addressing) and the empty declaration `()` marks the path's far ends. Start from it to build from scratch, end at it for a full teardown.

---

## Batteries - declare a dev environment

A setup script that breaks on its second run is dead. `battery.setup` ships ready-made `Step`s for the most common desired state a developer declares - directories, files, symlinked dotfiles, a line in a shell profile, a key in a JSON config - so you get value without writing a single `drift`/`apply` yourself.

```python
import asyncio

from cabaxiom import Reconciler
from cabaxiom.laboratory import Idempotence
from battery.setup import Directory, File, Symlink, LineInFile, JsonKey

class AppDir(Directory):
    def __init__(self): super().__init__("~/.config/myapp")

class Config(File):
    expects = (AppDir,)                                   # ordered after the directory that holds it
    def __init__(self): super().__init__("~/.config/myapp/config.toml", '[core]\nmode = "fast"\n')

class Editor(JsonKey):
    def __init__(self): super().__init__("~/.config/Code/settings.json", ("editor", "tabSize"), 4)

setup = (AppDir(), Config(), Editor(), LineInFile("~/.gitignore", "*.pyc"))
asyncio.run(Reconciler(setup).converge())               # brings the machine to desired state
assert asyncio.run(Idempotence(Reconciler(setup)).prove())   # PROVES a second run is a clean no-op
```

Every battery is a `Step`, so a declared setup **converges** to the machine you want, **self-verifies** by re-probing, **proves idempotent** under `Idempotence` (not trusted, proven), **self-heals** when the world drifts and **reverses** through `prune` - and it is never reckless. `Directory` prunes only when empty, `JsonKey` removes its key but not a file it shares, so a teardown never deletes what it did not fully own.

The batteries - `Directory`, `File`, `Symlink`, `LineInFile`, `JsonKey`. They live in `examples/battery/` and are deliberately NOT part of the wheel, because a demonstration that ships as public API is a promise nobody asked for - the kernel is domain-agnostic on purpose and the moment a `Symlink` sits inside it that claim needs an asterisk. Copy the ones you want or read them as the worked answer to what a real `Step` looks like. They are held to the same gate as the kernel (strict typing, full branch coverage) and they import it through the same front door you do. See `examples/dev_setup.py` for the full arc - declare, converge, prove, drift, self-heal, reverse.

---

## Fleet standards - prove your repos conform

Stop asking "is every repo compliant?" and prove it. `battery.repository` reconciles one repository or a whole fleet, to an organisation standard and the residual reads as a **compliance report**. An empty residual PROVES every repo conforms, a non-empty one NAMES the repos that resist.

```python
import asyncio

from cabaxiom import Reconciler
from battery.repository import GitHub, RepoSetting

gh = GitHub(token)
standard = [RepoSetting(gh, repo, "has_issues", True) for repo in ("acme/api", "acme/web", "acme/cli")]

report = asyncio.run(Reconciler(standard).assess())    # read-only, names the repos out of standard
residual = asyncio.run(Reconciler(standard).converge())   # enforce it across the fleet
assert not residual                          # empty means the fleet conforms, PROVEN by re-probe
```

### Batteries - declare a warehouse (`battery.data`)

The data batteries take a PORT, never a driver. Any PEP-249 connection the domain's own client minted -
Snowflake, Postgres, DuckDB or the standard library's sqlite3, which is what the whole suite proves
them on. `Schema` and `Table` converge and tear down honestly (a table holding rows is LEFT STANDING and
named, never dropped), `Loaded` is the idempotent incremental load with the watermark as its judge,
`Fresh` and `Quality` are pure sensors - criticals dirty the proof, advisories never do - and `Lineage`
is data lineage as a trace - an Observer on the kernel's own `produced()` seam, one JSONL line per clean
producer, with not one step instrumented. Identifiers are vetted, never quoted - the vet is the
injection guard. `DbtRun` reads the run state dbt itself records (`target/run_results.json`) and runs `dbt build`
through stdlib subprocess only when the reading is dirty - the command is the seam, so no dbt in the
dependencies and the suite rehearses it offline. The full arc, proofs included, runs in
`examples/data_warehouse.py`.

The GitHub client is stdlib `urllib` only - no `requests`, no `PyGithub` - and its transport is injectable, so a compliance run rehearses against a fake in-memory GitHub with no token and no network, exactly the way the kernel rehearses everything. The self-verifying loop is the point. `apply` patches a repo but the RE-READ is the judge, so a setting the API accepted yet did not change (a locked or archived repo) is caught and named, never called done on the strength of the API's word. When a repo carries many standards and one will not hold, `Isolation` delta-debugs them down to the single blocker and names it (`examples/repo_isolation.py`) and file standards - a required LICENSE, a gitignore entry - reuse the `battery.setup` batteries on a checked-out path. See `examples/repo_standards.py`.

---

## Examples

The [`examples/`](examples/) directory holds runnable, self-contained programs. Each builds a real throwaway resource (or an in-memory one), converges it, ends with an empty residual and cleans up on the way out. Run any of them with `python examples/<name>.py`.

**Start here:** the three below are the grounding trio (a real git repo, a real filesystem tree, a parallel service graph). **Then reach for the feature tours:** [`async_service_mesh.py`](examples/async_service_mesh.py) (concurrent bring-up on the event loop, plus `Supervised` bounding a hung dependency with a `Deadline`), [`parallel_fixpoint.py`](examples/parallel_fixpoint.py) (`ThreadDispatcher` fanning a blocking domain across worker threads, settled by `Fixpoint`), [`controller_watch.py`](examples/controller_watch.py) (the reactive `watch()` loop with `Clean` vs `Stable` stop conditions on a flapping service), [`fractal_idempotence.py`](examples/fractal_idempotence.py) (`Idempotence.prove()` catching a churn a single converge cannot, then `Enclave` nesting whole stacks and proving the tree), [`scoped_rollout.py`](examples/scoped_rollout.py) (`Only` / `Skip` / `WithTag` / `WithoutTag` selection and a hard `requires`), [`resilient_run.py`](examples/resilient_run.py) (`BestEffort` blocking a failure's dependents, `Retry` recovering the transient and a live `Observer` + `Journal`), [`blue_green_transition.py`](examples/blue_green_transition.py) (`Transition` pruning what left the declaration and converging what joined), [`convergence_shapes.py`](examples/convergence_shapes.py) (the convergence axis end to end - `Shrinking` vs `Fixpoint` on a churning world, `Linear` backoff pacing a stall and a custom convergence built on the `BaseLooping` seam) and [`fanout_reduce.py`](examples/fanout_reduce.py) (the `Fanout` base - one step lists the world, declares a child reconciler over what it found and reduces through namespaced keys, the expansion the kernel refuses to make mid-run and supports honestly outside it).

### `dev_setup.py` - the batteries, proven

A development environment declared with `battery.setup`, then converged, certified idempotent, drifted, self-healed and torn down - the whole beachhead arc against a throwaway temp home, safe to run again and again.

### `repo_standards.py` - the fleet, proven

An organisation standard reconciled across a fleet of repositories against a fake in-memory GitHub - the compliance report that names who resists, the enforcement and the empty residual that proves the fleet conforms.

### `repo_isolation.py` - which standard will not hold

One repository, several standards, one of them structurally unsatisfiable. `Isolation` delta-debugs the standards down to the single blocker and mints an `Indictment` naming it, instead of leaving you to read a wall of residual.

### `blast_radius.py` - the forecast, checked against the run

`foresee()` predicts what a failing migration would cost, the script then runs the fleet for real and diffs the prediction against the residual. They match exactly, because both read the one `fallout()` walk. It also shows why Halt is reported in two channels. A serial walk and a fanning one skip different sets and the difference is precisely the group the forecast called indeterminate.

### `silent_edges.py` - the failures that never fail

One ordinary refactor - extracting a database into its own stack - passes `Transition`, `Idempotence` and `explain()` without a mark, while silently dropping both edges that ordered the api and the worker after it. `Succession` names what the change took away, `Enclosure` names what the nesting voids right now and one fix satisfies both. Neither touches the world.

### `git_repo_state.py` - the flagship

Drives a real throwaway git repository through plain `subprocess` calls, over the chain `GitConfig -> InitialCommit -> LocalBranch`. The steps go in scrambled and `Kahn` resolves the order. Every `assess()` is a genuine read, every `apply()` a genuine mutation. Read it first. Its full output is at the top of this README.

### `filesystem_layout.py`

Brings a temp directory tree to a desired layout with `Directory` and `TextFile` steps, ordered so directories land before the files inside them. Then it tampers with a file behind the reconciler's back and re-converges. This is the clearest look at drift as something you recover from.

```
Tampering: overwrite config/app.toml with the wrong content
  drift now sees 1 problem(s):
    ! /tmp/reconciler-fs-0gafhd5o/config/app.toml: content does not match desired
Converge again to self-heal:
  applied this run:
    + /tmp/reconciler-fs-0gafhd5o/config/app.toml: wrote desired content
  residual: empty -> layout verified by re-probe
```

### `parallel_fixpoint.py`

Provisions a service dependency graph with `ThreadDispatcher`, so each dependency wave fans across worker threads and settles a multi-pass replica scale-up with `Fixpoint` convergence.

```
Resolved waves (Kahn):
    wave 0: Network
    wave 1: Cache, Database
    wave 2: AppServers

Converge (ThreadDispatcher, Fixpoint convergence):
  applied this run: 6 change(s)
    + Network: provisioned
    + Cache: provisioned
    + Database: provisioned
    + AppServers: scaled up to 1 replica(s)
    + AppServers: scaled up to 2 replica(s)
    + AppServers: scaled up to 3 replica(s)
  residual: empty -> whole stack verified by re-probe
```

---

## Install

```
pip install cabaxiom
```

Nothing else is pulled in. The kernel leans on the standard library alone and everything you need is re-exported from the top-level package.

---

## When not to reach for this

The re-probe is the entire guarantee, only as honest as your `assess()`. If a step cannot observe the thing it changed, `converge()` can't tell a real fix from a no-op. An empty residual then means only that `assess()` reported nothing. Write `assess()` to read the world, never to echo what `apply()` intended.

A few more boundaries, stated plainly:

- Reconciliation earns its keep when a system will drift and you want it to keep correcting itself. If all you need is a one-shot transformation that runs once and is never checked again, a plain function is simpler and you should write that instead. The value here is the loop.
- It does not poll or schedule on its own. `watch()` sleeps until a step announces its world moved through `Step.watch()`, so the clock belongs to the world rather than to a timer.
- It's not a state store. It keeps no history and no desired-state document. Each step owns its own notion of desired and observed.
- The engine is asyncio to the bone. A blocking or CPU-bound `apply()` belongs on `ThreadDispatcher`, which relocates the call to a thread, while everything else stays on the caller's loop.

---

## Development

The kernel's internal composition - who holds whom and how a converge runs - is mapped in [docs/architecture.md](docs/architecture.md).

```
pip install -e ".[dev]"
ruff check .
pytest --cov=cabaxiom --cov-report=term-missing
```

The suite is written on the standard-library `unittest` framework with subtests and runs under pytest with coverage, currently at 100% across ordering, execution, convergence, cancellation, planning and pruning. CI lints with Ruff and runs the full suite on CPython 3.12 through 3.14, on every push to `master` and every pull request. `fail-fast` is off, so a break on one interpreter does not hide the others.

---

## Status

The kernel is feature-complete. Every axis the design set out to cover - scoping, ordering, execution (serial, threaded and async), convergence, backoff, retry, cancellation, the control loop, idempotence proofs, fractal nesting and stateless cutover - is in and exercised at 100% coverage. The surface is settled. From here the work is hardening and the Semantic Versioning promise, not new features. The next and last milestone is the 1.0.0 freeze.

This is where the building stops.

---

## License

Released under the MIT License. See [LICENSE](LICENSE).
