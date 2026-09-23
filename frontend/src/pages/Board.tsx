import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { Empty, MarketCard, Spinner } from "../components/ui";
import {
  getActivity,
  getMarketsByCategory,
  getStats,
  type Market,
} from "../lib/contract";
import { CATEGORIES, HAS_CONTRACT, PAGE_SIZE, type Category } from "../lib/env";
import { fmtGen } from "../lib/format";
import { useUniverse } from "../lib/useUniverse";

export function Board() {
  const [markets, setMarkets] = useState<Market[]>([]);
  const [stats, setStats] = useState<any>(null);
  const [activity, setActivity] = useState<string[]>([]);
  const [tab, setTab] = useState<Category>("CRYPTO");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);

  const universe = useUniverse();

  // Paginating a filtered subset of get_markets() gave wrong page counts, so the
  // category is pushed down into the contract view and the offset resets with it.
  function pickTab(t: Category) {
    setTab(t);
    setOffset(0);
  }

  useEffect(() => {
    if (!HAS_CONTRACT) {
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    getMarketsByCategory(tab, offset, PAGE_SIZE)
      .then((page) => {
        if (!live) return;
        setMarkets(page.items ?? []);
        setTotal(page.total ?? 0);
        setError(null);
      })
      .catch((e) => live && setError(e?.message ?? String(e)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [tab, offset]);

  useEffect(() => {
    if (!HAS_CONTRACT) return;
    let live = true;
    getStats()
      .then((s) => live && setStats(s))
      .catch(() => {
        /* the health line in the footer already reports this */
      });
    getActivity(0, 8)
      .then((a) => live && setActivity(a.items ?? []))
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const groups = useMemo(() => {
    const g: Record<string, Market[]> = {
      OPEN: [],
      WINDOW_LIVE: [],
      READY_TO_SETTLE: [],
      SETTLED: [],
    };
    for (const m of markets) {
      if (m.phase === "OPEN") g.OPEN.push(m);
      else if (m.phase === "WINDOW_LIVE") g.WINDOW_LIVE.push(m);
      else if (m.phase === "READY_TO_SETTLE") g.READY_TO_SETTLE.push(m);
      else g.SETTLED.push(m);
    }
    return g;
  }, [markets]);

  return (
    <div>
      <section className="mb-8">
        <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50 sm:text-4xl">
          Predict the close.
          <span className="text-spike"> Settled by two sources, not by us.</span>
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-zinc-400">
          Every market resolves inside the contract, from two independent public feeds
          fetched by every validator. If the feeds disagree, nobody wins and every stake is
          refundable. There is no admin key.
        </p>

        {stats && (
          <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Markets" value={String(stats.markets)} />
            <Stat label="Open" value={String(stats.open_markets)} />
            <Stat label="Resolved" value={String(stats.resolved_markets)} />
            <Stat label="Staked" value={`${fmtGen(stats.total_staked_wei)} GEN`} />
          </div>
        )}
      </section>

      <div className="mb-5 flex items-center gap-1 border-b border-ink-800">
        {CATEGORIES.map((t) => (
          <button
            key={t}
            onClick={() => pickTab(t)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold transition-colors ${
              tab === t
                ? "border-spike text-spike"
                : "border-transparent text-zinc-500 hover:text-zinc-300"
            }`}
          >
            {t === "CRYPTO" ? "Crypto" : "Commodities"}
          </button>
        ))}
        <Link to="/create" className="btn-ghost ml-auto mb-1 !py-1.5 !text-xs">
          New market
        </Link>
      </div>

      {tab === "COMMODITIES" && (
        <p className="mb-4 text-xs text-zinc-500">
          Commodities settle on liquid ETF proxies (
          {universe.assets.COMMODITIES.map((a) => universe.label(a).split(" ")[1])
            .join(", ")
            .replace(/[()]/g, "")}
          ) over the US session, because no second keyless public feed serves intraday
          commodity data. Labelled honestly everywhere.
        </p>
      )}

      {loading && (
        <div className="flex items-center gap-2 py-10 text-sm text-zinc-500">
          <Spinner /> Loading markets…
        </div>
      )}

      {error && <Empty title="Could not reach the contract" body={error} />}

      {!loading && !error && markets.length === 0 && (
        <Empty
          title="No markets here yet"
          body="Anyone can create one — there is no gatekeeper."
        />
      )}

      {!loading && !error && markets.length > 0 && (
        <div className="space-y-8">
          <Group title="Open for staking" markets={groups.OPEN} />
          <Group title="Window live" markets={groups.WINDOW_LIVE} />
          <Group title="Ready to settle" markets={groups.READY_TO_SETTLE} />
          <Group title="Settled" markets={groups.SETTLED} />
        </div>
      )}

      {total > PAGE_SIZE && (
        <div className="mt-8 flex items-center justify-center gap-3">
          <button
            className="btn-ghost"
            disabled={offset === 0 || loading}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          >
            Previous
          </button>
          <span className="text-xs text-zinc-500">
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <button
            className="btn-ghost"
            disabled={offset + PAGE_SIZE >= total || loading}
            onClick={() => setOffset(offset + PAGE_SIZE)}
          >
            Next
          </button>
        </div>
      )}

      {activity.length > 0 && (
        <section className="mt-12">
          <h2 className="label mb-3">Recent activity</h2>
          <ul className="card divide-y divide-ink-800 text-xs">
            {activity.map((line, i) => (
              <ActivityRow key={i} line={line} />
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** Activity lines are compact pipe-delimited records written by the contract. */
function ActivityRow({ line }: { line: string }) {
  const [kind, ...rest] = line.split("|");
  const tone: Record<string, string> = {
    CREATE: "text-sky-300",
    STAKE: "text-spike",
    REFUND: "text-amber-300",
    RESOLVE: "text-emerald-300",
    CLAIM: "text-emerald-300",
    TERMINAL: "text-zinc-400",
  };
  return (
    <li className="flex items-center gap-3 px-4 py-2">
      <span className={`mono w-20 shrink-0 font-bold ${tone[kind] ?? "text-zinc-400"}`}>
        {kind}
      </span>
      <span className="mono truncate text-zinc-500">{rest.join(" · ")}</span>
    </li>
  );
}

function Group({ title, markets }: { title: string; markets: Market[] }) {
  if (markets.length === 0) return null;
  return (
    <section>
      <h2 className="label mb-3">
        {title} · {markets.length}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {markets.map((m) => (
          <MarketCard key={m.market_id} market={m} />
        ))}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="card px-4 py-3">
      <p className="label">{label}</p>
      <p className="mono mt-1 text-lg font-bold text-zinc-100">{value}</p>
    </div>
  );
}
