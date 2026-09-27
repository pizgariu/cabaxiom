# Changelog

All notable changes to Cabaxiom are recorded here. This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html). What reconciliation is and why this kernel exists, lives in the [README](README.md).

Every release is a pre-release on the road to the 1.0.0 freeze.

## [Unreleased]

Nothing yet.

## [0.5.2] - 2026-09-27

**Two reads of a resolved run that answered less than they knew.**

### Fixed
- **`explain()` said nothing about the contention that seated the run.** `contends` is not an edge, so it moves steps between groups without ordering them. Three independent steps came back in two waves with an empty `reasons`, empty `edges` and nothing drawn, so a reader could see the split and never learn its cause. An `Explanation` now pairs each contended resource with its rivals. Both renderers draw that as an undirected link rather than an arrow, since the declaration takes no view on which of the two goes first.
- **`because()` answered a typo with silence.** A name this run never resolved came back as an empty tuple, which is also what a step that declared nothing comes back as. Two different findings spelled the same way. It refuses an unresolved name now, the way `foresee()` already refused one.

### BC break
Nothing. `Explanation` grew a keyword argument with a default, so a caller or a `Diagram` written against 0.5.0 still works. `because()` raising `Unresolvable` is the repair - a name it refuses is one it previously answered wrongly.
## [0.5.1] - 2026-09-27

**Three defects in the drawing axis 0.5.0 shipped, all of them in what the picture says rather than in what the run does.**

### Fixed
- **A capability could close a Mermaid edge label.** An edge label is delimited by pipes and a capability is free text a domain writes, so `provides = {"cache|store"}` rendered `-->|demands 'cache|store'| Api` and the flowchart stopped parsing at the pipe. The label is quoted now and a quote inside it becomes the entity Mermaid spells it with.
- **A DOT label flattened a quote into an apostrophe.** A capability holding a double quote was rewritten rather than escaped, so the drawing named something nobody declared. It is escaped now, backslash first. The guard meant to catch this compared one count to itself, which is an assertion that cannot fail.
- **Two instances of one class were drawn twice.** Both renderers key a node by name, so a run holding two instances of one class declared the node twice and drew every arrow twice. DOT rendered that as two parallel edges between the same pair, which reads as two distinct dependencies. A shared node is one node, so it is emitted once.

### BC break
Nothing. The rendered text changes for a declaration that carries punctuation. No API moved.
## [0.5.0] - 2026-09-26
**One derivation. Every question about what depends on what is answered by the same object, while the language it reads grew from one slot to eight.**

