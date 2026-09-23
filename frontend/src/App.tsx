import { useEffect, useState } from "react";
import { NavLink, Route, Routes, useLocation } from "react-router-dom";

import { Board } from "./pages/Board";
import { CreateMarket } from "./pages/CreateMarket";
import { HowItWorks } from "./pages/HowItWorks";
import { MarketDetail } from "./pages/MarketDetail";
import { Portfolio } from "./pages/Portfolio";
import {
  CHAIN_ID,
  CHAIN_NAME,
  CONTRACT_ADDRESS,
  EXPLORER_URL,
  FAUCET_URL,
  HAS_CONTRACT,
} from "./lib/env";
import { shortAddr } from "./lib/format";
import { subscribeHealth, type Health } from "./lib/health";
import { useWallet } from "./lib/useWallet";
import { Banner, WalletError } from "./components/ui";

const LINKS = [
  { to: "/", label: "Board", end: true },
  { to: "/create", label: "Create" },
  { to: "/portfolio", label: "Portfolio" },
  { to: "/how-it-works", label: "How it works" },
];

function WalletButton() {
  const { account, connect, connecting, hasWallet, onStudionet, switchNetwork } =
    useWallet();

  if (!hasWallet) {
    return (
      <a
        href="https://metamask.io/download/"
        target="_blank"
        rel="noreferrer"
        className="btn-ghost !px-3 !text-xs sm:!px-4 sm:!text-sm"
      >
        Install a wallet
      </a>
    );
  }
  if (!account) {
    return (
      <button
        className="btn-primary !px-3 !text-xs sm:!px-4 sm:!text-sm"
        onClick={connect}
        disabled={connecting}
      >
        {connecting ? "Connecting…" : "Connect"}
      </button>
    );
  }
  if (!onStudionet) {
    return (
      <button
        className="btn-ghost !px-3 !text-xs !border-amber-500/50 !text-amber-300 sm:!px-4 sm:!text-sm"
        onClick={switchNetwork}
      >
        Switch network
      </button>
    );
  }
  return (
    <span className="mono rounded-md border border-ink-700 px-2 py-2 text-[11px] text-zinc-300 sm:px-3 sm:text-xs">
      {shortAddr(account)}
    </span>
  );
}

function Nav() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();

  // A route change should never leave the menu covering the page.
  useEffect(() => setOpen(false), [pathname]);

  const link = ({ isActive }: { isActive: boolean }) =>
    `text-sm font-semibold transition-colors ${
      isActive ? "text-spike" : "text-zinc-400 hover:text-zinc-100"
    }`;

  return (
    <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3.5 sm:gap-6">
        <NavLink to="/" className="flex shrink-0 items-center gap-2">
          <span className="text-xl font-extrabold tracking-tight text-zinc-50">SPIKE</span>
          <span className="h-4 w-[3px] -skew-x-12 bg-spike" />
        </NavLink>

        <nav className="hidden items-center gap-5 sm:flex">
          {LINKS.map((l) => (
            <NavLink key={l.to} to={l.to} end={l.end} className={link}>
              {l.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <a
            href={FAUCET_URL}
            target="_blank"
            rel="noreferrer"
            className="hidden text-xs font-semibold text-zinc-500 hover:text-spike sm:block"
          >
            Get test GEN
          </a>
          <WalletButton />

          <button
            className="rounded-md border border-ink-700 p-2 text-zinc-300 sm:hidden"
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              {open ? (
                <path
                  d="M3 3l10 10M13 3L3 13"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              ) : (
                <path
                  d="M2 4h12M2 8h12M2 12h12"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                />
              )}
            </svg>
          </button>
        </div>
      </div>

      {open && (
        <nav className="border-t border-ink-800 px-4 py-2 sm:hidden">
          {LINKS.map((l) => (
            <NavLink
              key={l.to}
              to={l.to}
              end={l.end}
              className={({ isActive }) =>
                `block rounded-md px-2 py-2.5 text-sm font-semibold ${
                  isActive ? "text-spike" : "text-zinc-300"
                }`
              }
            >
              {l.label}
            </NavLink>
          ))}
          <a
            href={FAUCET_URL}
            target="_blank"
            rel="noreferrer"
            className="block rounded-md px-2 py-2.5 text-sm font-semibold text-zinc-500"
          >
            Get test GEN ↗
          </a>
        </nav>
      )}
    </header>
  );
}

function RpcHealth() {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => subscribeHealth(setH), []);
  if (!h) return null;

  const ok = h.lastOkAt !== null && !h.lastError;
  const when = h.lastOkAt
    ? new Date(h.lastOkAt).toISOString().slice(11, 19) + "Z"
    : "never";

  return (
    <span
      className="mono inline-flex items-center gap-1.5 text-[11px]"
      title={h.lastError ?? `${h.lastFn ?? "view"} ok`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${
          h.lastError ? "bg-down" : ok ? "bg-up" : "bg-zinc-600"
        }`}
      />
      <span className="text-zinc-600">
        chain {h.chainId} · {shortAddr(h.contract)} ·{" "}
        {h.lastError ? (
          <span className="text-down">
            {h.lastErrorFn} failed: {h.lastError.slice(0, 60)}
          </span>
        ) : (
          <>last view {when}</>
        )}
      </span>
    </span>
  );
}

export default function App() {
  return (
    <div className="min-h-screen">
      <Nav />

      <main className="mx-auto max-w-6xl px-4 py-8">
        <div className="mb-4 empty:mb-0">
          <WalletError />
        </div>

        {!HAS_CONTRACT && (
          <div className="mb-6">
            <Banner tone="warn">
              No contract address is configured yet. Deploy Spike to {CHAIN_NAME} and set{" "}
              <code className="mono">CONTRACT_ADDRESS</code> in{" "}
              <code className="mono">frontend/src/lib/env.ts</code>.
            </Banner>
          </div>
        )}

        <Routes>
          <Route path="/" element={<Board />} />
          <Route path="/market/:id" element={<MarketDetail />} />
          <Route path="/create" element={<CreateMarket />} />
          <Route path="/portfolio" element={<Portfolio />} />
          <Route path="/how-it-works" element={<HowItWorks />} />
        </Routes>
      </main>

      <footer className="border-t border-ink-800 py-6">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 text-xs text-zinc-600 sm:flex-row sm:items-center sm:gap-4">
          <span>Spike · {CHAIN_NAME}</span>
          <span className="hidden text-zinc-700 sm:inline">·</span>
          <span>No owner. No admin resolve. Two sources or nothing.</span>
          <a
            href={
              HAS_CONTRACT
                ? `${EXPLORER_URL}/address/${CONTRACT_ADDRESS}`
                : EXPLORER_URL
            }
            target="_blank"
            rel="noreferrer"
            className="hover:text-spike sm:ml-auto"
          >
            {HAS_CONTRACT ? "Contract on explorer ↗" : "Explorer ↗"}
          </a>
        </div>
        <div className="mx-auto mt-2 max-w-6xl px-4">
          <RpcHealth />
        </div>
      </footer>
    </div>
  );
}
