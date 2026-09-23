import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { UniverseProvider } from "./lib/useUniverse";
import { WalletProvider } from "./lib/useWallet";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <WalletProvider>
        <UniverseProvider>
          <App />
        </UniverseProvider>
      </WalletProvider>
    </BrowserRouter>
  </React.StrictMode>
);
