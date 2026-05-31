import "./src/js/components/index.js";
import mainContentHtml from "./src/partials/main-content.html";
import dialogsHtml from "./src/partials/dialogs.html";
import { initializeApp } from "./src/js/main.js";

document.body.innerHTML = `${mainContentHtml}${dialogsHtml}`;
await new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
initializeApp();
