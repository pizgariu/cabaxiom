# The cost baseline

**Wall time here is informational. The COUNTS are the gate.**

Every count below is asserted as an exact equality by `tests/test_cost.py`, which fails the suite when one
moves. Every millisecond below was measured once, on one machine, on one afternoon and is recorded so a
human can answer "what does a five thousand step graph cost" without running anything - never so that a
number in seconds can fail a build. Regenerate the whole page with

    python3 bench/cost.py                 # the counts, the timings and the growth
    python3 bench/cost.py --deep          # the same scaling sweep an order of magnitude larger
    python3 bench/cost.py --json bench/out/cost.json

`bench/cost.py` imports its counters from `tests/test_cost.py`, so this page is produced by the very
instruments the gate asserts and the two cannot drift apart.

## Read on

- date - 2026-08-12
- interpreter - CPython 3.14.4 (main, Jun 18 2026, GCC 15.2.0)
- platform - Linux x86_64, kernel 7.0.0-27-generic
- machine - Intel Core Ultra 5 125H, 18 logical cores
- timings - best of 3, `gc.collect()` between rounds, no coverage instrumentation
- the suite itself runs these same gates under `pytest --cov`, which is roughly 3x slower than the numbers
  here. The gate holds either way, because it asserts counts.

## The counts and what they mean

### One converge over N independent steps, default axes

| what | count | independent of N |
| --- | --- | --- |
| `apply()` entries | N | 1 per step |
| `assess()` entries | N | 1 per step, the re-probe that proves the pass |
| `began` / `acted` / `remained` | 1 / 1 / 1 | per CYCLE, not per step |
| `dispatching` / `stepped` / `produced` | N / N / N | 1 per step each |
| `retried` | 0 | nothing failed |
| dependents map built | no | a clean run never asks for the inversion |

Read at N = 100, 200 and 400. The per-step total is exactly 2 verb entries and 3 unit hooks at every size, and
the per-run total is exactly 3 pass hooks at every size. A converge that entered a verb more than a small
constant times N would be quadratic in disguise and no residual would ever say so.

### One teardown over N steps

| what | count |
| --- | --- |
| `prune()` entries | N |
| `assess()` entries | 0 - a teardown is deliberately not re-probed |
| `pruned` | 1 |
| `began` / `acted` / `remained` | 0 / 0 / 0 - the pass hooks belong to converge |

### How many passes a convergence takes

| world | passes | applies |
| --- | --- | --- |
| clean, `Once` | 1 | N |
| clean, `Fixpoint(max_passes=10)` | 1 | N |
| two steps needing three applies each, `Fixpoint` | 3 | 6 |

A `Fixpoint` over an already clean world costs what `Once` costs. The third pass's own re-probe is the proof,
so no fourth pass is ever spent confirming it.

### Resolution, counted as name lookups

The counter is the vocabulary's own `Addressing.found`, injected as a metered `Vocabulary`, so the number is
literally how many times the graph was asked to resolve a declared name.

| declaration | names asked | steps reached | derived edges |
| --- | --- | --- | --- |
| chain of 200 (`uses`) | 199 | 199 | 199 |
| fan of 200 (`uses`) | 199 | 199 | 199 |
| 100 replicas + 100 consumers (`expects`) | 100 | 10000 | 10000 |
| layered 32x32 span 2 (1024 steps) | 1984 | 1984 | 1984 |

The class fan is the one to read twice. Doubling that declaration doubles the ASKS and quadruples the EDGES,
which is the correct answer - the quadratic is in the declaration, not in the derivation. A derivation that
re-asked per edge would show its asks following the edges.

Two further resolution costs, both by design and both pinned so they stay where they are:

| phase | asks, for a chain of 10 |
| --- | --- |
| the whole `Reconciler` construction, soft names | 9 - the derivation only, no later phase re-asks |
| a hard name (`needs`) | 18 - the derivation, then `demand()` once membership is final |
| `Only` scope keeping everything | 18 - the full derivation, then a second one over the kept set |
| each `explain()` call | +9 - the per-name read keeps nothing, by design |

Class membership inside the derivation is answered by an index and not by a walk. A `Roster` of 100 and one of
400 both cost exactly one hash per probe. Zero hashes would mean the list scan is back, which is the
quadratic this kernel already shipped once - a hundred seconds on a 200000 step chain, against a third of one
second for the ordering it fed.

