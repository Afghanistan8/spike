# Spike — Specification

Spike is a permissionless daily prediction market that resolves itself.

No owner. No pause switch. No admin resolve. No upgrade hook. No privileged
address. No LLM price judge. The contract settles by fetching two independent
public feeds **from inside the contract**, during consensus, and only writes a
result when both feeds independently agree.

Target network: **GenLayer Studionet**, chain id `61999`, RPC
`https://studio.genlayer.com/api`, native token `GEN`.

---

## 1. Why this has to be GenLayer

An ordinary chain cannot make an HTTP request. Prediction markets on ordinary
chains therefore resolve through an admin key or a single oracle — you are
trusting somebody.

GenLayer validators can each independently fetch live HTTP inside GenVM and still
reach consensus through the Equivalence Principle. Spike is built on exactly that
one capability: every validator fetches **both** feeds itself, derives a verdict
from each, and consensus is reached on the derived verdict rather than on any one
node's view of the internet.

That is the whole product. Remove it and Spike is not possible.

---

## 2. Catalog

Two locked categories, four assets each. Frozen in `__init__`. Nobody can add,
remove or rename an asset after deployment — there is no function that can.

| Category | Assets |
|----------|--------|
| `CRYPTO` | `ADA`, `ZEC`, `ZAMA`, `ARB` |
| `COMMODITIES` | `GOLD`, `SILVER`, `WTI`, `COPPER` |

Feed ids, symbols and URL templates are in [RESOLUTION.md](RESOLUTION.md).

---

## 3. Market kinds

### `KIND_DIRECTION`

One asset from one category. The user predicts whether that asset's **completed
GMT+1 daily candle** closes `UP` or `DOWN`.

- Flat candle (`close == open`) is **`DOWN`**.
- `target_hour` is forced to `-1`.
- Stake 1–5 GEN.

### `KIND_DOMINANCE`

One category, no single-asset field. The user picks which of that category's four
assets delivers the **strongest percentage return over the window**.

- CRYPTO: the window is **one exact GMT+1 hour**, `target_hour` in `0..23`.
- COMMODITIES: the window is the **daily session** on `target_day`,
  `target_hour` is `-1`. There is no second keyless intraday commodity source,
  so an hourly commodity market could only be settled from one feed — which
  Spike refuses to do. See [RESOLUTION.md §4](RESOLUTION.md).
- Return per source = `(close − open) / open`, computed only from that source's
  own open and close for that window.
- Compared by integer cross-multiplication. No floats.
- If two or more assets tie for first **within a source's own series**, that
  source's verdict is `TIE`, which cannot produce a winner.
- Stake 1–5 GEN.

### Window selector

| Category | Kind | Window | `target_hour` |
|----------|------|--------|---------------|
| CRYPTO | `KIND_DIRECTION` | whole GMT+1 day | `-1` |
| CRYPTO | `KIND_DOMINANCE` | exact GMT+1 hour | `0..23` |
| COMMODITIES | `KIND_DIRECTION` | US equity session on `target_day` | `-1` |
| COMMODITIES | `KIND_DOMINANCE` | US equity session on `target_day` | `-1` |

---

## 4. Resolution

Anyone may call `resolve_market(market_id)`. There are no price arguments, no
URLs and no slugs in calldata — the contract already knows the catalog.

1. The contract fetches **two independent public feeds** inside a single
   `gl.eq_principle.strict_eq` block.
2. It reconstructs the target window from each feed **separately**.
3. It derives a direction or a dominance winner from each feed's own open and
   close.
4. A directional or winning result is stored **only if both feeds independently
   produce the same verdict**.
5. Any disagreement stores `INCONCLUSIVE` and every stake becomes refundable.
6. **A single source can never produce `UP`, `DOWN`, or a winner.**
7. If a feed is unreachable, malformed, rate-limited, or missing the window,
   resolution reverts as retryable. The market stays open for another
   `resolve_market` call. The contract never invents a price.
8. Five full days after the window ends, `resolve_market` stops touching the web
   and refunds everyone.

Rules for the non-deterministic block:

