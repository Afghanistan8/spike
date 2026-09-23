# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
"""
Spike - a permissionless daily prediction market that resolves itself.

There is no owner, no pause switch, no admin resolve, no upgrade hook and no
privileged address anywhere in this file. Settlement happens because every
validator independently fetches two public feeds inside a single equivalence
block and the contract only writes a result when both feeds agree.

See docs/SPEC.md and docs/RESOLUTION.md.
"""

from genlayer import *

import datetime as _dt
import json
from dataclasses import dataclass

# ===========================================================================
# Catalog - frozen at compile time.
#
# These are module-level constants rather than storage. Storage would be
# weaker: it would need a writer somewhere. There is no function in this
# contract that can add, remove or rename an asset, because the catalog is
# not writable in the first place.
# ===========================================================================

CAT_CRYPTO = "CRYPTO"
CAT_COMMODITIES = "COMMODITIES"

KIND_DIRECTION = "KIND_DIRECTION"
KIND_DOMINANCE = "KIND_DOMINANCE"

CRYPTO_ASSETS = ("ADA", "ZEC", "ZAMA", "ARB")
COMMODITY_ASSETS = ("GOLD", "SILVER", "WTI", "COPPER")

# Source A / Source B identifiers, persisted verbatim in the evidence payload.
SRC_GATE = "gateio"
SRC_BINANCE = "binance"
SRC_YAHOO = "yahoo"
SRC_NASDAQ = "nasdaq"

GATE_PAIR = {
    "ADA": "ADA_USDT",
    "ZEC": "ZEC_USDT",
    "ZAMA": "ZAMA_USDT",
    "ARB": "ARB_USDT",
}

BINANCE_SYMBOL = {
    "ADA": "ADAUSDT",
    "ZEC": "ZECUSDT",
    "ZAMA": "ZAMAUSDT",
    "ARB": "ARBUSDT",
}

# Commodities settle on liquid ETF proxies, because no second keyless public
# domain serves intraday or futures commodity data. The UI labels them as
# proxies. See docs/RESOLUTION.md section 4.
COMMODITY_PROXY = {
    "GOLD": "GLD",
    "SILVER": "SLV",
    "WTI": "USO",
    "COPPER": "CPER",
}

COMMODITY_LABEL = {
    "GOLD": "GOLD (GLD proxy)",
    "SILVER": "SILVER (SLV proxy)",
    "WTI": "WTI (USO proxy)",
    "COPPER": "COPPER (CPER proxy)",
}

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# ===========================================================================
# Constants
# ===========================================================================

ONE_GEN = 10**18
MIN_STAKE_WEI = 1 * ONE_GEN
MAX_STAKE_WEI = 5 * ONE_GEN
MAX_FORWARD_DAYS = 366
TERMINAL_REFUND_DELAY_SECS = 5 * 86400
PRICE_SCALE = 10**8
PAGE_LIMIT = 50

GMT1_OFFSET = 3600  # fixed +01:00, never DST

SIDE_UP = "UP"
SIDE_DOWN = "DOWN"

V_UP = "UP"
V_DOWN = "DOWN"
V_TIE = "TIE"
V_MISSING = "MISSING"
V_INCONCLUSIVE = "INCONCLUSIVE"

PH_OPEN = "OPEN"
PH_WINDOW_LIVE = "WINDOW_LIVE"
PH_READY = "READY_TO_SETTLE"
PH_SETTLED_UP = "SETTLED_UP"
PH_SETTLED_DOWN = "SETTLED_DOWN"
PH_SETTLED_WINNER = "SETTLED_WINNER"
PH_INCONCLUSIVE = "INCONCLUSIVE"

E_EXPECTED = "EXPECTED:"
E_TRANSIENT = "TRANSIENT:"
E_EXTERNAL = "EXTERNAL:"
E_INVARIANT = "INVARIANT:"


# ===========================================================================
# Pure helpers. No gl, no storage, no I/O. Unit-testable against fixtures.
# ===========================================================================

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _is_leap(y: int) -> bool:
    return (y % 4 == 0 and y % 100 != 0) or y % 400 == 0


def _days_in_month(y: int, m: int) -> int:
    if m == 2 and _is_leap(y):
        return 29
    return _DAYS_IN_MONTH[m - 1]


def _parse_day(day: str):
    """'YYYY-MM-DD' -> (y, m, d). Returns None if malformed."""
    if not isinstance(day, str) or len(day) != 10:
        return None
    if day[4] != "-" or day[7] != "-":
        return None
    ys, ms, ds = day[0:4], day[5:7], day[8:10]
    if not (ys.isdigit() and ms.isdigit() and ds.isdigit()):
        return None
    y, m, d = int(ys), int(ms), int(ds)
    if y < 1970 or y > 9999 or m < 1 or m > 12:
        return None
    if d < 1 or d > _days_in_month(y, m):
        return None
    return (y, m, d)


def _days_from_civil(y: int, m: int, d: int) -> int:
    """Howard Hinnant's civil-to-days algorithm. Integer only, no datetime."""
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    doy = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _day_utc_midnight(day: str) -> int:
    """Unix seconds at 00:00:00 UTC on that calendar date."""
    parsed = _parse_day(day)
    if parsed is None:
        return -1
    y, m, d = parsed
    return _days_from_civil(y, m, d) * 86400


def _weekday(day: str) -> int:
    """0 = Monday ... 6 = Sunday."""
    return (_days_from_civil(*_parse_day(day)) + 3) % 7


