# Spike

A permissionless daily prediction market that resolves itself.

No owner. No pause switch. No admin resolve. No upgrade hook. No privileged
address. When a market settles, it settles because the contract went and looked
— twice, at two unrelated sources — and both agreed.

**Live on GenLayer Studionet:** [`0xE1582599A503a2E97B6640545B1DCB0c85e49841`](https://explorer-studio.genlayer.com/address/0xE1582599A503a2E97B6640545B1DCB0c85e49841)

---

## Why this needs GenLayer

An ordinary chain cannot make an HTTP request, so prediction markets on ordinary
chains resolve through an admin key or a single oracle. Either way you are
trusting somebody.

GenLayer validators each fetch live HTTP inside GenVM and still reach consensus
through the Equivalence Principle. Spike is built entirely on that one
capability: every validator fetches **both** feeds itself, derives a verdict from
each, and the network agrees on the derived verdict rather than on any one
node's view of the internet.

Remove that and Spike is not possible.

---

## Catalog

Frozen at compile time. There is no function that can add, remove or rename an
asset.

| Category | Assets | Source A | Source B |
|----------|--------|----------|----------|
| `CRYPTO` | ADA · ZEC · ZAMA · ARB | Gate.io | Binance |
| `COMMODITIES` | GOLD · SILVER · WTI · COPPER | Yahoo Finance | Nasdaq |

Commodities settle on liquid **ETF proxies** — GLD, SLV, USO, CPER — and are
labelled that way everywhere in the UI. No second keyless public domain serves
intraday or futures commodity data; ten candidates were live-probed and every
one failed. The evidence is in [docs/RESOLUTION.md](docs/RESOLUTION.md).

```bash
python scripts/print_catalog.py
```

---

## Market kinds

**`KIND_DIRECTION`** — does one asset's completed candle close `UP` or `DOWN`?
A flat close (`close == open`) is **`DOWN`**.

**`KIND_DOMINANCE`** — which of a category's four assets posts the strongest
percentage return over the window?

| Category | Kind | Window | `target_hour` |
|----------|------|--------|---------------|
| CRYPTO | direction | whole GMT+1 day | `-1` |
| CRYPTO | dominance | exact GMT+1 hour | `0..23` |
| COMMODITIES | direction | US session on that date | `-1` |
| COMMODITIES | dominance | US session on that date | `-1` |

Time is a **fixed GMT+1 offset**. Not the browser's timezone, not DST. A GMT+1
day is rebuilt from 24 consecutive hourly bars — a UTC daily bar is one hour off
and is never used.

Stakes are **1–5 GEN**. You can top up; you cannot switch sides; your total on a
market still caps at 5 GEN.

---

## How resolution works

Anyone can call `resolve_market(market_id)`. There are no prices, URLs or slugs
in calldata — the contract already knows the catalog.

1. It fetches **two independent public feeds** inside one
   `gl.eq_principle.strict_eq` block.
2. It reconstructs the target window from each feed **separately**.
3. It derives a verdict from each feed's own open and close.
4. A result is stored **only if both feeds independently produced the same
   verdict**.
5. Any disagreement stores `INCONCLUSIVE` and every stake becomes refundable.
6. **A single source can never produce `UP`, `DOWN`, or a winner.**
7. If a feed is unreachable, rate-limited, malformed or missing the window,
   resolution reverts as retryable and the market is left untouched. The
   contract never invents a price.
8. Five days after the window ends, `resolve_market` stops touching the network
   entirely and refunds everyone.

Settlement is integer-only — prices scaled by `10^8`, returns compared by
cross-multiplication. No floats, and no LLM decides open, close, direction or
winner.

---

## Repo layout

```
contracts/Spike.py        the Intelligent Contract
docs/SPEC.md              product + contract surface
docs/RESOLUTION.md        feed design, with the live probe evidence
docs/ARCHITECTURE.md      decisions, and where docs and SDK disagree
frontend/                 Vite + React + TS + Tailwind
scripts/deploy.py         deploy to Studionet via the genlayer CLI
scripts/probe_feeds.py    hit every live feed and print parsed open/close
scripts/record_fixtures.py  capture real responses into tests/fixtures/
scripts/print_catalog.py  print the frozen catalog
tests/direct/             in-process contract tests
tests/consensus/          equivalence / payload tests
tests/fixtures/           recorded real feed responses
```

---

## Testing

```bash
pip install -r requirements-dev.txt
pytest tests/ -q                       # 172 tests, no network
genvm-lint check contracts/Spike.py    # must pass
```

Unit tests never touch the live web. They replay real responses recorded into
`tests/fixtures/` by `scripts/record_fixtures.py`, so the parsers are exercised
against bytes the feeds actually produced. Live probing lives in
`scripts/probe_feeds.py`:

```bash
python scripts/probe_feeds.py --day 2026-09-22 --hour 14
```

Frontend:

```bash
cd frontend
npm install
npm test          # 16 tests, incl. the full write/fee flow
npm run build
npm run dev
```

---

## Deploying to Studionet

Studionet is chain **61999**, RPC `https://studio.genlayer.com/api`, native token
GEN, faucet inside [studio.genlayer.com](https://studio.genlayer.com).

```bash
npm install -g genlayer
genlayer account unlock       # once; caches the key in your OS keychain
genlayer account show         # expect status: 'unlocked' and a GEN balance
python scripts/deploy.py      # deploys and wires the address into the frontend
```

`scripts/deploy.py` never reads, passes or stores a private key — it shells out
to the CLI, which does the signing.

Verify:

```bash
genlayer call <address> get_supported_universe --rpc https://studio.genlayer.com/api
```

Then point the frontend at it — `scripts/deploy.py` does this for you, or set
`CONTRACT_ADDRESS` in [`frontend/src/lib/env.ts`](frontend/src/lib/env.ts) (or
`VITE_SPIKE_ADDRESS`). No environment variables are required to build.

---

## A note on fees

Every contract write in the frontend goes through one helper,
`writeWithEstimatedFees` in [`frontend/src/lib/write.ts`](frontend/src/lib/write.ts).
Nothing else may call `writeContract`. When the installed SDK exposes the
consensus-v0.6 fee flow, that helper calls `estimateTransactionFeesForWrite` for
the exact call it is about to make and passes the returned fees into
`writeContract`; if estimation fails it raises rather than submitting an unpriced
transaction.

Studionet currently rejects genlayer-js 2.x outright, so this app is pinned to
genlayer-js **1.1.8**, which Studionet accepts and which has no fee API at all.
The helper is capability-driven rather than version-hardcoded, so pointing Spike
at a consensus-v0.6 network with genlayer-js 2.x makes every write start pricing
itself with no code changes. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

---

## Current state

- Contract deployed and answering on Studionet at
  `0xE1582599A503a2E97B6640545B1DCB0c85e49841` — **unchanged**; the fix pass of
  2026-09-23 needed no contract edit and no redeploy
- Frontend live at [spike-sepia.vercel.app](https://spike-sepia.vercel.app/)
- Market #1 created on-chain (ADA, direction, 2026-09-25)
- **Outbound GEN works on Studionet.** An Intelligent Contract really can pay a
  wallet via `emit_transfer`, measured with a disposable probe: 1 GEN moved
  contract → EOA about 30 seconds after the call was accepted. An earlier
  revision of `docs/ARCHITECTURE.md` claimed this did not work; that was wrong
  and is corrected. Refunds and claims are sound.
- Payable calls (staking) require a browser wallet — the `genlayer` CLI
  hardcodes `value: 0n` and cannot attach GEN to a call. Use the UI.

See [docs/FIX-AUDIT.md](docs/FIX-AUDIT.md) for the live-site audit behind that
correction.
