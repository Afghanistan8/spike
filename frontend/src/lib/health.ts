/**
 * RPC health, recorded where the reads actually happen.
 *
 * The board used to fail with a bare "Could not reach the contract". This keeps
 * the last successful view and the last failure, so the footer can always say
 * which chain, which contract, and when it last heard back — and an error names
 * the RPC URL and the raw exception instead of swallowing them.
 */

import { CHAIN_ID, CONTRACT_ADDRESS, RPC_URL } from "./env";

export type Health = {
  chainId: number;
  contract: string;
  rpc: string;
  lastOkAt: number | null;
  lastFn: string | null;
  lastError: string | null;
  lastErrorFn: string | null;
};

let state: Health = {
  chainId: CHAIN_ID,
  contract: CONTRACT_ADDRESS,
  rpc: RPC_URL,
  lastOkAt: null,
  lastFn: null,
  lastError: null,
  lastErrorFn: null,
};

const listeners = new Set<(h: Health) => void>();

function emit() {
  for (const l of listeners) l(state);
}

export function subscribeHealth(fn: (h: Health) => void): () => void {
  listeners.add(fn);
  fn(state);
  return () => listeners.delete(fn);
}

export function getHealth(): Health {
  return state;
}

export function recordOk(functionName: string) {
  state = {
    ...state,
    lastOkAt: Date.now(),
    lastFn: functionName,
    lastError: null,
    lastErrorFn: null,
  };
  emit();
}

export function recordError(functionName: string, e: unknown) {
  state = {
    ...state,
    lastError: describeRpcError(e),
    lastErrorFn: functionName,
  };
  emit();
}

/** Keep the raw exception; a swallowed message is how the blank page happened. */
export function describeRpcError(e: unknown): string {
  if (!e) return "unknown error";
  const a = e as any;
  const parts = [a?.shortMessage, a?.details, a?.message].filter(
    (p, i, all) => p && all.indexOf(p) === i
  );
  return parts.length ? parts.join(" — ") : String(e);
}

/** A full, quotable sentence for the UI when a read fails. */
export function readFailureMessage(functionName: string, e: unknown): string {
  return `${functionName} failed against ${RPC_URL} (chain ${CHAIN_ID}, contract ${CONTRACT_ADDRESS}): ${describeRpcError(
    e
  )}`;
}
