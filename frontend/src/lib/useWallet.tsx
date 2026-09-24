import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  connectWallet,
  connectedAccount,
  currentChainId,
  ensureStudionet,
  getInjectedProvider,
} from "./client";
import {
  getSelected,
  selectWallet,
  startDiscovery,
  subscribeWallets,
  walletKey,
  type DiscoveredWallet,
} from "./discovery";
import { CHAIN_ID } from "./env";

type WalletState = {
  account: `0x${string}` | null;
  chainId: number | null;
  onStudionet: boolean;
  /** True once a wallet has actually been discovered - not a first-paint guess. */
  hasWallet: boolean;
  /** Discovery is still in its grace period; do not claim "no wallet" yet. */
  searching: boolean;
  /** Every wallet found, so the user can pick rather than be picked for. */
  wallets: DiscoveredWallet[];
  /** The wallet in use, or null while the choice is still open. */
  selected: DiscoveredWallet | null;
  /** Several wallets exist and none has been chosen. */
  needsChoice: boolean;
  /** The picker is open. */
  picking: boolean;
  setPicking: (v: boolean) => void;
  connecting: boolean;
  error: string | null;
  connect: () => Promise<void>;
  connectWith: (key: string) => Promise<void>;
  switchNetwork: () => Promise<void>;
  disconnect: () => void;
  /** Forget the remembered wallet so the picker comes back. */
  changeWallet: () => void;
};

const Ctx = createContext<WalletState | null>(null);

export function WalletProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<`0x${string}` | null>(null);
  const [chainId, setChainId] = useState<number | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);

  // Wallet presence is STATE, not a value computed during render. Extensions
  // inject asynchronously, so a one-shot check during the first render is a
  // race the page frequently loses - and losing it used to strand the user on
  // "Install a wallet" with no way to recover short of a reload.
  const [wallets, setWallets] = useState<DiscoveredWallet[]>([]);
  const [searching, setSearching] = useState(true);

  useEffect(() => {
    startDiscovery();
    const stop = subscribeWallets(setWallets);
    // Grace period: until this elapses we must not tell anyone they have no
    // wallet, because a slow extension has not had its chance yet.
    const t = setTimeout(() => setSearching(false), 2500);
    return () => {
      stop();
      clearTimeout(t);
    };
  }, []);

  // Recomputed whenever the discovered set or the selection changes, because
  // selectWallet() re-emits and that replaces `wallets`.
  const selected = useMemo(() => getSelected(), [wallets]);
  const selectedKey = selected ? walletKey(selected) : null;
  const needsChoice = wallets.length > 1 && selected === null;

  const refresh = useCallback(async () => {
    setAccount(await connectedAccount());
    setChainId(await currentChainId());
  }, []);

  // Re-read the account whenever the chosen wallet changes, so an already
  // authorised session is picked up without the user clicking anything.
  useEffect(() => {
    if (!selectedKey) return;
    refresh();
  }, [selectedKey, refresh]);

  useEffect(() => {
    const p = getInjectedProvider();
    if (!p?.on) return;
    const onAccounts = (a: string[]) => setAccount((a?.[0] as `0x${string}`) ?? null);
    const onChain = (id: string) => setChainId(parseInt(String(id), 16));
    p.on("accountsChanged", onAccounts);
    p.on("chainChanged", onChain);
    return () => {
      p.removeListener?.("accountsChanged", onAccounts);
      p.removeListener?.("chainChanged", onChain);
    };
  }, [selectedKey]);

  const doConnect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      setAccount(await connectWallet());
      setChainId(await currentChainId());
      setPicking(false);
    } catch (e: any) {
      // 4001 is the user closing the popup; not worth an angry red banner.
      setError(
        e?.code === 4001
          ? "Connection request was rejected in your wallet."
          : e?.message || "Could not connect."
      );
    } finally {
      setConnecting(false);
    }
  }, []);

  /** Ask first when there is a real choice to make. */
  const connect = useCallback(async () => {
    if (needsChoice) {
      setPicking(true);
      return;
    }
    await doConnect();
  }, [needsChoice, doConnect]);

  const connectWith = useCallback(
    async (key: string) => {
      selectWallet(key);
      await doConnect();
    },
    [doConnect]
  );

  const switchNetwork = useCallback(async () => {
    setError(null);
    try {
      await ensureStudionet();
      setChainId(await currentChainId());
    } catch (e: any) {
      setError(
        e?.code === 4001
          ? "Network switch was rejected in your wallet."
          : e?.message || "Could not switch network."
      );
    }
  }, []);

  /**
   * Forget the account locally.
   *
   * EIP-1193 has no real disconnect - the wallet decides what a site may see -
   * so this clears our own state and is honest about it in the UI.
   */
  const disconnect = useCallback(() => {
    setAccount(null);
    setError(null);
  }, []);

  /** Drop the remembered wallet and reopen the picker. */
  const changeWallet = useCallback(() => {
    selectWallet(null);
    setAccount(null);
    setError(null);
    setPicking(true);
  }, []);

  const value = useMemo<WalletState>(
    () => ({
      account,
      chainId,
      onStudionet: chainId === CHAIN_ID,
      hasWallet: wallets.length > 0,
      searching: searching && wallets.length === 0,
      wallets,
      selected,
      needsChoice,
      picking,
      setPicking,
      connecting,
      error,
      connect,
      connectWith,
      switchNetwork,
      disconnect,
      changeWallet,
    }),
    [
      account,
      chainId,
      wallets,
      selected,
      needsChoice,
      picking,
      searching,
      connecting,
      error,
      connect,
      connectWith,
      switchNetwork,
      disconnect,
      changeWallet,
    ]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWallet(): WalletState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWallet must be used inside <WalletProvider>");
  return v;
}