### Added
- **`cabaxiom.Graph`, the one home for every edge a declaration draws.** Seven places used to walk the declarations themselves - four ordering strategies, the seating guard, `Only`'s closure and `explain()` - and the walks had already drifted apart. The guard resolved a class name to every instance of that class while the ordering resolved it to the first one, so a run holding two of a kind could be seated in a shape the guard called clean and the order called impossible. There is one `Graph` per run now, built by the `Reconciler` and handed to everything downstream, so those answers are about one world rather than four opinions about four.
- **Eight declaration slots in four pairs plus the table that holds them.** `expects`/`requires` name a class, `prepares`/`mandates` name a class and run BEFORE it, `wants`/`demands` name a capability that `provides` answers, `uses`/`needs` name one step by identity. The soft half of each pair orders against the thing when it is present and shrugs when it is not. The hard half refuses the run. They are rows in a `Vocabulary` rather than branches in the derivation, so growing the language is adding a row and nothing that reads edges has to learn the new one.
- **`contends`, the declaration that is not an edge and could not be.** An edge says which of two steps comes first. Contention says neither may run beside the other and takes no view on the order, so drawing it as an edge would force a sequence the domain never asked for. It is read where the run is SEATED - `Kahn` splits a wave that holds two rivals, `Components` unions them into one chain. Whether two seats run at the same time is derived from the placement rule each shape already declares, so a shape added later answers it the day it declares its placement.
- **`Malformed`, `Unresolvable` and `Misconfigured`, the kernel's named refusals.** Each subclasses the builtin it replaces, so `except TypeError` and `except ValueError` keep working. They have no shared root deliberately - a malformed declaration, an unsatisfiable run and a misconfigured strategy are three unrelated mistakes, so one base would invite a caller to catch all three where they meant to catch one.
- **`Explanation.reasons` and `because(step)`.** A flat "Api depends on Db" was enough when one slot drew every edge. With eight it is a question nobody asked, because a class named softly, a capability named hardly and an instance named by identity read identically once flattened and have three different fixes. A `Reason` carries the slot, what was written, what it resolved to and whether it was hard.
- **`Reconciler.foresee(step)`, explain()'s counterfactual twin.** If that one step failed, what would this run lose? `blocked` is the `Graph`'s own `fallout()` walk, which is the closure walk with the direction reversed, so the forecast cannot drift from the derivation it forecasts about. `skipped` and `settling` are the FailFast answer and come off the run position instead, because FailFast gates by where a step sits and not by what depends on it. `starves` names the capabilities the step is the only present provider of.
- **`cabaxiom.Diagram`, with `Mermaid` and `Dot` on it.** A diagram is a strategy over an `Explanation` and reaches nothing else - not the `Reconciler`, not the `Graph`, not a `Step` - so a rendering bug makes an ugly picture and never a wrong run. It draws the reasons rather than the edges, so an arrow carries the declaration that drew it and a soft one is dashed.
- **`cabaxiom.records`, where the verdicts of a run live.** `Residual`, `Explanation`, `Reason` and `Casualty` hold what they were handed and do no work, which is why they outlive the `Reconciler` that made them. The engine imports them and nothing there imports the engine.
- **`examples/derived_order.py`.** Six steps using every slot in the language, where nothing touches the world until the last line. It prints the resolved waves, the declaration behind each edge, the wave the seating split for contention, what one failure would cost and the run as a Mermaid diagram.

### Fixed
- **A seating that dropped a step passed the guard.** The check asked whether each dependency was placed correctly relative to its dependent, yet asked it only of dependencies it could find in the seating. One placed nowhere was skipped rather than answered, so `Levels(((api,),)).verify(graph)` came back clean while `db` never ran and the run reconciled a smaller world than the caller passed in. A step seated into two groups vanished the same way and then ran twice. Both are refused before any placement is judged.
- **A refusal blamed the declaration when the scope was at fault.** A scope chooses membership, which is what the hard-presence rule reads, so `Skip(Vault)` could turn a correct run into one the caller's own declaration refuses. The refusal then advised loosening a `demands` that was right, which fixes the message and breaks the next run. `demand()` is handed the derivation it was narrowed from and tells the two apart.
- **The README taught an API this project had deleted.** `drift()` as a step hook, a synchronous `converge()`, a `Controller` and an `Executor` were all still written down as the way to use the kernel. `tests/test_docs.py` reads the prose now - it refuses a name in a code fence the package does not export, refuses a retired name anywhere, refuses an engine verb shown without `await` and requires every shipped slot to be documented.
- **Two steps that compare equal collapsed into one node.** Identity is the dependency currency, since every structure the kernel derives is keyed by step instance. A `@dataclass` step slipped past the class-definition check because a decorator runs after the class body, so the guard fires again at first construction.