- All web I/O lives inside the function passed to `strict_eq`.
- Non-det code never reads or writes contract storage, never calls another
  contract, never emits a message.
- Leader and every validator fetch both feeds themselves.
- Only a small canonical payload is persisted: source labels, scaled integer
  prices, per-source verdict, final verdict. Never raw HTML or raw JSON.
- After `strict_eq` returns, deterministic Python re-validates the payload shape
  and raises `INVARIANT:` if the agreed bytes are self-contradictory.
- No LLM decides open, close, direction or winner. Structured API bytes are
  parsed with Python.

---

## 5. Contract surface

File: `contracts/Spike.py`. Exactly one `class Spike(gl.Contract)`.

### Constants

| Name | Value |
|------|-------|
| `MIN_STAKE_WEI` | `1 GEN` = `10**18` |
| `MAX_STAKE_WEI` | `5 GEN` = `5 * 10**18` |
| `MAX_FORWARD_DAYS` | `366` |
| `TERMINAL_REFUND_DELAY_SECS` | `5 days` = `432000` |
| `PRICE_SCALE` | `10**8` |

### Derived phases

Phases are **computed**, never stored:

```
OPEN -> WINDOW_LIVE -> READY_TO_SETTLE
     -> SETTLED_UP | SETTLED_DOWN | SETTLED_WINNER | INCONCLUSIVE
```

Time comes from `gl.message_raw['datetime']` (ISO 8601). Calldata timestamps are
never trusted.

### Writes

#### `create_market(kind, category, asset, target_day, target_hour) -> str`

Anyone. Rejects, as `EXPECTED:`:

- unknown category or asset (catalog is closed)
- an asset supplied for `KIND_DOMINANCE`, or missing for `KIND_DIRECTION`
- a window already started or in the past
- more than `MAX_FORWARD_DAYS` ahead
- a duplicate of the unique key `(kind, category, asset, target_day, target_hour)`
- a commodity market targeting a Saturday or Sunday (crypto may target any day)
- `target_hour` outside `0..23` for a CRYPTO dominance market
- a meaningful `target_hour` anywhere the window selector says `-1` — that is,
  every direction market, and every COMMODITIES dominance market

Returns the market id.

#### `take_position(market_id, side) -> str` — `@gl.public.write.payable`

Anyone, while the phase is `OPEN`.

- The first stake on a market must be ≥ 1 GEN and ≤ 5 GEN.
- Later top-ups stay on the same side; the running total must stay ≤ 5 GEN.
- No side switching.

> **CRITICAL MONEY RULE.** GEN attached to a call is credited to the contract
> **even if the call reverts**. Therefore once value is attached,
> `take_position` **must not revert**. It validates first, then either records
> the position and returns `STAKED:<total_wei>`, or sends the GEN back and
> returns `REFUNDED:<reason>`. A call carrying zero value may revert normally.

#### `resolve_market(market_id) -> str`

Anyone.

- Before `settles_at` → `EXPECTED:` revert.
- After `terminal_refund_at` → **no web access at all**; stores empty verdicts,
  sets `INCONCLUSIVE`, `refund_all = true`, returns `TERMINAL_REFUND`.
- Otherwise runs the equivalence block, parses, persists evidence + verdict.
- Feed failure → `TRANSIENT:` or `EXTERNAL:`, market unchanged, retryable.
- Disagreement or `TIE` → `INCONCLUSIVE`, refundable.
- Agreement on `UP` / `DOWN` / `WIN:*` → that terminal status. The winning side
  later splits the whole pool pro-rata.

#### `claim(market_id) -> str`

Position owner, once.

- The GEN transfer is emitted **first**, then `claimed` is flipped. If anything
  afterwards raises, the whole call reverts and `claimed` stays false.
- `SETTLED_*` → winners receive `stake * total_pool // winning_pool` (floor
  division). Dust remains in the contract.
- `INCONCLUSIVE` → every staker withdraws their exact stake.

There are no other write methods.

### Views

Pure, paginated at 50:

`get_supported_universe`, `get_stats`, `get_market`, `get_market_phase`,
`get_position`, `get_claimable`, `get_markets`, `get_open_markets`,
`get_markets_by_category`, `get_market_by_unique_key`, `get_user_markets`,
`get_user_positions`, `get_market_positions`, `get_settlement_evidence`,
`get_activity`.

### Error classes

`EXPECTED:` · `TRANSIENT:` · `EXTERNAL:` · `INVARIANT:` — see
[RESOLUTION.md §6](RESOLUTION.md).

### Money out

Payouts and refunds leave the contract as **external messages** to an EOA:

```python
@gl.evm.contract_interface
class _Payee:
    class View:
        pass
    class Write:
        pass

_Payee(Address(recipient)).emit_transfer(value=u256(amount))
```

This is the only correct form. Using `gl.get_contract_at(eoa).emit_transfer()`
against a wallet is accepted by consensus, returns success, and **moves zero
wei** — a silent loss of funds. External messages always execute
`on='finalized'`, so GEN arrives as a **separate follow-up transaction after
finality**. The UI must say so.

---

## 6. Frontend

Vite + React + TypeScript + Tailwind. `genlayer-js` plus an injected EIP-1193
wallet (MetaMask / Rabby). WalletConnect is optional; injected wallets work
without it.

Brand: **Spike**. Sharp, dark, high contrast, one accent. Terse copy.

| Route | Purpose |
|-------|---------|
| `/` | Live board. Crypto / Commodities tabs. Cards for open, live, settling, settled. Dominance cards show the four-asset race; direction cards show UP vs DOWN pools. |
| `/market/:id` | Sides, pool depths, your position, evidence after settlement, resolve button when `READY_TO_SETTLE`, claim button when you have a claimable balance. |
| `/create` | Kind, category, asset or dominance, GMT+1 day, hour for dominance. Previews the unique key. |
| `/portfolio` | Connected wallet's positions and claimable GEN. |
| `/how-it-works` | Two-source resolution, equivalence principle, inconclusive refunds, no admin. |

Rules:

- Reads come only from contract views. **The UI never computes a settlement
  outcome.**
- Any chart or live price is display-only and labelled "not used for settlement".
- Chain id, RPC and contract address live in `frontend/src/lib/env.ts`. No env
  vars are required to build.
- Lists paginate at 50.
- Every write estimates fees the way the installed `genlayer-js` requires, then
  waits for the validator outcome. Success, revert reason, `STAKED:` and
  `REFUNDED:` are all surfaced.
- Wallet connect, network-add for Studionet, and a faucet link.

---

## 7. Definition of done

- Permissionless create, stake 1–5 GEN, resolve, claim
- `CRYPTO` catalog ADA / ZEC / ZAMA / ARB
- `COMMODITIES` catalog GOLD / SILVER / WTI / COPPER
- `KIND_DIRECTION` on a completed GMT+1 daily candle
- `KIND_DOMINANCE` on an exact GMT+1 hour (CRYPTO) / the daily session
  (COMMODITIES)
- Two independent public feeds inside an equivalence-principle block
- Disagreement → `INCONCLUSIVE` + full refund
- One source cannot settle
- No owner / pause / admin resolve / upgrade
- Frontend branded Spike, locked to Studionet
- A README a stranger can follow

### Deliberate deviations from the original brief

Two live-probe findings changed the brief. Both are signed off and frozen, with
the evidence in [RESOLUTION.md](RESOLUTION.md):

1. **Crypto settles on Gate.io + Binance, not CoinGecko + Binance.** CoinGecko
   returned `HTTP 429` twice inside one probe run from a single residential IP,
   is sampled spot rather than OHLC, and returns an empty series for narrow
   ranges. It survives in the UI as a display-only price, labelled "not used for
   settlement".
2. **Commodities settle on ETF proxies over the daily session.** No second
   keyless public domain serves intraday commodity data — ten candidates were
   probed and every one failed. The catalog therefore settles GLD / SLV / USO /
   CPER from Yahoo Finance + Nasdaq, labelled honestly as proxies, and
   `KIND_DOMINANCE` on COMMODITIES ranks returns over the daily session instead
   of an hour. Hourly dominance stays exact on CRYPTO.
