/**
 * One GMT+1 calendar.
 *
 * Every "today" / "tomorrow" / weekend decision in the app must agree with the
 * contract, which uses a fixed +01:00 offset and never DST. The dangerous hours
 * are the ones either side of 23:00 UTC, where the GMT+1 date has already
 * rolled over but the UTC date has not.
 */

import { describe, expect, it } from "vitest";

import {
  addDays,
  defaultTargetDay,
  gmt1Day,
  isWeekendGmt1,
  todayGmt1,
  weekdayGmt1,
} from "../format";

const at = (iso: string) => Math.floor(Date.parse(iso) / 1000);

describe("the GMT+1 date rolls at 23:00 UTC", () => {
  it("22:59 UTC is still the same GMT+1 day", () => {
    expect(todayGmt1(at("2026-09-23T22:59:00Z"))).toBe("2026-09-23");
  });

  it("23:00 UTC has already become the next GMT+1 day", () => {
    expect(todayGmt1(at("2026-09-23T23:00:00Z"))).toBe("2026-09-24");
  });

  it("23:30 UTC is the next GMT+1 day", () => {
    expect(todayGmt1(at("2026-09-23T23:30:00Z"))).toBe("2026-09-24");
  });

  it("00:30 UTC is that same GMT+1 day, not a second rollover", () => {
    expect(todayGmt1(at("2026-09-24T00:30:00Z"))).toBe("2026-09-24");
  });

  it("midnight UTC on the 1st is still the 1st in GMT+1", () => {
    expect(todayGmt1(at("2026-10-01T00:30:00Z"))).toBe("2026-10-01");
  });

  it("23:00 UTC on the last of a month rolls the month", () => {
    expect(todayGmt1(at("2026-09-30T23:00:00Z"))).toBe("2026-10-01");
  });

  it("23:00 UTC on 31 Dec rolls the year", () => {
    expect(todayGmt1(at("2026-12-31T23:00:00Z"))).toBe("2027-01-01");
  });

  it("does not shift across a DST boundary", () => {
    // Europe/Paris leaves DST on 2026-10-25. A fixed +01:00 offset must not care.
    expect(todayGmt1(at("2026-10-24T23:30:00Z"))).toBe("2026-10-25");
    expect(todayGmt1(at("2026-10-25T23:30:00Z"))).toBe("2026-10-26");
  });

  it("agrees with gmt1Day on the same instant", () => {
    const t = at("2026-09-23T23:15:00Z");
    expect(todayGmt1(t)).toBe(gmt1Day(t));
  });
});

describe("weekday in the GMT+1 calendar", () => {
  it("knows the week", () => {
    expect(weekdayGmt1("2026-10-19")).toBe(0); // Monday
    expect(weekdayGmt1("2026-10-15")).toBe(3); // Thursday
    expect(weekdayGmt1("2026-10-17")).toBe(5); // Saturday
    expect(weekdayGmt1("2026-10-18")).toBe(6); // Sunday
  });

  it("flags the weekend", () => {
    expect(isWeekendGmt1("2026-10-17")).toBe(true);
    expect(isWeekendGmt1("2026-10-18")).toBe(true);
    expect(isWeekendGmt1("2026-10-16")).toBe(false);
  });

  it("matches the contract's own weekday maths", () => {
    // contracts/Spike.py _weekday() over the same dates
    const expected: Record<string, number> = {
      "2026-01-01": 3,
      "2026-02-28": 5,
      "2026-12-31": 3,
      "2028-02-29": 1,
    };
    for (const [day, want] of Object.entries(expected)) {
      expect(weekdayGmt1(day)).toBe(want);
    }
  });
});

describe("addDays", () => {
  it("crosses months, years and a leap day", () => {
    expect(addDays("2026-09-30", 1)).toBe("2026-10-01");
    expect(addDays("2026-12-31", 1)).toBe("2027-01-01");
    expect(addDays("2028-02-28", 1)).toBe("2028-02-29");
    expect(addDays("2026-02-28", 1)).toBe("2026-03-01");
    expect(addDays("2026-10-01", -1)).toBe("2026-09-30");
  });
});

describe("defaultTargetDay", () => {
  it("crypto defaults to tomorrow in GMT+1", () => {
    expect(defaultTargetDay("CRYPTO", at("2026-09-23T12:00:00Z"))).toBe("2026-09-24");
  });

  it("crypto late-evening default is driven by the GMT+1 date, not the UTC one", () => {
    // 23:30 UTC on the 23rd is already the 24th in GMT+1, so tomorrow is the 25th
    expect(defaultTargetDay("CRYPTO", at("2026-09-23T23:30:00Z"))).toBe("2026-09-25");
  });

  it("crypto may target a weekend", () => {
    expect(defaultTargetDay("CRYPTO", at("2026-10-16T12:00:00Z"))).toBe("2026-10-17");
  });

  it("commodities skip Saturday and Sunday", () => {
    // Friday 2026-10-16 -> tomorrow is Sat -> next weekday is Mon 2026-10-19
    expect(defaultTargetDay("COMMODITIES", at("2026-10-16T12:00:00Z"))).toBe("2026-10-19");
    // Saturday -> Monday
    expect(defaultTargetDay("COMMODITIES", at("2026-10-17T12:00:00Z"))).toBe("2026-10-19");
  });

  it("always returns a day strictly after today in GMT+1", () => {
    for (const iso of [
      "2026-09-23T00:30:00Z",
      "2026-09-23T12:00:00Z",
      "2026-09-23T22:59:00Z",
      "2026-09-23T23:00:00Z",
      "2026-09-23T23:59:00Z",
    ]) {
      const now = at(iso);
      for (const cat of ["CRYPTO", "COMMODITIES"]) {
        expect(defaultTargetDay(cat, now) > todayGmt1(now)).toBe(true);
      }
    }
  });
});