### BC break
- `Step.after` is now `Step.expects`. It is the same slot with the same meaning - the name changed because it stopped being the only one, while `after` reads as an ordering primitive rather than as a dependency.
- `Ordering.__call__`, `.levels()` and `.chains()` take a `Graph` instead of a tuple of steps. A custom Ordering reads `graph.steps` for the membership and `graph.dependencies(step)` for the edges.
- `Partition.verify()` takes the `Graph` the seating came from. A custom Dispatcher that builds and verifies its own shape writes `partition.verify(graph)`.
- `Scope.select()` takes a `Graph`. A custom Scope reads `graph.steps` and can now narrow along `graph.closure()` instead of walking a slot itself.
- `Priority(key=...)` receives the step, not its class. Write `key=lambda step: type(step).__name__` for the old behaviour. An instance-addressed run can hold two steps of one class that deserve different priorities, which a key seeing only the class cannot express.
- A `Partition` shape declares `_placement` as a class attribute checked at class definition. A shape without one raises `Misconfigured` at the class statement rather than at its first `verify()`.
- `Kahn`'s flat order is its waves flattened. It used to ask `TopologicalSorter.static_order()`, which breaks ties its own way, so the flat order was not the order the waves would run in. Anything that depended on the old tie-breaking sees a different but equally valid topological order.
- `Explanation` and `Residual` moved to `cabaxiom.records`. Both are still exported from `cabaxiom` itself, so `from cabaxiom import Residual` is unchanged.

## [0.4.2] - 2026-09-12

**The documentation said four things about this package that were not true. Nothing in the suite could have noticed.**

### Fixed
- **The front page handed an engine read to a `Step`.** Its verb list opened on "a handful of verbs, each of which a `Step` can implement" and then named `drift()`, `plan()`, `audit()` and `footprint()`. Those four are the `Reconciler`'s own reads of what the steps reported. A `Step` answers `assess()`, `apply()` and `prune()`, which is what the quickstart two screens above already showed. Every name in the sentence was real, so a check for a retired name would have passed it. The owner was wrong rather than the word.
- **The roadmap promised what this line already ships or will never cut.** It offered capability-based dependencies as a 2.0.0 idea while `provides` lands in the next release, offered a `cabaxiom.testing` module for 1.1.0 while it lands in the one after that. It also said the 1.0.0 freeze would be cut from a 0.11.0 that this line does not plan. The milestones now name what is genuinely ahead, one bullet per release up to the freeze.
- **Two colons used as punctuation**, in a project whose own style bans them.
- **Every compare link named a repository this package is not.** The fourteen links at the foot of this file still pointed at `pizgariu/state-reconciler` while `pyproject.toml` declares `pizgariu/cabaxiom`. GitHub answers the old name with a redirect, which holds only for as long as nobody else claims it.
- **Nothing read the prose until now.** `tests/test_docs.py` is new. It refuses an engine verb taught as a step hook, refuses a verb the `Reconciler` does not answer, refuses a colon used as punctuation and refuses a roadmap milestone that promises a module the package already imports and refuses a compare link that names a repository other than the declared one. The sentence that shipped in 0.4.1 fails all of the first three.

### BC break
Nothing. Not one line of `src/` changed.
## [0.4.1] - 2026-09-11

**Two contracts the type checker could not hold, found by running it properly on what 0.4.0 shipped.**

### Fixed
- **A `Partition` shape declares its placement rule where a checker can see it.** The base declared that slot as an abstract property and every shape answers it with a plain class attribute, which is not a valid override - so the one line each shape actually writes was the one shape the contract could not express. The `abstractmethod` was not buying anything either, because a tuple subclass's C-level `__new__` skips the instantiate-check, so a shape with no rule constructed happily and only failed at its first `verify()`. It is a declared `ClassVar` checked in `__init_subclass__` now, which fires at the class statement that got it wrong.
- **Every `Dispatcher.execute` uses the parameter name its own base declares.** `cabaxiom.Dispatcher.execute` calls the first argument `groups`, while `Parallel`, `Async` and `Pipeline` each renamed it to whatever their own shape happens to be. A caller writing `execute(groups=...)` was correct against the type it programs to and wrong against every class that runs, so that argument could not be passed by keyword at all. Positional callers are unaffected, which is every caller that goes through the `Reconciler`.
- **The changelog's own comparison links.** The 0.4.0 section had no link line and `[unreleased]` still compared against `v0.3.1`, so the newest release was the one with no diff to click through to.
- **The front page still taught 0.3.0.** The quickstart now awaits the coroutines it calls, the step example writes `assess()` and answers with the verdict factories, the `Controller` section became the `watch()` section, the axis table names the `Dispatcher` family and the `Parallel` example drops the `with` block the dispatcher never needed. The parallel example's own docstring now promises the event loop its output shows rather than a pool of worker threads.

