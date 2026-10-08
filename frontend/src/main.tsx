import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/nunito-sans";
// Approved prototype styles, copied verbatim (except the hero scene selector),
// followed by world art and the React app additions.
import "./styles/styles.css";
import "./styles/worlds.css";
import "./styles/catalog.css";
import "./world-art/world-art.css";
import "./styles/app.css";
import { App } from "./app/App";
import { applyTheme } from "./app/theme";

applyTheme();
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
