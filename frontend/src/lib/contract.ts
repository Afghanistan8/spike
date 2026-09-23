/**
 * Typed access to the Spike contract.
 *
 * Reads go straight to contract views - the UI never computes a settlement
 * outcome itself. Writes all funnel through `writeWithEstimatedFees`, which is
 * the only place in this app that touches `client.writeContract`.
 */

import type { GenLayerClient } from "genlayer-js/types";

import { CONTRACT_ADDRESS, HAS_CONTRACT, PAGE_SIZE } from "./env";
import { readClient, writeClient } from "./client";
import { writeWithEstimatedFees, type WriteResult } from "./write";

export type Phase =
  | "OPEN"
  | "WINDOW_LIVE"
  | "READY_TO_SETTLE"
  | "SETTLED_UP"
  | "SETTLED_DOWN"
  | "SETTLED_WINNER"
  | "INCONCLUSIVE";

export type Market = {
  market_id: string;
  kind: string;
  category: string;
  asset: string;
  asset_label: string;
  target_day: string;
  target_hour: number;
  window_open: number;
  window_close: number;
  created_at: number;
  settles_at: number;
  terminal_refund_at: number;
  creator: string;
  phase: Phase;
  final_verdict: string;
  resolved_at: number;
  refund_all: boolean;
  total_pool: string;
  sides: string[];
  pools: Record<string, string>;
  unique_key: string;
};

export type Position = {
  wallet: string;
  market_id: string;
  side: string;
  amount_wei: string;
  claimed: boolean;
  claimable_wei: string;
  phase: Phase;
};

export type Page<T> = { total: number; items: T[] };

export type Evidence = {
  market_id: string;
  source_a_id: string;
  source_b_id: string;
  source_a_verdict: string;
  source_b_verdict: string;
  final_verdict: string;
  refund_all: boolean;
  resolved_at: number;
  evidence: string;
};

export class NoContractError extends Error {
  constructor() {
    super(
      "No Spike contract address is configured. Deploy the contract and set " +
        "CONTRACT_ADDRESS in src/lib/env.ts (or VITE_SPIKE_ADDRESS)."
    );
    this.name = "NoContractError";
  }
}

function addr(): `0x${string}` {
  if (!HAS_CONTRACT) throw new NoContractError();
  return CONTRACT_ADDRESS as `0x${string}`;
}

async function read<T>(functionName: string, args: any[] = []): Promise<T> {
  const client = readClient();
  const out = await client.readContract({
    address: addr(),
    functionName,
    args,
  });
  return out as T;
}

// ---------------------------------------------------------------- reads

export const getSupportedUniverse = () => read<any>("get_supported_universe");
export const getStats = () => read<any>("get_stats");
export const getMarket = (id: string) => read<Market>("get_market", [id]);
export const getMarketPhase = (id: string) => read<Phase>("get_market_phase", [id]);

export const getMarkets = (offset = 0, limit = PAGE_SIZE) =>
  read<Page<Market>>("get_markets", [offset, limit]);

export const getOpenMarkets = (offset = 0, limit = PAGE_SIZE) =>
  read<Page<Market>>("get_open_markets", [offset, limit]);

export const getMarketsByCategory = (category: string, offset = 0, limit = PAGE_SIZE) =>
  read<Page<Market>>("get_markets_by_category", [category, offset, limit]);

export const getMarketByUniqueKey = (
  kind: string,
  category: string,
  asset: string,
  day: string,
  hour: number
) => read<Market>("get_market_by_unique_key", [kind, category, asset, day, hour]);

export const getPosition = (marketId: string, wallet: string) =>
  read<Position>("get_position", [marketId, wallet]);

export const getClaimable = (marketId: string, wallet: string) =>
  read<string>("get_claimable", [marketId, wallet]);

export const getUserPositions = (wallet: string, offset = 0, limit = PAGE_SIZE) =>
  read<Page<Position>>("get_user_positions", [wallet, offset, limit]);

export const getUserMarkets = (wallet: string, offset = 0, limit = PAGE_SIZE) =>
  read<Page<Market>>("get_user_markets", [wallet, offset, limit]);

export const getMarketPositions = (marketId: string, offset = 0, limit = PAGE_SIZE) =>
  read<Page<Position>>("get_market_positions", [marketId, offset, limit]);

export const getSettlementEvidence = (marketId: string) =>
  read<Evidence>("get_settlement_evidence", [marketId]);

export const getActivity = (offset = 0, limit = PAGE_SIZE) =>
  read<Page<string>>("get_activity", [offset, limit]);

// ---------------------------------------------------------------- writes
//
// Each of these is a thin wrapper over the ONE write helper. None of them may
// call client.writeContract directly - see src/lib/write.ts.

function w(account: `0x${string}`): GenLayerClient<any> {
  return writeClient(account);
}

export function createMarket(
  account: `0x${string}`,
  kind: string,
  category: string,
  asset: string,
  targetDay: string,
  targetHour: number
): Promise<WriteResult> {
  return writeWithEstimatedFees({
    client: w(account),
    account,
    address: addr(),
    functionName: "create_market",
    args: [kind, category, asset, targetDay, targetHour],
  });
}

export function takePosition(
  account: `0x${string}`,
  marketId: string,
  side: string,
  valueWei: bigint
): Promise<WriteResult> {
  return writeWithEstimatedFees({
    client: w(account),
    account,
    address: addr(),
    functionName: "take_position",
    args: [marketId, side],
    value: valueWei,
  });
}

export function resolveMarket(
  account: `0x${string}`,
  marketId: string
): Promise<WriteResult> {
  return writeWithEstimatedFees({
    client: w(account),
    account,
    address: addr(),
    functionName: "resolve_market",
    args: [marketId],
  });
}

export function claim(
  account: `0x${string}`,
  marketId: string
): Promise<WriteResult> {
  return writeWithEstimatedFees({
    client: w(account),
    account,
    address: addr(),
    functionName: "claim",
    args: [marketId],
  });
}
