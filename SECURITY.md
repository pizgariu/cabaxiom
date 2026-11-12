# Security

## Reporting a vulnerability

Use GitHub's **private vulnerability reporting** on this repository, the
[report a vulnerability](https://github.com/pizgariu/cabaxiom/security/advisories/new) form. It reaches me
without the report being public, which an ordinary issue would be the moment you press the button.

Please do not open a public issue for anything that could be exploited before there is a fix. Ordinary
issues are the right place for everything else, including a refusal that failed to say what to write.

Tell me what you can. A description of the problem, the version you saw it on and the smallest input that
shows it are enough to start. A patch is welcome and never expected.

You should get an acknowledgement within a week. If you do not, assume the report went missing rather than
that it was ignored. Send it again.

## What counts

This is a reconciliation kernel with no runtime dependencies. It runs whatever a caller's `Step` does, so a
`Step` that deletes a disk is the caller's decision rather than a defect here. What IS in scope is the
kernel doing something the caller did not declare. Or reporting that it did something it did not do.

These are worth reporting.

- a run that reports VERIFIED against a world it did not reach or hides a failure from the record
- a declaration guard that can be walked past, so an edge, a seating or a data-plane rule stops holding
- anything crossing `RemoteDispatcher` that makes the local side act outside the protocol on an envelope the
  kernel built itself
- a refusal that can be turned into arbitrary execution, a read outside the process or an unbounded resource

These are out of scope.

- what a caller's own `Step` does when it runs
- resource use that follows from a declaration, such as a fan-in of n steps drawing n edges
- a denial of service that needs control of the declaration, since a declaration already runs code
- what a peer can do by sending its own envelope to `RemoteDispatcher.work()`. The envelope is a pickle and
  loading one runs code, so the transport has to carry it between peers that trust each other

## Versions

Only the latest release gets fixes. The fix ships in the next release rather than as a patch to an older
one. 1.0.0 froze the forty-three names `cabaxiom` exports. `cabaxiom.core` and `cabaxiom.laboratory` are
public and carry no such promise, which `MIGRATING.md` says in full.

## Disclosure

I will credit you unless you ask me not to. Once a fix is out, the defect is written up with what it was,
how it was reproduced and why nothing caught it, the same as every other defect in this repository.
