# Spike — Architecture & Decisions

What was built, why it is shaped this way, and every place where the published
documentation and the installed SDK disagree.

Verified against **py-genlayer `1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6`**
(GenVM v0.3.0-rc7), **genlayer-test 0.29.2**, **genlayer CLI 0.39.2** and
**genlayer-js 1.1.8**, on 2026-09-23.

---

## 1. Shape of the system

```
                      ┌──────────────────────────────┐
  browser wallet ───► │  frontend/src/lib/write.ts   │  the ONLY writeContract
                      │  writeWithEstimatedFees      │  call site in the app
                      └──────────────┬───────────────┘
                                     │
                      ┌──────────────▼───────────────┐
                      │   contracts/Spike.py         │
                      │                              │
   create_market ────►│  deterministic: validate,    │
   take_position ────►│  store, pay out              │
   claim         ────►│                              │
                      │  resolve_market:             │
   resolve_market ───►│    gl.eq_principle.strict_eq │
                      │      └─ _collect()           │──► source A  ─┐
                      │                              │──► source B  ─┤ every
                      │  deterministic again:        │               │ validator
                      │    validate payload,         │               │ fetches
                      │    compare verdicts,         │◄──────────────┘ both
                      │    store or revert           │
                      └──────────────────────────────┘
```

The non-deterministic block is a single module-level function, `_collect`. It is
module-level on purpose: the closure passed to `strict_eq` is cloudpickled, and
capturing `self` would drag contract storage into it.

---

## 2. Decisions that shaped the contract

### Failures are returned as data, not raised

`strict_eq`'s validator is literally `spawn_sandbox(fn) == leaders_res`, and
both `Return` and `UserError` are dataclasses, so a raised error is compared by
message. Messages that embed anything node-specific would produce spurious
consensus failures.

So `_collect` never raises. A feed failure comes back as
`{"error": "TRANSIENT", "detail": ...}`, every node produces a comparable value,
and the revert happens in **deterministic** code after consensus. This makes the
revert reason stable and the retry semantics predictable.

### The payload is re-validated after consensus

"The validators agreed" is not the same as "the value is well formed".
`_check_payload` re-derives the final verdict from the two source verdicts and
raises `INVARIANT:` if the agreed bytes are self-contradictory, the price array
is the wrong length, or a verdict falls outside the permitted vocabulary. It
should never fire in honest execution.

### Money out uses the EVM interface, deliberately

```python
@gl.evm.contract_interface
class _Payee:
    class View: pass
    class Write: pass

_Payee(Address(recipient)).emit_transfer(value=u256(amount))
```

Using `gl.get_contract_at(eoa).emit_transfer()` against a wallet is accepted by
consensus, reports success, and **moves zero wei**. That is a silent loss of
funds, so it appears nowhere in this repo. External messages always execute
`on='finalized'`, which is why payouts land as a separate follow-up transaction
and the UI says so.

**This path is verified working on Studionet** (2026-09-23). An earlier revision
of this document claimed the opposite; see §6.

### `take_position` cannot revert once value is attached

GEN attached to a call is credited to the contract even when the call reverts.
So the method validates first and then either records the stake
(`STAKED:<wei>`) or sends the GEN back (`REFUNDED:<reason>`). A zero-value call
has nothing to lose and reverts normally.

### The catalog is module-level, not storage

The brief said "frozen in `__init__`". Module-level constants are strictly
stronger: storage would need a writer somewhere, whereas a module constant has
no setter to attack. `get_supported_universe` reads the same constants, so the
on-chain view and the compiled catalog cannot drift.

### Time comes from the clock, not `message_raw`

Both are documented as the transaction datetime and are the same value on chain.
The contract uses `datetime.now(timezone.utc)` because `gl.message_raw` is
decoded **once at module load** — correct on chain, where each transaction gets
a fresh VM, but stale in the in-process test runner, which reuses the module
across calls. The test harness patches the clock (`vm.warp`) but does **not**
refresh `gl.message_raw['datetime']`, so reading the clock is the only choice
that behaves identically in both environments. The attribute is resolved at call
time so a mid-test warp is seen immediately.

---

## 3. Where the docs and the installed SDK disagree

Each of these was checked against the runner the docs' own `Depends` hash
resolves to.