### BC break
Nothing. This release only makes contracts that were already written hold.

## [0.4.0] - 2026-09-09

**One engine and one read hook, so there is a single thing to learn and a single place a bug can live.**

### Added
- **The kernel is async native and there is exactly one of it.** `cabaxiom.Reconciler.converge()`, `.assess()` and `.prune()` are coroutines awaited on the caller's own loop. 0.3.0 shipped a synchronous `Reconciler` beside an `Async` executor that spun a private event loop per pass, so a caller who already had a loop ended up with two and an `apply()` that wanted to share the caller's connection pool could not. The sync twin is not deprecated, it is deleted, because a mirror is two implementations of one idea and the second one is always slightly wrong.
- **`cabaxiom.Assessment`, the record one read hook returns.** Four channels, deviation and plan and advisory and footprint, replacing `drift()`, `plan()`, `audit()` and `footprint()`. A step with an expensive probe used to pay for it four times, yet nothing forced the four answers to describe the same moment of the world. The advisory channel is the one that had no home before. It is what lets a step report a finding without dirtying its own proof.
- **`cabaxiom.Step.verified()`, `.drifted()`, `.unchanged()` and `.changed()`, with `Step.named(step)` for the subject.** These are the line every declaration writes on every hook. Before them a first declaration had to meet `Assessment` and `DriftItem` in order to say a file is missing. A domain's own richer `Drift` still passes through untouched, which is the point of the `Drift` protocol staying two fields wide.
- **`Reconciler.watch()` and `Step.watch()`, the reactive graph.** `Reconciler.watch()` is an async iterator of `Residual`. `Step.watch()` yields nothing by default and exits. The wake carries no payload, deliberately, because a level-triggered wake costs one clean pass when it is spurious and an edge-triggered one costs correctness. `cabaxiom.Clean` and `cabaxiom.Stable` are the stop conditions for the loop, on `cabaxiom.Settle`.
- **`cabaxiom.ThreadDispatcher`, the sanctioned route for a blocking domain.** It relocates the raw callable to `asyncio.to_thread` and lays the retry back over it. This ships in the same tag that removes the sync engine rather than a later one, because otherwise the release strands every caller whose `apply()` shells out or talks to a driver that has no async form.
- **`Step` is frozen after construction.** Assigning any attribute to a constructed step raises `TypeError` naming the class. Two passes over one step now read the same declaration, which is the precondition for everything the later tags do with steps as values.

### Fixed
- **An abort could be swallowed by ordinary error handling** (`9b13197`). `Cancelled` derived from `Exception`, so a domain hook's `except Exception` ate a cooperative abort and the run kept converging a world somebody had stopped. It is a `BaseException` now, on the `KeyboardInterrupt` precedent, while the worker boundaries ferry it as a value because a `BaseException` loose in a pool worker hangs the map.
- **A broken read abandoned its wave-mates.** The read fan used a bare `gather`, so the first failure propagated at once while the sibling reads kept running detached on the loop and warned at teardown. The fan settles the whole wave, then raises the first broken read in resolved order. Reads stay single-try and fail loud, they just no longer leave the loop dirty.