### The failure machinery on a clean run

| what | count |
| --- | --- |
| dependents map built after a clean converge | no |
| dependents map built after one `BestEffort` failure | yes, once and cached |
| failure drift for 2 failures with 20 shared dependents | 22 - one per blocked step, not one per culprit edge |

### The neutral axes cost nothing rather than behaving the same

| axis | neutral | proof |
| --- | --- | --- |
| retry | `Retry(1)` | hands the write callable back by identity, wrapping nothing |
| authority | none injected | `Write.raw` IS the raw call, with no permit layer |
| authority | injected, no `leases` declared | 0 acquires, 0 releases |
| observer | `Observer()` | 0 reads of the residual it is handed, 0 reads of a step's name |
| warrant | none injected | no leading probe - pinned in `tests/test_warrant.py`, not repeated |

### Every dispatcher costs the same

`Parallel`, `Supervised`, `ThreadDispatcher()` and `ThreadDispatcher(Supervised())`, each with `Retry(1)` and
with `Retry(2)`, over one chain of 20 steps - eight runs, one reading:

    applies 20, reads 20, began 1, dispatching 20, stepped 20, produced 20, acted 1, remained 1,
    retried 0, pruned 0, payload keys mounted 19

That crossing is the one this suite was missing. `ThreadDispatcher` composed with `Retry(2)` once ran
`apply()` ZERO times, because `to_thread` handed back an unawaited coroutine and the bug shipped because no
test had put those two objects in one `Reconciler`. A count of the verb entries is the shortest statement of
that defect.

## The wall time, informational

### Doubling V and E together, layered 32 wide, span 2

| V | E | resolve | converge | prune | converge per V+E |
| --- | --- | --- | --- | --- | --- |
| 512 | 960 | 2.8 ms | 3.7 ms | 1.6 ms | 2.5 us |
| 1024 | 1984 | 7.4 ms | 7.8 ms | 4.3 ms | 2.6 us |
| 2048 | 4032 | 12.7 ms | 15.2 ms | 7.4 ms | 2.5 us |
| 4096 | 8128 | 24.3 ms | 28.4 ms | 14.0 ms | 2.3 us |
| 8192 | 16320 | 49.7 ms | 56.7 ms | 26.7 ms | 2.3 us |

Adjacent growth, against a size that doubles - resolve 2.67x, 1.71x, 1.92x, 2.05x and converge 2.10x, 1.94x,
1.87x, 2.00x. Both track the size and the microseconds per V+E fall slightly with scale rather than rising,
which is what linear looks like once the fixed costs are amortised.

### Holding V at 2048 and growing E alone

| E | resolve | converge |
| --- | --- | --- |
| 2016 | 9.4 ms | 14.0 ms |
| 4032 | 12.6 ms | 14.4 ms |
| 8064 | 17.3 ms | 15.3 ms |
| 16128 | 28.2 ms | 16.3 ms |
| 32256 | 47.2 ms | 18.8 ms |

Resolution carries the edge term - 16x the edges for 5x the time, since the vertex term dominates at the
bottom of that range. The converge barely moves, because a write path is paid per step and the edges only
decide how the waves are cut and what each payload holds.

### The Ledger inversion on a dense graph

| declaration | E | first ask | cached ask |
| --- | --- | --- | --- |
| 100 replicas + 100 consumers | 10000 | 0.266 ms | 0.0011 ms |
| 200 replicas + 200 consumers | 40000 | 0.912 ms | 0.0006 ms |
| 400 replicas + 400 consumers | 160000 | 3.700 ms | 0.0007 ms |

4x the edges for roughly 3.5x to 4x the time, so the inversion is linear in the edges and the cached ask is
three orders of magnitude cheaper than building it. Both halves of the lazy claim are worth what the docstring
says they are worth - which is exactly why a clean run must never pay it and why the gate asserts that it
does not.

### One large run, end to end

    layered 50x100 span 3      V=5000  E=14850
    resolve 35.3 ms            converge 33.3 ms
    applies 5000               reads 5000              residual 0

A five thousand step declaration resolves and converges in about seventy milliseconds on this machine, with
every step written once and read once. The gated version of this run is 1024 steps over 1984 edges, bounded by
a 60 second timeout - roughly a hundred times the measured cost, because that bound exists to catch a run that
stopped finishing and never to grade the machine it runs on.
