/**
 * Confirming that GEN actually arrived.
 *
 * `claim` returning CLAIMED: and the position flipping `claimed = true` only
 * mean the contract emitted an external message. That message executes on
 * finalisation, so the wallet balance moves a little later — measured at about
 * 30 seconds on Studionet.
 *
 * This watches the balance so the UI can distinguish three real outcomes:
 * arrived, still in flight, or the bookkeeping moved but the money did not.
 */

import { getNativeBalance } from "./client";

export type PayoutWatch =
  | { kind: "arrived"; delta: bigint; afterMs: number }
  | { kind: "pending"; waitedMs: number }
  | { kind: "failed"; reason: string };

export async function watchPayout(
  wallet: string,
  balanceBefore: bigint,
  opts: { timeoutMs?: number; intervalMs?: number } = {}
): Promise<PayoutWatch> {
  const timeoutMs = opts.timeoutMs ?? 90_000;
  const intervalMs = opts.intervalMs ?? 5_000;
  const started = Date.now();

  while (Date.now() - started < timeoutMs) {
    await sleep(intervalMs);
    let now: bigint;
    try {
      now = await getNativeBalance(wallet);
    } catch (e) {
      return { kind: "failed", reason: (e as any)?.message ?? String(e) };
    }
    if (now > balanceBefore) {
      return {
        kind: "arrived",
        delta: now - balanceBefore,
        afterMs: Date.now() - started,
      };
    }
  }
  return { kind: "pending", waitedMs: Date.now() - started };
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
