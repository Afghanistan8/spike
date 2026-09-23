import { Link } from "react-router-dom";
import type { ReactNode } from "react";

import { PHASE_LABEL, fmtGen, pct, phaseTone } from "../lib/format";
import type { Market } from "../lib/contract";
import { SOURCE_LABELS } from "../lib/env";

export function Chip({ children, tone }: { children: ReactNode; tone?: string }) {
  return <span className={`chip ${tone ?? "bg-ink-800 text-zinc-400"}`}>{children}</span>;
}

export function PhaseChip({ phase }: { phase: string }) {
  return <Chip tone={phaseTone(phase)}>{PHASE_LABEL[phase] ?? phase}</Chip>;
}

export function Spinner() {
  return (
    <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
  );
}

export function Empty({ title, body }: { title: string; body?: string }) {
  return (
    <div className="card p-10 text-center">
      <p className="text-sm font-semibold text-zinc-300">{title}</p>
      {body && <p className="mt-1 text-sm text-zinc-500">{body}</p>}
    </div>
  );
}

export function Banner({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "error" | "good";
  children: ReactNode;
}) {
  const tones = {
    info: "border-sky-500/30 bg-sky-500/10 text-sky-200",
    warn: "border-amber-500/30 bg-amber-500/10 text-amber-200",
    error: "border-red-500/30 bg-red-500/10 text-red-200",
    good: "border-spike/30 bg-spike/10 text-spike",
  } as const;
  return (
    <div className={`rounded-md border px-4 py-3 text-sm ${tones[tone]}`}>{children}</div>
  );
}

/** A two-sided pool bar for direction markets. */
export function DirectionBar({ market }: { market: Market }) {
  const up = market.pools["UP"] ?? "0";
  const down = market.pools["DOWN"] ?? "0";
  const total = BigInt(up) + BigInt(down);
  const upPct = total === 0n ? 50 : pct(up, total.toString());

  return (
    <div>
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-semibold text-up">UP {fmtGen(up)} GEN</span>
        <span className="font-semibold text-down">DOWN {fmtGen(down)} GEN</span>
      </div>
      <div className="mt-1.5 flex h-2 overflow-hidden rounded-full bg-ink-800">
        <div className="bg-up" style={{ width: `${upPct}%` }} />
        <div className="bg-down" style={{ width: `${100 - upPct}%` }} />
      </div>
    </div>
  );
}

/** A four-way race for dominance markets. */
export function DominanceRace({ market }: { market: Market }) {
  const total = market.sides.reduce((a, s) => a + BigInt(market.pools[s] ?? "0"), 0n);
  const winner = market.final_verdict.startsWith("WIN:")
    ? market.final_verdict.slice(4)
    : null;

  return (
    <div className="space-y-1.5">
      {market.sides.map((s) => {
        const v = market.pools[s] ?? "0";
        const p = total === 0n ? 0 : pct(v, total.toString());
        const won = winner === s;
        return (
          <div key={s} className="flex items-center gap-2">
            <span
              className={`w-16 shrink-0 text-xs font-semibold ${
                won ? "text-spike" : "text-zinc-400"
              }`}
            >
              {s}
            </span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-800">
              <div
                className={won ? "h-full bg-spike" : "h-full bg-zinc-600"}
                style={{ width: `${Math.max(p, total === 0n ? 0 : 2)}%` }}
              />
            </div>
            <span className="mono w-20 shrink-0 text-right text-xs text-zinc-500">
              {fmtGen(v)}
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function MarketCard({ market }: { market: Market }) {
  const isDominance = market.kind === "KIND_DOMINANCE";
  const title = isDominance
    ? `${market.category === "CRYPTO" ? "Crypto" : "Commodity"} dominance`
    : market.asset_label;

  return (
    <Link
      to={`/market/${market.market_id}`}
      className="card block p-4 transition-colors hover:border-spike/60"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-bold text-zinc-100">{title}</p>
          <p className="mono mt-0.5 text-xs text-zinc-500">
            {market.target_day}
            {market.target_hour >= 0
              ? ` · ${String(market.target_hour).padStart(2, "0")}:00 GMT+1`
              : " · daily"}
          </p>
        </div>
        <PhaseChip phase={market.phase} />
      </div>

      <div className="mt-4">
        {isDominance ? <DominanceRace market={market} /> : <DirectionBar market={market} />}
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-ink-800 pt-3 text-[11px] text-zinc-500">
        <span>Pool {fmtGen(market.total_pool)} GEN</span>
        <span>
          {SOURCE_LABELS[sourceA(market)] ?? sourceA(market)} +{" "}
          {SOURCE_LABELS[sourceB(market)] ?? sourceB(market)}
        </span>
      </div>
    </Link>
  );
}

function sourceA(m: Market) {
  return m.category === "CRYPTO" ? "gateio" : "yahoo";
}
function sourceB(m: Market) {
  return m.category === "CRYPTO" ? "binance" : "nasdaq";
}
