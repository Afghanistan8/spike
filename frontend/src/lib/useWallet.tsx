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
  hasInjectedWallet,
} from "./client";
import { CHAIN_ID } from "./env";

type WalletState = {
  account: `0x${string}` | null;
  chainId: number | null;
  onStudionet: boolean;
  hasWallet: boolean;
  connecting: boolean;
  error: string | null;
  connect: () => Promise<void>;
  switchNetwork: () => Promise<void>;
};

const Ctx = createContext<WalletState | null>(null);

export function WalletProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<`0x${string}` | null>(null);
  const [chainId, setChainId] = useState<number | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setAccount(await connectedAccount());
    setChainId(await currentChainId());
  }, []);

  useEffect(() => {
    refresh();
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
  }, [refresh]);

  const connect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      setAccount(await connectWallet());
      setChainId(await currentChainId());
    } catch (e: any) {
      setError(e?.message || "Could not connect.");
    } finally {
      setConnecting(false);
    }
  }, []);

  const switchNetwork = useCallback(async () => {
    setError(null);
    try {
      await ensureStudionet();
      setChainId(await currentChainId());
    } catch (e: any) {
      setError(e?.message || "Could not switch network.");
    }
  }, []);

  const value = useMemo<WalletState>(
    () => ({
      account,
      chainId,
      onStudionet: chainId === CHAIN_ID,
      hasWallet: hasInjectedWallet(),
      connecting,
      error,
      connect,
      switchNetwork,
    }),
    [account, chainId, connecting, error, connect, switchNetwork]
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useWallet(): WalletState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useWallet must be used inside <WalletProvider>");
  return v;
}