### BC break
- `Reconciler.converge()`, `.assess()` and `.prune()` are coroutines. A synchronous caller writes `asyncio.run(Reconciler(steps).converge())`.
- The `Async` executor is gone. A coroutine `apply()` needs no special executor now. A **blocking** `apply()` writes `Reconciler(steps, dispatcher=ThreadDispatcher())`.
- `Step.drift()`, `.plan()`, `.audit()` and `.footprint()` are gone. Write one `async def assess(self)` returning `Step.verified()`, `Step.drifted(...)` or a full `Assessment`.
- `Controller` is gone. Write `async for residual in reconciler.watch()` and pass `Clean()` or `Stable(passes)` where you drove `Controller.settle()`.
- `Reconciler(executor=...)` is `Reconciler(dispatcher=...)`, because the parameter no longer holds one member of a two-colour family. `Executor` and `BaseExecutor` are `cabaxiom.Dispatcher` and `BaseDispatcher`.
- Assigning to a constructed `Step` raises. Move the assignment into `__init__`.
- `except Exception` no longer catches `Cancelled`. Catch it by name if you were relying on that, then reconsider why.

**The rung.** The executor moves **working -> ok**. It ran, in two colours, with two implementations of every shape. Now it runs in one colour with one implementation, which is tolerable rather than good, because the arranging still lives on the worker.

## [0.3.1] - 2026-08-17

**0.3.0 did not import on Python 3.10 and its coverage gate could not pass on 3.10 or 3.11. Both are fixed here and nothing else changed.**

### Fixed
- **`import cabaxiom` raised `TypeError` on Python 3.10.** Not a degraded feature, the package did not load at all, on a version `requires-python` declares and the classifiers list. `Kahn`'s private graph builder names a `TopologicalSorter` in its return annotation and `graphlib.TopologicalSorter` only gained `__class_getitem__` in 3.11 - a signature is evaluated when its `def` runs, so importing the module ran that subscript and it raised. The annotation is quoted, which is never evaluated. `tests/test_python_floor.py` walks every signature in the package for a subscript the declared floor cannot take, so the next one is caught before a release rather than after.
- **The coverage gate could not reach 100% on 3.10 or 3.11.** `_compat.py` picks `typing.override` on 3.12 and up and defines a no-op below it. Exactly one branch runs on any interpreter and the `# pragma: no cover` sat on only one of them, so the other was uncovered wherever it was not taken. Both sides carry it now.

### BC break
Nothing. 0.3.1 is 0.3.0 with two defects removed.


## [0.3.0] - 2026-08-13

### Added
- **The full test pyramid.** Property-based tests with Hypothesis pin the invariants across the whole input space. Kahn orders every dependency before its dependent, Parallel accepts every wave Kahn resolves and Fixpoint always terminates. A stateful state machine drives arbitrary perturb-and-reconcile interleavings, `mutmut` hunts lines the tests cover without pinning their behaviour and example smoke tests keep the documented runs from rotting.
- **A strict type gate and a sealed hierarchy.** The kernel type-checks under `mypy --strict` in CI. Every concrete class is `@final` with `@override` on every override, which keeps the pluggable seams exactly the abstract bases and stops a renamed base method from leaving an override dangling.
- **Run introspection.** `Reconciler.explain()` answers an `Explanation` of the groups the executor walks in run order, plus the `after` edges behind that order. It reads off the same resolved partition every verb uses and re-resolves nothing, which makes it a view of the actual run rather than a second opinion about it.
- **`Jitter` backoff.** A full-jitter decorator over any `Backoff`, spreading each pause across the range up to the wrapped delay. The standard defence against a thundering herd of clients retrying in lockstep.

## [0.2.0] - 2026-08-08

### Breaking
- **Renamed to `cabaxiom`.** The distribution, the import and the package directory. CABAL, the artificial intelligence of Command and Conquer Tiberian Sun, plus axiom. A thing that holds a world to a declaration and does not negotiate about it. Import `cabaxiom`, not `state_reconciler`. The rename lands here rather than later because its cost grows with every release and 1.0.0 has to signal stability rather than churn. The public surface is untouched, all 45 names included. The import line is the only edit a consumer makes. The 0.1.x releases stay published under the old name.

