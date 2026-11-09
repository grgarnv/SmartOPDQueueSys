import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import { SessionProvider } from "./auth/session";
import "./design/base.css";
import { AppRoutes } from "./routes";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "")}>
      <SessionProvider>
        <AppRoutes />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
);