| # | Docs say | Installed SDK actually has | What Spike does |
|---|----------|---------------------------|-----------------|
| 1 | `response.status_code` (Web Access page) | `Response` is a dataclass with **`status`**, `headers`, `body`. No `status_code`. | Uses `.status`. |
| 2 | `raise gl.UserError(...)` (Web Access page) | `gl.__all__` has no `UserError`; it is `gl.vm.UserError`. | Uses `gl.vm.UserError`. |
| 3 | `json.loads(response)` (Equivalence page) | `body` is `bytes \| None`, not a string. | `response.body.decode("utf-8")`, with the `None`/empty case treated as `TRANSIENT`. |
| 4 | `gl.message` carries the transaction datetime | `MessageType` is `(contract_address, sender_address, origin_address, value, chain_id)` — **no datetime**. | Reads the clock; see above. |
| 5 | `gl.nondet.web.request(url, method='POST', body={})` | `method` is **keyword-only and required**; `body` is `str \| bytes \| None`, not a dict. `headers` is supported. | Passes `method="GET"` and a browser `User-Agent`. |
| 6 | `DynArray[T]()` appears constructible | `DynArray.__init__` raises `TypeError: this class can't be instantiated by user`. | `TreeMap.get_or_insert_default(key).append(...)`. |
| 7 | Depends `1jb45aa8…` | The newest genvm-manager (v0.6.0-rc6) ships only `5jycge4q…`, which binds a **redesigned** std lib (`import genlayer as gl`, `gl.contract.Contract`, no `from genlayer import *`). | Stays on the documented `1jb45aa8…`, which the docs specify and which direct-mode tests and the live Studionet deploy both accept. The new layout is a breaking API change and Studionet is not on it. |

### `genvm-lint` validation

`genvm-lint check contracts/Spike.py` reports:

```
✓ Lint passed (3 checks)
✗ Validation failed
  Failed to load SDK: "filename 'runners/py-genlayer/1j/b45aa8….tar' not found"
```

The **lint checks pass**. The validation step then fails to *load* the runner,
because the linter pulls its own genvm-manager (v0.6.0-rc6) which ships only the
redesigned `5jycge4q…` runner and has dropped the one the docs specify. It is a
missing artifact in the linter's cache, not a finding about this contract — the
same `Depends` hash loads fine in direct-mode tests and deployed successfully to
Studionet.

### Harness gaps worked around in tests

- **`EthSend` is unimplemented in direct mode.** Every `emit_transfer` would
  fail with "Unknown gl_call request type". `tests/conftest.py` installs a
  `_gl_call_hook` that accepts it and records `(address, wei)` — which also lets
  the tests assert the right amount went to the right wallet.
- **`spawn_sandbox` is unimplemented in direct mode**, so
  `direct_vm.run_validator()` cannot drive a `strict_eq` validator (it fails
  decoding the sub-VM result: `unknown type 14`). Since `strict_eq` decides
  consensus purely by value-equality of the payload, `tests/consensus/` runs
  `_collect` under two different sets of feeds and compares the payloads
  directly. That tests the real property without depending on the gap.
- **Web mocks match in registration order**, so a test that wants one source to
  fail must register that source's mock first.

---

## 4. Deliberate deviations from the original brief

Both came out of the live feed probe on 2026-09-23 and were signed off before
the catalog was frozen. Full evidence in [RESOLUTION.md](RESOLUTION.md).

### Crypto settles on Gate.io + Binance, not CoinGecko + Binance

CoinGecko returned `HTTP 429` twice inside a single probe run from one
residential IP — validators on hosted Studio share an egress IP, so it would be
worse there. It is also *sampled spot*, not OHLC, so its "open" is a sample near
the boundary rather than the first trade of the window: a systematic ~0.1 pp
offset against a true kline open, enough to flip a close dominance ranking. And
it returns an empty series for narrow ranges (a 1-hour range gave `n=0`).

Gate.io is keyless, returns true OHLC on the exact instants, answered every
probe call without throttling, and has a genuinely different JSON shape (a
positional array with a different field order), which forces a genuinely
different parser. CoinGecko survives in the UI as a display-only price.

### Commodities settle on ETF proxies over the daily session

