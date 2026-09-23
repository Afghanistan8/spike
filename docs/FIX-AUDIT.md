# Spike — Live Site Fix Audit

Against **https://spike-sepia.vercel.app/** and contract
**`0xE1582599A503a2E97B6640545B1DCB0c85e49841`** on Studionet (chain 61999),
audited 2026-09-23. Every line below was observed, not inferred.

## Findings

| # | Area | Finding | Verdict |
|---|------|---------|---------|
| 01 | P0-1 reads | Live board loads and lists market #1 (ADA, 2026-09-25, daily). Stats read `markets:1, open:1`. | **PASS** |
| 02 | P0-1 reads | `get_stats`, `get_supported_universe`, `get_markets(0,50)`, `get_market("1")` all succeed from the deployed origin on genlayer-js 1.1.8. | **PASS** |
| 03 | P0-1 reads | `get_market("999")` returns `{}`; the UI renders "No market with id 999" rather than throwing. | **PASS** |
| 04 | P0-1 reads | No CORS failures, no console errors, no failed requests to `studio.genlayer.com`. | **PASS** |
| 05 | P0-1 reads | No RPC health indicator exists anywhere in the UI. | **FIX** |
| 06 | **P0-2 payout** | **`emit_transfer` to an EOA DOES work on Studionet.** Disposable probe `0xf65908DFD8210593c3da8E599f85F8c389754c78` funded with 3 GEN, pushed 1 GEN to `0xBEEF…0001`: recipient `0 → 1000000000000000000`, probe `3 GEN → 2 GEN`, landed ~30s after the call was accepted. | **PASS** |
| 07 | **P0-2 docs** | `docs/ARCHITECTURE.md` and `README.md` both assert outbound GEN does **not** work on Studionet. That claim is **false** — it was inherited from a doc warning about "EVM contract interaction *beyond* value transfers to EOAs", which says the opposite of how it was read. | **FIX (docs only)** |
| 08 | P0-2 contract | Because 06 passes, the refund branch of `take_position` and `claim` are correct as written. **No contract change, no redeploy.** | **PASS** |
| 09 | P0-2 UI | Payout lands ~30s after acceptance, but the UI says only "arrives as a separate transaction" and never confirms it landed. | **FIX** |
| 10 | P0-3 Vercel | Root Directory `frontend`, Vite preset, output `dist`, `frontend/vercel.json` rewrite present. `/market/1`, `/create`, `/portfolio`, `/how-it-works` all serve the SPA on direct load. | **PASS** |
| 11 | P1-1 board | `Board.tsx:27` calls `getMarkets(offset, PAGE_SIZE)` then filters client-side at line 43. Pagination counts every category, so the Crypto tab can show <50 rows while claiming more pages exist. | **FIX** |
| 12 | P1-1 board | Tab change does not reset `offset`. | **FIX** |
| 13 | P1-2 clock | `CreateMarket.tsx:236` `tomorrow()` uses `new Date(Date.now() + 86400000 + 3600000)` then `.toISOString()` — browser-relative, not the GMT+1 calendar the contract uses. West of UTC−1 it can default to a day the contract rejects as already started. | **FIX** |
| 14 | P1-2 clock | Weekend check uses `new Date(day+"T00:00:00Z").getUTCDay()` — right answer by luck, but not routed through the one GMT+1 helper. | **FIX** |
| 15 | P1-3 wallet | `useWallet()` exposes `error`, and **no page renders it**. A failed connect or a rejected network switch is silent. | **FIX** |
| 16 | P1-4 mobile | `App.tsx:66` nav is `hidden … sm:flex`. At 375px the header shows only the logo and the wallet button — Board / Create / Portfolio / How it works are unreachable. Confirmed on the live site. | **FIX** |
| 17 | P1-5 copy | How-it-works is broadly correct but never states that CoinGecko is not used for settlement, and does not mention the 5-day terminal refund in the sources section. | **FIX** |
| 18 | P2-1 create | No `get_market_by_unique_key` pre-check; a duplicate costs a signature and returns `EXPECTED: duplicate market`. | **FIX** |
| 19 | P2-2 stake | Submit is enabled for any text; `parseGen` throws inside the handler, and the 1–5 GEN / same-side / ≤5 total rules are only enforced on-chain. | **FIX** |
| 20 | P2-3 footer | Explorer link points at `EXPLORER_URL` root, not the contract address. | **FIX** |
| 21 | P2-4 labels | `get_supported_universe` is never loaded on boot; `env.ts` labels are the only source. | **FIX** |
| 22 | P2-5 claim | After a claim, nothing re-reads `get_position` / `get_claimable`, so a stuck payout would look like success. | **FIX** |

