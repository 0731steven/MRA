import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import "github-markdown-css/github-markdown-light.css";
import "highlight.js/styles/github.css";
import "katex/dist/katex.min.css";
import "./markdown-table.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
