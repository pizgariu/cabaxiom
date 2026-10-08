"""Prove a reconciler is idempotent, then nest whole reconcilers and prove the entire tree.

Idempotence is the whole promise. Converge and a second converge on the settled world changes
nothing. Idempotence.prove() checks that instead of trusting it. It converges to desired state,
converges once MORE and returns a Proof:

  churned    what the second converge's apply() reported doing (empty when idempotent)
  residual   what was still wrong after it (empty when it actually converged)
  stable     both empty

The subtle failure it catches - an apply() that keeps working even when drift() reads clean. The
residual alone hides that, since the residual is empty whenever drift is clean. It is the second
converge's APPLIED channel that exposes the churn.

Then Enclave closes the composition on itself. The Step surface and the reconciler surface align
verb for verb, so a whole reconciler joins a parent run as ONE step. Stacks nest, one top-level
converge returns one residual and Idempotence.prove() on the parent certifies the whole tree.

Run it:

    python examples/fractal_idempotence.py

Expected stdout - an idempotent step proves stable. A churning step proves NOT stable with its
churn surfaced. Then two sub-stacks nest under one parent reconciler, converge as one and the
parent's Proof certifies the whole tree stable. All in memory.
"""

import asyncio
import sys
from pathlib import Path

try:
    from cabaxiom import Assessment, DriftItem, Enclave, Idempotence, Reconciler, Step
except ModuleNotFoundError:  # running from a source checkout without an install
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    from cabaxiom import Assessment, DriftItem, Enclave, Idempotence, Reconciler, Step


class Provisioned(Step):
    """A well-behaved step. It applies once, then is a genuine no-op - idempotent."""

    def __init__(self, name: str):
        self.name = name
        self.done = [False]   # a cell, since the frozen Step forbids reassigning an attribute

    def assess(self, inputs):
        return Assessment(deviation=[] if self.done[0] else [DriftItem(self.name, "not provisioned")]), {}

    def apply(self, inputs):
        if self.done[0]:
            return None, {}
        self.done[0] = True
        return [DriftItem(self.name, "provisioned")], {}


class Churning(Step):
    """A NON-idempotent step. drift() always reads clean, yet apply() does work every single time -
    the exact bug a single converge cannot see. The residual stays empty. Only the churn reveals it."""

    def assess(self, inputs):
        return Assessment(deviation=[]), {}

    def apply(self, inputs):
        return [DriftItem("cache", "rebuilt the whole cache again")], {}


def show(label: str, proof) -> None:
    print(f"{label}: stable={proof.stable}")
    if proof.churned:
        print(f"    churned (worked when it should not have): {[str(i) for i in proof.churned]}")
    if proof.residual:
        print(f"    residual (never converged): {[str(i) for i in proof.residual]}")


async def main() -> None:
    print("Proving single reconcilers:")
    honest = await Idempotence(Reconciler((Provisioned("db"), Provisioned("api")))).prove()
    churner = await Idempotence(Reconciler((Churning(),))).prove()
    show("  idempotent stack", honest)
    show("  churning stack", churner)

    assert honest.stable
    # The subtle failure, stated as an assertion. The churner's residual is EMPTY, so a run that only
    # looked at the residual would call it converged. It is the second converge's applied channel that
    # convicts. Drop that channel from the Proof and this line is the one that fails.
    assert not churner.residual and churner.churned and not churner.stable
    print()

    print("Nesting whole stacks (reconciliation is fractal):")
    # Each sub-stack is a full reconciler with its own steps and resolution.
    leaves = (Provisioned("postgres"), Provisioned("redis"), Provisioned("web"), Provisioned("worker"))
    database = Reconciler(leaves[:2])
    application = Reconciler(leaves[2:])

    # An Enclave IS a Step, so the parent orders and runs whole stacks as single units.
    class DatabaseStack(Enclave):
        pass

    class ApplicationStack(Enclave):
        expects = (DatabaseStack,)  # the app stack converges after the database stack, like any edge

    top = Reconciler((ApplicationStack(application), DatabaseStack(database)))

    residual = await top.converge()
    print(f"  one top-level converge, one residual: {'empty -> whole tree verified' if not residual else residual}")
    assert not residual
    # ONE converge at the top reached every leaf two levels down. Without that, an empty residual would
    # only mean the parent asked nobody anything.
    assert all(leaf.done for leaf in leaves)

    proof = await Idempotence(top).prove()
    print(f"  Idempotence.prove() on the parent certifies the TREE: stable={proof.stable}")
    assert proof.stable   # the certificate covers the enclaves, not just the parent's own two steps


if __name__ == "__main__":
    asyncio.run(main())

