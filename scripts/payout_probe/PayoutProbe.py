# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
DISPOSABLE PROBE - NOT PART OF SPIKE.

Answers one question empirically: on Studionet, does an Intelligent Contract
actually move native GEN to an EOA via the documented external-message path?

    @gl.evm.contract_interface -> _Payee(Address(x)).emit_transfer(value=...)

docs/ARCHITECTURE.md asserted this does not work on Studionet. That assertion was
inherited from a doc warning, never tested. Spike's refund and claim paths both
depend on the answer, so it gets tested here in a throwaway contract rather than
by adding a probe method to the production one.

Deployed and driven by scripts/probe_payout.py. Never imported by Spike.
"""

from genlayer import *


@gl.evm.contract_interface
class _Payee:
    class View:
        pass

    class Write:
        pass


class PayoutProbe(gl.Contract):
    pushes: u256

    def __init__(self):
        self.pushes = u256(0)

    @gl.public.view
    def get_balance(self) -> str:
        """What the contract believes it holds."""
        return str(int(self.balance))

    @gl.public.view
    def get_pushes(self) -> int:
        return int(self.pushes)

    @gl.public.write
    def push(self, recipient: Address, amount_wei: str) -> str:
        """
        Emit an outbound native transfer to an EOA.

        Deliberately non-payable: the probe is funded up front with
        `genlayer account send`, so this call carries no value and the only
        thing under test is the outbound leg.
        """
        amount = int(amount_wei)
        before = int(self.balance)
        if amount > before:
            raise gl.vm.UserError(f"probe holds {before}, cannot push {amount}")

        _Payee(recipient).emit_transfer(value=u256(amount))
        self.pushes = u256(int(self.pushes) + 1)
        return f"EMITTED:{amount}:balance_before:{before}"