### Added
- **Scope.** Choose which of the handed steps take part in a run, resolved once so every verb sees the same set. `Only(TypeA, ...)` keeps its targets plus everything they transitively depend on. A targeted run never converges against state nobody put there. `Skip(TypeB, ...)` drops the named types and keeps the rest. Both fail loudly on a named type that no step in the run carries. That catches a typo instead of quietly reconciling a smaller world.
- **Retry and backoff.** Every `apply()` and `prune()` is guarded by an injected `Retry`. A transient failure is retried inside the executor's own unit of work and only a failure that outlives every attempt reaches the error policy. An optional `Backoff` paces the attempts, `Fixed` holding a constant delay and `Exponential` doubling up to a cap. The same backoff turns an unchanged `Fixpoint` pass into a paced retry. Drift that waits on external state gets the time to settle. `Retry(1)` is the neutral, zero-cost guard.
- **The async executor.** Fans each dependency wave onto an asyncio event loop instead of a thread pool, the cooperative dual of `Parallel`, for steps whose `apply()` is a coroutine that closes its gap over I/O. It awaits a wave concurrently and bars between waves. Every `after` edge still holds.
- **Observer.** Trace hooks fired around each converge pass (`began`, `acted`, `remained`). A run's changes and what the world still shows can be followed without instrumenting a Step by hand. Silent by default. Compose several with `Chorus`, which is itself an `Observer` and nests.

### Fixed
- **The source distribution ships an explicit file list.** The wheel already named what it packed, the sdist did not. A build inherited whatever the builder's working tree happened to hold and the artifact differed from machine to machine. It now names src, tests, examples and the metadata files. What ships is the same whoever builds it.
- **A read-engine helper stopped being a staticmethod.** `__probe` took the groups and the read callable but never `self`. It was marked static and then reached through the class. One word removed, one indirection gone.

## [0.1.6] - 2026-07-21

### Added
- **Changelog.** This file, following Keep a Changelog, with a section per release and a roadmap of what is planned next.

## [0.1.5] - 2026-07-21

### Added
- **Continuous integration.** A GitHub Actions pipeline that lints with Ruff and runs the suite on CPython 3.10 through 3.14, on every push to `master` and every pull request, with `fail-fast` off so a break on one interpreter does not hide the others. Dependabot keeps the pip and Actions dependencies current.

## [0.1.4] - 2026-07-20

### Added
- **Test suite.** Broad coverage of the kernel across the ordering strategies, executors, convergence policies and cancellation sources, at 100 percent line and branch coverage, split by concern.

## [0.1.3] - 2026-07-18

### Added
- **README.** The full documentation - the reconciliation principle, the building blocks, the pluggable behaviour axes and the runnable examples walked through end to end.

## [0.1.2] - 2026-07-18

### Added
- **Examples.** Three runnable, self-contained scripts. `filesystem_layout.py` brings a temp directory tree to a desired layout, then tampers with a file and self-heals on the next converge. `git_repo_state.py` drives a throwaway git repository to desired state and proves success with an empty residual. `parallel_fixpoint.py` provisions a service dependency graph with the `Parallel` executor and settles a multi-pass replica scale-up under `Fixpoint` convergence.

## [0.1.1] - 2026-07-15

### Added
- **Packaging.** Packaged for PyPI with hatchling and released under the MIT License, with a `py.typed` marker so downstream type checkers see the annotations.

## [0.1.0] - 2026-07-13

### Added

