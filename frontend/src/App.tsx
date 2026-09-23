import { NavLink, Route, Routes } from "react-router-dom";

import { Board } from "./pages/Board";
import { CreateMarket } from "./pages/CreateMarket";
import { HowItWorks } from "./pages/HowItWorks";
import { MarketDetail } from "./pages/MarketDetail";
import { Portfolio } from "./pages/Portfolio";
import { CHAIN_NAME, EXPLORER_URL, FAUCET_URL, HAS_CONTRACT } from "./lib/env";
import { shortAddr } from "./lib/format";
import { useWallet } from "./lib/useWallet";
import { Banner } from "./components/ui";

function WalletButton() {
  const { account, connect, connecting, hasWallet, onStudionet, switchNetwork } =
    useWallet();

  if (!hasWallet) {
    return (
      <a
        href="https://metamask.io/download/"
        target="_blank"
        rel="noreferrer"
        className="btn-ghost"
      >
        Install a wallet
      </a>
    );
  }
  if (!account) {
    return (
      <button className="btn-primary" onClick={connect} disabled={connecting}>
        {connecting ? "Connecting…" : "Connect"}
      </button>
    );
  }
  if (!onStudionet) {
    return (
      <button className="btn-ghost !border-amber-500/50 !text-amber-300" onClick={switchNetwork}>
        Switch to Studionet
      </button>
    );
  }
  return (
    <span className="mono rounded-md border border-ink-700 px-3 py-2 text-xs text-zinc-300">
      {shortAddr(account)}
    </span>
  );
}

function Nav() {
  const link = ({ isActive }: { isActive: boolean }) =>
    `text-sm font-semibold transition-colors ${
      isActive ? "text-spike" : "text-zinc-400 hover:text-zinc-100"
    }`;

  return (
    <header className="sticky top-0 z-20 border-b border-ink-800 bg-ink-950/85 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3.5">
        <NavLink to="/" className="flex items-center gap-2">
          <span className="text-xl font-extrabold tracking-tight text-zinc-50">
            SPIKE
          </span>
          <span className="h-4 w-[3px] -skew-x-12 bg-spike" />
        </NavLink>

        <nav className="hidden items-center gap-5 sm:flex">
          <NavLink to="/" end className={link}>
            Board
          </NavLink>
          <NavLink to="/create" className={link}>
            Create
          </NavLink>
          <NavLink to="/portfolio" className={link}>
            Portfolio
          </NavLink>
          <NavLink to="/how-it-works" className={link}>
            How it works
          </NavLink>
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
        </div>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <div className="min-h-screen">
      <Nav />

      <main className="mx-auto max-w-6xl px-4 py-8">
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
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-4 gap-y-2 px-4 text-xs text-zinc-600">
          <span>Spike · {CHAIN_NAME}</span>
          <span className="text-zinc-700">·</span>
          <span>No owner. No admin resolve. Two sources or nothing.</span>
          <a
            href={EXPLORER_URL}
            target="_blank"
            rel="noreferrer"
            className="ml-auto hover:text-spike"
          >
            Explorer
          </a>
        </div>
      </footer>
    </div>
  );
}
