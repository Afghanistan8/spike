# Spike — Resolution & Feed Design

This document is written **before** the production parsers, and records what was
actually observed on the wire. Every URL template below was live-probed on
**2026-09-23** with `scripts/probe_feeds.py` and raw `curl`. Nothing here is from
memory or from a blog post.

**Catalog status: FROZEN 2026-09-23.** Both open decisions were signed off — see
DECISION 1 (§3) and DECISION 2 (§4). The contract compiles this catalog into
`__init__` and exposes no function that can change it.

---

## 1. Time model

Spike settles on a **fixed GMT+1 offset**. Not `Europe/Paris`, not DST, not the
browser's local time. `UTC+01:00`, always.

A market stores a `target_day` (`YYYY-MM-DD`) and, for dominance, a
`target_hour` (`0..23`). Both are GMT+1 wall-clock values. The contract converts
them to two UTC instants:

```
KIND_DIRECTION  (whole GMT+1 day)
  open_instant  = target_day 00:00 GMT+1  = (target_day 00:00 UTC) − 3600
  close_instant = open_instant + 86400

KIND_DOMINANCE  (exact GMT+1 hour)
  open_instant  = target_day HH:00 GMT+1  = (target_day 00:00 UTC) + HH*3600 − 3600
  close_instant = open_instant + 3600
```

Worked example, verified by the probe:

```
day 2026-09-22 GMT+1  -> UTC [1790031600, 1790118000)
                         2026-09-21 23:00Z .. 2026-09-22 23:00Z
hour 2026-09-22 14:00 -> UTC [1790082000, 1790085600)
                         13:00Z .. 14:00Z
```

### The one-hour trap

Binance daily (`1d`) klines are **UTC-aligned**. A UTC day is one hour off a
GMT+1 day. Spike therefore **never** reads a `1d` kline. Every window — daily or
hourly — is rebuilt from `1h` klines, and a full GMT+1 day is exactly **24
consecutive 1h bars** starting at `open_instant`. The same rule applies to every
other exchange-style source.

### Same two instants

Both sources must measure **the same two instants**: `open_instant` and
`close_instant`. A source that reports "the last sample before the window ended"
instead of the value at `close_instant` produces false disagreements. Each parser
below asserts that the bar it uses starts exactly on the instant, and refuses the
window otherwise.

---

## 2. Canonical scaling and integer math

Settlement touches **no floats**.

```
scaled = int(round(price * 10**8))     # 8 dp, banker's rounding at the boundary
```

Percentage returns are never computed as floats. Dominance ranks assets by
cross-multiplication on integers:

```
return_a > return_b
  <=>  (close_a − open_a) * open_b  >  (close_b − open_b) * open_a
```

(valid because all opens are strictly positive; the contract rejects a window
with a non-positive open).

Default equivalence is **exact integer comparison** of the scaled prices. No
tolerance band is applied. The prices are not part of the consensus-critical
decision set in the sense that a mismatch is tolerated — they are persisted as
evidence and compared exactly. If a future source proves noisy, a documented
relative tolerance would be added here first, never silently in code.

---

## 3. CRYPTO

### Probe results — 2026-09-22, GMT+1 day and hour 14:00

Daily GMT+1 candle:

| Asset | Binance open→close | Gate.io open→close | Binance | Gate.io |
|-------|-------------------|--------------------|---------|---------|
| ADA   | 24630000 → 25310000 (+2.761%) | 24639000 → 25312000 (+2.731%) | UP | UP |
| ZEC   | 147160000000 → 155320000000 (+5.545%) | 147175000000 → 155308000000 (+5.526%) | UP | UP |
| ZAMA  | 9249000 → 9410000 (+1.741%) | 9259000 → 9410000 (+1.631%) | UP | UP |
| ARB   | 22590000 → 22550000 (−0.177%) | 22583000 → 22550000 (−0.146%) | DOWN | DOWN |

Exact GMT+1 hour 14:00:

| Asset | Binance | Gate.io | CoinGecko |
|-------|---------|---------|-----------|
| ADA   | +1.441% UP | +1.493% UP | +1.469% UP |
| ZEC   | −0.598% DOWN | −0.572% DOWN | −0.493% DOWN |
| ZAMA  | −2.159% DOWN | −2.252% DOWN | **HTTP 429** |
| ARB   | −2.076% DOWN | −1.982% DOWN | **HTTP 429** |

All three sources agree on direction wherever they respond. Binance and Gate.io
track each other to within ~0.11 percentage points on the daily window.

### Symbol verification

All four Binance spot symbols returned HTTP 200 on both `data-api.binance.vision`
and `api.binance.com`:

```
ADAUSDT 200   ZECUSDT 200   ZAMAUSDT 200   ARBUSDT 200
```

**ZAMA trades on Binance as `ZAMAUSDT`** — confirmed live, not assumed.

CoinGecko ids confirmed via `/api/v3/search`:

```
cardano | zcash | zama | arbitrum        ("zama" returns id=zama, symbol=ZAMA, name=Zama)
```

Gate.io pairs confirmed, all four return candles including `ZEC_USDT` and
`ZAMA_USDT`.

### Rejected crypto sources

| Source | Result |
|--------|--------|
| OKX `www.okx.com/api/v5` | empty body for every symbol — unreachable from this egress |
| KuCoin `api.kucoin.com` | empty body for every symbol |
| Bybit `api.bybit.com` | has ADA/ZAMA/ARB but **`ZECUSDT` returns an empty list** — cannot cover the catalog |

### The CoinGecko problem

CoinGecko is in the original brief as Source A. The probe shows why it is a poor
fit for a validator-side fetch:

1. **It rate-limits hard and fast.** Two `market_chart/range` calls six seconds
   apart already returned `HTTP 429` during the probe run, from a single
   residential IP. Validators on hosted Studio share an egress IP, so they will
   429 harder than this.
2. **It is not OHLC.** `market_chart/range` returns *sampled spot prices*. Its
   "open" is a sample near the hour boundary, not the first trade of the hour.
   Against Binance's true kline open this introduces a systematic ~0.1 pp
   difference — tolerable for direction, but enough to flip a **dominance**
   ranking when two assets finish close together.
3. **It silently changes granularity** with range width, and returns an empty
   `prices` array for narrow ranges (a 1-hour range returned `n=0`).
4. A range older than ~365 days returns `HTTP 401` on the public tier.

Gate.io, by contrast, is keyless, returns true OHLC on the exact instants,
answered every probe call without throttling, and is a genuinely different
domain with a different JSON shape (a positional array with a different field
order), forcing a genuinely different parser.

> **DECISION 1 — crypto Source A. LOCKED 2026-09-23.**
> **Gate.io** is Source A, **Binance** is Source B. CoinGecko is dropped from
> settlement entirely. It may still drive display-only prices in the UI,
> clearly labelled "not used for settlement".
>
> This is a deliberate deviation from the original brief, which named
> CoinGecko + Binance. The probe evidence above is the reason: CoinGecko
> returned `HTTP 429` twice during a single probe run from one residential IP,
> and its sampled-spot open/close is not comparable instant-for-instant with a
> true kline open/close.

### URL templates

Source B — Binance (LOCKED). Public data host preferred; it does not throttle
shared IPs as aggressively as the trading API.

```
https://data-api.binance.vision/api/v3/klines
    ?symbol={SYMBOL}&interval=1h&startTime={open_ms}&endTime={close_ms−1}&limit=1000
```

Kline row is positional:
`[openTime, open, high, low, close, volume, closeTime, ...]`
→ `open  = row[0][1]` where `row[0][0] == open_instant*1000`
→ `close = row[-1][4]` where the row count equals `(close−open)/3600`

Fallback host (only if the primary is dead): `https://api.binance.com/api/v3/klines`.

Source A — Gate.io (LOCKED).

```
https://api.gateio.ws/api/v4/spot/candlesticks
    ?currency_pair={PAIR}&interval=1h&from={open_s}&to={close_s−1}
```

Candle row is positional with a **different order** from Binance:
`[timestamp_s, quote_volume, close, high, low, open, base_volume, window_closed]`
→ `open  = row[0][5]`
→ `close = row[-1][2]`