- **Reconciliation kernel.** A domain-agnostic engine with zero dependencies. Steps own the desired state. A Reconciler resolves their order, converges actual toward desired, then self-verifies by re-probing for any drift that survived. The kernel carries no domain vocabulary. It reads a drift item only through the two fields of the `Drift` protocol, its `name` and its `message`.
- **Drift surface.** The `Drift` protocol as the single interface the kernel reads drift through and `DriftItem` as the concrete carrier of a name and a message.
- **Step surface.** `Step`, the unit of desired state, with an `after` class attribute that declares dependencies on other step types. A step reports through `drift()`, `plan()`, `audit()`, `footprint()` and `prune()` and closes gaps through `apply()`.
- **Reconciler and Controller.** `Reconciler` wires steps to an ordering, an executor, a convergence policy and a cancellation source. It exposes `drift()`, `plan()`, `audit()`, `footprint()`, `prune()` and `converge()`. `converge()` returns a `Residual`, the drift that outlived the pass, with the applied changes carried on a separate channel. An empty residual means the state was verified clean. `Controller` drives one convergence per tick, with `run()` for a lazy stream of residuals and `settle()` to stop on the first clean pass.
- **Ordering strategies.** Run order is resolved from the `after` dependency graph. `Kahn` is the default and sorts into dependency waves. For a flat post-order, use `DFS`. `Priority` walks a best-first frontier over a caller-supplied key. `Components` splits the graph into independent chains.
- **Executors.** `Serial` runs one step at a time and is the default. `Parallel` fans each dependency wave across a thread pool. `Pipeline` runs independent chains concurrently. Both concurrent executors are context managers that release their pool on exit. An `OnError` policy chooses between `FailFast` and `BestEffort`.
- **Convergence policies.** `Once` runs a single apply-then-probe pass and is the default. `Fixpoint` repeats the loop until the residual stops changing or a pass ceiling is reached.
- **Cancellation.** Cooperative abort between steps through the `Cancellation` base, a wall-clock `Deadline`, a manual `Flag` and the composites `AnyOf`, `AllOf` and `Majority` that nest into a tree or a `Quorum` under a custom `Some`, `Every` or `Most` rule. `Cancelled` is raised when a run is aborted.

## Roadmap

Planned milestones, in rough order. Nothing here is a promise of scope.

- **0.6.0** - The other half of the kernel. A `Ledger` that keeps what a run said about itself rather than two lists, artifacts flowing between steps through `produces` and `consumes`, a run mode that pairs a shape with the worker walking it, capacity held across processes, a warrant that can refuse a run before its first write, chaos injected on purpose, a whole reconciler nested inside one step and three proofs that read a run back - idempotence, reversibility and the smallest failing subset. The reusable doubles the suite grew ship with it as `cabaxiom.testing`, so a domain tests its own Steps against ready-made fakes. The Python floor rises to 3.12.
- **0.7.0** - Layers a test can enforce. The flat package becomes `cabaxiom.core` in four layers whose arrows a linter checks, the laboratory moves out to `cabaxiom.laboratory` and the front door narrows to what you declare, run and catch. Every name that moves answers with the line to type instead of a bare ImportError.
- **0.8.0** - The easter egg, kept for last because the kernel came first.
- **1.0.0** - API stability. Freeze the public surface and commit to Semantic Versioning guarantees for it. The first non-prerelease, cut from the last of the 0.x line.
[unreleased]: https://github.com/pizgariu/cabaxiom/compare/v0.5.2...HEAD
[0.5.2]: https://github.com/pizgariu/cabaxiom/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/pizgariu/cabaxiom/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/pizgariu/cabaxiom/compare/v0.4.2...v0.5.0
[0.4.2]: https://github.com/pizgariu/cabaxiom/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/pizgariu/cabaxiom/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/pizgariu/cabaxiom/compare/v0.3.0...v0.4.0
[0.3.1]: https://github.com/pizgariu/cabaxiom/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/pizgariu/cabaxiom/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/pizgariu/cabaxiom/compare/v0.1.6...v0.2.0
[0.1.6]: https://github.com/pizgariu/cabaxiom/compare/v0.1.5...v0.1.6
[0.1.5]: https://github.com/pizgariu/cabaxiom/compare/v0.1.4...v0.1.5
[0.1.4]: https://github.com/pizgariu/cabaxiom/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/pizgariu/cabaxiom/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/pizgariu/cabaxiom/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/pizgariu/cabaxiom/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/pizgariu/cabaxiom/releases/tag/v0.1.0
