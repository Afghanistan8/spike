#!/usr/bin/env python3
"""
Deploy Spike to GenLayer Studionet.

This wraps the stable `genlayer` CLI rather than signing anything itself, so no
private key is ever read, passed or stored by this repo. The CLI holds the key
in an encrypted keystore and, once unlocked, caches it in the OS keychain:

    genlayer account unlock          # once, interactive, asks for the password
    genlayer account show            # should print status: 'unlocked'
    python scripts/deploy.py

After a successful deploy the printed address goes into
frontend/src/lib/env.ts (CONTRACT_ADDRESS), or into VITE_SPIKE_ADDRESS.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "contracts" / "Spike.py"
ENV_TS = ROOT / "frontend" / "src" / "lib" / "env.ts"

STUDIONET_RPC = "https://studio.genlayer.com/api"


def run(cmd: list[str]) -> str:
    print("$ " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    out = (p.stdout or "") + (p.stderr or "")
    print(out)
    if p.returncode != 0:
        raise SystemExit(f"command failed with exit code {p.returncode}")
    return out


def cli() -> str:
    exe = shutil.which("genlayer")
    if not exe:
        raise SystemExit(
            "The genlayer CLI is not on PATH. Install it with:\n"
            "    npm install -g genlayer"
        )
    return exe


def check_account(exe: str) -> None:
    out = run([exe, "account", "show"])
    if "unlocked" not in out:
        raise SystemExit(
            "The deployer account is not unlocked.\n"
            "Run `genlayer account unlock` first - it will prompt for the\n"
            "keystore password and cache the key in your OS keychain.\n"
            "This script never handles the password itself."
        )
    if "GEN" not in out:
        print("warning: could not read a balance; the deploy may run out of gas")


def write_address(address: str) -> None:
    if not ENV_TS.exists():
        print(f"note: {ENV_TS} not found, skipping frontend wiring")
        return
    src = ENV_TS.read_text(encoding="utf-8")
    new, n = re.subn(
        r'("0x[0-9a-fA-F]{40}")(;\s*\n)',
        f'"{address}"\\2',
        src,
        count=1,
    )
    if n == 0:
        print(f"note: could not find an address literal in {ENV_TS.name};")
        print(f"      set CONTRACT_ADDRESS to {address} by hand")
        return
    ENV_TS.write_text(new, encoding="utf-8")
    print(f"wired {address} into {ENV_TS.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rpc", default=STUDIONET_RPC)
    ap.add_argument(
        "--no-wire",
        action="store_true",
        help="do not write the address into the frontend",
    )
    args = ap.parse_args()

    exe = cli()
    if not CONTRACT.exists():
        raise SystemExit(f"contract not found: {CONTRACT}")

    print("Spike -> GenLayer Studionet (chain 61999)\n")
    check_account(exe)

    out = run([exe, "deploy", "--contract", str(CONTRACT), "--rpc", args.rpc])

    m = re.search(r"'Contract Address':\s*'(0x[0-9a-fA-F]{40})'", out) or re.search(
        r"(0x[0-9a-fA-F]{40})", out
    )
    if not m:
        raise SystemExit("deploy succeeded but no contract address was found in output")
    address = m.group(1)

    print(f"\nDeployed: {address}")
    if not args.no_wire:
        write_address(address)

    print("\nVerify with:")
    print(f"  genlayer call {address} get_supported_universe --rpc {args.rpc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