No API key, no headers beyond a User-Agent.

### Catalog — LOCKED

| Asset | Gate.io pair (source A) | Binance symbol (source B) | CoinGecko id (display only) |
|-------|-------------------------|---------------------------|-----------------------------|
| ADA   | `ADA_USDT`   | `ADAUSDT`  | `cardano`  |
| ZEC   | `ZEC_USDT`   | `ZECUSDT`  | `zcash`    |
| ZAMA  | `ZAMA_USDT`  | `ZAMAUSDT` | `zama`     |
| ARB   | `ARB_USDT`   | `ARBUSDT`  | `arbitrum` |

The CoinGecko column is **not** compiled into the contract. It exists only so the
frontend can show an indicative price, and it is labelled as such in the UI.

---

## 4. COMMODITIES

This is the hard half, and the probe produced a result that changes the product.

### What works

**Yahoo Finance** (`query1.finance.yahoo.com`) serves real COMEX/NYMEX futures,
keyless, with a browser `User-Agent`, at both `1h` and `1d` granularity:

| Asset | Symbol | GMT+1 day 2026-09-22 | GMT+1 hour 14:00 |
|-------|--------|----------------------|------------------|
| GOLD   | `GC=F` | 439870019531 → 440060009766 (+0.043%) UP | −0.014% DOWN |
| SILVER | `SI=F` | 6688500214 → 6782499695 (+1.405%) UP | +0.053% UP |
| WTI    | `CL=F` | 9216999817 → 8963999939 (−2.745%) DOWN | +0.133% UP |
| COPPER | `HG=F` | 679799986 → 690250015 (+1.537%) UP | +0.183% UP |

**Nasdaq** (`api.nasdaq.com`) serves ETF daily OHLC, keyless with a browser
`User-Agent`, but **daily only** — there is no intraday endpoint:

```
https://api.nasdaq.com/api/quote/GLD/historical?assetclass=etf&fromdate=2026-09-18&todate=2026-09-23&limit=10
  -> 09/22/2026 open 397.07 close 400.07   (UP)
```

Note the request needs a **multi-day range**; a single-day `fromdate==todate`
returns `data: null`. `assetclass` must be `etf` — `commodities`, `commodity` and
`futures` are all rejected with `code 1007`.

### What does not work

Ten candidate second sources were live-probed. All failed:

| Candidate | Observed |
|-----------|----------|
| Stooq `stooq.com` | JS **proof-of-work** interstitial on every CSV URL. Requires running SHA-256 in a browser. Unusable from GenVM. |
| Pyth Hermes `hermes.pyth.network` | Feed catalog is public and has stable non-rolling ids for all four (`Metal.XAU/USD`, `Metal.XAG/USD`, `Commodities.Index.WTI1M/USD`, `Commodities.Index.CU/USD`) — but **historical** `/v2/updates/price/{ts}` returns `HTTP 401 unauthorized`. Latest-only is useless for settling a past window. |
| Pyth Benchmarks TradingView shim | `HTTP 404` — endpoint removed. |
| Dukascopy `freeserv.dukascopy.com` | `HTTP 403` |
| Investing.com `api.investing.com` | `HTTP 403` |
| CNBC `quote.cnbc.com` | Works, returns real gold futures — but it is a **snapshot quote only** (current day open/high/low/last). No historical series. `ts-api.cnbc.com` chart path returns `HTTP 400`. |
| TradingEconomics `guest:guest` | "the guest account has been discontinued" |
| Alpha Vantage `apikey=demo` | demo key refused for this symbol |
| Twelve Data `apikey=demo` | `HTTP 401`, demo key refused |
| FMP / EODHD `demo` | "Invalid API KEY" / `Forbidden` |
| Bitget / MEXC commodity perps | `XAUUSDT` / `XAUTUSDT` do not exist |

### The conclusion

> **There is no second keyless public domain serving *intraday* commodity data.**
> Yahoo Finance is the only one. Everything else is daily-only, snapshot-only,
> bot-walled, or behind a key.

