/**
 * Finding the browser wallet, without a race.
 *
 * The old detection read `window.ethereum` once during the first React render
 * and never looked again. Extensions inject asynchronously, so if the injection
 * lost that race the UI said "Install a wallet" forever, with no way back even
 * though a wallet was sitting right there.
 *
 * Three things fix it:
 *
 *  1. EIP-6963 discovery. Modern wallets (MetaMask, Rabby, Coinbase, Brave)
 *     announce themselves on an event instead of fighting over `window.ethereum`.
 *     We ask, and we keep listening, because announcements can arrive late.
 *  2. A `window.ethereum` fallback for anything older, including the case where
 *     several wallets pile into `window.ethereum.providers`.
 *  3. A subscription, so React re-renders when a provider shows up rather than
 *     sampling once and giving up.
 */

export type Eip1193Provider = {
  request: (args: { method: string; params?: any[] | object }) => Promise<any>;
  on?: (event: string, cb: (...a: any[]) => void) => void;
  removeListener?: (event: string, cb: (...a: any[]) => void) => void;
  isMetaMask?: boolean;
  isRabby?: boolean;
};

export type WalletInfo = {
  uuid: string;
  name: string;
  icon?: string;
  rdns?: string;
};

export type DiscoveredWallet = {
  info: WalletInfo;
  provider: Eip1193Provider;
};

const found = new Map<string, DiscoveredWallet>();
const listeners = new Set<(w: DiscoveredWallet[]) => void>();
let started = false;

function snapshot(): DiscoveredWallet[] {
  return [...found.values()];
}

function emit() {
  const list = snapshot();
  for (const l of listeners) l(list);
}

function add(w: DiscoveredWallet) {
  const key = w.info.rdns || w.info.uuid || w.info.name;
  if (!key || found.has(key)) return;
  found.set(key, w);
  emit();
}

/** Pull whatever is already on `window.ethereum`, including multi-wallet arrays. */
function scanLegacy() {
  const eth = (globalThis as any)?.ethereum;
  if (!eth) return;

  // Several extensions installed: they queue themselves here rather than
  // overwriting each other.
  const list: Eip1193Provider[] = Array.isArray(eth.providers) ? eth.providers : [eth];
  for (const p of list) {
    if (!p || typeof p.request !== "function") continue;
    add({
      info: {
        uuid: `legacy:${nameOf(p)}`,
        name: nameOf(p),
        rdns: undefined,
      },
      provider: p,
    });
  }
}

function nameOf(p: Eip1193Provider): string {
  if (p.isRabby) return "Rabby";
  if (p.isMetaMask) return "MetaMask";
  return "Browser wallet";
}

/**
 * Begin discovery. Safe to call repeatedly.
 *
 * We announce-request once, keep the listener attached for late arrivals, and
 * poll briefly for the legacy global, which some extensions set without firing
 * anything at all.
 */
export function startDiscovery() {
  if (started || typeof window === "undefined") return;
  started = true;

  window.addEventListener("eip6963:announceProvider", (e: any) => {
    const d = e?.detail;
    if (d?.provider && d?.info) add({ info: d.info, provider: d.provider });
  });
  window.dispatchEvent(new Event("eip6963:requestProvider"));

  // Some builds fire this instead of announcing.
  window.addEventListener("ethereum#initialized", scanLegacy, { once: true });

  scanLegacy();

  // Extensions that neither announce nor signal: give them a moment.
  let tries = 0;
  const timer = setInterval(() => {
    scanLegacy();
    if (++tries >= 10 || found.size > 0) clearInterval(timer);
  }, 200);
}

export function subscribeWallets(cb: (w: DiscoveredWallet[]) => void): () => void {
  startDiscovery();
  listeners.add(cb);
  cb(snapshot());
  return () => listeners.delete(cb);
}

export function listWallets(): DiscoveredWallet[] {
  return snapshot();
}

// --------------------------------------------------------------------------
// Which wallet to use
//
// This used to guess: prefer `window.ethereum`, else the first that announced.
// With two extensions installed that is a coin toss, and it popped the wrong
// wallet. Guessing is now gone. With one wallet we use it; with several the
// caller must choose, and the choice is remembered.
// --------------------------------------------------------------------------

const STORAGE_KEY = "spike.wallet";

let selectedKey: string | null = readStoredKey();

function readStoredKey(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null; // private mode, blocked storage - not fatal
  }
}

function writeStoredKey(key: string | null) {
  try {
    if (key === null) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, key);
  } catch {
    /* the selection still applies for this page load */
  }
}

/** Stable identity for a wallet: its rdns if it has one. */
export function walletKey(w: DiscoveredWallet): string {
  return w.info.rdns || w.info.uuid || w.info.name;
}

export function getSelected(): DiscoveredWallet | null {
  const list = snapshot();
  if (list.length === 0) return null;
  if (selectedKey) {
    const hit = list.find((w) => walletKey(w) === selectedKey);
    if (hit) return hit;
  }
  // Exactly one wallet is not a choice, so it needs no ceremony.
  return list.length === 1 ? list[0] : null;
}

/** Choose a wallet by key. Pass null to forget the choice. */
export function selectWallet(key: string | null) {
  selectedKey = key;
  writeStoredKey(key);
  emit();
}

/**
 * The provider to use, or null when the user still has to pick.
 *
 * Returning null with several wallets present is deliberate: it is the signal
 * that makes the UI ask instead of assuming.
 */
export function pickProvider(): Eip1193Provider | null {
  return getSelected()?.provider ?? null;
}

export function hasWallet(): boolean {
  return snapshot().length > 0;
}

/** True when wallets exist but none has been chosen yet. */
export function needsChoice(): boolean {
  return snapshot().length > 1 && getSelected() === null;
}
