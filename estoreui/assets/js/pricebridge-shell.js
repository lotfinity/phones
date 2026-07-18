(() => {
  "use strict";

  if (window.PriceBridgeShell?.initialized) return;

  const LOCAL_DJANGO_API_URL = "http://127.0.0.1:8000/estore/api/opportunities/";
  const API_KEY = "pricebridge-api-base";
  const FX_API_PATH = "/estore/api/fx/";
  const FX_REFRESH_API_PATH = "/estore/api/fx/refresh/";
  const PROJECT_FRONTEND_URL = "/";
  const CAPTURED_ORIGIN = "https://bagisto-headless-electronic.vercel.app";

  let lastFxPayload = null;
  let refreshingFx = false;

  function loadingFxPayload() {
    return {
      ok: true,
      latest_observed: "",
      pairs: [
        {label: "€1", quote: "TRY", display: "...", pair: "EUR/TRY", source: "loading"},
        {label: "$1", quote: "TRY", display: "...", pair: "USD/TRY", source: "loading"},
        {label: "€1", quote: "DZD", display: "...", pair: "EUR/DZD", source: "loading"},
      ],
    };
  }

  function apiBase() {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = params.get("api");
    if (fromUrl) {
      localStorage.setItem(API_KEY, fromUrl);
      return fromUrl;
    }
    const stored = localStorage.getItem(API_KEY);
    if (window.location.protocol === "file:") {
      return stored && /^https?:\/\//i.test(stored) ? stored : LOCAL_DJANGO_API_URL;
    }
    return stored || "/estore/api/opportunities/";
  }

  function siblingApiUrl(path) {
    try {
      const url = new URL(apiBase());
      url.pathname = path;
      url.search = "";
      return url.toString();
    } catch {
      return path;
    }
  }

  async function fetchJson(url, options = {}, timeoutMs = 8000) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url, {...options, signal: controller.signal});
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      return response.json();
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function projectHrefForCapturedUrl(url) {
    try {
      const parsed = new URL(url);
      if (parsed.origin !== CAPTURED_ORIGIN) return "";
      if (parsed.pathname === "/" || parsed.pathname === "/search") return PROJECT_FRONTEND_URL;
      if (parsed.pathname === "/smartphones") return `${PROJECT_FRONTEND_URL}?category=phone`;
      if (parsed.pathname.startsWith("/product/")) return PROJECT_FRONTEND_URL;
      return "#";
    } catch {
      return "";
    }
  }

  function sanitizeCapturedHrefs(root = document) {
    root.querySelectorAll(`a[href^="${CAPTURED_ORIGIN}"]`).forEach((link) => {
      const replacement = projectHrefForCapturedUrl(link.href);
      if (!replacement) return;
      link.dataset.pbOriginalHref = link.href;
      link.href = replacement;
      if (replacement === "#" && link.dataset.pbNeutralized !== "true") {
        link.dataset.pbNeutralized = "true";
        link.addEventListener("click", (event) => event.preventDefault());
      }
    });
  }

  function closeIcon() {
    return `
      <svg class="w-5 h-5 text-neutral-600 dark:text-neutral-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
      </svg>
    `;
  }

  function refreshIcon() {
    return `
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v6h6M20 20v-6h-6M5 19A9 9 0 0119 5M19 5h-5M5 19h5"></path>
      </svg>
    `;
  }

  function fxIcon() {
    return `
      <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6v12m3-9.5C14.5 7.6 13.5 7 12 7c-2 0-3 .9-3 2.2 0 3.4 6 1.4 6 5.1 0 1.5-1.2 2.7-3.2 2.7-1.6 0-2.8-.7-3.4-1.7"></path>
      </svg>
    `;
  }

  function pairValue(pair) {
    if (pair.display === "...") return "...";
    if (pair.quote === "TRY") return `₺${pair.display}`;
    if (pair.quote === "USD") return `$${pair.display}`;
    if (pair.quote === "DZD") return `${pair.display} DZD`;
    return `${pair.display} ${pair.quote}`;
  }

  function fxUpdatedText(payload) {
    if (!payload?.latest_observed) return "Using fallback FX settings";
    try {
      return `Updated ${new Date(payload.latest_observed).toLocaleString()}`;
    } catch {
      return `Updated ${payload.latest_observed}`;
    }
  }

  function desktopFxNav() {
    return [...document.querySelectorAll("header ul")].find((node) => {
      const className = String(node.className || "");
      return className.includes("md:flex") && /All|Smartphones|Headphones|Entertainment|Appliances/.test(node.textContent);
    });
  }

  function mobileBottomNav() {
    const shell = [...document.querySelectorAll("div")].find((node) => {
      const className = String(node.className || "");
      return className.includes("fixed") && className.includes("bottom-0") && className.includes("lg:hidden");
    });
    if (shell) {
      shell.dataset.pbMobileBottomNav = "1";
      if (shell.parentElement !== document.body) document.body.appendChild(shell);
    }
    return shell;
  }

  function mobileCategoriesButton() {
    const shell = mobileBottomNav();
    if (!shell) return null;
    return [...shell.querySelectorAll("button, a")].find((node) => {
      return node.textContent.replace(/\s+/g, " ").trim() === "Categories";
    });
  }

  function ensureFxDrawer() {
    if (document.querySelector("[data-pb-fx-drawer]")) return;
    const container = document.createElement("div");
    container.dataset.pbShellFx = "true";
    container.innerHTML = `
      <p class="hidden fixed bottom-4 left-1/2 z-[80] max-w-xl -translate-x-1/2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow-lg dark:border-amber-900/60 dark:bg-amber-950 dark:text-amber-100" data-pb-shell-status></p>
      <div class="fixed inset-0 bg-black/50 z-[65] transition-opacity duration-300 ease-in-out cursor-pointer opacity-0 pointer-events-none" data-pb-fx-overlay></div>
      <aside class="fixed top-0 right-0 h-full w-full max-w-md bg-white dark:bg-neutral-900 z-[70] shadow-2xl transform transition-transform duration-300 ease-in-out flex flex-col translate-x-full" data-pb-fx-drawer aria-label="Currency exchange" aria-hidden="true">
        <div class="flex items-center justify-between px-6 py-4 border-b border-neutral-200 dark:border-neutral-700">
          <div>
            <h2 class="text-xl font-semibold text-neutral-900 dark:text-white">Currency Exchange</h2>
            <p class="mt-1 text-xs text-neutral-500 dark:text-neutral-400" data-pb-fx-meta>Loading rates</p>
          </div>
          <button class="p-2 rounded-full cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors" type="button" data-pb-close-fx aria-label="Close currency exchange">${closeIcon()}</button>
        </div>
        <div class="flex-1 overflow-y-auto px-6 py-6">
          <div class="space-y-3" data-pb-fx-list></div>
        </div>
        <div class="px-6 py-4 border-t border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
          <button class="w-full px-4 py-3 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 rounded-xl font-medium hover:bg-neutral-800 dark:hover:bg-neutral-100 transition-colors inline-flex items-center justify-center gap-2 cursor-pointer" type="button" data-pb-fx-refresh>${refreshIcon()}<span>Refresh</span></button>
        </div>
      </aside>
    `;
    document.body.appendChild(container);
    container.querySelector("[data-pb-close-fx]")?.addEventListener("click", closeFxDrawer);
    container.querySelector("[data-pb-fx-overlay]")?.addEventListener("click", closeFxDrawer);
    container.querySelector("[data-pb-fx-refresh]")?.addEventListener("click", refreshFx);
  }

  function setStatus(message) {
    const node = document.querySelector("[data-pb-shell-status]");
    if (!node) return;
    node.textContent = message || "";
    node.hidden = !message;
    node.classList.toggle("hidden", !message);
  }

  function renderDesktopFx(payload) {
    const nav = desktopFxNav();
    if (!nav) return;
    nav.dataset.pbFxStrip = "true";
    nav.className = "hidden gap-2 text-sm md:flex items-center";
    nav.innerHTML = `
      ${(payload.pairs || []).map((pair) => `
        <li class="relative">
          <span class="inline-flex items-center gap-1.5 rounded-full border border-neutral-700 bg-neutral-900/70 px-3 py-2 text-neutral-200" title="${pair.pair} · ${pair.source || ""}">
            <span class="text-neutral-400">${pair.label}</span>
            <strong class="font-semibold text-white">${pairValue(pair)}</strong>
          </span>
        </li>
      `).join("")}
      <li class="relative">
        <button class="inline-flex items-center gap-1.5 rounded-full border border-neutral-700 bg-neutral-900/70 px-3 py-2 font-medium text-neutral-200 transition-colors hover:bg-white/10" type="button" data-pb-fx-refresh>
          ${refreshIcon()}
          <span>Refresh</span>
        </button>
      </li>
    `;
    nav.querySelector("[data-pb-fx-refresh]")?.addEventListener("click", refreshFx);
  }

  function renderMobileFxButton(payload) {
    const button = mobileCategoriesButton() || document.querySelector("[data-pb-open-fx-drawer]");
    if (!button) return;
    const firstPair = (payload.pairs || [])[0] || {quote: "TRY", display: "..."};
    button.dataset.pbOpenFxDrawer = "true";
    button.setAttribute("aria-label", "Open currency exchange");
    if (button.tagName === "A") button.removeAttribute("href");
    button.innerHTML = `
      <div class="flex items-center justify-center rounded-full transition-all duration-300 px-6 py-1 bg-transparent text-neutral-900 dark:text-neutral-400">
        ${fxIcon()}
      </div>
      <span>FX</span>
    `;
    button.title = `Currency Exchange · ${pairValue(firstPair)} · ${fxUpdatedText(payload)}`;
    if (button.dataset.pbFxBound !== "true") {
      button.dataset.pbFxBound = "true";
      const openFromEvent = (event) => {
        event.preventDefault();
        event.stopImmediatePropagation();
        openFxDrawer();
      };
      button.addEventListener("click", openFromEvent, true);
      button.addEventListener("pointerup", openFromEvent, true);
    }
  }

  function renderFxDrawer(payload) {
    const list = document.querySelector("[data-pb-fx-list]");
    const meta = document.querySelector("[data-pb-fx-meta]");
    if (!list) return;
    list.innerHTML = (payload.pairs || []).map((pair) => `
      <div class="flex items-center justify-between gap-4 rounded-xl border border-neutral-200 bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-950">
        <div>
          <p class="text-sm font-semibold text-neutral-900 dark:text-white">${pair.label} → ${pair.quote}</p>
          <p class="text-xs text-neutral-500 dark:text-neutral-400">${pair.pair} · ${pair.source || "settings"}</p>
        </div>
        <strong class="text-base font-bold text-neutral-900 dark:text-white">${pairValue(pair)}</strong>
      </div>
    `).join("");
    if (meta) meta.textContent = fxUpdatedText(payload);
  }

  function renderFx(payload) {
    lastFxPayload = payload;
    ensureFxDrawer();
    renderDesktopFx(payload);
    renderMobileFxButton(payload);
    renderFxDrawer(payload);
  }

  async function loadFx() {
    try {
      const payload = await fetchJson(siblingApiUrl(FX_API_PATH), {
        credentials: "include",
        headers: {"Accept": "application/json"},
      });
      if (!payload.ok) throw new Error(payload.error || "FX API returned an error");
      renderFx(payload);
    } catch (error) {
      setStatus(`Could not load FX rates. ${error.message}`);
    }
  }

  async function refreshFx() {
    if (refreshingFx) return;
    refreshingFx = true;
    setStatus("Refreshing exchange rates and opportunity snapshots...");
    try {
      const payload = await fetchJson(siblingApiUrl(FX_REFRESH_API_PATH), {
        method: "POST",
        credentials: "include",
        headers: {"Accept": "application/json"},
      }, 30000);
      if (!payload.ok) throw new Error(payload.error || "FX refresh returned an error");
      renderFx(payload);
      setStatus("");
      window.dispatchEvent(new CustomEvent("pricebridge:fx-refreshed", {detail: payload}));
    } catch (error) {
      setStatus(`Could not refresh FX rates. ${error.message}`);
    } finally {
      refreshingFx = false;
    }
  }

  function openFxDrawer() {
    ensureFxDrawer();
    const overlay = document.querySelector("[data-pb-fx-overlay]");
    const drawer = document.querySelector("[data-pb-fx-drawer]");
    overlay?.classList.remove("opacity-0", "pointer-events-none");
    overlay?.classList.add("opacity-100");
    drawer?.classList.remove("translate-x-full");
    drawer?.classList.add("translate-x-0");
    drawer?.setAttribute("aria-hidden", "false");
    if (lastFxPayload) renderFxDrawer(lastFxPayload);
  }

  function closeFxDrawer() {
    const overlay = document.querySelector("[data-pb-fx-overlay]");
    const drawer = document.querySelector("[data-pb-fx-drawer]");
    overlay?.classList.add("opacity-0", "pointer-events-none");
    overlay?.classList.remove("opacity-100");
    drawer?.classList.add("translate-x-full");
    drawer?.classList.remove("translate-x-0");
    drawer?.setAttribute("aria-hidden", "true");
  }

  function init() {
    mobileBottomNav();
    ensureFxDrawer();
    sanitizeCapturedHrefs();
    renderFx(loadingFxPayload());
    loadFx();
  }

  window.PriceBridgeShell = {
    initialized: true,
    apiBase,
    sanitizeCapturedHrefs,
    loadFx,
    refreshFx,
    openFxDrawer,
    closeFxDrawer,
  };

  init();
})();
