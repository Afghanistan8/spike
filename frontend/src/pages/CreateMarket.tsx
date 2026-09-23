import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Banner, Spinner } from "../components/ui";
import { createMarket } from "../lib/contract";
import {
  ASSETS,
  ASSET_LABELS,
  KIND_DIRECTION,
  KIND_DOMINANCE,
  SOURCE_LABELS,
  SOURCES,
  type Category,
} from "../lib/env";
import { todayGmt1 } from "../lib/format";
import { useWallet } from "../lib/useWallet";
import { explainError } from "../lib/write";

export function CreateMarket() {
  const { account, onStudionet } = useWallet();
  const navigate = useNavigate();

  const [kind, setKind] = useState(KIND_DIRECTION);
  const [category, setCategory] = useState<Category>("CRYPTO");
  const [asset, setAsset] = useState("ADA");
  const [day, setDay] = useState(tomorrow());
  const [hour, setHour] = useState(14);

  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "good" | "error" | "warn"; text: string } | null>(
    null
  );

  // Only CRYPTO dominance is hourly; everything else uses -1.
  const hourly = category === "CRYPTO" && kind === KIND_DOMINANCE;
  const effectiveHour = hourly ? hour : -1;
  const effectiveAsset = kind === KIND_DOMINANCE ? "" : asset;

  const uniqueKey = `${kind}|${category}|${effectiveAsset}|${day}|${effectiveHour}`;

  const weekendProblem = useMemo(() => {
    if (category !== "COMMODITIES") return null;
    const d = new Date(day + "T00:00:00Z").getUTCDay();
    return d === 0 || d === 6
      ? "Commodity markets cannot target a Saturday or Sunday — there is no session."
      : null;
  }, [category, day]);

  const pastProblem = day <= todayGmt1() ? "Pick a day that has not started yet in GMT+1." : null;

  async function submit() {
    if (!account) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await createMarket(
        account,
        kind,
        category,
        effectiveAsset,
        day,
        effectiveHour
      );
      const id = String(res.returned ?? "");
      setMsg({ tone: "good", text: `Market ${id} created.` });
      if (/^\d+$/.test(id)) setTimeout(() => navigate(`/market/${id}`), 600);
    } catch (e) {
      setMsg({ tone: "error", text: explainError(e) });
    } finally {
      setBusy(false);
    }
  }

  const blocked = weekendProblem || pastProblem;
  const disabled = !account || !onStudionet || busy || !!blocked;

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-extrabold text-zinc-50">Create a market</h1>
      <p className="mt-2 text-sm text-zinc-400">
        Anyone can list one. There is no approval step and no listing fee beyond gas.
      </p>

      <div className="card mt-6 space-y-5 p-5">
        <div>
          <label className="label">Kind</label>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <Choice
              active={kind === KIND_DIRECTION}
              onClick={() => setKind(KIND_DIRECTION)}
              title="Direction"
              sub="One asset, UP or DOWN"
            />
            <Choice
              active={kind === KIND_DOMINANCE}
              onClick={() => setKind(KIND_DOMINANCE)}
              title="Dominance"
              sub="Which of four wins"
            />
          </div>
        </div>

        <div>
          <label className="label">Category</label>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {(["CRYPTO", "COMMODITIES"] as Category[]).map((c) => (
              <Choice
                key={c}
                active={category === c}
                onClick={() => {
                  setCategory(c);
                  setAsset(ASSETS[c][0]);
                }}
                title={c === "CRYPTO" ? "Crypto" : "Commodities"}
                sub={ASSETS[c].join(" · ")}
              />
            ))}
          </div>
        </div>

        {kind === KIND_DIRECTION && (
          <div>
            <label className="label">Asset</label>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {ASSETS[category].map((a) => (
                <button
                  key={a}
                  onClick={() => setAsset(a)}
                  className={`rounded-md border px-2 py-2 text-xs font-bold transition-colors ${
                    asset === a
                      ? "border-spike bg-spike/10 text-spike"
                      : "border-ink-700 text-zinc-400 hover:border-zinc-500"
                  }`}
                >
                  {a}
                </button>
              ))}
            </div>
            {category === "COMMODITIES" && (
              <p className="mt-2 text-[11px] text-zinc-500">
                Settles on {ASSET_LABELS[asset]} over the US session.
              </p>
            )}
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label">Target day (GMT+1)</label>
            <input
              type="date"
              className="input mono mt-1"
              value={day}
              onChange={(e) => setDay(e.target.value)}
            />
          </div>

          {hourly && (
            <div>
              <label className="label">Target hour (GMT+1)</label>
              <select
                className="input mono mt-1"
                value={hour}
                onChange={(e) => setHour(Number(e.target.value))}
              >
                {Array.from({ length: 24 }, (_, h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, "0")}:00 – {String(h + 1).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>

        {kind === KIND_DOMINANCE && category === "COMMODITIES" && (
          <Banner tone="info">
            Commodity dominance is ranked over the <strong>daily session</strong>, not an
            hour. There is no second keyless public feed with intraday commodity data, and
            Spike will not settle anything from a single source.
          </Banner>
        )}

        <div className="rounded-md border border-ink-800 bg-ink-950 p-3">
          <p className="label">Unique key</p>
          <p className="mono mt-1 break-all text-xs text-zinc-400">{uniqueKey}</p>
          <p className="mt-2 text-[11px] text-zinc-600">
            Settled by {SOURCE_LABELS[SOURCES[category][0]]} +{" "}
            {SOURCE_LABELS[SOURCES[category][1]]}. A market with this exact key can only
            exist once.
          </p>
        </div>

        {blocked && <Banner tone="warn">{blocked}</Banner>}
        {msg && <Banner tone={msg.tone}>{msg.text}</Banner>}
        {!account && <Banner tone="info">Connect a wallet to create a market.</Banner>}

        <button className="btn-primary w-full" disabled={disabled} onClick={submit}>
          {busy ? <Spinner /> : null}
          {busy ? "Creating…" : "Create market"}
        </button>
      </div>
    </div>
  );
}

function Choice({
  active,
  onClick,
  title,
  sub,
}: {
  active: boolean;
  onClick: () => void;
  title: string;
  sub: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-md border p-3 text-left transition-colors ${
        active
          ? "border-spike bg-spike/10"
          : "border-ink-700 hover:border-zinc-500"
      }`}
    >
      <p className={`text-sm font-bold ${active ? "text-spike" : "text-zinc-200"}`}>
        {title}
      </p>
      <p className="mt-0.5 text-[11px] text-zinc-500">{sub}</p>
    </button>
  );
}

function tomorrow(): string {
  const d = new Date(Date.now() + 86400000 + 3600000);
  return d.toISOString().slice(0, 10);
}