## Headline

The app is healthier than its own documentation. Reads, routing and deployment
are fine; the one genuinely dangerous finding is **07** — the repo told the next
reader that money could not leave the contract, which is wrong, and would have
pushed someone into redesigning a payout path that already works.

Nothing here requires a contract change. Everything is frontend plus a
correction to two docs.

## Method

- Live site driven in a browser; network and console inspected on `/`, `/market/1`.
- View calls made from a standalone client against the deployed address.
- Payout tested with a **disposable** probe contract
  (`scripts/payout_probe/PayoutProbe.py`), never by adding a probe method to
  the production contract. Balances read through raw `eth_getBalance`.

---

## Fixes applied

**No contract change. No redeploy.** `0xE1582599A503a2E97B6640545B1DCB0c85e49841`
is still the live contract, because finding 06 showed the payout path was
already correct.

| Finding | Fix |
|---------|-----|
| 05 | `lib/health.ts` records every view call; the footer shows chain id, short contract address and the last successful view — or the failing view, the RPC URL and the raw exception. Reads no longer swallow errors. |
| 07 | `ARCHITECTURE.md` §6 and `README.md` corrected, with the measurement that disproves the old claim. |
| 09, 22 | `lib/payout.ts` watches the wallet balance after a claim or refund. The UI now says "Paid, N GEN arrived after 32s" or warns that the bookkeeping moved but the money did not — instead of assuming success. |
| 11, 12 | Board calls `get_markets_by_category(tab, offset, limit)`; `offset` resets on tab change and paging is disabled while a page is in flight. |
| 13, 14 | `tomorrow()` deleted. `format.ts` now owns `weekdayGmt1`, `isWeekendGmt1`, `addDays` and `defaultTargetDay`, all pure date-string maths on the fixed +01:00 calendar. The date input also gets a `min`. 18 tests cover 22:59/23:00/23:30/00:30 UTC, month, year and DST boundaries. |
| 15 | `<WalletError />` renders in the header and on Create, Market and Portfolio. When a network switch fails it prints the RPC URL, chain id 61999 and symbol GEN for manual entry. |
| 16 | Header has a mobile menu; all four routes plus the faucet are reachable at 375px. |
| 17 | How-it-works now states that CoinGecko is not used for settlement, that a GMT+1 day is 24 hourly bars, that commodities are ETF proxies over the US session, and that the 5-day cutoff refunds everyone. |
| 18 | Create calls `get_market_by_unique_key` as the form changes and blocks with a link to the existing market before anyone signs. |
| 19 | Stake submit is disabled unless the amount parses and satisfies the 1 GEN floor, the 5 GEN cap including an existing position, and the same-side rule. The locked-out side button is disabled with a reason. |
| 20 | Footer links to `/address/<contract>`. |
| 21 | `useUniverse` loads `get_supported_universe` on boot and prefers it over `env.ts`, which stays as the fallback. |

Two contract tests were added (`test_no_rejection_path_traps_gen`,
`test_rejected_stake_is_recoverable_even_if_transfer_is_deferred`) walking all
five refusal reasons and asserting the staker is made whole every time.

Suite after the fix pass: **174 contract tests, 34 frontend tests.**
