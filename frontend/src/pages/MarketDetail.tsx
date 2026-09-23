import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import {
  Banner,
  Chip,
  DirectionBar,
  DominanceRace,
  PhaseChip,
  Spinner,
  WalletError,
} from "../components/ui";
import {
  claim as claimCall,
  getMarket,
  getMarketPositions,
  getPosition,
  getSettlementEvidence,
  resolveMarket,
  takePosition,
  type Evidence,
  type Market,
  type Position,
} from "../lib/contract";
import { getNativeBalance } from "../lib/client";
import { MAX_STAKE_WEI, MIN_STAKE_WEI, SOURCE_LABELS } from "../lib/env";
import { watchPayout } from "../lib/payout";
import { countdown, fmtGen, gmt1, parseGen, shortAddr } from "../lib/format";
import { useWallet } from "../lib/useWallet";
import { explainError, parseStakeOutcome } from "../lib/write";

export function MarketDetail() {
  const { id = "" } = useParams();
  const { account, onStudionet } = useWallet();

  const [market, setMarket] = useState<Market | null>(null);
  const [position, setPosition] = useState<Position | null>(null);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [holders, setHolders] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [msg, setMsg] = useState<{ tone: "good" | "warn" | "error" | "info"; text: string } | null>(
    null
  );
  const [busy, setBusy] = useState<string | null>(null);

  const [side, setSide] = useState<string>("");
  const [amount, setAmount] = useState("1");

  const load = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const m = await getMarket(id);
      if (!m || !m.market_id) {
        setMarket(null);
        return;
      }
      setMarket(m);
      setSide((s) => s || m.sides[0]);
      setHolders((await getMarketPositions(id)).items ?? []);
      if (m.final_verdict) setEvidence(await getSettlementEvidence(id));
      if (account) setPosition(await getPosition(id, account));
    } catch (e: any) {
      setMsg({ tone: "error", text: e?.message ?? String(e) });
    } finally {
      setLoading(false);
    }
  }, [id, account]);

  useEffect(() => {
    load();
  }, [load]);

  async function onStake() {
    if (!account || !market) return;
    setBusy("stake");
    setMsg(null);
    try {
      const wei = parseGen(amount);
      let balanceBefore = 0n;
      try {
        balanceBefore = await getNativeBalance(account);
      } catch {
        /* confirmation is best-effort */
      }
      const res = await takePosition(account, market.market_id, side, wei);
      const outcome = parseStakeOutcome(res.returned);
      if (outcome.kind === "staked") {
        setMsg({
          tone: "good",
          text: `Staked. Your position on ${side} is now ${fmtGen(outcome.totalWei)} GEN.`,
        });
      } else if (outcome.kind === "refunded") {
        setMsg({
          tone: "warn",
          text: `Not accepted — ${outcome.reason}. Returning your GEN…`,
        });
        const watch = await watchPayout(account, balanceBefore - wei);
        setMsg(
          watch.kind === "arrived"
            ? {
                tone: "good",
                text: `Not accepted — ${outcome.reason}. Your ${fmtGen(
                  watch.delta
                )} GEN came back.`,
              }
            : {
                tone: "warn",
                text: `Not accepted — ${outcome.reason}. The refund is emitted on finality and had not landed yet; check your balance shortly.`,
              }
        );
      } else {
        setMsg({ tone: "info", text: `Submitted. Contract said: ${outcome.raw}` });
      }
      await load();
    } catch (e) {
      setMsg({ tone: "error", text: explainError(e) });
    } finally {
      setBusy(null);
    }
  }

  async function onResolve() {
    if (!account || !market) return;
    setBusy("resolve");
    setMsg(null);
    try {
      const res = await resolveMarket(account, market.market_id);
      setMsg({ tone: "good", text: `Resolved: ${String(res.returned)}` });
      await load();
    } catch (e) {
      setMsg({ tone: "error", text: explainError(e) });
    } finally {
      setBusy(null);
    }
  }

  /**
   * Claim, then verify the GEN actually landed.
   *
   * The contract emits an external message that executes on finalisation, so
   * `claimed = true` alone does not mean the wallet was paid. We snapshot the
   * balance first and watch it, so a stuck payout cannot read as success.
   */
  async function onClaim() {
    if (!account || !market) return;
    setBusy("claim");
    setMsg(null);
    let before = 0n;
    try {
      before = await getNativeBalance(account);
    } catch {
      /* if we cannot read it we simply cannot confirm; the claim still proceeds */
    }
    try {
      const res = await claimCall(account, market.market_id);
      setMsg({
        tone: "info",
        text: `${String(res.returned)} — waiting for the payout to finalise…`,
      });
      await load();

      const watch = await watchPayout(account, before);
      if (watch.kind === "arrived") {
        setMsg({
          tone: "good",
          text: `Paid. ${fmtGen(watch.delta)} GEN arrived in your wallet after ${Math.round(
            watch.afterMs / 1000
          )}s.`,
        });
      } else if (watch.kind === "pending") {
        setMsg({
          tone: "warn",
          text:
            `The contract recorded your claim, but no GEN had reached your wallet after ` +
            `${Math.round(watch.waitedMs / 1000)}s. Outbound transfers execute on finality, ` +
            `so it may still land — check your balance shortly. If it never arrives, the ` +
            `payout path is broken, not your position.`,
        });
      } else {
        setMsg({
          tone: "warn",
          text: `Claim recorded, but the balance check failed (${watch.reason}). Check your wallet.`,
        });
      }
      await load();
    } catch (e) {
      setMsg({ tone: "error", text: explainError(e) });
    } finally {
      setBusy(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-10 text-sm text-zinc-500">
        <Spinner /> Loading market…
      </div>
    );
  }
  if (!market) return <Banner tone="warn">No market with id {id}.</Banner>;

  const isDominance = market.kind === "KIND_DOMINANCE";
  const canStake = market.phase === "OPEN";
  const canResolve = market.phase === "READY_TO_SETTLE";
  const claimable = position ? BigInt(position.claimable_wei || "0") : 0n;
  const disabled = !account || !onStudionet;

  // The same rules the contract enforces, checked before anyone signs. A
  // rejected stake is refunded rather than reverted, but it still costs a
  // round trip and is confusing, so it is better not to send it at all.
  const held = position && position.market_id ? BigInt(position.amount_wei || "0") : 0n;
  const lockedSide = position && position.market_id ? position.side : null;
  const stakeProblem = ((): string | null => {
    let wei: bigint;
    try {
      wei = parseGen(amount);
    } catch {
      return "Enter an amount in GEN, for example 1 or 2.5.";
    }
    if (wei <= 0n) return "Enter an amount greater than zero.";
    if (lockedSide && lockedSide !== side)
      return `You already backed ${lockedSide} on this market. You cannot switch sides.`;
    if (held === 0n && wei < MIN_STAKE_WEI)
      return `The first stake on a market must be at least ${fmtGen(MIN_STAKE_WEI, 0)} GEN.`;
    if (held + wei > MAX_STAKE_WEI)
      return held === 0n
        ? `The most you can stake on one market is ${fmtGen(MAX_STAKE_WEI, 0)} GEN.`
        : `You already hold ${fmtGen(held)} GEN here, so you can add at most ${fmtGen(
            MAX_STAKE_WEI - held
          )} GEN.`;
    return null;
  })();

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div className="space-y-6">
        <div className="card p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-2xl font-extrabold text-zinc-50">
                {isDominance
                  ? `${market.category === "CRYPTO" ? "Crypto" : "Commodity"} dominance`
                  : market.asset_label}
              </h1>
              <p className="mono mt-1 text-sm text-zinc-500">
                {market.target_day}
                {market.target_hour >= 0
                  ? ` · ${String(market.target_hour).padStart(2, "0")}:00–${String(
                      market.target_hour + 1
                    ).padStart(2, "0")}:00 GMT+1`
                  : " · full session, GMT+1"}
              </p>
            </div>
            <PhaseChip phase={market.phase} />
          </div>

          <p className="mt-4 text-sm text-zinc-400">
            {isDominance
              ? `Which of ${market.sides.join(", ")} posts the strongest percentage return over the window.`
              : `Does the completed candle close UP or DOWN? A flat close counts as DOWN.`}
          </p>

          <div className="mt-5">
            {isDominance ? (
              <DominanceRace market={market} />
            ) : (
              <DirectionBar market={market} />
            )}
          </div>

          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-ink-800 pt-4 text-xs sm:grid-cols-3">
            <Field label="Pool" value={`${fmtGen(market.total_pool)} GEN`} />
            <Field label="Window opens" value={gmt1(market.window_open) + " GMT+1"} />
            <Field label="Window closes" value={gmt1(market.window_close) + " GMT+1"} />
            <Field
              label="Settles"
              value={
                market.final_verdict
                  ? "done"
                  : countdown(market.settles_at) + " from now"
              }
            />
            <Field
              label="Terminal refund"
              value={gmt1(market.terminal_refund_at) + " GMT+1"}
            />
            <Field label="Creator" value={shortAddr(market.creator)} />
          </dl>
        </div>

        {evidence && <EvidencePanel ev={evidence} />}

        <div className="card p-5">
          <h2 className="label mb-3">Positions · {holders.length}</h2>
          {holders.length === 0 ? (
            <p className="text-sm text-zinc-500">Nobody has staked yet.</p>
          ) : (
            <table className="w-full text-left text-xs">
              <thead className="text-zinc-600">
                <tr>
                  <th className="pb-2 font-semibold">Wallet</th>
                  <th className="pb-2 font-semibold">Side</th>
                  <th className="pb-2 text-right font-semibold">Stake</th>
                </tr>
              </thead>
              <tbody className="mono">
                {holders.map((p, i) => (
                  <tr key={i} className="border-t border-ink-800">
                    <td className="py-2 text-zinc-400">{shortAddr(p.wallet)}</td>
                    <td className="py-2 text-zinc-300">{p.side}</td>
                    <td className="py-2 text-right text-zinc-300">
                      {fmtGen(p.amount_wei)} GEN
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <aside className="space-y-4">
        <WalletError />
        {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}

        {disabled && (
          <Banner tone="info">
            {account ? "Switch to Studionet to act." : "Connect a wallet to act."}
          </Banner>
        )}

        {canStake && (
          <div className="card p-5">
            <h2 className="label mb-3">Take a position</h2>

            <div className="grid grid-cols-2 gap-2">
              {market.sides.map((s) => {
                const locked = lockedSide !== null && lockedSide !== s;
                return (
                  <button
                    key={s}
                    onClick={() => setSide(s)}
                    disabled={locked}
                    title={locked ? `You already backed ${lockedSide}` : undefined}
                    className={`rounded-md border px-3 py-2 text-sm font-bold transition-colors ${
                      side === s
                        ? "border-spike bg-spike/10 text-spike"
                        : locked
                          ? "cursor-not-allowed border-ink-800 text-zinc-700"
                          : "border-ink-700 text-zinc-400 hover:border-zinc-500"
                    }`}
                  >
                    {s}
                  </button>
                );
              })}
            </div>

            <label className="label mt-4 block">Stake (1–5 GEN)</label>
            <input
              className="input mono mt-1"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              inputMode="decimal"
            />
            <p className="mt-1.5 text-[11px] text-zinc-500">
              First stake must be {fmtGen(MIN_STAKE_WEI, 0)}–{fmtGen(MAX_STAKE_WEI, 0)} GEN.
              Top-ups stay on the same side and the total still caps at{" "}
              {fmtGen(MAX_STAKE_WEI, 0)} GEN. You cannot switch sides.
            </p>

            {stakeProblem && account && (
              <p className="mt-2 text-[11px] font-semibold text-amber-300">
                {stakeProblem}
              </p>
            )}

            <button
              className="btn-primary mt-4 w-full"
              disabled={disabled || busy !== null || stakeProblem !== null}
              onClick={onStake}
            >
              {busy === "stake" ? <Spinner /> : null}
              {busy === "stake" ? "Submitting…" : `Stake on ${side}`}
            </button>
            <p className="mt-2 text-[11px] leading-relaxed text-zinc-600">
              If the stake is not acceptable the contract returns your GEN rather than
              reverting, because value attached to a reverted call would be lost.
            </p>
          </div>
        )}

        {canResolve && (
          <div className="card p-5">
            <h2 className="label mb-2">Resolve</h2>
            <p className="text-sm text-zinc-400">
              Anyone can trigger resolution. Every validator fetches{" "}
              {SOURCE_LABELS[market.category === "CRYPTO" ? "gateio" : "yahoo"]} and{" "}
              {SOURCE_LABELS[market.category === "CRYPTO" ? "binance" : "nasdaq"]}{" "}
              independently.
            </p>
            <button
              className="btn-primary mt-4 w-full"
              disabled={disabled || busy !== null}
              onClick={onResolve}
            >
              {busy === "resolve" ? <Spinner /> : null}
              {busy === "resolve" ? "Resolving…" : "Resolve market"}
            </button>
            <p className="mt-2 text-[11px] text-zinc-600">
              If a feed is unreachable this reverts as retryable and the market is left
              untouched.
            </p>
          </div>
        )}

        {position && position.market_id && (
          <div className="card p-5">
            <h2 className="label mb-3">Your position</h2>
            <dl className="space-y-2 text-xs">
              <Field label="Side" value={position.side} />
              <Field label="Stake" value={`${fmtGen(position.amount_wei)} GEN`} />
              <Field
                label="Claimable"
                value={`${fmtGen(position.claimable_wei)} GEN`}
              />
              <Field label="Claimed" value={position.claimed ? "yes" : "no"} />
            </dl>

            {claimable > 0n && !position.claimed && (
              <>
                <button
                  className="btn-primary mt-4 w-full"
                  disabled={disabled || busy !== null}
                  onClick={onClaim}
                >
                  {busy === "claim" ? <Spinner /> : null}
                  {busy === "claim" ? "Claiming…" : `Claim ${fmtGen(claimable)} GEN`}
                </button>
                <p className="mt-2 text-[11px] text-zinc-600">
                  GEN leaves the contract as an external message and arrives in a
                  separate follow-up transaction after finality.
                </p>
              </>
            )}
          </div>
        )}
      </aside>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="mono mt-0.5 text-zinc-300">{value}</dd>
    </div>
  );
}

function EvidencePanel({ ev }: { ev: Evidence }) {
  let parsed: any = null;
  try {
    parsed = JSON.parse(ev.evidence);
  } catch {
    /* terminal refunds store plain text */
  }
  const agreed = ev.source_a_verdict === ev.source_b_verdict && ev.source_a_verdict !== "";

  return (
    <div className="card p-5">
      <h2 className="label mb-3">Settlement evidence</h2>

      <div className="grid gap-3 sm:grid-cols-2">
        <SourceBox
          name={SOURCE_LABELS[ev.source_a_id] ?? ev.source_a_id}
          verdict={ev.source_a_verdict}
          prices={parsed?.source_a_prices}
          assets={parsed?.assets}
        />
        <SourceBox
          name={SOURCE_LABELS[ev.source_b_id] ?? ev.source_b_id}
          verdict={ev.source_b_verdict}
          prices={parsed?.source_b_prices}
          assets={parsed?.assets}
        />
      </div>

      <div className="mt-4 flex items-center gap-2 border-t border-ink-800 pt-4">
        <Chip tone={agreed ? "bg-spike/15 text-spike" : "bg-zinc-500/15 text-zinc-400"}>
          {agreed ? "Sources agreed" : "Sources disagreed"}
        </Chip>
        <span className="mono text-sm font-bold text-zinc-100">
          {ev.final_verdict || "—"}
        </span>
        {ev.refund_all && (
          <span className="ml-auto text-xs text-zinc-400">
            Every stake is refundable.
          </span>
        )}
      </div>

      {!parsed && ev.evidence && (
        <p className="mt-3 text-xs text-zinc-500">{ev.evidence}</p>
      )}
    </div>
  );
}

function SourceBox({
  name,
  verdict,
  prices,
  assets,
}: {
  name: string;
  verdict: string;
  prices?: number[];
  assets?: string[];
}) {
  return (
    <div className="rounded-md border border-ink-800 p-3">
      <p className="label">{name}</p>
      <p className="mono mt-1 text-sm font-bold text-zinc-100">{verdict || "—"}</p>
      {prices && assets && (
        <table className="mono mt-2 w-full text-[11px] text-zinc-500">
          <tbody>
            {assets.map((a, i) => (
              <tr key={a}>
                <td className="pr-2">{a}</td>
                <td className="text-right">{scaled(prices[i * 2])}</td>
                <td className="px-1 text-zinc-700">→</td>
                <td className="text-right">{scaled(prices[i * 2 + 1])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function scaled(v?: number): string {
  if (v === undefined || v === null) return "—";
  return (Number(v) / 1e8).toLocaleString(undefined, { maximumFractionDigits: 6 });
}
