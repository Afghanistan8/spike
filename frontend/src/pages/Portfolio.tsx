import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Empty, PhaseChip, Spinner } from "../components/ui";
import { claim as claimCall, getUserPositions, type Position } from "../lib/contract";
import { HAS_CONTRACT } from "../lib/env";
import { fmtGen } from "../lib/format";
import { useWallet } from "../lib/useWallet";
import { explainError } from "../lib/write";

export function Portfolio() {
  const { account, onStudionet } = useWallet();
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ tone: "good" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    if (!account || !HAS_CONTRACT) return;
    setLoading(true);
    try {
      setPositions((await getUserPositions(account)).items ?? []);
    } catch (e: any) {
      setMsg({ tone: "error", text: e?.message ?? String(e) });
    } finally {
      setLoading(false);
    }
  }, [account]);

  useEffect(() => {
    load();
  }, [load]);

  async function onClaim(marketId: string) {
    if (!account) return;
    setBusy(marketId);
    setMsg(null);
    try {
      const res = await claimCall(account, marketId);
      setMsg({
        tone: "good",
        text: `${String(res.returned)} — GEN arrives as a separate transaction once this one finalises.`,
      });
      await load();
    } catch (e) {
      setMsg({ tone: "error", text: explainError(e) });
    } finally {
      setBusy(null);
    }
  }

  const staked = positions.reduce((a, p) => a + BigInt(p.amount_wei || "0"), 0n);
  const claimable = positions.reduce((a, p) => a + BigInt(p.claimable_wei || "0"), 0n);

  if (!account) {
    return (
      <Empty title="Connect a wallet" body="Your positions and claimable GEN appear here." />
    );
  }

  return (
    <div>
      <h1 className="text-2xl font-extrabold text-zinc-50">Portfolio</h1>

      <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Positions" value={String(positions.length)} />
        <Stat label="Staked" value={`${fmtGen(staked)} GEN`} />
        <Stat label="Claimable" value={`${fmtGen(claimable)} GEN`} accent />
      </div>

      {msg && (
        <div className="mt-4">
          <Banner tone={msg.tone}>{msg.text}</Banner>
        </div>
      )}
      {!onStudionet && (
        <div className="mt-4">
          <Banner tone="info">Switch to Studionet to claim.</Banner>
        </div>
      )}

      {loading && (
        <div className="mt-6 flex items-center gap-2 text-sm text-zinc-500">
          <Spinner /> Loading…
        </div>
      )}

      {!loading && positions.length === 0 && (
        <div className="mt-6">
          <Empty title="No positions yet" body="Back a side on the board to get started." />
        </div>
      )}

      {positions.length > 0 && (
        <div className="card mt-6 overflow-hidden">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-ink-800 text-zinc-600">
              <tr>
                <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider">
                  Market
                </th>
                <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider">
                  Side
                </th>
                <th className="px-4 py-3 text-xs font-semibold uppercase tracking-wider">
                  Phase
                </th>
                <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider">
                  Stake
                </th>
                <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wider">
                  Claimable
                </th>
                <th />
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const c = BigInt(p.claimable_wei || "0");
                return (
                  <tr key={p.market_id} className="border-b border-ink-800 last:border-0">
                    <td className="px-4 py-3">
                      <Link
                        to={`/market/${p.market_id}`}
                        className="mono text-zinc-300 hover:text-spike"
                      >
                        #{p.market_id}
                      </Link>
                    </td>
                    <td className="mono px-4 py-3 text-zinc-300">{p.side}</td>
                    <td className="px-4 py-3">
                      <PhaseChip phase={p.phase} />
                    </td>
                    <td className="mono px-4 py-3 text-right text-zinc-300">
                      {fmtGen(p.amount_wei)}
                    </td>
                    <td
                      className={`mono px-4 py-3 text-right ${
                        c > 0n ? "text-spike" : "text-zinc-600"
                      }`}
                    >
                      {fmtGen(p.claimable_wei)}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {c > 0n && !p.claimed && (
                        <button
                          className="btn-ghost !px-3 !py-1 !text-xs"
                          disabled={!onStudionet || busy !== null}
                          onClick={() => onClaim(p.market_id)}
                        >
                          {busy === p.market_id ? "Claiming…" : "Claim"}
                        </button>
                      )}
                      {p.claimed && <span className="text-xs text-zinc-600">claimed</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="card px-4 py-3">
      <p className="label">{label}</p>
      <p
        className={`mono mt-1 text-lg font-bold ${
          accent ? "text-spike" : "text-zinc-100"
        }`}
      >
        {value}
      </p>
    </div>
  );
}