This has a hard consequence: **`KIND_DOMINANCE` on COMMODITIES cannot be settled
by two independent sources.** Offering it anyway would mean settling a commodity
hour market from a single source, which is precisely the thing Spike exists to
refuse. Rule 6 — "a single source can never produce UP, DOWN, or a winner" — is
not negotiable.

### The instrument-mismatch trap

A tempting pairing is Yahoo **futures** + Nasdaq **ETF**. The probe shows why
that is wrong:

```
2026-09-22   GC=F (COMEX gold futures, 24h GMT+1 day)   +0.043%   UP
2026-09-22   GLD  (ETF, US equity session only)         +0.76%    UP
```

Same direction here by luck. These are **different instruments measured over
different sessions** — a 24-hour GMT+1 day versus a 6.5-hour US equity session.
On any quiet day they will disagree on direction and dump the market into
`INCONCLUSIVE`. Pairing them would make refunds the normal outcome rather than
the exception.

The correct pairing is **the same instrument from two independent vendors**:
Yahoo and Nasdaq both quoting the *same ETF*. Then a disagreement genuinely means
"the sources disagree", which is what `INCONCLUSIVE` is supposed to mean.

> **DECISION 2 — commodity instrument + window. LOCKED 2026-09-23.**
> - The commodity catalog settles on **ETF proxies**, labelled honestly
>   everywhere in the UI: `GOLD (GLD proxy)`, `SILVER (SLV proxy)`,
>   `WTI (USO proxy)`, `COPPER (CPER proxy)`.
> - Source A = Yahoo Finance `1d`, Source B = Nasdaq ETF `historical`. Same
>   instrument, two independent vendors.
> - **Both kinds stay available for COMMODITIES**, but the dominance window is
>   the **daily session**, not an hour: `KIND_DOMINANCE` on COMMODITIES ranks
>   the four proxies' returns over the same session `KIND_DIRECTION` uses.
> - `KIND_DOMINANCE` on CRYPTO keeps the **exact GMT+1 hour**, where two
>   independent hourly sources genuinely exist.
>
> The alternative — keep real futures (`GC=F`…) and settle commodities from
> Yahoo alone — is **rejected**: it breaks the core guarantee that one source
> can never settle a market.

### Window selector, by category and kind

`target_hour` is only meaningful where two independent **intraday** sources
exist. That is CRYPTO only.

| Category | Kind | Window | `target_hour` |
|----------|------|--------|---------------|
| CRYPTO | `KIND_DIRECTION` | whole GMT+1 day, 24×1h bars | `-1` |
| CRYPTO | `KIND_DOMINANCE` | exact GMT+1 hour | `0..23` |
| COMMODITIES | `KIND_DIRECTION` | US equity session on `target_day` | `-1` |
| COMMODITIES | `KIND_DOMINANCE` | US equity session on `target_day` | `-1` |

`create_market` enforces this: an hour supplied for any row whose `target_hour`
is `-1` is rejected as `EXPECTED:`, and a dominance market on CRYPTO without an
hour in `0..23` is likewise rejected.

### Session semantics

A commodity "daily candle" is the **US equity session** on that calendar date,
not a 00:00–24:00 GMT+1 day. This must be stated in the UI on the market card and
on `/how-it-works`. The `target_day` is still a GMT+1 calendar date; it selects
*which session*, and the two sources agree on which rows belong to it because
both are keyed by that calendar date.

Weekends and holidays: commodity direction markets targeting a Saturday or Sunday
are **rejected at `create_market`**. For a weekday holiday the session simply does
not exist — both sources omit the row, resolution reverts as retryable while
inside the 5-day window, and after `terminal_refund_at` everyone is refunded. The
contract never invents a candle.

### URL templates — LOCKED

Source A — Yahoo Finance. Requires a browser `User-Agent`.

```
https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}
    ?interval=1d&period1={open_s − 86400}&period2={close_s + 86400}
```

→ `chart.result[0].timestamp[]` plus `chart.result[0].indicators.quote[0].{open,close}`.
Daily bars are stamped at **session open in the exchange timezone**, so the
parser matches by *calendar date in the exchange timezone* (`meta.exchangeTimezoneName`),
not by instant equality. A `null` open or close means no session — refuse the
window.

