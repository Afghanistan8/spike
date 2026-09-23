/**
 * The catalog, preferring what the contract says over what env.ts guesses.
 *
 * env.ts is a compile-time mirror of a catalog that is frozen in the contract,
 * so the two should never diverge — but if they ever do, the chain is right and
 * a stale bundle is wrong. This loads get_supported_universe once on boot and
 * falls back to env.ts until it arrives (and forever, if the read fails).
 */

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { getSupportedUniverse } from "./contract";
import {
  ASSETS,
  ASSET_LABELS,
  HAS_CONTRACT,
  HOURLY_CATEGORIES,
  SOURCES,
  type Category,
} from "./env";

export type Universe = {
  assets: Record<Category, string[]>;
  label: (asset: string) => string;
  sources: Record<Category, string[]>;
  hourly: (category: string) => boolean;
  /** True once the on-chain catalog has been read. */
  fromChain: boolean;
};

const FALLBACK: Universe = {
  assets: ASSETS,
  label: (a) => ASSET_LABELS[a] ?? a,
  sources: SOURCES as unknown as Record<Category, string[]>,
  hourly: (c) => HOURLY_CATEGORIES.includes(c as Category),
  fromChain: false,
};

const Ctx = createContext<Universe>(FALLBACK);

export function UniverseProvider({ children }: { children: ReactNode }) {
  const [raw, setRaw] = useState<any>(null);

  useEffect(() => {
    if (!HAS_CONTRACT) return;
    let live = true;
    getSupportedUniverse()
      .then((u) => live && setRaw(u))
      .catch(() => {
        /* fallback stays in force; the footer health line reports the failure */
      });
    return () => {
      live = false;
    };
  }, []);

  const value = useMemo<Universe>(() => {
    if (!raw?.assets) return FALLBACK;
    const labels: Record<string, Record<string, string>> = raw.labels ?? {};
    const flat: Record<string, string> = {};
    for (const cat of Object.keys(labels)) Object.assign(flat, labels[cat]);
    return {
      assets: raw.assets,
      label: (a) => flat[a] ?? ASSET_LABELS[a] ?? a,
      sources: raw.sources ?? FALLBACK.sources,
      hourly: (c) => (raw.hourly_categories ?? ["CRYPTO"]).includes(c),
      fromChain: true,
    };
  }, [raw]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useUniverse(): Universe {
  return useContext(Ctx);
}