def _window_utc(category: str, kind: str, day: str, hour: int):
    """
    (open_instant, close_instant) in unix seconds for a GMT+1 window.

    Only CRYPTO dominance is hourly - it is the only place where two
    independent intraday sources exist. Everything else spans the GMT+1 day.
    """
    base = _day_utc_midnight(day) - GMT1_OFFSET  # 00:00 GMT+1, expressed in UTC
    if category == CAT_CRYPTO and kind == KIND_DOMINANCE:
        t0 = base + hour * 3600
        return (t0, t0 + 3600)
    return (base, base + 86400)


def _hour_required(category: str, kind: str) -> bool:
    return category == CAT_CRYPTO and kind == KIND_DOMINANCE


def _assets_of(category: str):
    return CRYPTO_ASSETS if category == CAT_CRYPTO else COMMODITY_ASSETS


def _scale_price(v) -> int:
    """
    Decimal string or float -> integer scaled by 10**8.

    Never uses float arithmetic for the scaling itself. A float input is first
    formatted to a fixed 8-decimal string, which is deterministic for a given
    CPython build, then parsed digit by digit. Raises ValueError on anything
    it cannot parse exactly.
    """
    if isinstance(v, bool):
        raise ValueError("bool is not a price")
    if isinstance(v, int):
        return v * PRICE_SCALE
    if isinstance(v, float):
        v = "%.8f" % v
    if not isinstance(v, str):
        raise ValueError("unparseable price type")

    s = v.strip().replace(",", "").replace("$", "")
    if not s:
        raise ValueError("empty price")
    neg = s.startswith("-")
    if neg or s.startswith("+"):
        s = s[1:]
    if "e" in s or "E" in s:
        raise ValueError("scientific notation refused")

    if "." in s:
        whole, frac = s.split(".", 1)
    else:
        whole, frac = s, ""
    if whole == "":
        whole = "0"
    if not whole.isdigit() or (frac != "" and not frac.isdigit()):
        raise ValueError("non numeric price")

    frac = (frac + "00000000")[:8]  # truncate, never round
    out = int(whole) * PRICE_SCALE + int(frac)
    return -out if neg else out


def _verdict_direction(open_i: int, close_i: int) -> str:
    """A flat candle is DOWN. This is a product rule, not an accident."""
    return V_UP if close_i > open_i else V_DOWN


def _better_return(o_a: int, c_a: int, o_b: int, c_b: int) -> int:
    """
    Compare (c_a-o_a)/o_a against (c_b-o_b)/o_b by cross-multiplication.

    Returns 1 if a is strictly greater, -1 if b is, 0 if equal.
    Both opens must be strictly positive - the caller guarantees it.
    """
    left = (c_a - o_a) * o_b
    right = (c_b - o_b) * o_a
    if left > right:
        return 1
    if left < right:
        return -1
    return 0


def _verdict_dominance(assets, opens, closes) -> str:
    """
    WIN:<asset> for the strictly greatest return, or TIE if the top is shared.

    assets/opens/closes are parallel sequences in a fixed catalog order, so
    every validator walks them identically.
    """
    best = 0
    tied = False
    for i in range(1, len(assets)):
        cmp = _better_return(opens[i], closes[i], opens[best], closes[best])
        if cmp > 0:
            best, tied = i, False
        elif cmp == 0:
            tied = True
    if tied:
        # Re-check: a tie only matters if it is a tie for FIRST place.
        for i in range(len(assets)):
            if i != best and _better_return(opens[i], closes[i], opens[best], closes[best]) == 0:
                return V_TIE
    return "WIN:" + assets[best]


def _final_verdict(a: str, b: str) -> str:
    """
    The whole point of Spike.

    A settling verdict requires both sources to have independently produced the
    same real verdict. TIE and MISSING can never settle, and a single source can
    never settle, because this comparison needs both.
    """
    if a == b and (a == V_UP or a == V_DOWN or a.startswith("WIN:")):
        return a
    return V_INCONCLUSIVE


def _is_settling(v: str) -> bool:
    return v == V_UP or v == V_DOWN or v.startswith("WIN:")


def _classify_status(status: int) -> str:
    """HTTP status -> error class, per docs/RESOLUTION.md section 6."""
    if status == 200:
        return ""
    if status in (408, 425, 429) or status >= 500 or status == 0:
        return "TRANSIENT"
    return "EXTERNAL"


# --------------------------------------------------------------------------
# Parsers. One per source, deliberately different code paths.
# Each returns (open_scaled, close_scaled) or raises ValueError.
# --------------------------------------------------------------------------


def _parse_binance_klines(body: bytes, t0: int, t1: int):
    """
    Binance 1h klines, positional rows:
        [openTime, open, high, low, close, volume, closeTime, ...]

    Binance DAILY bars are UTC-aligned and therefore one hour off a GMT+1 day.
    This parser only ever reads 1h bars and rebuilds the window from them.
    """
    rows = json.loads(body.decode("utf-8"))
    if not isinstance(rows, list) or len(rows) == 0:
        raise ValueError("empty klines")
    expected = (t1 - t0) // 3600
    if len(rows) != expected:
        raise ValueError("incomplete window %d/%d" % (len(rows), expected))
    if int(rows[0][0]) != t0 * 1000:
        raise ValueError("first bar not on open instant")
    if int(rows[-1][0]) != (t1 - 3600) * 1000:
        raise ValueError("last bar not on close instant")
    return (_scale_price(rows[0][1]), _scale_price(rows[-1][4]))


