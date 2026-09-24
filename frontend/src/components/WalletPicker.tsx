import { useEffect } from "react";

import { walletKey } from "../lib/discovery";
import { useWallet } from "../lib/useWallet";
import { Spinner } from "./ui";

/**
 * Choose which wallet to connect with.
 *
 * Spike used to pick for you - prefer `window.ethereum`, else the first that
 * announced itself - which with two extensions installed is a coin toss, and
 * popped the wrong one. Now nothing is assumed: every discovered wallet is
 * listed by the name and icon it reports about itself, and the choice is
 * remembered for next time.
 */
export function WalletPicker() {
  const { picking, setPicking, wallets, selected, connectWith, connecting, error } =
    useWallet();

  // Escape should close anything that covers the page.
  useEffect(() => {
    if (!picking) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setPicking(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [picking, setPicking]);

  if (!picking) return null;

  const selectedKey = selected ? walletKey(selected) : null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/70 p-4 backdrop-blur-sm sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label="Choose a wallet"
      onClick={() => setPicking(false)}
    >
      <div
        className="card w-full max-w-sm p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-bold text-zinc-50">Choose a wallet</h2>
            <p className="mt-1 text-xs text-zinc-500">
              {wallets.length} wallets found in this browser.
            </p>
          </div>
          <button
            className="rounded p-1 text-zinc-500 hover:text-zinc-200"
            aria-label="Close"
            onClick={() => setPicking(false)}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path
                d="M3 3l10 10M13 3L3 13"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        <ul className="mt-4 space-y-2">
          {wallets.map((w) => {
            const key = walletKey(w);
            const isSelected = key === selectedKey;
            return (
              <li key={key}>
                <button
                  className={`flex w-full items-center gap-3 rounded-md border px-3 py-3 text-left transition-colors ${
                    isSelected
                      ? "border-spike bg-spike/10"
                      : "border-ink-700 hover:border-spike/60 hover:bg-ink-800/60"
                  }`}
                  disabled={connecting}
                  onClick={() => connectWith(key)}
                >
                  {w.info.icon ? (
                    <img
                      src={w.info.icon}
                      alt=""
                      className="h-8 w-8 shrink-0 rounded"
                    />
                  ) : (
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded bg-ink-800 text-xs font-bold text-zinc-400">
                      {w.info.name.slice(0, 1).toUpperCase()}
                    </span>
                  )}
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-bold text-zinc-100">
                      {w.info.name}
                    </span>
                    {w.info.rdns && (
                      <span className="mono block truncate text-[10px] text-zinc-600">
                        {w.info.rdns}
                      </span>
                    )}
                  </span>
                  {connecting && isSelected ? (
                    <Spinner />
                  ) : isSelected ? (
                    <span className="text-[10px] font-bold uppercase tracking-wider text-spike">
                      Last used
                    </span>
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>

        {error && (
          <p className="mt-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200">
            {error}
          </p>
        )}

        <p className="mt-4 text-[11px] leading-relaxed text-zinc-600">
          Spike remembers this choice in your browser. Change it any time from the
          address menu.
        </p>
      </div>
    </div>
  );
}
