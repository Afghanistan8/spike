import { ASSETS, ASSET_LABELS } from "../lib/env";

export function HowItWorks() {
  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="text-3xl font-extrabold tracking-tight text-zinc-50">
        How Spike settles
      </h1>
      <p className="mt-3 text-sm leading-relaxed text-zinc-400">
        Most prediction markets resolve because somebody with a key says so, or
        because one oracle says so. Spike has neither. It resolves because the
        contract itself goes and looks — twice, from two unrelated places — and
        only writes an outcome when both agree.
      </p>

      <Section n="01" title="Two sources, fetched by every validator">
        <p>
          When anyone calls <Code>resolve_market</Code>, the contract runs a single
          non-deterministic block. Inside it, it fetches two independent public
          feeds, rebuilds the target window from each one separately, and derives a
          verdict from each feed&rsquo;s own open and close.
        </p>
        <p>
          This is not the leader fetching and everyone trusting it. Every validator
          makes both requests itself. The equivalence principle then requires them to
          agree on the resulting payload, byte for byte.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <SourcePair
            title="Crypto"
            assets={ASSETS.CRYPTO}
            a="Gate.io"
            b="Binance"
            note="Both give true hourly OHLC on the exact window instants. A GMT+1 day is rebuilt from 24 consecutive 1h bars — never a daily bar, which is UTC-aligned and an hour off."
          />
          <SourcePair
            title="Commodities"
            assets={ASSETS.COMMODITIES.map((a) => ASSET_LABELS[a])}
            a="Yahoo Finance"
            b="Nasdaq"
            note="The same ETF proxy from two independent vendors, over the US session — not an hour. GLD, SLV, USO and CPER stand in for gold, silver, WTI and copper."
          />
        </div>

        <p className="mt-4 rounded-md border border-ink-800 bg-ink-950 px-4 py-3 text-xs">
          <strong className="text-zinc-300">CoinGecko is not used for settlement.</strong>{" "}
          It rate-limits hard from shared IPs and reports sampled spot rather than true
          open and close, so it decides nothing here. If a price from it is ever shown in
          this app it is labelled display-only.
        </p>
      </Section>

      <Section n="02" title="One source can never decide anything">
        <p>
          A verdict is stored only if the two sources independently produced the{" "}
          <em>same</em> real verdict. Anything else — they disagree, one of them ties
          for first, one of them has no data — stores{" "}
          <Code>INCONCLUSIVE</Code> and every stake becomes refundable at exactly what
          was put in.
        </p>
        <p>
          If a feed is unreachable, rate-limited, malformed, or simply missing the
          window, resolution reverts as retryable and the market is left completely
          untouched. The contract never settles from whichever source happened to
          answer, and it never invents a price.
        </p>
        <p>
          <strong className="text-zinc-200">Five days</strong> after a window closes the
          contract stops touching the web altogether, marks the market{" "}
          <Code>INCONCLUSIVE</Code> and makes every stake refundable — so a feed that
          never comes back cannot strand anyone&rsquo;s GEN.
        </p>
      </Section>

      <Section n="03" title="What you are predicting">
        <p>
          <strong className="text-zinc-200">Direction</strong> — does one
          asset&rsquo;s completed candle close UP or DOWN? A flat close (close equals
          open) counts as DOWN.
        </p>
        <p>
          <strong className="text-zinc-200">Dominance</strong> — which of a
          category&rsquo;s four assets posts the strongest percentage return over the
          window? Returns are compared as integers by cross-multiplication; there are
          no floats anywhere in settlement.
        </p>
        <p>
          Crypto dominance uses an exact GMT+1 hour. Commodity dominance uses the
          daily session, because no second keyless public feed serves intraday
          commodity data and Spike will not settle from one source to paper over that.
        </p>
      </Section>

      <Section n="04" title="Time is fixed GMT+1">
        <p>
          Every window is defined on a fixed <Code>UTC+01:00</Code> offset. Not your
          browser&rsquo;s timezone, and not daylight saving. A GMT+1 day is rebuilt
          from 24 consecutive hourly bars — a UTC daily bar is one hour off and is
          never used.
        </p>
      </Section>

      <Section n="05" title="Staking and payouts">
        <p>
          Stakes are 1–5 GEN. You can top up, but you cannot switch sides, and your
          total on a market still caps at 5 GEN.
        </p>
        <p>
          GEN attached to a call is credited to the contract even when the call
          fails, so <Code>take_position</Code> never reverts once value is attached.
          It either records your stake and answers <Code>STAKED:</Code>, or it sends
          your GEN straight back and answers <Code>REFUNDED:</Code> with the reason.
        </p>
        <p>
          Winners split the whole pool pro-rata, floor-divided so the contract can
          never over-pay. On an inconclusive market everyone withdraws their exact
          stake — including after the five-day cutoff.
        </p>
        <p>
          <strong className="text-zinc-200">GEN leaves as a second transaction.</strong>{" "}
          Payouts are external messages that execute on finality, so your balance moves a
          little after the claim confirms — measured at about 30 seconds on Studionet.
          Spike watches your balance after a claim and tells you whether the money
          actually arrived, rather than assuming it did.
        </p>
      </Section>

      <Section n="06" title="Nobody is in charge">
        <p>
          There is no owner, no pause switch, no admin resolve, no upgrade hook and
          no privileged address anywhere in the contract. The asset catalog is frozen
          at compile time — there is no function that could add to it. Anyone can
          create a market, anyone can stake, anyone can trigger resolution.
        </p>
        <p>
          Five days after a window closes, resolution stops touching the network
          entirely and refunds everyone, so funds cannot be stranded by a feed that
          never comes back.
        </p>
      </Section>

      <div className="card mt-8 p-5">
        <p className="label">A note on prices shown in this app</p>
        <p className="mt-2 text-sm text-zinc-400">
          Anything this interface displays is for reading only. The UI never computes
          a settlement outcome — every number that decides a market comes from
          contract views, and the outcome itself is decided inside the contract.
        </p>
      </div>
    </div>
  );
}

function Section({
  n,
  title,
  children,
}: {
  n: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-10 border-t border-ink-800 pt-6">
      <div className="flex items-baseline gap-3">
        <span className="mono text-xs font-bold text-spike">{n}</span>
        <h2 className="text-lg font-bold text-zinc-100">{title}</h2>
      </div>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-zinc-400">
        {children}
      </div>
    </section>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return (
    <code className="mono rounded bg-ink-800 px-1.5 py-0.5 text-[12px] text-spike">
      {children}
    </code>
  );
}

function SourcePair({
  title,
  assets,
  a,
  b,
  note,
}: {
  title: string;
  assets: string[];
  a: string;
  b: string;
  note: string;
}) {
  return (
    <div className="rounded-md border border-ink-800 p-4">
      <p className="text-sm font-bold text-zinc-200">{title}</p>
      <p className="mono mt-1 text-[11px] text-zinc-500">{assets.join(" · ")}</p>
      <p className="mt-3 text-xs">
        <span className="text-spike">{a}</span>
        <span className="text-zinc-600"> + </span>
        <span className="text-spike">{b}</span>
      </p>
      <p className="mt-1.5 text-[11px] text-zinc-500">{note}</p>
    </div>
  );
}
