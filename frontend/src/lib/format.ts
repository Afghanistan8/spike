/** Display helpers. None of this is used for settlement. */

import { ONE_GEN } from "./env";

export function fmtGen(wei: string | bigint, dp = 2): string {
  const v = typeof wei === "bigint" ? wei : BigInt(wei || "0");
  const whole = v / ONE_GEN;
  const frac = v % ONE_GEN;
  if (dp === 0) return whole.toString();
  const fracStr = frac.toString().padStart(18, "0").slice(0, dp);
  return `${whole}.${fracStr}`;
}

export function parseGen(input: string): bigint {
  const s = (input || "").trim();
  if (!s) return 0n;
  if (!/^\d*\.?\d*$/.test(s)) throw new Error("Enter a number");
  const [w, f = ""] = s.split(".");
  const frac = (f + "0".repeat(18)).slice(0, 18);
  return BigInt(w || "0") * ONE_GEN + BigInt(frac || "0");
}

/** Spike settles on a FIXED GMT+1 offset - never the browser's timezone. */
export function gmt1(ts: number): string {
  const d = new Date((ts + 3600) * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(
    d.getUTCHours()
  )}:${p(d.getUTCMinutes())}`;
}

export function gmt1Day(ts: number): string {
  return gmt1(ts).slice(0, 10);
}

/** Today's date in GMT+1, as YYYY-MM-DD. */
export function todayGmt1(): string {
  return gmt1Day(Math.floor(Date.now() / 1000));
}

export function countdown(toTs: number, nowTs = Math.floor(Date.now() / 1000)): string {
  let s = toTs - nowTs;
  if (s <= 0) return "now";
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

export function shortAddr(a: string): string {
  if (!a || a.length < 12) return a || "";
  return `${a.slice(0, 6)}…${a.slice(-4)}`;
}

export function pct(part: string | bigint, total: string | bigint): number {
  const p = typeof part === "bigint" ? part : BigInt(part || "0");
  const t = typeof total === "bigint" ? total : BigInt(total || "0");
  if (t === 0n) return 0;
  return Number((p * 10000n) / t) / 100;
}

export const PHASE_LABEL: Record<string, string> = {
  OPEN: "Open",
  WINDOW_LIVE: "Live",
  READY_TO_SETTLE: "Ready to settle",
  SETTLED_UP: "Settled · UP",
  SETTLED_DOWN: "Settled · DOWN",
  SETTLED_WINNER: "Settled",
  INCONCLUSIVE: "Inconclusive",
};

export function phaseTone(phase: string): string {
  switch (phase) {
    case "OPEN":
      return "bg-spike/15 text-spike";
    case "WINDOW_LIVE":
      return "bg-amber-400/15 text-amber-300";
    case "READY_TO_SETTLE":
      return "bg-sky-400/15 text-sky-300";
    case "INCONCLUSIVE":
      return "bg-zinc-500/15 text-zinc-400";
    default:
      return "bg-emerald-400/15 text-emerald-300";
  }
}
