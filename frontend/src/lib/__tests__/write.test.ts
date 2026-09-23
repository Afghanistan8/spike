/**
 * The browser write flow, verified end to end without a network.
 *
 * The thing being proven here is narrow and important: create, stake, resolve
 * and claim must each call `estimateTransactionFeesForWrite` for their own
 * call, and must pass the returned fees into `writeContract`. A write that
 * skips estimation is a transaction the network will not accept.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  FeeEstimationError,
  WriteRevertedError,
  classifyRevert,
  explainError,
  parseStakeOutcome,
  writeWithEstimatedFees,
} from "../write";

const ADDRESS = ("0x" + "ab".repeat(20)) as `0x${string}`;
const ACCOUNT = ("0x" + "cd".repeat(20)) as `0x${string}`;

const ESTIMATE = {
  distribution: { leader: 1n, validators: 2n },
  messageAllocations: [{ index: 0, budget: 7n }],
  feeValue: 12345n,
  policy: { enabled: true },
};

/**
 * A fake GenLayer client that records the order and shape of every call.
 *
 * `noFeeApi` models genlayer-js 1.1.8 - the version Studionet accepts - which
 * has no `estimateTransactionFeesForWrite` at all.
 */
function fakeClient(
  opts: { returned?: unknown; estimateThrows?: boolean; noFeeApi?: boolean } = {}
) {
  const calls: string[] = [];
  const client: any = {
    calls,
    writeContract: vi.fn(async (args: any) => {
      calls.push("write:" + args.functionName);
      return "0xdeadbeef";
    }),
    waitForTransactionReceipt: vi.fn(async () => {
      calls.push("wait");
      return { status: "ACCEPTED", result: { returned: opts.returned ?? "OK" } };
    }),
  };
  if (!opts.noFeeApi) {
    client.estimateTransactionFeesForWrite = vi.fn(async (args: any) => {
      calls.push("estimate:" + args.functionName);
      if (opts.estimateThrows) throw new Error("fee policy unavailable");
      return ESTIMATE;
    });
  }
  return client;
}

describe("writeWithEstimatedFees", () => {
  it("estimates fees before writing, and passes them through", async () => {
    const client = fakeClient();
    const res = await writeWithEstimatedFees({
      client,
      account: ACCOUNT,
      address: ADDRESS,
      functionName: "create_market",
      args: ["KIND_DIRECTION", "CRYPTO", "ADA", "2026-10-15", -1],
    });

    expect(client.estimateTransactionFeesForWrite).toHaveBeenCalledTimes(1);
    expect(client.writeContract).toHaveBeenCalledTimes(1);

    // ordering: estimate must happen first
    expect(client.calls).toEqual(["estimate:create_market", "write:create_market", "wait"]);

    const passed = client.writeContract.mock.calls[0][0];
    expect(passed.fees).toEqual({
      distribution: ESTIMATE.distribution,
      messageAllocations: ESTIMATE.messageAllocations,
      feeValue: ESTIMATE.feeValue,
    });
    expect(res.feeValue).toBe(12345n);
    expect(res.txHash).toBe("0xdeadbeef");
  });

  it("estimates against the same call it is about to submit", async () => {
    const client = fakeClient();
    await writeWithEstimatedFees({
      client,
      account: ACCOUNT,
      address: ADDRESS,
      functionName: "take_position",
      args: ["7", "UP"],
      value: 10n ** 18n,
    });

    const est = client.estimateTransactionFeesForWrite.mock.calls[0][0];
    const wrote = client.writeContract.mock.calls[0][0];
    expect(est.functionName).toBe(wrote.functionName);
    expect(est.args).toEqual(wrote.args);
    expect(est.value).toBe(wrote.value);
    expect(est.address).toBe(wrote.address);
  });

  it("never submits an unpriced transaction when estimation fails", async () => {
    const client = fakeClient({ estimateThrows: true });
    await expect(
      writeWithEstimatedFees({
        client,
        account: ACCOUNT,
        address: ADDRESS,
        functionName: "claim",
        args: ["7"],
      })
    ).rejects.toBeInstanceOf(FeeEstimationError);

    expect(client.writeContract).not.toHaveBeenCalled();
  });

  it("writes unpriced only when the SDK has no fee API at all", async () => {
    // genlayer-js 1.1.8 / Studionet: there is no fee flow to honour.
    const client = fakeClient({ noFeeApi: true });
    const res = await writeWithEstimatedFees({
      client,
      account: ACCOUNT,
      address: ADDRESS,
      functionName: "resolve_market",
      args: ["1"],
    });

    expect(res.feesEstimated).toBe(false);
    expect(res.feeValue).toBeNull();
    const passed = client.writeContract.mock.calls[0][0];
    expect(passed).not.toHaveProperty("fees");
  });

  it("surfaces a revert reason from the receipt", async () => {
    const client = fakeClient();
    client.waitForTransactionReceipt = vi.fn(async () => ({
      status: "ERROR",
      result: { returned: "EXPECTED: duplicate market" },
    }));

    await expect(
      writeWithEstimatedFees({
        client,
        account: ACCOUNT,
        address: ADDRESS,
        functionName: "create_market",
        args: [],
      })
    ).rejects.toBeInstanceOf(WriteRevertedError);
  });
});

