/**
 * The single write path.
 *
 * EVERY state-changing call in Spike goes through `writeWithEstimatedFees`.
 * Nothing else in this app is allowed to call `client.writeContract` directly.
 *
 * Why this file exists at all: on consensus v0.6 a write must carry a fee
 * distribution. Submitting `writeContract` without one produces a transaction
 * the network will not accept. So we always:
 *
 *   1. call `estimateTransactionFeesForWrite` for THIS exact call
 *   2. pass the returned distribution / messageAllocations / feeValue into
 *      `writeContract` as `fees`
 *   3. wait for the validator outcome and surface it verbatim
 *
 * If estimation fails we do NOT fall back to an unpriced write - we raise a
 * `FeeEstimationError` so the UI can say why, rather than sending a doomed
 * transaction and leaving the user staring at a pending hash.
 */

import type { GenLayerClient } from "genlayer-js/types";

export class FeeEstimationError extends Error {
  readonly cause?: unknown;
  constructor(functionName: string, cause: unknown) {
    super(
      `Could not price the "${functionName}" transaction on this network. ` +
        `Nothing was submitted. ${describe(cause)}`
    );
    this.name = "FeeEstimationError";
    this.cause = cause;
  }
}

export class WriteRevertedError extends Error {
  readonly reason: string;
  readonly kind: SpikeErrorKind;
  constructor(reason: string) {
    super(reason);
    this.name = "WriteRevertedError";
    this.reason = reason;
    this.kind = classifyRevert(reason);
  }
}

export type SpikeErrorKind =
  | "EXPECTED"
  | "TRANSIENT"
  | "EXTERNAL"
  | "INVARIANT"
  | "UNKNOWN";

/** The contract prefixes every revert so the UI can branch on it. */
export function classifyRevert(reason: string): SpikeErrorKind {
  const r = (reason || "").toUpperCase();
  if (r.includes("EXPECTED:")) return "EXPECTED";
  if (r.includes("TRANSIENT:")) return "TRANSIENT";
  if (r.includes("EXTERNAL:")) return "EXTERNAL";
  if (r.includes("INVARIANT:")) return "INVARIANT";
  return "UNKNOWN";
}

export function describe(e: unknown): string {
  if (!e) return "";
  if (typeof e === "string") return e;
  const anyE = e as any;
  return anyE?.shortMessage || anyE?.details || anyE?.message || String(e);
}

export type WriteArgs = {
  client: GenLayerClient<any>;
  account: any;
  address: `0x${string}`;
  functionName: string;
  args?: any[];
  /** Native GEN to attach, in wei. */
  value?: bigint;
};

export type WriteResult = {
  txHash: string;
  /** Whatever the contract method returned, e.g. "STAKED:...", "REFUNDED:...". */
  returned: unknown;
  /** The fee estimate that was actually used. Surfaced for the UI/receipts. */
  feeValue: bigint;
};

/**
 * Estimate fees for this exact call, then submit it carrying those fees.
 *
 * Exported separately so tests can assert the ordering without a network.
 */
export async function estimateFees(a: WriteArgs) {
  try {
    return await a.client.estimateTransactionFeesForWrite({
      account: a.account,
      address: a.address,
      functionName: a.functionName,
      args: a.args ?? [],
      value: a.value ?? 0n,
    });
  } catch (e) {
    throw new FeeEstimationError(a.functionName, e);
  }
}

export async function writeWithEstimatedFees(
  a: WriteArgs,
  opts: { waitForReceipt?: boolean } = {}
): Promise<WriteResult> {
  // 1. price this call
  const estimate = await estimateFees(a);

  // 2. submit carrying those fees - never an unpriced write
  const txHash = await a.client.writeContract({
    account: a.account,
    address: a.address,
    functionName: a.functionName,
    args: a.args ?? [],
    value: a.value ?? 0n,
    fees: {
      distribution: estimate.distribution,
      messageAllocations: estimate.messageAllocations,
      feeValue: estimate.feeValue,
    },
  });

  if (opts.waitForReceipt === false) {
    return { txHash, returned: undefined, feeValue: estimate.feeValue };
  }

  // 3. wait for the validators to decide, and surface the outcome.
  //    "decided" is the point at which the contract's return value and any
  //    revert reason are known. Outbound GEN still moves on finalisation, which
  //    is why the UI says payouts arrive as a separate follow-up transaction.
  const receipt = await a.client.waitForTransactionReceipt({
    hash: txHash,
    waitUntil: "decided",
    retries: 60,
    interval: 3000,
  });

  const returned = readReturn(receipt);
  const revert = readRevert(receipt);
  if (revert) throw new WriteRevertedError(revert);

  return { txHash, returned, feeValue: estimate.feeValue };
}

function readReturn(receipt: any): unknown {
  return (
    receipt?.result?.returned ??
    receipt?.returned ??
    receipt?.consensus_data?.leader_receipt?.[0]?.result?.returned ??
    receipt?.consensus_data?.leader_receipt?.result?.returned ??
    undefined
  );
}

function readRevert(receipt: any): string | null {
  const status =
    receipt?.status ?? receipt?.consensus_data?.leader_receipt?.[0]?.execution_result;
  const errish =
    receipt?.result?.error ??
    receipt?.error ??
    receipt?.consensus_data?.leader_receipt?.[0]?.error ??
    null;

  if (errish) return describe(errish);
  if (typeof status === "string" && /ERROR|REVERT|UNDETERMINED/i.test(status)) {
    const ret = readReturn(receipt);
    return typeof ret === "string" && ret ? ret : status;
  }
  return null;
}

/**
 * A `take_position` call never reverts once value is attached - it answers
 * either STAKED:<wei> or REFUNDED:<reason>. This turns that into something the
 * UI can render without guessing.
 */
export type StakeOutcome =
  | { kind: "staked"; totalWei: bigint }
  | { kind: "refunded"; reason: string }
  | { kind: "unknown"; raw: string };

export function parseStakeOutcome(returned: unknown): StakeOutcome {
  const s = typeof returned === "string" ? returned : String(returned ?? "");
  if (s.startsWith("STAKED:")) {
    return { kind: "staked", totalWei: BigInt(s.slice("STAKED:".length) || "0") };
  }
  if (s.startsWith("REFUNDED:")) {
    return { kind: "refunded", reason: s.slice("REFUNDED:".length) };
  }
  return { kind: "unknown", raw: s };
}

/** Plain-language text for each error class. */
export function explainError(e: unknown): string {
  if (e instanceof FeeEstimationError) return e.message;
  if (e instanceof WriteRevertedError) {
    const body = e.reason.replace(/^.*?(EXPECTED|TRANSIENT|EXTERNAL|INVARIANT):\s*/i, "");
    switch (e.kind) {
      case "EXPECTED":
        return body || "That action is not allowed right now.";
      case "TRANSIENT":
        return `A price feed was temporarily unreachable (${body}). Nothing changed - try resolving again in a moment.`;
      case "EXTERNAL":
        return `A price feed answered but the window could not be rebuilt (${body}). Nothing changed - this is retryable.`;
      case "INVARIANT":
        return `The agreed settlement payload failed validation (${body}). This should never happen; the market is untouched.`;
      default:
        return e.reason;
    }
  }
  return describe(e) || "Something went wrong.";
}
