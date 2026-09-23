/**
 * Every network and address constant lives here.
 *
 * Nothing in this file is a required environment variable - the app builds and
 * runs with no .env at all. Vite env vars are honoured if present so a fork can
 * point at its own deployment without editing source.
 */

export const CHAIN_ID = 61999;
export const CHAIN_NAME = "GenLayer Studionet";
export const RPC_URL = "https://studio.genlayer.com/api";
export const EXPLORER_URL = "https://explorer-studio.genlayer.com";
export const FAUCET_URL = "https://studio.genlayer.com";

export const NATIVE_CURRENCY = {
  name: "GEN",
  symbol: "GEN",
  decimals: 18,
};

/**
 * The deployed Spike contract.
 *
 * Filled in by scripts/deploy.py after a successful Studionet deploy. While it
 * is empty the UI stays readable and tells you so instead of throwing.
 */
export const CONTRACT_ADDRESS: string =
  (import.meta as any).env?.VITE_SPIKE_ADDRESS || "";

export const HAS_CONTRACT = /^0x[0-9a-fA-F]{40}$/.test(CONTRACT_ADDRESS);

/** Optional. Injected wallets work without it. */
export const WALLETCONNECT_PROJECT_ID: string =
  (import.meta as any).env?.VITE_WALLETCONNECT_PROJECT_ID || "";

export const ONE_GEN = 10n ** 18n;
export const MIN_STAKE_WEI = 1n * ONE_GEN;
export const MAX_STAKE_WEI = 5n * ONE_GEN;
export const PAGE_SIZE = 50;

export const CATEGORIES = ["CRYPTO", "COMMODITIES"] as const;
export type Category = (typeof CATEGORIES)[number];

export const KIND_DIRECTION = "KIND_DIRECTION";
export const KIND_DOMINANCE = "KIND_DOMINANCE";

/** Only CRYPTO has two independent intraday sources, so only it takes an hour. */
export const HOURLY_CATEGORIES: Category[] = ["CRYPTO"];

export const ASSETS: Record<Category, string[]> = {
  CRYPTO: ["ADA", "ZEC", "ZAMA", "ARB"],
  COMMODITIES: ["GOLD", "SILVER", "WTI", "COPPER"],
};

/** Commodities settle on ETF proxies. The UI never pretends otherwise. */
export const ASSET_LABELS: Record<string, string> = {
  ADA: "ADA",
  ZEC: "ZEC",
  ZAMA: "ZAMA",
  ARB: "ARB",
  GOLD: "GOLD (GLD proxy)",
  SILVER: "SILVER (SLV proxy)",
  WTI: "WTI (USO proxy)",
  COPPER: "COPPER (CPER proxy)",
};

export const SOURCES: Record<Category, [string, string]> = {
  CRYPTO: ["gateio", "binance"],
  COMMODITIES: ["yahoo", "nasdaq"],
};

export const SOURCE_LABELS: Record<string, string> = {
  gateio: "Gate.io",
  binance: "Binance",
  yahoo: "Yahoo Finance",
  nasdaq: "Nasdaq",
};