// ---------------------------------------------------------------------------
// Source-level coverage: the four write paths all route through the helper.
// ---------------------------------------------------------------------------

describe("every contract write uses estimated fees", () => {
  let client: any;

  beforeEach(() => {
    vi.resetModules();
    client = fakeClient({ returned: "OK" });
    vi.doMock("../client", () => ({
      writeClient: () => client,
      readClient: () => client,
    }));
    vi.doMock("../env", async () => {
      const actual = await vi.importActual<any>("../env");
      return { ...actual, CONTRACT_ADDRESS: ADDRESS, HAS_CONTRACT: true };
    });
  });

  const cases: Array<[string, (c: any) => Promise<unknown>]> = [
    [
      "create_market",
      (c) => c.createMarket(ACCOUNT, "KIND_DIRECTION", "CRYPTO", "ADA", "2026-10-15", -1),
    ],
    ["take_position", (c) => c.takePosition(ACCOUNT, "1", "UP", 10n ** 18n)],
    ["resolve_market", (c) => c.resolveMarket(ACCOUNT, "1")],
    ["claim", (c) => c.claim(ACCOUNT, "1")],
  ];

  it.each(cases)("%s estimates fees and passes them to writeContract", async (fn, run) => {
    const contract = await import("../contract");
    await run(contract);

    expect(client.estimateTransactionFeesForWrite).toHaveBeenCalledTimes(1);
    expect(client.writeContract).toHaveBeenCalledTimes(1);

    const est = client.estimateTransactionFeesForWrite.mock.calls[0][0];
    const wrote = client.writeContract.mock.calls[0][0];
    expect(est.functionName).toBe(fn);
    expect(wrote.functionName).toBe(fn);
    expect(wrote.fees.feeValue).toBe(ESTIMATE.feeValue);
    expect(wrote.fees.distribution).toBe(ESTIMATE.distribution);

    // estimate strictly precedes the write
    expect(client.calls.indexOf("estimate:" + fn)).toBeLessThan(
      client.calls.indexOf("write:" + fn)
    );
  });

  it("take_position forwards the attached stake to both estimate and write", async () => {
    const contract = await import("../contract");
    await contract.takePosition(ACCOUNT, "1", "UP", 3n * 10n ** 18n);

    const est = client.estimateTransactionFeesForWrite.mock.calls[0][0];
    const wrote = client.writeContract.mock.calls[0][0];
    expect(est.value).toBe(3n * 10n ** 18n);
    expect(wrote.value).toBe(3n * 10n ** 18n);
  });
});

// ---------------------------------------------------------------------------

describe("stake outcome parsing", () => {
  it("reads STAKED", () => {
    expect(parseStakeOutcome("STAKED:1000000000000000000")).toEqual({
      kind: "staked",
      totalWei: 10n ** 18n,
    });
  });

  it("reads REFUNDED", () => {
    expect(parseStakeOutcome("REFUNDED:side switch not allowed")).toEqual({
      kind: "refunded",
      reason: "side switch not allowed",
    });
  });

  it("does not pretend to understand anything else", () => {
    expect(parseStakeOutcome("weird").kind).toBe("unknown");
  });
});

describe("error classification", () => {
  it("maps each contract prefix", () => {
    expect(classifyRevert("EXPECTED: duplicate market")).toBe("EXPECTED");
    expect(classifyRevert("TRANSIENT: gateio http transient")).toBe("TRANSIENT");
    expect(classifyRevert("EXTERNAL: binance incomplete window")).toBe("EXTERNAL");
    expect(classifyRevert("INVARIANT: bad payload")).toBe("INVARIANT");
    expect(classifyRevert("something else")).toBe("UNKNOWN");
  });

  it("explains a transient feed failure as retryable", () => {
    const msg = explainError(new WriteRevertedError("TRANSIENT: gateio http transient"));
    expect(msg).toMatch(/retry|try resolving again/i);
    expect(msg).toMatch(/nothing changed/i);
  });

  it("explains a fee estimation failure without blaming the user", () => {
    const msg = explainError(new FeeEstimationError("claim", new Error("nope")));
    expect(msg).toMatch(/nothing was submitted/i);
  });
});
