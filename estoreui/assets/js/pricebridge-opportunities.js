(() => {
  "use strict";

  const SAME_ORIGIN_API_PATH = "/estore/api/opportunities/";
  const LOCAL_DJANGO_API_URL = "http://127.0.0.1:8000/estore/api/opportunities/";
  const API_KEY = "pricebridge-api-base";
  const FX_API_PATH = "/estore/api/fx/";
  const FX_REFRESH_API_PATH = "/estore/api/fx/refresh/";
  const PROJECT_FRONTEND_URL = "/";
  const CAPTURED_ORIGIN = "https://bagisto-headless-electronic.vercel.app";

  const prototypeGrid = document.querySelector("[data-pb-grid]");
  const prototypeForm = document.querySelector("[data-pb-filters]");
  const prototypeTemplate = document.querySelector("[data-pb-card-template]");
  const prototypeStatus = document.querySelector("[data-pb-status]");
  const prototypeTotal = document.querySelector("[data-pb-total]");
  const prototypeLoadMore = document.querySelector("[data-pb-load-more]");

  const capturedCards = [...document.querySelectorAll("main li.transition-opacity.animate-fadeIn.flex.flex-col")];
  const capturedGrid = capturedCards[0]?.parentElement || null;
  const capturedTemplate = capturedCards[0]?.cloneNode(true) || null;

  if ((!prototypeGrid || !prototypeForm || !prototypeTemplate) && !capturedGrid) return;

  let offset = 0;
  let limit = 24;
  let lastQuery = "";
  let loading = false;
  const initialParams = new URLSearchParams(window.location.search);
  let activeCategory = initialParams.get("category") || "";
  let activeBrand = initialParams.get("brand") || "";
  let activeQuery = initialParams.get("q") || "";
  let activeCurrency = initialParams.get("currency") || "TRY";
  let pendingCategory = activeCategory;
  let pendingBrand = activeBrand;
  let lastFxPayload = null;
  let refreshingFx = false;

  function isCapturedMode() {
    return Boolean(capturedGrid && !prototypeGrid);
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
    return stored || SAME_ORIGIN_API_PATH;
  }

  function activeForm() {
    return prototypeForm;
  }

  function capturedSearchInput() {
    return document.querySelector('[aria-label="Search drawer"] input[type="text"]');
  }

  function mobileSearchInput() {
    return document.querySelector('input[name="search"][placeholder*="Search"]');
  }

  function syncCapturedSearchState(input = capturedSearchInput()) {
    if (!input || !isCapturedMode()) return;
    activeQuery = String(input.value || "").trim();
  }

  function statusNode() {
    return prototypeStatus || document.querySelector("[data-pb-captured-status]");
  }

  function setStatus(message) {
    const node = statusNode();
    if (!node) return;
    if (!message) {
      node.hidden = true;
      node.classList.add("hidden");
      node.textContent = "";
      return;
    }
    node.hidden = false;
    node.classList.remove("hidden");
    node.textContent = message;
  }

  function queryString() {
    if (isCapturedMode()) {
      const params = new URLSearchParams();
      if (activeCategory) params.set("category", activeCategory);
      if (activeBrand) params.set("brand", activeBrand);
      if (activeQuery) params.set("q", activeQuery);
      if (activeCurrency) params.set("currency", activeCurrency);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      return params.toString();
    }

    const form = activeForm();
    const data = form ? new FormData(form) : new FormData();
    const params = new URLSearchParams();
    for (const [key, value] of data.entries()) {
      const text = String(value || "").trim();
      if (text) params.set(key, text);
    }
    params.set("limit", String(limit));
    params.set("offset", String(offset));
    return params.toString();
  }

  function endpoint() {
    const base = apiBase();
    return `${base}${base.includes("?") ? "&" : "?"}${queryString()}`;
  }

  function siblingApiUrl(path) {
    const base = apiBase();
    try {
      const url = new URL(base);
      url.pathname = path;
      url.search = "";
      return url.toString();
    } catch {
      return path;
    }
  }

  function fxEndpoint() {
    return siblingApiUrl(FX_API_PATH);
  }

  function fxRefreshEndpoint() {
    return siblingApiUrl(FX_REFRESH_API_PATH);
  }

  function absoluteUrl(url) {
    if (!url) return "";
    try {
      return new URL(url, apiBase()).toString();
    } catch {
      return url;
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
    if (!isCapturedMode()) return;
    root.querySelectorAll(`a[href^="${CAPTURED_ORIGIN}"]`).forEach((link) => {
      const replacement = projectHrefForCapturedUrl(link.href);
      if (!replacement) return;
      link.dataset.pbOriginalHref = link.href;
      link.href = replacement;
      if (replacement === "#") {
        link.addEventListener("click", (event) => event.preventDefault(), {once: true});
      }
    });
  }

  function badgeClass(value) {
    if (value === "buy" || value === "good_opportunity") {
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-100";
    }
    if (value === "watch" || value === "marginal") {
      return "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-100";
    }
    return "bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200";
  }

  function fallbackImage(card, square = false) {
    const initials = encodeURIComponent(card.initials || "PB");
    const viewBox = square ? "0 0 800 800" : "0 0 800 600";
    return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='${viewBox}'%3E%3Crect width='800' height='800' fill='%23f4f4f5'/%3E%3Ctext x='50%25' y='48%25' dominant-baseline='middle' text-anchor='middle' font-family='Arial' font-size='112' font-weight='700' fill='%2318181b'%3E${initials}%3C/text%3E%3Ctext x='50%25' y='61%25' dominant-baseline='middle' text-anchor='middle' font-family='Arial' font-size='34' fill='%2371717a'%3EPriceBridge%3C/text%3E%3C/svg%3E`;
  }

  function text(root, selector, value) {
    const node = root.querySelector(selector);
    if (node) node.textContent = value || "";
  }

  function capturedHeaderSection() {
    const heading = [...document.querySelectorAll("main h2")].find((node) => {
      const label = node.textContent.trim();
      return label === "Smartphones" || label === "PriceBridge Opportunities";
    });
    let node = heading;
    while (node && node !== document.body) {
      const className = String(node.className || "");
      if (className.includes("max-w-screen-2xl") && className.includes("py-6")) return node;
      node = node.parentElement;
    }
    return null;
  }

  function capturedToolbarFilterButton() {
    const section = capturedHeaderSection();
    if (!section) return null;
    return [...section.querySelectorAll("button")].find((button) => {
      return button.textContent.replace(/\s+/g, " ").trim() === "Filters";
    });
  }

  function capturedCountNode() {
    const section = capturedHeaderSection();
    const heading = section?.querySelector("h2");
    return heading?.parentElement?.querySelector("p") || null;
  }

  function desktopFxNav() {
    return [...document.querySelectorAll("header ul")].find((node) => {
      const className = String(node.className || "");
      return className.includes("md:flex") && node.textContent.includes("Smartphones");
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

  function closeIcon() {
    return `
      <svg class="w-5 h-5 text-neutral-600 dark:text-neutral-300" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
      </svg>
    `;
  }

  function caretIcon() {
    return `
      <svg class="w-4 h-4 text-neutral-500 transition-transform duration-200 rotate-180" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path>
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

  function renderDesktopFx(payload) {
    const nav = desktopFxNav();
    if (!nav) return;
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
    const shell = mobileBottomNav();
    if (shell && shell.dataset.pbFxDelegated !== "true") {
      shell.dataset.pbFxDelegated = "true";
      const openDelegated = (event) => {
        const target = event.target.closest("[data-pb-open-fx-drawer]");
        if (!target) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        openFxDrawer();
      };
      shell.addEventListener("click", openDelegated, true);
      shell.addEventListener("pointerup", openDelegated, true);
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
    renderDesktopFx(payload);
    renderMobileFxButton(payload);
    renderFxDrawer(payload);
  }

  async function loadFx() {
    try {
      const response = await fetch(fxEndpoint(), {
        credentials: "include",
        headers: {"Accept": "application/json"},
      });
      if (!response.ok) throw new Error(`FX API returned ${response.status}`);
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || "FX API returned an error");
      renderFx(payload);
    } catch (error) {
      setStatus(`Could not load FX rates from ${fxEndpoint()}. ${error.message}`);
    }
  }

  async function refreshFx() {
    if (refreshingFx) return;
    refreshingFx = true;
    setFxRefreshing(true);
    setStatus("Refreshing exchange rates and opportunity snapshots...");
    try {
      const response = await fetch(fxRefreshEndpoint(), {
        method: "POST",
        credentials: "include",
        headers: {"Accept": "application/json"},
      });
      if (!response.ok) throw new Error(`FX refresh returned ${response.status}`);
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || "FX refresh returned an error");
      renderFx(payload);
      offset = 0;
      await load();
      setStatus("");
    } catch (error) {
      setStatus(`Could not refresh FX rates. ${error.message}`);
    } finally {
      refreshingFx = false;
      setFxRefreshing(false);
    }
  }

  function setFxRefreshing(value) {
    document.querySelectorAll("[data-pb-fx-refresh]").forEach((button) => {
      button.disabled = value;
      button.classList.toggle("opacity-60", value);
      const label = button.querySelector("span");
      if (label) label.textContent = value ? "Refreshing" : "Refresh";
    });
  }

  function openFxDrawer() {
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

  function ensureCapturedControls() {
    if (!capturedGrid || document.querySelector("[data-pb-captured-controls]")) return;

    const controls = document.createElement("div");
    controls.dataset.pbCapturedControls = "true";
    controls.innerHTML = `
      <p class="hidden fixed bottom-4 left-1/2 z-[80] max-w-xl -translate-x-1/2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 shadow-lg dark:border-amber-900/60 dark:bg-amber-950 dark:text-amber-100" data-pb-captured-status></p>
      <div class="fixed inset-0 bg-black/50 z-[65] transition-opacity duration-300 ease-in-out cursor-pointer opacity-0 pointer-events-none" data-pb-filter-overlay></div>
      <aside class="fixed top-0 right-0 h-full w-full max-w-md bg-white dark:bg-neutral-900 z-[70] shadow-2xl transform transition-transform duration-300 ease-in-out flex flex-col translate-x-full" data-pb-filter-drawer aria-label="Filters" aria-hidden="true">
        <div class="flex items-center justify-between px-6 py-4 border-b border-neutral-200 dark:border-neutral-700">
          <h2 class="text-xl font-semibold text-neutral-900 dark:text-white">Filters</h2>
          <button class="p-2 rounded-full cursor-pointer hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors" type="button" data-pb-close-filters aria-label="Close filters">${closeIcon()}</button>
        </div>
        <div class="flex-1 overflow-y-auto px-6 py-6">
          <div class="mb-6 border-b border-neutral-100 dark:border-neutral-800 pb-6 last:border-0">
            <button class="flex items-center justify-between w-full mb-3 cursor-pointer" type="button">
              <h3 class="text-sm font-semibold text-neutral-900 dark:text-white uppercase tracking-wide">CATEGORY</h3>
              ${caretIcon()}
            </button>
            <div class="space-y-2" data-pb-category-strip aria-label="Category filters"></div>
          </div>
          <div class="mb-6 border-b border-neutral-100 dark:border-neutral-800 pb-6 last:border-0">
            <button class="flex items-center justify-between w-full mb-3 cursor-pointer" type="button">
              <h3 class="text-sm font-semibold text-neutral-900 dark:text-white uppercase tracking-wide">BRAND</h3>
              ${caretIcon()}
            </button>
            <div class="mb-4">
              <input placeholder="Search brands..." class="w-full px-3 py-2 text-sm border border-neutral-200 dark:border-neutral-700 rounded-lg bg-white dark:bg-neutral-800 text-neutral-900 dark:text-white focus:outline-none focus:ring-2 focus:ring-neutral-900 dark:focus:ring-neutral-500" type="text" data-pb-brand-search>
            </div>
            <div class="max-h-64 overflow-y-auto space-y-2" data-pb-brand-strip aria-label="Brand filters"></div>
          </div>
        </div>
        <div class="px-6 py-4 border-t border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50">
          <div class="flex gap-3">
            <button class="flex-1 px-4 cursor-pointer py-3 border border-neutral-200 dark:border-neutral-700 rounded-xl text-neutral-700 dark:text-neutral-300 font-medium hover:bg-neutral-100 dark:hover:bg-neutral-700 transition-colors" type="button" data-pb-cancel-filters>Cancel</button>
            <button class="flex-1 px-4 py-3 bg-neutral-900 dark:bg-white text-white dark:text-neutral-900 rounded-xl font-medium hover:bg-neutral-800 dark:hover:bg-neutral-100 transition-colors inline-flex items-center justify-center gap-2 cursor-pointer" type="button" data-pb-apply-filters>Apply Filters</button>
          </div>
        </div>
      </aside>
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
    document.body.appendChild(controls);
    bindFilterDrawer(controls);
    bindFxDrawer(controls);
    bindCapturedToolbar();
    bindCapturedSearch();
  }

  function updateCapturedHeadings(data) {
    const title = "PriceBridge Opportunities";
    document.title = title;
    const h2 = [...document.querySelectorAll("main h2")].find((node) => node.textContent.trim() === "Smartphones");
    if (h2) h2.textContent = title;
    const total = capturedCountNode();
    if (total) total.textContent = `${data.pagination?.total || 0} clean opportunities`;
  }

  function openFilterDrawer() {
    pendingCategory = activeCategory;
    pendingBrand = activeBrand;
    const overlay = document.querySelector("[data-pb-filter-overlay]");
    const drawer = document.querySelector("[data-pb-filter-drawer]");
    overlay?.classList.remove("opacity-0", "pointer-events-none");
    overlay?.classList.add("opacity-100");
    drawer?.classList.remove("translate-x-full");
    drawer?.classList.add("translate-x-0");
    drawer?.setAttribute("aria-hidden", "false");
    updatePendingFilterChecks();
  }

  function closeFilterDrawer() {
    const overlay = document.querySelector("[data-pb-filter-overlay]");
    const drawer = document.querySelector("[data-pb-filter-drawer]");
    overlay?.classList.add("opacity-0", "pointer-events-none");
    overlay?.classList.remove("opacity-100");
    drawer?.classList.add("translate-x-full");
    drawer?.classList.remove("translate-x-0");
    drawer?.setAttribute("aria-hidden", "true");
  }

  function bindFilterDrawer(root) {
    root.querySelector("[data-pb-close-filters]")?.addEventListener("click", closeFilterDrawer);
    root.querySelector("[data-pb-filter-overlay]")?.addEventListener("click", closeFilterDrawer);
    root.querySelector("[data-pb-cancel-filters]")?.addEventListener("click", () => {
      pendingCategory = activeCategory;
      pendingBrand = activeBrand;
      updatePendingFilterChecks();
      closeFilterDrawer();
    });
    root.querySelector("[data-pb-apply-filters]")?.addEventListener("click", () => {
      syncCapturedSearchState();
      activeCategory = pendingCategory;
      activeBrand = pendingBrand;
      offset = 0;
      closeFilterDrawer();
      load();
    });
    root.querySelector("[data-pb-brand-search]")?.addEventListener("input", (event) => {
      const needle = String(event.currentTarget.value || "").trim().toLowerCase();
      document.querySelectorAll("[data-pb-brand-option]").forEach((option) => {
        const label = String(option.dataset.label || "").toLowerCase();
        option.hidden = Boolean(needle) && !label.includes(needle);
      });
    });
  }

  function bindFxDrawer(root) {
    root.querySelector("[data-pb-close-fx]")?.addEventListener("click", closeFxDrawer);
    root.querySelector("[data-pb-fx-overlay]")?.addEventListener("click", closeFxDrawer);
    root.querySelector("[data-pb-fx-refresh]")?.addEventListener("click", refreshFx);
  }

  function bindCapturedToolbar() {
    const button = capturedToolbarFilterButton();
    if (!button || button.dataset.pbOpenFilters === "true") return;
    button.dataset.pbOpenFilters = "true";
    button.type = "button";
    button.addEventListener("click", (event) => {
      event.preventDefault();
      openFilterDrawer();
    });
  }

  function bindCapturedSearch() {
    const drawerInput = capturedSearchInput();
    const drawerButton = drawerInput?.parentElement?.querySelector('button[aria-label="Search"]');
    const mobileInput = mobileSearchInput();

    if (drawerInput && drawerInput.dataset.pbSearchBound !== "true") {
      drawerInput.dataset.pbSearchBound = "true";
      drawerInput.value = activeQuery;
      drawerInput.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        syncCapturedSearchState(drawerInput);
        offset = 0;
        load();
      });
    }

    if (drawerButton && drawerButton.dataset.pbSearchBound !== "true") {
      drawerButton.dataset.pbSearchBound = "true";
      drawerButton.addEventListener("click", (event) => {
        event.preventDefault();
        syncCapturedSearchState(drawerInput);
        offset = 0;
        load();
      });
    }

    if (mobileInput && mobileInput.dataset.pbSearchBound !== "true") {
      mobileInput.dataset.pbSearchBound = "true";
      mobileInput.value = activeQuery;
      mobileInput.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") return;
        event.preventDefault();
        activeQuery = String(mobileInput.value || "").trim();
        const drawer = capturedSearchInput();
        if (drawer) drawer.value = activeQuery;
        offset = 0;
        load();
      });
    }
  }

  function updatePendingFilterChecks() {
    document.querySelectorAll("[data-pb-filter-target='category']").forEach((input) => {
      input.checked = (input.dataset.value || "") === pendingCategory;
    });
    document.querySelectorAll("[data-pb-filter-target='brand']").forEach((input) => {
      input.checked = (input.dataset.value || "") === pendingBrand;
    });
  }

  function renderFilterOption({value, label, count, active, logo, target}) {
    const wrapper = document.createElement("label");
    wrapper.className = "flex items-center gap-3 cursor-pointer group";
    if (target === "brand") {
      wrapper.dataset.pbBrandOption = "true";
      wrapper.dataset.label = label || "";
    }

    const input = document.createElement("input");
    input.className = "w-4 h-4 cursor-pointer rounded border-neutral-300 text-neutral-900 focus:ring-neutral-900 dark:border-neutral-600 dark:focus:ring-neutral-500";
    input.type = "radio";
    input.name = `pb-${target}`;
    input.dataset.pbFilterTarget = target;
    input.dataset.value = value || "";
    input.checked = Boolean(active);
    wrapper.appendChild(input);

    if (logo) {
      const img = document.createElement("img");
      img.src = absoluteUrl(logo);
      img.alt = "";
      img.className = "h-5 w-5 rounded-full object-contain";
      wrapper.appendChild(img);
    }

    const span = document.createElement("span");
    span.className = "text-sm text-neutral-600 dark:text-neutral-400 group-hover:text-neutral-900 dark:group-hover:text-white transition-colors";
    span.textContent = label || "All";
    wrapper.appendChild(span);

    const strong = document.createElement("strong");
    strong.className = "ml-auto rounded-full bg-neutral-100 px-2 py-0.5 text-xs font-semibold text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300";
    strong.textContent = String(count ?? 0);
    wrapper.appendChild(strong);

    input.addEventListener("change", () => {
      if (target === "category") {
        pendingCategory = input.dataset.value || "";
        pendingBrand = "";
      } else {
        pendingBrand = input.dataset.value || "";
      }
      updatePendingFilterChecks();
    });

    return wrapper;
  }

  function renderCapturedFilters(data) {
    const categoryStrip = document.querySelector("[data-pb-category-strip]");
    const brandStrip = document.querySelector("[data-pb-brand-strip]");
    if (!categoryStrip || !brandStrip) return;

    const totalCount = Object.values(data.counts || {}).reduce((sum, value) => sum + Number(value || 0), 0);
    const categoryOptions = [
      {value: "", label: "Tümü", count: totalCount, active: !activeCategory},
      ...(data.category_options || []).map((option) => ({
        value: option.value || "",
        label: option.label || option.value || "Category",
        count: option.count || 0,
        active: activeCategory === (option.value || ""),
      })),
    ];

    categoryStrip.textContent = "";
    categoryOptions.forEach((option) => categoryStrip.appendChild(renderFilterOption({...option, target: "category"})));

    const brandOptions = data.brand_options || [];
    brandStrip.textContent = "";
    brandOptions.forEach((option) => {
      brandStrip.appendChild(renderFilterOption({
        value: option.value || "",
        label: option.name || "Tümü",
        count: option.count || 0,
        active: Boolean(option.active),
        logo: option.logo || "",
        target: "brand",
      }));
    });
    updatePendingFilterChecks();
    updateActiveFilterSummary(data);
  }

  function updateActiveFilterSummary(data) {
    const total = capturedCountNode();
    if (!total) return;
    const category = (data.category_options || []).find((option) => option.value === activeCategory);
    const parts = [];
    if (category) parts.push(`Category: ${category.label}`);
    if (activeBrand) parts.push(`Brand: ${activeBrand}`);
    if (activeQuery) parts.push(`Search: ${activeQuery}`);
    const count = data.pagination?.total || 0;
    total.textContent = parts.length ? `${count} clean opportunities / ${parts.join(" / ")}` : `${count} clean opportunities`;
  }

  function recommendationLabel(card) {
    const gain = card.buyer_gain_percent ? ` · ${card.buyer_gain_percent}` : "";
    return `${card.recommendation || "Opportunity"}${gain}`;
  }

  function cardDetailUrl(card) {
    return absoluteUrl(card.frontend_detail_url || card.detail_url || card.api_url || "#");
  }

  function updateCapturedCard(node, card) {
    const title = card.title || "";
    const detailUrl = cardDetailUrl(card);
    const image = node.querySelector("img");
    if (image) {
      image.src = card.image_url ? absoluteUrl(card.image_url) : fallbackImage(card, true);
      image.srcset = "";
      image.alt = title;
      image.loading = "lazy";
      image.removeAttribute("data-nimg");
    }

    node.querySelectorAll("a[href]").forEach((link) => {
      link.href = detailUrl;
      link.setAttribute("aria-label", `View ${title}`);
    });

    text(node, "h3", title);
    const ratingCount = [...node.querySelectorAll("span")].find((item) => /^\(\d+\)$/.test(item.textContent.trim()));
    if (ratingCount) ratingCount.textContent = `${card.confidence_score || 0}% confidence`;

    const priceContainer = [...node.querySelectorAll("div")].find((item) => {
      const compact = item.className || "";
      const copy = item.textContent.replace(/\s+/g, " ").trim();
      return compact.includes("mt-1.5") && /\$|TRY|EUR|USD|DZD|Starting at/.test(copy);
    });
    if (priceContainer) {
      priceContainer.innerHTML = `
        <div class="min-w-0">
          <p class="text-base font-bold text-neutral-900 dark:text-white">${card.buyer_offer || ""}</p>
          <p class="text-xs text-neutral-500 dark:text-neutral-400">Türkiye avg ${card.turkiye_avg || "-"}</p>
        </div>
        <span class="ml-auto rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-200">${card.buyer_gain || ""}</span>
      `;
    }

    const imageShell = node.querySelector(".group.relative");
    if (imageShell) {
      let badge = imageShell.querySelector("[data-pb-rec-badge]");
      if (!badge) {
        badge = document.createElement("div");
        badge.dataset.pbRecBadge = "true";
        imageShell.appendChild(badge);
      }
      badge.className = `absolute right-3 top-3 rounded-full px-3 py-1 text-xs font-semibold shadow-sm ${badgeClass(card.recommendation_value)}`;
      badge.textContent = recommendationLabel(card);
    }

    node.querySelectorAll("span").forEach((span) => {
      if (span.textContent.trim() === "Add to Cart") span.textContent = "View Opportunity";
    });
  }

  function renderCaptured(data, append = false) {
    if (!capturedGrid || !capturedTemplate) return;
    if (!append) capturedGrid.textContent = "";
    for (const card of data.cards || []) {
      const node = capturedTemplate.cloneNode(true);
      updateCapturedCard(node, card);
      capturedGrid.appendChild(node);
    }
    sanitizeCapturedHrefs(capturedGrid);
    updateCapturedHeadings(data);
    renderCapturedFilters(data);
  }

  function renderPrototypeCard(card) {
    const fragment = prototypeTemplate.content.cloneNode(true);
    const link = fragment.querySelector("[data-pb-detail-link]");
    const image = fragment.querySelector("[data-pb-image]");
    const rec = fragment.querySelector("[data-pb-rec]");
    if (link) link.href = cardDetailUrl(card);
    if (image) {
      image.src = card.image_url ? absoluteUrl(card.image_url) : fallbackImage(card);
      image.alt = card.title || "Opportunity image";
      image.loading = "lazy";
    }
    if (rec) {
      rec.textContent = card.recommendation || "";
      rec.className = `absolute right-3 top-3 rounded-full px-3 py-1 text-xs font-semibold shadow-sm ${badgeClass(card.recommendation_value)}`;
    }
    text(fragment, "[data-pb-category]", card.category_label || card.category || "");
    text(fragment, "[data-pb-brand]", card.brand || "");
    text(fragment, "[data-pb-title]", card.title || "");
    text(fragment, "[data-pb-offer]", card.buyer_offer || "");
    text(fragment, "[data-pb-turkiye]", card.turkiye_avg || "");
    text(fragment, "[data-pb-gain]", card.buyer_gain || "");
    return fragment;
  }

  function render(data, append = false) {
    if (capturedGrid && !prototypeGrid) {
      renderCaptured(data, append);
      return;
    }

    if (!append) prototypeGrid.textContent = "";
    (data.cards || []).forEach((card) => prototypeGrid.appendChild(renderPrototypeCard(card)));
    if (prototypeTotal) prototypeTotal.textContent = `${data.pagination?.total || 0} opportunities`;
    if (prototypeLoadMore) {
      prototypeLoadMore.hidden = !data.pagination?.has_more;
      prototypeLoadMore.classList.toggle("hidden", !data.pagination?.has_more);
    }
  }

  async function load({append = false} = {}) {
    if (loading) return;
    loading = true;
    if (prototypeLoadMore) prototypeLoadMore.disabled = true;
    setStatus(append ? "Loading more opportunities..." : "Loading PriceBridge opportunities...");

    try {
      const currentQuery = queryString();
      const response = await fetch(endpoint(), {
        credentials: "include",
        headers: {"Accept": "application/json"},
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const data = await response.json();
      if (!data.ok) throw new Error(data.error || "API returned an error");
      render(data, append && currentQuery === lastQuery);
      window.PriceBridgeOpportunityPayload = data;
      document.dispatchEvent(new CustomEvent("pricebridge:opportunities-loaded", { detail: data }));
      lastQuery = currentQuery;
      setStatus("");
    } catch (error) {
      setStatus(`Could not load PriceBridge API data from ${apiBase()}. Start Django on 127.0.0.1:8000 or pass ?api=http://host:port/estore/api/opportunities/. ${error.message}`);
    } finally {
      loading = false;
      if (prototypeLoadMore) prototypeLoadMore.disabled = false;
    }
  }

  mobileBottomNav();
  ensureCapturedControls();
  sanitizeCapturedHrefs();
  if (isCapturedMode()) loadFx();

  activeForm()?.addEventListener("submit", (event) => {
    event.preventDefault();
    offset = 0;
    load();
  });

  activeForm()?.elements.currency?.addEventListener("change", (event) => {
    offset = 0;
    load();
  });

  prototypeLoadMore?.addEventListener("click", () => {
    offset += limit;
    load({append: true});
  });

  load();
})();