Source B — Nasdaq. Requires a browser `User-Agent` and a multi-day range.

```
https://api.nasdaq.com/api/quote/{SYMBOL}/historical
    ?assetclass=etf&fromdate={day − 5d}&todate={day + 1d}&limit=10
```

→ `data.tradesTable.rows[]`, each `{date: "MM/DD/YYYY", open: "$397.07", close: "400.07", ...}`.
Strip `$` and `,` before scaling. Match `date` to the target calendar date. A
missing row means no session — refuse the window.

### Catalog — LOCKED

| Asset | Label shown in UI | Yahoo symbol | Nasdaq symbol |
|-------|-------------------|--------------|---------------|
| GOLD   | GOLD (GLD proxy)   | `GLD`  | `GLD`  |
| SILVER | SILVER (SLV proxy) | `SLV`  | `SLV`  |
| WTI    | WTI (USO proxy)    | `USO`  | `USO`  |
| COPPER | COPPER (CPER proxy)| `CPER` | `CPER` |

---

## 5. Verdicts and the equivalence payload

Each source independently produces a verdict string. Permitted values, exactly:

```
UP | DOWN | TIE | MISSING
WIN:ADA | WIN:ZEC | WIN:ZAMA | WIN:ARB
WIN:GOLD | WIN:SILVER | WIN:WTI | WIN:COPPER
```

- `KIND_DIRECTION`: `UP` if `close > open`, else `DOWN`. A flat candle
  (`close == open`) is **DOWN**.
- `KIND_DOMINANCE`: `WIN:<asset>` for the strictly greatest integer return among
  the four assets of the category, over that category's window (exact GMT+1 hour
  for CRYPTO, the daily session for COMMODITIES). If two or more tie for first
  **within that source's own series**, that source returns `TIE`.
- `MISSING` is never a settling verdict; it exists only so the payload can
  describe a source that had no data, and it always forces `INCONCLUSIVE`.

The payload returned from inside `gl.eq_principle.strict_eq` is a small canonical
dict. Raw HTML and raw JSON bodies are **never** persisted.

Fields all validators must agree on, byte for byte:

```
kind, category, asset_or_blank, target_day, target_hour_or_minus_one,
source_a_id, source_b_id,
source_a_verdict, source_b_verdict,
final_verdict,
source_a_prices[], source_b_prices[]    (scaled integers, fixed asset order)
```

Final verdict rule, applied in **deterministic** Python after `strict_eq`
returns:

```
final = source_a_verdict
        if  source_a_verdict == source_b_verdict
        and source_a_verdict in {UP, DOWN, WIN:*}
        else INCONCLUSIVE
```

`TIE` and `MISSING` can never become final. A single source can never produce a
settling verdict, because the comparison requires both.

After `strict_eq` returns, deterministic code re-validates the payload shape. If
the agreed bytes are self-contradictory — a `final_verdict` that does not follow
from the two source verdicts, a price array of the wrong length, a verdict string
outside the permitted set — the contract raises `INVARIANT:` and reverts. This
must never fire in honest execution.

---

## 6. Error classes

The prefix is part of the returned message so the frontend can branch on it.

| Prefix | Meaning | Market state | Retryable |
|--------|---------|--------------|-----------|
| `EXPECTED:` | bad input, wrong phase, duplicate, side switch, too early | unchanged | n/a |
| `TRANSIENT:` | timeout, `408`, `425`, `429`, `5xx`, empty body | unchanged | yes |
| `EXTERNAL:` | other `4xx`, malformed body, incomplete window, no session, oversized, non-UTF-8 | unchanged | yes |
| `INVARIANT:` | agreed payload self-contradictory | reverts | never in honest execution |

A `429` from one source **never** settles the market from the other. Any source
failure aborts the whole resolution and leaves the market `READY_TO_SETTLE` for
the next caller.

Five days after `close_instant` (`terminal_refund_at`), `resolve_market` stops
touching the network entirely, stores empty verdicts, sets `INCONCLUSIVE` and
marks every stake refundable.