def _parse_gate_candles(body: bytes, t0: int, t1: int):
    """
    Gate.io v4 candlesticks, positional rows in a DIFFERENT order to Binance:
        [timestamp_s, quote_volume, close, high, low, open, base_volume, closed]
    """
    rows = json.loads(body.decode("utf-8"))
    if not isinstance(rows, list) or len(rows) == 0:
        raise ValueError("empty candles")
    expected = (t1 - t0) // 3600
    if len(rows) != expected:
        raise ValueError("incomplete window %d/%d" % (len(rows), expected))
    if int(rows[0][0]) != t0:
        raise ValueError("first bar not on open instant")
    if int(rows[-1][0]) != t1 - 3600:
        raise ValueError("last bar not on close instant")
    return (_scale_price(rows[0][5]), _scale_price(rows[-1][2]))


def _parse_yahoo_daily(body: bytes, day: str):
    """
    Yahoo Finance chart API, 1d bars.

    Daily bars are stamped at session open in the exchange timezone, not at
    GMT+1 midnight, so we match by calendar date in the exchange timezone
    rather than by instant equality.
    """
    doc = json.loads(body.decode("utf-8"))
    chart = doc.get("chart") or {}
    results = chart.get("result")
    if not results:
        raise ValueError("no chart result")
    res = results[0]
    stamps = res.get("timestamp") or []
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    opens = quote.get("open") or []
    closes = quote.get("close") or []
    if not stamps or len(stamps) != len(opens) or len(stamps) != len(closes):
        raise ValueError("malformed chart series")

    gmt_off = int((res.get("meta") or {}).get("gmtoffset") or 0)
    target = _day_utc_midnight(day)
    for i in range(len(stamps)):
        # Local calendar date of the bar, floored to midnight.
        local_day = ((int(stamps[i]) + gmt_off) // 86400) * 86400
        if local_day == target:
            if opens[i] is None or closes[i] is None:
                raise ValueError("null bar - no session")
            return (_scale_price(opens[i]), _scale_price(closes[i]))
    raise ValueError("no session on target day")


def _parse_nasdaq_daily(body: bytes, day: str):
    """
    Nasdaq ETF historical rows:
        {"date": "MM/DD/YYYY", "open": "$397.07", "close": "400.07", ...}
    """
    doc = json.loads(body.decode("utf-8"))
    data = doc.get("data")
    if not data:
        raise ValueError("no data - no session or bad range")
    table = data.get("tradesTable") or {}
    rows = table.get("rows") or []
    if not rows:
        raise ValueError("empty trades table")
    parsed = _parse_day(day)
    want = "%02d/%02d/%04d" % (parsed[1], parsed[2], parsed[0])
    for r in rows:
        if r.get("date") == want:
            return (_scale_price(r.get("open")), _scale_price(r.get("close")))
    raise ValueError("target day not in series")


# --------------------------------------------------------------------------
# URL builders
# --------------------------------------------------------------------------


def _url_binance(asset: str, t0: int, t1: int) -> str:
    return (
        "https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1h"
        "&startTime=%d&endTime=%d&limit=1000"
        % (BINANCE_SYMBOL[asset], t0 * 1000, t1 * 1000 - 1)
    )


def _url_gate(asset: str, t0: int, t1: int) -> str:
    return (
        "https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair=%s"
        "&interval=1h&from=%d&to=%d" % (GATE_PAIR[asset], t0, t1 - 1)
    )


def _url_yahoo(asset: str, t0: int, t1: int) -> str:
    return (
        "https://query1.finance.yahoo.com/v8/finance/chart/%s"
        "?interval=1d&period1=%d&period2=%d"
        % (COMMODITY_PROXY[asset], t0 - 86400 * 5, t1 + 86400)
    )


def _url_nasdaq(asset: str, day: str) -> str:
    start = _day_utc_midnight(day) - 86400 * 7
    end = _day_utc_midnight(day) + 86400
    return (
        "https://api.nasdaq.com/api/quote/%s/historical?assetclass=etf"
        "&fromdate=%s&todate=%s&limit=20"
        % (COMMODITY_PROXY[asset], _unix_to_day(start), _unix_to_day(end))
    )


def _civil_from_days(z: int):
    """Inverse of _days_from_civil."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + (3 if mp < 10 else -9)
    return (y + (1 if m <= 2 else 0), m, d)


def _unix_to_day(ts: int) -> str:
    y, m, d = _civil_from_days(ts // 86400)
    return "%04d-%02d-%02d" % (y, m, d)


# ===========================================================================
# Storage records
# ===========================================================================


@allow_storage
@dataclass
class Market:
    market_id: str
    kind: str
    category: str
    asset: str  # "" for dominance
    target_day: str
    target_hour: i32  # -1 where the window is not hourly
    created_at: u256
    settles_at: u256
    terminal_refund_at: u256
    creator: Address
    resolved_at: u256
    final_verdict: str  # "" until resolved
    source_a_id: str
    source_b_id: str
    source_a_verdict: str
    source_b_verdict: str
    evidence: str
    refund_all: bool
    total_pool: u256


@allow_storage
@dataclass
class Position:
    wallet: Address
    market_id: str
    side: str
    amount: u256
    claimed: bool


@gl.evm.contract_interface
class _Payee:
    """
    Paying a wallet is an EXTERNAL message and must go through the EVM
    interface even though the recipient is not a contract.

    Using gl.get_contract_at(eoa).emit_transfer() instead is accepted by
    consensus, reports success, and moves zero wei. That is a silent loss of
    funds, so it is never used in this file.
    """

    class View:
        pass

    class Write:
        pass


# ===========================================================================


class Spike(gl.Contract):
    _next_id: u256

    _markets: TreeMap[str, Market]
    _market_ids: DynArray[str]
    _unique_key_to_id: TreeMap[str, str]

    # f"{market_id}|{side}" -> wei
    _pools: TreeMap[str, u256]
    # f"{market_id}|{0xwallet}" -> Position
    _positions: TreeMap[str, Position]

    _market_position_keys: TreeMap[str, DynArray[str]]
    _user_position_keys: TreeMap[str, DynArray[str]]
    _user_market_ids: TreeMap[str, DynArray[str]]

    _activity: DynArray[str]

    _total_staked: u256
    _total_paid_out: u256

    def __init__(self):
        self._next_id = u256(1)
        self._total_staked = u256(0)
        self._total_paid_out = u256(0)

    # -- internal helpers ---------------------------------------------------

    def _now(self) -> int:
        """
        Transaction datetime, never calldata.

        GenVM wires the Python clock to the transaction datetime - it is the
        same value as gl.message_raw['datetime'], not host wall-clock time. We
        read it through the clock rather than the raw message because
        message_raw is decoded once at module load, which is correct on chain
        (a fresh VM per transaction) but stale in the in-process test runner,
        where the module is reused across calls. The attribute is resolved at
        call time so a test that warps mid-run is seen immediately.
        """
        return int(_dt.datetime.now(_dt.timezone.utc).timestamp())

    def _fail(self, cls: str, msg: str):
        raise gl.vm.UserError(cls + " " + msg)

    def _pool_key(self, mid: str, side: str) -> str:
        return mid + "|" + side

    def _pos_key(self, mid: str, who: Address) -> str:
        return mid + "|" + who.as_hex

    def _pool(self, mid: str, side: str) -> int:
        return int(self._pools.get(self._pool_key(mid, side), u256(0)))

    def _sides_of(self, m) -> list:
        if m.kind == KIND_DIRECTION:
            return [SIDE_UP, SIDE_DOWN]
        return list(_assets_of(m.category))

    def _phase(self, m) -> str:
        if m.final_verdict != "":
            v = m.final_verdict
            if v == V_UP:
                return PH_SETTLED_UP
            if v == V_DOWN:
                return PH_SETTLED_DOWN
            if v.startswith("WIN:"):
                return PH_SETTLED_WINNER
            return PH_INCONCLUSIVE
        t0, t1 = _window_utc(m.category, m.kind, m.target_day, int(m.target_hour))
        now = self._now()
        if now < t0:
            return PH_OPEN
        if now < t1:
            return PH_WINDOW_LIVE
        return PH_READY

    def _winning_side(self, m) -> str:
        v = m.final_verdict
        if v == V_UP:
            return SIDE_UP
        if v == V_DOWN:
            return SIDE_DOWN
        if v.startswith("WIN:"):
            return v[4:]
        return ""

    def _log(self, line: str) -> None:
        self._activity.append(line)

    def _market_view(self, m) -> dict:
        sides = self._sides_of(m)
        pools = {}
        for s in sides:
            pools[s] = str(self._pool(m.market_id, s))
        label = m.asset
        if m.category == CAT_COMMODITIES and m.asset != "":
            label = COMMODITY_LABEL[m.asset]
        t0, t1 = _window_utc(m.category, m.kind, m.target_day, int(m.target_hour))
        return {
            "market_id": m.market_id,
            "kind": m.kind,
            "category": m.category,
            "asset": m.asset,
            "asset_label": label,
            "target_day": m.target_day,
            "target_hour": int(m.target_hour),
            "window_open": t0,
            "window_close": t1,
            "created_at": int(m.created_at),
            "settles_at": int(m.settles_at),
            "terminal_refund_at": int(m.terminal_refund_at),
            "creator": m.creator.as_hex,
            "phase": self._phase(m),
            "final_verdict": m.final_verdict,
            "resolved_at": int(m.resolved_at),
            "refund_all": m.refund_all,
            "total_pool": str(int(m.total_pool)),
            "sides": sides,
            "pools": pools,
            "unique_key": self._unique_key(
                m.kind, m.category, m.asset, m.target_day, int(m.target_hour)
            ),
        }

    def _unique_key(self, kind, category, asset, day, hour) -> str:
        return "%s|%s|%s|%s|%d" % (kind, category, asset, day, hour)

    # -- writes -------------------------------------------------------------

    @gl.public.write
    def create_market(
        self, kind: str, category: str, asset: str, target_day: str, target_hour: int
    ) -> str:
        """Anyone. No value attached, so this may revert normally."""
        if kind != KIND_DIRECTION and kind != KIND_DOMINANCE:
            self._fail(E_EXPECTED, "unknown kind")
        if category != CAT_CRYPTO and category != CAT_COMMODITIES:
            self._fail(E_EXPECTED, "unknown category")
        if _parse_day(target_day) is None:
            self._fail(E_EXPECTED, "bad target_day, want YYYY-MM-DD")

        assets = _assets_of(category)
        if kind == KIND_DIRECTION:
            if asset not in assets:
                self._fail(E_EXPECTED, "asset not in catalog for category")
        else:
            if asset != "":
                self._fail(E_EXPECTED, "dominance takes no asset")

        hour = int(target_hour)
        if _hour_required(category, kind):
            if hour < 0 or hour > 23:
                self._fail(E_EXPECTED, "target_hour must be 0..23")
        else:
            # Every other combination has no independent intraday source pair,
            # so an hour would be meaningless. Reject rather than silently coerce.
            if hour != -1:
                self._fail(E_EXPECTED, "target_hour must be -1 for this market")

        if category == CAT_COMMODITIES and _weekday(target_day) >= 5:
            self._fail(E_EXPECTED, "no commodity session on Sat/Sun")

        t0, t1 = _window_utc(category, kind, target_day, hour)
        now = self._now()
        if t0 <= now:
            self._fail(E_EXPECTED, "window already started or past")
        if t0 - now > MAX_FORWARD_DAYS * 86400:
            self._fail(E_EXPECTED, "more than 366 days ahead")

        ukey = self._unique_key(kind, category, asset, target_day, hour)
        if ukey in self._unique_key_to_id:
            self._fail(E_EXPECTED, "duplicate market")

        mid = str(int(self._next_id))
        self._next_id = u256(int(self._next_id) + 1)

        if category == CAT_CRYPTO:
            src_a, src_b = SRC_GATE, SRC_BINANCE
        else:
            src_a, src_b = SRC_YAHOO, SRC_NASDAQ

        sender = gl.message.sender_address
        self._markets[mid] = Market(
            market_id=mid,
            kind=kind,
            category=category,
            asset=asset,
            target_day=target_day,
            target_hour=i32(hour),
            created_at=u256(now),
            settles_at=u256(t1),
            terminal_refund_at=u256(t1 + TERMINAL_REFUND_DELAY_SECS),
            creator=sender,
            resolved_at=u256(0),
            final_verdict="",
            source_a_id=src_a,
            source_b_id=src_b,
            source_a_verdict="",
            source_b_verdict="",
            evidence="",
            refund_all=False,
            total_pool=u256(0),
        )
        self._market_ids.append(mid)
        self._unique_key_to_id[ukey] = mid

        self._user_market_ids.get_or_insert_default(sender.as_hex).append(mid)
        who = sender.as_hex

        self._log("CREATE|%s|%s|%s|%s" % (mid, kind, category, who))
        return mid

    @gl.public.write.payable
    def take_position(self, market_id: str, side: str) -> str:
        """
        CRITICAL MONEY RULE.

        GEN attached to a call is credited to this contract even if the call
        reverts. So once value is attached this method must NOT revert: it
        validates first and then either records the stake and returns
        STAKED:<total>, or returns the GEN and answers REFUNDED:<reason>.

        A call carrying zero value has nothing to lose and may revert normally.
        """
        value = int(gl.message.value)
        sender = gl.message.sender_address

        if value == 0:
            self._fail(E_EXPECTED, "no value attached")

        reason = self._validate_stake(market_id, side, sender, value)
        if reason != "":
            _Payee(sender).emit_transfer(value=u256(value))
            self._log("REFUND|%s|%s|%s" % (market_id, sender.as_hex, reason))
            return "REFUNDED:" + reason

        m = self._markets[market_id]
        pkey = self._pos_key(market_id, sender)
        existing = self._positions.get(pkey, None)
        if existing is None:
            self._positions[pkey] = Position(
                wallet=sender,
                market_id=market_id,
                side=side,
                amount=u256(value),
                claimed=False,
            )
            self._market_position_keys.get_or_insert_default(market_id).append(pkey)
            self._user_position_keys.get_or_insert_default(sender.as_hex).append(pkey)
            total = value
        else:
            total = int(existing.amount) + value
            existing.amount = u256(total)

        pk = self._pool_key(market_id, side)
        self._pools[pk] = u256(self._pool(market_id, side) + value)
        m.total_pool = u256(int(m.total_pool) + value)
        self._total_staked = u256(int(self._total_staked) + value)

        self._log("STAKE|%s|%s|%s|%d" % (market_id, sender.as_hex, side, value))
        return "STAKED:" + str(total)

    def _validate_stake(self, market_id: str, side: str, sender, value: int) -> str:
        """Returns '' if the stake is acceptable, else a short refund reason."""
        m = self._markets.get(market_id, None)
        if m is None:
            return "unknown market"
        if self._phase(m) != PH_OPEN:
            return "market not open"
        if side not in self._sides_of(m):
            return "invalid side"

        pkey = self._pos_key(market_id, sender)
        existing = self._positions.get(pkey, None)
        prior = 0 if existing is None else int(existing.amount)
        if existing is not None and existing.side != side:
            return "side switch not allowed"

        total = prior + value
        if prior == 0 and value < MIN_STAKE_WEI:
            return "below 1 GEN minimum"
        if total > MAX_STAKE_WEI:
            return "above 5 GEN maximum"
        return ""

    @gl.public.write
    def resolve_market(self, market_id: str) -> str:
        """
        Anyone. No prices, no URLs, no slugs in calldata - the contract already
        knows the catalog.
        """
        m = self._markets.get(market_id, None)
        if m is None:
            self._fail(E_EXPECTED, "unknown market")
        if m.final_verdict != "":
            self._fail(E_EXPECTED, "already resolved")

        now = self._now()
        if now < int(m.settles_at):
            self._fail(E_EXPECTED, "window has not closed yet")

        # Terminal refund path: never touches the network.
        if now >= int(m.terminal_refund_at):
            m.source_a_verdict = ""
            m.source_b_verdict = ""
            m.final_verdict = V_INCONCLUSIVE
            m.refund_all = True
            m.resolved_at = u256(now)
            m.evidence = "terminal refund after 5 days, no feeds consulted"
            self._log("TERMINAL|%s" % market_id)
            return "TERMINAL_REFUND"

        kind = m.kind
        category = m.category
        asset = m.asset
        day = m.target_day
        hour = int(m.target_hour)
        t0, t1 = _window_utc(category, kind, day, hour)
        assets = list(_assets_of(category)) if kind == KIND_DOMINANCE else [asset]

        # Everything the closure needs is a plain local. It must not touch
        # storage, call a contract or emit a message.
        def nondet_block():
            return _collect(category, kind, assets, day, hour, t0, t1)

        payload = gl.eq_principle.strict_eq(nondet_block)

        # --- deterministic from here on ---------------------------------
        if not isinstance(payload, dict):
            self._fail(E_INVARIANT, "payload is not a dict")

        err = payload.get("error", "")
        if err != "":
            detail = payload.get("detail", "")
            if err == "TRANSIENT":
                self._fail(E_TRANSIENT, detail)
            elif err == "EXTERNAL":
                self._fail(E_EXTERNAL, detail)
            else:
                self._fail(E_INVARIANT, "unknown error class " + str(err))

        va = payload.get("source_a_verdict", "")
        vb = payload.get("source_b_verdict", "")
        pa = payload.get("source_a_prices", [])
        pb = payload.get("source_b_prices", [])

        self._check_payload(payload, m, assets, va, vb, pa, pb)

        final = _final_verdict(va, vb)
        if final != payload.get("final_verdict", ""):
            self._fail(E_INVARIANT, "final verdict does not follow from sources")

        m.source_a_verdict = va
        m.source_b_verdict = vb
        m.final_verdict = final
        m.resolved_at = u256(now)
        m.refund_all = not _is_settling(final)
        m.evidence = json.dumps(
            {
                "kind": kind,
                "category": category,
                "asset": asset,
                "target_day": day,
                "target_hour": hour,
                "assets": assets,
                "source_a_id": m.source_a_id,
                "source_b_id": m.source_b_id,
                "source_a_verdict": va,
                "source_b_verdict": vb,
                "source_a_prices": pa,
                "source_b_prices": pb,
                "final_verdict": final,
            },
            sort_keys=True,
        )

        # A settling verdict with an empty winning pool means nobody can claim
        # the pot; everyone is refunded instead of burning the stakes.
        if _is_settling(final):
            if self._pool(market_id, self._winning_side(m)) == 0:
                m.refund_all = True

        self._log("RESOLVE|%s|%s" % (market_id, final))
        return final

    def _check_payload(self, payload, m, assets, va, vb, pa, pb) -> None:
        """
        Deterministic re-validation of the bytes the validators agreed on.

        This must never fire in honest execution. It exists because "the
        validators agreed" is not the same as "the value is well formed".
        """
        allowed = {V_UP, V_DOWN, V_TIE, V_MISSING}
        for a in assets:
            allowed.add("WIN:" + a)
        if va not in allowed or vb not in allowed:
            self._fail(E_INVARIANT, "verdict outside permitted set")
        if payload.get("kind", "") != m.kind or payload.get("category", "") != m.category:
            self._fail(E_INVARIANT, "payload describes a different market")
        if payload.get("target_day", "") != m.target_day:
            self._fail(E_INVARIANT, "payload describes a different day")
        if int(payload.get("target_hour", -99)) != int(m.target_hour):
            self._fail(E_INVARIANT, "payload describes a different hour")
        if payload.get("source_a_id", "") != m.source_a_id:
            self._fail(E_INVARIANT, "source a mismatch")
        if payload.get("source_b_id", "") != m.source_b_id:
            self._fail(E_INVARIANT, "source b mismatch")
        if not isinstance(pa, list) or not isinstance(pb, list):
            self._fail(E_INVARIANT, "prices are not lists")
        if len(pa) != len(assets) * 2 or len(pb) != len(assets) * 2:
            self._fail(E_INVARIANT, "price array wrong length")
        for x in list(pa) + list(pb):
            if not isinstance(x, int) or isinstance(x, bool) or x <= 0:
                self._fail(E_INVARIANT, "non positive integer price")

    @gl.public.write
    def claim(self, market_id: str) -> str:
        """
        Position owner, once.

        The transfer is emitted BEFORE claimed is flipped. If anything after it
        raises, the whole call reverts and claimed stays false.
        """
        m = self._markets.get(market_id, None)
        if m is None:
            self._fail(E_EXPECTED, "unknown market")
        if m.final_verdict == "":
            self._fail(E_EXPECTED, "not resolved yet")

        sender = gl.message.sender_address
        pkey = self._pos_key(market_id, sender)
        pos = self._positions.get(pkey, None)
        if pos is None:
            self._fail(E_EXPECTED, "no position")
        if pos.claimed:
            self._fail(E_EXPECTED, "already claimed")

        amount = self._payout_for(m, pos)
        if amount == 0:
            self._fail(E_EXPECTED, "nothing to claim")

        _Payee(sender).emit_transfer(value=u256(amount))
        pos.claimed = True
        self._total_paid_out = u256(int(self._total_paid_out) + amount)
        self._log("CLAIM|%s|%s|%d" % (market_id, sender.as_hex, amount))
        return "CLAIMED:" + str(amount)

    def _payout_for(self, m, pos) -> int:
        if pos.claimed:
            return 0
        if m.final_verdict == "":
            return 0
        if m.refund_all or not _is_settling(m.final_verdict):
            return int(pos.amount)
        win = self._winning_side(m)
        if pos.side != win:
            return 0
        win_pool = self._pool(m.market_id, win)
        if win_pool == 0:
            return 0
        # Floor division. Dust stays in the contract rather than over-paying.
        return int(pos.amount) * int(m.total_pool) // win_pool

    # -- views --------------------------------------------------------------

    @gl.public.view
    def get_supported_universe(self) -> dict:
        return {
            "categories": [CAT_CRYPTO, CAT_COMMODITIES],
            "kinds": [KIND_DIRECTION, KIND_DOMINANCE],
            "assets": {
                CAT_CRYPTO: list(CRYPTO_ASSETS),
                CAT_COMMODITIES: list(COMMODITY_ASSETS),
            },
            "labels": {
                CAT_CRYPTO: {a: a for a in CRYPTO_ASSETS},
                CAT_COMMODITIES: dict(COMMODITY_LABEL),
            },
            "sources": {
                CAT_CRYPTO: [SRC_GATE, SRC_BINANCE],
                CAT_COMMODITIES: [SRC_YAHOO, SRC_NASDAQ],
            },
            "hourly_categories": [CAT_CRYPTO],
            "min_stake_wei": str(MIN_STAKE_WEI),
            "max_stake_wei": str(MAX_STAKE_WEI),
            "max_forward_days": MAX_FORWARD_DAYS,
            "terminal_refund_delay_secs": TERMINAL_REFUND_DELAY_SECS,
            "price_scale": PRICE_SCALE,
            "timezone": "GMT+1 fixed offset, never DST",
        }

    @gl.public.view
    def get_stats(self) -> dict:
        open_n = 0
        resolved_n = 0
        for mid in self._market_ids:
            m = self._markets[mid]
            if m.final_verdict != "":
                resolved_n += 1
            elif self._phase(m) == PH_OPEN:
                open_n += 1
        return {
            "markets": len(self._market_ids),
            "open_markets": open_n,
            "resolved_markets": resolved_n,
            "total_staked_wei": str(int(self._total_staked)),
            "total_paid_out_wei": str(int(self._total_paid_out)),
        }

    @gl.public.view
    def get_market(self, market_id: str) -> dict:
        m = self._markets.get(market_id, None)
        if m is None:
            return {}
        return self._market_view(m)

    @gl.public.view
    def get_market_phase(self, market_id: str) -> str:
        m = self._markets.get(market_id, None)
        if m is None:
            return ""
        return self._phase(m)

    @gl.public.view
    def get_market_by_unique_key(
        self, kind: str, category: str, asset: str, target_day: str, target_hour: int
    ) -> dict:
        ukey = self._unique_key(kind, category, asset, target_day, int(target_hour))
        mid = self._unique_key_to_id.get(ukey, "")
        if mid == "":
            return {}
        return self._market_view(self._markets[mid])

    def _page(self, ids, offset: int, limit: int):
        limit = min(max(int(limit), 0), PAGE_LIMIT)
        offset = max(int(offset), 0)
        out = []
        n = len(ids)
        i = offset
        while i < n and len(out) < limit:
            out.append(ids[i])
            i += 1
        return out, n

    @gl.public.view
    def get_markets(self, offset: int, limit: int) -> dict:
        ids, total = self._page(self._market_ids, offset, limit)
        return {
            "total": total,
            "items": [self._market_view(self._markets[i]) for i in ids],
        }

    @gl.public.view
    def get_open_markets(self, offset: int, limit: int) -> dict:
        matched = [
            mid for mid in self._market_ids if self._phase(self._markets[mid]) == PH_OPEN
        ]
        ids, total = self._page(matched, offset, limit)
        return {
            "total": total,
            "items": [self._market_view(self._markets[i]) for i in ids],
        }

    @gl.public.view
    def get_markets_by_category(self, category: str, offset: int, limit: int) -> dict:
        matched = [
            mid for mid in self._market_ids if self._markets[mid].category == category
        ]
        ids, total = self._page(matched, offset, limit)
        return {
            "total": total,
            "items": [self._market_view(self._markets[i]) for i in ids],
        }

    @gl.public.view
    def get_user_markets(self, wallet: str, offset: int, limit: int) -> dict:
        key = Address(wallet).as_hex
        src = self._user_market_ids.get(key, None)
        arr = [] if src is None else list(src)
        ids, total = self._page(arr, offset, limit)
        return {
            "total": total,
            "items": [self._market_view(self._markets[i]) for i in ids],
        }

    def _position_view(self, pos) -> dict:
        m = self._markets[pos.market_id]
        return {
            "wallet": pos.wallet.as_hex,
            "market_id": pos.market_id,
            "side": pos.side,
            "amount_wei": str(int(pos.amount)),
            "claimed": pos.claimed,
            "claimable_wei": str(self._payout_for(m, pos)),
            "phase": self._phase(m),
        }

    @gl.public.view
    def get_position(self, market_id: str, wallet: str) -> dict:
        pos = self._positions.get(self._pos_key(market_id, Address(wallet)), None)
        if pos is None:
            return {}
        return self._position_view(pos)

    @gl.public.view
    def get_claimable(self, market_id: str, wallet: str) -> str:
        m = self._markets.get(market_id, None)
        pos = self._positions.get(self._pos_key(market_id, Address(wallet)), None)
        if m is None or pos is None:
            return "0"
        return str(self._payout_for(m, pos))

    @gl.public.view
    def get_user_positions(self, wallet: str, offset: int, limit: int) -> dict:
        key = Address(wallet).as_hex
        src = self._user_position_keys.get(key, None)
        arr = [] if src is None else list(src)
        keys, total = self._page(arr, offset, limit)
        return {
            "total": total,
            "items": [self._position_view(self._positions[k]) for k in keys],
        }

    @gl.public.view
    def get_market_positions(self, market_id: str, offset: int, limit: int) -> dict:
        src = self._market_position_keys.get(market_id, None)
        arr = [] if src is None else list(src)
        keys, total = self._page(arr, offset, limit)
        return {
            "total": total,
            "items": [self._position_view(self._positions[k]) for k in keys],
        }

    @gl.public.view
    def get_settlement_evidence(self, market_id: str) -> dict:
        m = self._markets.get(market_id, None)
        if m is None:
            return {}
        return {
            "market_id": market_id,
            "source_a_id": m.source_a_id,
            "source_b_id": m.source_b_id,
            "source_a_verdict": m.source_a_verdict,
            "source_b_verdict": m.source_b_verdict,
            "final_verdict": m.final_verdict,
            "refund_all": m.refund_all,
            "resolved_at": int(m.resolved_at),
            "evidence": m.evidence,
        }

    @gl.public.view
    def get_activity(self, offset: int, limit: int) -> dict:
        n = len(self._activity)
        limit = min(max(int(limit), 0), PAGE_LIMIT)
        offset = max(int(offset), 0)
        out = []
        i = n - 1 - offset
        while i >= 0 and len(out) < limit:
            out.append(self._activity[i])
            i -= 1
        return {"total": n, "items": out}


# ===========================================================================
# Non-deterministic collection.
#
# Module-level so the closure in resolve_market stays free of `self`. Nothing
# in here reads or writes storage, calls a contract, or emits a message.
# ===========================================================================


def _http_get(url: str):
    """-> (err_class, body). err_class is '' on success."""
    resp = gl.nondet.web.request(url, method="GET", headers={"User-Agent": UA})
    cls = _classify_status(int(resp.status))
    if cls != "":
        return (cls, b"")
    body = resp.body
    if body is None or len(body) == 0:
        return ("TRANSIENT", b"")
    if len(body) > 4_000_000:
        return ("EXTERNAL", b"")
    return ("", body)


def _fetch_one(source: str, asset: str, day: str, t0: int, t1: int):
    """
    -> (err_class, detail, open, close)

    One source, one asset, one window. Every source has its own URL shape and
    its own parser; nothing is shared between the two sides of a pair.
    """
    if source == SRC_BINANCE:
        url = _url_binance(asset, t0, t1)
    elif source == SRC_GATE:
        url = _url_gate(asset, t0, t1)
    elif source == SRC_YAHOO:
        url = _url_yahoo(asset, t0, t1)
    elif source == SRC_NASDAQ:
        url = _url_nasdaq(asset, day)
    else:
        return ("EXTERNAL", "unknown source", 0, 0)

    cls, body = _http_get(url)
    if cls != "":
        return (cls, source + " http " + cls.lower(), 0, 0)

    try:
        if source == SRC_BINANCE:
            o, c = _parse_binance_klines(body, t0, t1)
        elif source == SRC_GATE:
            o, c = _parse_gate_candles(body, t0, t1)
        elif source == SRC_YAHOO:
            o, c = _parse_yahoo_daily(body, day)
        else:
            o, c = _parse_nasdaq_daily(body, day)
    except UnicodeDecodeError:
        return ("EXTERNAL", source + " non-utf8 body", 0, 0)
    except Exception as e:
        return ("EXTERNAL", source + " " + str(e)[:80], 0, 0)

    if o <= 0 or c <= 0:
        return ("EXTERNAL", source + " non positive price", 0, 0)
    return ("", "", o, c)


def _verdict_for(kind: str, assets, opens, closes) -> str:
    if kind == KIND_DIRECTION:
        return _verdict_direction(opens[0], closes[0])
    return _verdict_dominance(assets, opens, closes)


def _collect(category: str, kind: str, assets, day: str, hour: int, t0: int, t1: int) -> dict:
    """
    Fetch BOTH sources, derive a verdict from each independently, and return a
    small canonical payload.

    Failures are returned as data rather than raised, so that every node
    produces a comparable value and the revert happens deterministically after
    consensus instead of inside the sandbox.

    Raw HTML and raw JSON never leave this function.
    """
    if category == CAT_CRYPTO:
        src_a, src_b = SRC_GATE, SRC_BINANCE
    else:
        src_a, src_b = SRC_YAHOO, SRC_NASDAQ

    prices = {src_a: [], src_b: []}
    for source in (src_a, src_b):
        for a in assets:
            cls, detail, o, c = _fetch_one(source, a, day, t0, t1)
            if cls != "":
                return {"error": cls, "detail": detail}
            prices[source].append(o)
            prices[source].append(c)

    opens_a = [prices[src_a][i * 2] for i in range(len(assets))]
    closes_a = [prices[src_a][i * 2 + 1] for i in range(len(assets))]
    opens_b = [prices[src_b][i * 2] for i in range(len(assets))]
    closes_b = [prices[src_b][i * 2 + 1] for i in range(len(assets))]

    va = _verdict_for(kind, assets, opens_a, closes_a)
    vb = _verdict_for(kind, assets, opens_b, closes_b)

    return {
        "error": "",
        "detail": "",
        "kind": kind,
        "category": category,
        "asset": assets[0] if kind == KIND_DIRECTION else "",
        "target_day": day,
        "target_hour": hour,
        "source_a_id": src_a,
        "source_b_id": src_b,
        "source_a_verdict": va,
        "source_b_verdict": vb,
        "source_a_prices": prices[src_a],
        "source_b_prices": prices[src_b],
        "final_verdict": _final_verdict(va, vb),
    }