No second keyless public domain serves intraday commodity data. Probed and
rejected: Stooq (JS proof-of-work wall), Pyth (historical behind `401`),
Dukascopy (`403`), Investing.com (`403`), CNBC (snapshot only), Nasdaq
(daily only), TradingEconomics (guest discontinued), Alpha Vantage / Twelve Data
/ FMP / EODHD (demo keys refused), Bitget / MEXC (no commodity symbols).

Pairing Yahoo **futures** with Nasdaq **ETF** was rejected as a trap: on
2026-09-22 `GC=F` moved +0.043% while `GLD` moved +0.76%, because a 24-hour
GMT+1 day and a 6.5-hour equity session are different windows. They would
disagree constantly and make refunds the normal outcome. The correct pairing is
the **same instrument from two independent vendors**, so a disagreement really
does mean "the sources disagree".

Consequently commodity dominance ranks returns over the **daily session** rather
than an hour. Hourly dominance stays exact on crypto, where two independent
hourly sources genuinely exist.

---

## 5. Frontend

### One write path

`writeWithEstimatedFees` in `frontend/src/lib/write.ts` is the only place in the
app that calls `writeContract`. When the client exposes
`estimateTransactionFeesForWrite`, it prices the exact call it is about to make
and passes `distribution` / `messageAllocations` / `feeValue` into
`writeContract`. If estimation throws it raises `FeeEstimationError` rather than
submitting a transaction the network will not accept.

### The genlayer-js version split

| | genlayer-js 1.1.8 | genlayer-js 2.0.0-rc.1 |
|---|---|---|
| `estimateTransactionFeesForWrite` | absent | present |
| `writeContract({ fees })` | absent | present |
| Works against Studionet | **yes** | **no** — every `gen_call` returns "Missing or invalid parameters" |

Verified against the live deployment: identical `readContract` calls succeed on
1.1.8 and fail on 2.0.0-rc.1.

The brief anticipated this — *"use the stable CLI + current genlayer-js that
matches that network… if studionet rejects that flow, degrade writes with a
clear UI message instead of sending a doomed tx"*. So the app is pinned to
**1.1.8**, and the helper is **capability-driven rather than version-hardcoded**:

- client exposes fee estimation → always estimate, never write unpriced
- client does not → that network has no fee flow to honour (proven by the CLI's
  own deploy and `create_market`, both of which landed with no fees)

Point Spike at a consensus-v0.6 network with genlayer-js 2.x and every write
starts pricing itself with no code changes. `write.test.ts` covers both paths.

### Reads only from views

The UI never computes a settlement outcome. Every number that decides a market
comes from a contract view. Chain id, RPC and contract address live in
`src/lib/env.ts`; no environment variable is required to build.

---

## 6. Known limits

- **Payable calls need a browser wallet.** The `genlayer` CLI hardcodes
  `value: 0n` in its write path, so it cannot attach GEN to `take_position`.
  Creating, resolving and claiming work from the CLI; staking does not.
- ~~**Studionet has no EVM layer**, so the `emit_transfer` payout path cannot be
  exercised end-to-end there.~~ **This was wrong, and it was the most dangerous
  sentence in this repo.** Corrected 2026-09-23 after testing it instead of
  trusting it.

  The claim was read off the doc warning *"EVM contract interaction **beyond
  value transfers to EOAs** is not implemented"*, which actually says value
  transfers to EOAs **are** supported — only EVM *method* calls are not. Spike
  only ever does the former.

  Measured with a disposable probe contract
  (`scripts/payout_probe/PayoutProbe.py`, deployed to
  `0xf65908DFD8210593c3da8E599f85F8c389754c78`, never part of the product):
  funded with 3 GEN, pushed 1 GEN to `0xBEEF…0001`, and via raw
  `eth_getBalance` the recipient went `0 → 1000000000000000000` while the probe
  went `3 GEN → 2 GEN`, roughly 30 seconds after the call was accepted.

  So outbound GEN works on Studionet, the refund and claim paths are correct as
  written, and no contract change was needed. Balances there are still simulated
  in a database rather than held by a real ghost contract, which is why the
  settlement is fast and why this should be re-checked on a network with a true
  EVM layer.
- **Commodity dominance is a daily-session ranking**, not an hourly one. This is
  a data-availability limit, not an implementation shortcut.
- **CoinGecko is display-only.** It is not compiled into the contract.
