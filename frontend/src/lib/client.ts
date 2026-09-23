/**
 * GenLayer client + injected wallet.
 *
 * Spike is locked to Studionet. There is no network switcher, because silently
 * moving a user to a different chain than the one holding their stakes would be
 * a way to lose money.
 */

import { createClient } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import type { GenLayerClient } from "genlayer-js/types";

import { CHAIN_ID, CHAIN_NAME, EXPLORER_URL, NATIVE_CURRENCY, RPC_URL } from "./env";

export type Eip1193Provider = {
  request: (args: { method: string; params?: any[] | object }) => Promise<any>;
  on?: (event: string, cb: (...a: any[]) => void) => void;
  removeListener?: (event: string, cb: (...a: any[]) => void) => void;
};

export function getInjectedProvider(): Eip1193Provider | null {
  const w = globalThis as any;
  return (w?.ethereum as Eip1193Provider) ?? null;
}

export function hasInjectedWallet(): boolean {
  return getInjectedProvider() !== null;
}

/** A read-only client. Works with no wallet at all, so the board always loads. */
export function readClient(): GenLayerClient<any> {
  return createClient({ chain: studionet, endpoint: RPC_URL });
}

/** A client bound to the connected wallet, for writes. */
export function writeClient(account: `0x${string}`): GenLayerClient<any> {
  const provider = getInjectedProvider();
  if (!provider) throw new Error("No injected wallet found.");
  return createClient({
    chain: studionet,
    endpoint: RPC_URL,
    account,
    provider: provider as any,
  });
}

const CHAIN_ID_HEX = "0x" + CHAIN_ID.toString(16);

export async function connectWallet(): Promise<`0x${string}`> {
  const provider = getInjectedProvider();
  if (!provider) {
    throw new Error(
      "No browser wallet detected. Install MetaMask or Rabby, then reload."
    );
  }
  const accounts: string[] = await provider.request({
    method: "eth_requestAccounts",
  });
  if (!accounts?.length) throw new Error("Wallet returned no accounts.");
  await ensureStudionet();
  return accounts[0] as `0x${string}`;
}

export async function currentChainId(): Promise<number | null> {
  const provider = getInjectedProvider();
  if (!provider) return null;
  try {
    const id = await provider.request({ method: "eth_chainId" });
    return parseInt(String(id), 16);
  } catch {
    return null;
  }
}

/** Ask the wallet to switch to Studionet, adding it first if unknown. */
export async function ensureStudionet(): Promise<void> {
  const provider = getInjectedProvider();
  if (!provider) return;
  try {
    await provider.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (e: any) {
    // 4902 = chain unknown to the wallet
    if (e?.code === 4902 || /unrecognized|not been added/i.test(String(e?.message))) {
      await provider.request({
        method: "wallet_addEthereumChain",
        params: [
          {
            chainId: CHAIN_ID_HEX,
            chainName: CHAIN_NAME,
            rpcUrls: [RPC_URL],
            nativeCurrency: NATIVE_CURRENCY,
            blockExplorerUrls: [EXPLORER_URL],
          },
        ],
      });
      return;
    }
    throw e;
  }
}

export async function connectedAccount(): Promise<`0x${string}` | null> {
  const provider = getInjectedProvider();
  if (!provider) return null;
  try {
    const accounts: string[] = await provider.request({ method: "eth_accounts" });
    return (accounts?.[0] as `0x${string}`) ?? null;
  } catch {
    return null;
  }
}
