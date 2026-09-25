# Cabaxiom

Declare the state you want. The loop reads the world, finds the gap and closes it. Then it looks again to prove the gap is gone.

[![CI](https://github.com/pizgariu/cabaxiom/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/pizgariu/cabaxiom/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/cabaxiom.svg)](https://pypi.org/project/cabaxiom/)
[![Python versions](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue.svg)](https://github.com/pizgariu/cabaxiom)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

A reconciliation kernel with no domain baked in and nothing to install alongside it. You describe each concern as a `Step` that reads its own drift and knows how to close it. The kernel resolves the order and runs the steps, then reads reality back. A clean result is verified, not assumed. Pure standard library, zero runtime dependencies.

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

Cabaxiom is that principle and nothing else, boiled down to a small kernel with no domain vocabulary. It has no idea what a file or a git repo is. You teach it one `Step` at a time.

---

## The building blocks

### `Step` - a unit of desired state

You subclass `Step` and answer one question. What is the gap between the world and what I want? You report that gap as drift and you know how to close it.

```python
from cabaxiom import Step, DriftItem

class Config(Step):
    def __init__(self, key: str, want: str) -> None:
        self.key = key
        self.want = want

    async def assess(self):
        have = await read_config(self.key)            # WATCH
        if have == self.want:                         # COMPARE
            return self.verified()                    # no gap
        return self.drifted(self.key, f"want {self.want!r}, have {have!r}")

    async def apply(self):
        await write_config(self.key, self.want)       # ACT
        return self.changed(self.key, "wrote desired value")
```

`assess()` is WATCH plus COMPARE in one method and it never mutates. `apply()` is ACT and it must be idempotent. The kernel calls both. You never write the loop. The git example at the top is three steps of exactly this shape.

One read, four channels. `assess()` returns an `Assessment` carrying `deviation` (the gap), `plan` (what closing it would do), `advisory` (a finding about a world that is already correct) and `footprint` (what a teardown would remove). One probe fills all four, so an expensive read is paid for once and the four answers describe the same moment. `verified()`, `drifted()`, `unchanged()` and `changed()` are the shorthands for the ordinary cases, while a step that needs more than one channel returns a full `Assessment`.

The kernel reads only two fields out of your drift, through the `Drift` protocol - a `name` and a `message`. That is the entire contract. `DriftItem(name, message)` is the ready-made implementation and covers almost every step. Because the kernel reads nothing else, your domain stays entirely yours.

### The declaration language - say what you need, get ordering for free

A step names what must be ready before it, while the slot it uses says both HOW the thing is addressed and how badly it is needed.

```python
class InitialCommit(Step):
    expects = (GitConfig,)               # a class, softly

class Api(Step):
    demands = ("database",)              # a capability, and the run is wrong without it

class Postgres(Step):
    provides = frozenset({"database"})   # what answers a capability

class Migrate(Step):
    contends = frozenset({"db"})         # never runs beside anything else naming "db"
```

Eight slots in four pairs, one soft and one hard in each. A soft slot orders against the thing if it is present and shrugs if it is not. A hard slot refuses the run when nothing answers it.

| Addressed by | Soft | Hard | Resolves to |
| --- | --- | --- | --- |
| Class | `expects` | `requires` | every step of that class |
| Class, reversed | `prepares` | `mandates` | run BEFORE the steps named |
| Capability | `wants` | `demands` | every step whose `provides` names it |
| Instance | `uses` | `needs` | that one step and no other |

`contends` is the one declaration that is not an edge, nor could it be. An edge says which of two steps comes first. Contention says neither may run beside the other and takes no view on the order, so it is read where the run is SEATED - a wave shape puts rivals in different waves, a chain shape puts them in the same chain.

Hand the reconciler these in any order and it derives one dependency graph, which the ordering, the seating guard, the scope and `explain()` all read. A cycle raises `Cycle` at construction and names the steps it could not place.

### `Reconciler` - the engine

```python
import asyncio
from cabaxiom import Reconciler

reconciler = Reconciler([LocalBranch(...), GitConfig(...), InitialCommit(...)])

await reconciler.plan()                  # the ordered gap, no changes made
residual = await reconciler.converge()   # WATCH -> COMPARE -> ACT -> re-probe

if not residual:
    print("verified clean")
```

The kernel is async native and there is exactly one of it, awaited on your own loop. A blocking `apply()` gets there through `ThreadDispatcher`, which relocates the call to a worker thread and lays the retry back over it.

`converge()` returns a `Residual`, a `list[Drift]` of whatever gap outlived the run. Empty means the kernel acted, probed again and confirmed reality now matches intent. The changes made along the way live on a separate channel, `residual.applied`, which is what the examples print under "applied this run". Keeping the two apart means "what I fixed" never blurs into "what is still wrong".

### `watch()` - the loop that never ends

`converge()` is one turn of the crank. `watch()` turns it, hands back the residual, then waits for a step to say look again.

```python
async for residual in reconciler.watch():
    log_gap(residual)
```

The difference from a tick source is who decides when to look. A step implements `watch()` to yield when its own corner of the world moves. The wake carries no payload deliberately - a level-triggered wake costs one clean pass when it is spurious, while an edge-triggered one costs correctness. `Clean` and `Stable` are the stop conditions.

---

## Choosing behavior

Every axis of behavior is a small object you swap. The defaults resolve to `Kahn`, `Serial`, `Once` and no cancellation. Pass nothing and you get all four.

| Axis | The question it answers | Default | Alternatives |
| --- | --- | --- | --- |
| **Ordering** | Given the derived graph, in what order do steps run? | `Kahn` (dependency waves) | `DFS` (flat post-order), `Priority(key=...)` (best-first frontier over a key), `Components` (split into independent chains) |
| **Dispatcher** | How does an ordered group actually run? | `Serial` (one step at a time) | `Parallel` (fan each wave onto the loop), `Pipeline` (run independent chains concurrently), `ThreadDispatcher` (relocate a blocking step to a worker) |
| **Scope** | Which of the handed steps take part at all? | `Scope` (all of them) | `Only(...)` (the named types plus everything they depend on), `Skip(...)` (drop the named types, no cascade) |
| **Error policy** | When a step fails, stop or push on? | `OnError.FailFast` | `OnError.BestEffort` (finish the group, collect failures) |
| **Convergence** | How many apply-then-probe passes per converge? | `Once` (single pass) | `Fixpoint(max_passes=...)` (repeat until the residual stops changing by value or a ceiling is hit) |
| **Cancellation** | When should a run abort cooperatively between steps? | `Cancellation` (never aborts) | `Deadline(seconds)` (wall-clock budget), `Flag` (manual switch), the composites `AnyOf` / `AllOf` / `Majority` that nest into a tree or `Quorum(..., rule=...)` with `Some` / `Every` / `Most` for a custom rule |

```python
from cabaxiom import Reconciler, Parallel, Fixpoint, Deadline

reconciler = Reconciler(
    steps,
    dispatcher=Parallel(),
    convergence=Fixpoint(max_passes=10),
    cancellation=Deadline(seconds=30),
)
residual = await reconciler.converge()
```

### More than converge

A `Reconciler` reads and writes state through a handful of verbs. Each fans across every step in resolved order, reversed for the teardown verbs.

- `drift()` reports the gap without touching anything.
- `plan()` is a dry-run read of the pending diff, in resolved order.
- `audit()` returns advisory findings about a concern that is already satisfied. These never trigger an apply.
- `footprint()` previews what a teardown would remove, in reverse order.
- `converge()` applies, then re-probes, returning the `Residual`.
- `prune()` is the reverse-order teardown itself, verifying the same way a converge does.

Two more read the run rather than the world, so neither touches anything and neither is a coroutine.

`explain()` hands back what was resolved - the groups the dispatcher will walk plus one `Reason` per declaration the steps actually wrote. A flat "Api depends on Postgres" is not enough to act on when eight slots can draw that edge, so a Reason names the slot, what was written and whether it was hard.

```python
told = reconciler.explain()
told.groups                     # (('Postgres', 'Cache'), ('Api',))
told.because("Api")             # Api.expects Cache -> Cache
                                # Api.demands 'database' -> Postgres
```

`foresee(step)` is the counterfactual twin. If that one step failed, what would this run lose?

```python
told = reconciler.foresee(postgres)
told.blocked                    # ('Api', 'Cdn')  - everything that transitively needs it
told.starves                    # ('database',)   - it is the only present provider
bool(told)                      # True, because the damage is not contained
```

Read `blocked` for what it is. It says what a failure WOULD cost, not what the kernel withholds - `OnError.BestEffort` records the failure and keeps going, so those steps still run, against state nobody put there. Naming them is the measurement that says how much a run stands to lose.

### Drawing a run

`Mermaid` and `Dot` render an `Explanation` as source text. Both are handed a run that is already resolved and can reach nothing else, so a rendering bug makes an ugly picture and never a wrong run.

```python
from cabaxiom import Mermaid

print(Mermaid()(reconciler.explain()))
```

```
flowchart TD
    subgraph g0["wave 1"]
        Postgres[Postgres]
        Cache[Cache]
    end
    subgraph g1["wave 2"]
        Api[Api]
    end
    Cache -.->|expects| Api
    Postgres -->|demands 'database'| Api
```

A dashed arrow is a soft declaration, so the picture shows at a glance which edges the run would still be correct without.

---

## Examples

The [`examples/`](examples/) directory holds four runnable, self-contained programs. Each builds a real throwaway resource, converges it, ends with an empty residual and cleans up on the way out. Run any of them with `python examples/<name>.py`.

### `derived_order.py` - the run, read before it runs

Every verb in it reads the RUN rather than the world, so nothing is touched until the last line. A six-step stack uses every slot in the language. The script prints the resolved waves, one `Reason` per declaration behind them, the wave the seating split because two steps `contends` for the same resource, what a `Vault` failure would cost and the whole thing as a Mermaid diagram. Read it second.

### `git_repo_state.py` - the flagship

Drives a real throwaway git repository through plain `subprocess` calls, over the chain `GitConfig -> InitialCommit -> LocalBranch`. The steps go in scrambled and `Kahn` resolves the order. Every `drift()` is a genuine read, every `apply()` a genuine mutation. Read it first. Its full output is at the top of this README.

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

Provisions a service dependency graph with the `Parallel` dispatcher, so each dependency wave is gathered on the event loop and settles a multi-pass replica scale-up with `Fixpoint` convergence.

```
Resolved waves (Kahn):
    wave 0: Network
    wave 1: Cache, Database
    wave 2: AppServers

Converge (Parallel dispatcher, Fixpoint convergence):
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
- It does not poll or schedule on its own. `watch()` advances when one of your own steps says the world moved. Nothing in the kernel holds a clock.
- It's not a state store. It keeps no history and no desired-state document. Each step owns its own notion of desired and observed.
- Concurrency is the event loop, plus `ThreadDispatcher` for a blocking domain. Neither scales CPU-bound apply work across cores. This is built for I/O-bound reconciliation.

---

## Development

```
pip install -e ".[dev]"
ruff check .
pytest --cov=cabaxiom --cov-report=term-missing
```

The suite is written on the standard-library `unittest` framework with subtests and runs under pytest with coverage, currently at 100% across ordering, execution, convergence, cancellation, planning and pruning. CI lints with Ruff and runs the full suite on CPython 3.10 through 3.14, on every push to `master` and every pull request. `fail-fast` is off, so a break on one interpreter does not hide the others.

---

## License

Released under the MIT License. See [LICENSE](LICENSE).
