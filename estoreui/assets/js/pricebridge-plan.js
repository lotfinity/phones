(() => {
  "use strict";

  const dataNode = document.getElementById("pricebridge-opportunity-data");
  if (!dataNode) return;

  let payload;
  try {
    payload = JSON.parse(dataNode.textContent || "{}");
  } catch (error) {
    console.error("PriceBridge plan payload could not be parsed", error);
    return;
  }

  const currency = String(payload.selected_currency || "TRY").toUpperCase();
  const STORAGE_KEY = `pricebridge.purchasePlan.v1.${currency}`;
  const MAX_QUANTITY = 99;
  const all = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function parseMoney(value) {
    if (typeof value === "number") return Number.isFinite(value) ? value : 0;
    const normalized = String(value || "")
      .replace(/\s/g, "")
      .replace(/[^0-9,.-]/g, "")
      .replace(/,/g, "");
    const amount = Number.parseFloat(normalized);
    return Number.isFinite(amount) ? amount : 0;
  }

  function money(value) {
    const amount = Number(value) || 0;
    try {
      return new Intl.NumberFormat("tr-TR", {
        style: "currency",
        currency,
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch (_) {
      return `${amount.toLocaleString("tr-TR", { maximumFractionDigits: 2 })} ${currency}`;
    }
  }

  function emptyState() {
    return { version: 1, currency, budget: 0, items: {} };
  }

  function readState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (!parsed || typeof parsed !== "object" || parsed.currency !== currency) return emptyState();
      return {
        version: 1,
        currency,
        budget: Math.max(0, Number(parsed.budget) || 0),
        items: parsed.items && typeof parsed.items === "object" ? parsed.items : {},
      };
    } catch (_) {
      return emptyState();
    }
  }

  let state = readState();

  function saveState() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    document.dispatchEvent(new CustomEvent("pricebridge:plan-changed", { detail: state }));
  }

  function opportunityRecords() {
    if (Array.isArray(payload.cards)) return payload.cards;
    return payload.opportunity ? [payload.opportunity] : [];
  }

  function opportunityKey(record) {
    const category = record.category || record.device_type || "opportunity";
    const id = record.pk ?? record.snapshot_id;
    return `${category}:${id}`;
  }

  function normalizedItem(record) {
    const key = opportunityKey(record);
    return {
      key,
      category: record.category || record.device_type || "opportunity",
      pk: record.pk ?? record.snapshot_id,
      title: record.title || `${record.brand || ""} ${record.model || ""}`.trim() || "Fırsat",
      subtitle: record.subtitle || record.spec || "",
      imageUrl: record.has_image && record.image_url ? record.image_url : "",
      detailUrl: record.detail_url || window.location.pathname,
      unitPrice: parseMoney(record.buyer_offer),
      unitPriceLabel: record.buyer_offer || "",
      buyerGain: record.buyer_gain || "",
      buyerGainPercent: record.buyer_gain_percent || "",
      quantity: 1,
    };
  }

  const records = new Map(opportunityRecords().map((record) => [opportunityKey(record), record]));

  function findPlanDialog() {
    const dialogs = all('[role="dialog"]');
    return dialogs.find((dialog) => /shopping cart|cart|alım planı|alim plani/i.test(text(dialog.querySelector("h1,h2,h3"))))
      || dialogs.find((dialog) => /cart|shopping/i.test(`${dialog.id} ${dialog.getAttribute("aria-label") || ""}`));
  }

  function ensurePlanDialog() {
    let dialog = findPlanDialog();
    if (dialog) return dialog;

    const overlay = document.createElement("div");
    overlay.className = "fixed inset-0 z-40 bg-black/40 opacity-0 pointer-events-none transition-opacity";
    overlay.dataset.pbPlanOverlay = "";

    dialog = document.createElement("aside");
    dialog.setAttribute("role", "dialog");
    dialog.setAttribute("aria-modal", "true");
    dialog.setAttribute("aria-hidden", "true");
    dialog.className = "fixed inset-y-0 right-0 z-50 w-full max-w-md translate-x-full transition-transform";
    dialog.dataset.pbPlanDrawer = "";

    document.body.append(overlay, dialog);
    overlay.addEventListener("click", closePlan);
    return dialog;
  }

  function overlayFor(dialog) {
    const previous = dialog?.previousElementSibling;
    if (previous?.classList.contains("fixed") && previous?.classList.contains("inset-0")) return previous;
    return document.querySelector("[data-pb-plan-overlay]");
  }

  function openPlan() {
    const dialog = ensurePlanDialog();
    renderPlan();
    dialog.hidden = false;
    dialog.classList.remove("translate-x-full");
    dialog.classList.add("translate-x-0");
    dialog.setAttribute("aria-hidden", "false");
    const overlay = overlayFor(dialog);
    if (overlay) {
      overlay.hidden = false;
      overlay.classList.remove("opacity-0", "pointer-events-none");
      overlay.classList.add("opacity-100");
    }
    document.body.style.overflow = "hidden";
    window.setTimeout(() => dialog.querySelector("[data-pb-plan-close]")?.focus(), 30);
  }

  function closePlan() {
    const dialog = ensurePlanDialog();
    dialog.classList.remove("translate-x-0");
    dialog.classList.add("translate-x-full");
    dialog.setAttribute("aria-hidden", "true");
    const overlay = overlayFor(dialog);
    if (overlay) {
      overlay.classList.remove("opacity-100");
      overlay.classList.add("opacity-0", "pointer-events-none");
    }
    document.body.style.overflow = "";
  }

  function itemValues() {
    return Object.values(state.items).filter((item) => item && Number(item.quantity) > 0);
  }

  function quantityCount() {
    return itemValues().reduce((sum, item) => sum + (Number(item.quantity) || 0), 0);
  }

  function plannedTotal() {
    return itemValues().reduce(
      (sum, item) => sum + (Number(item.unitPrice) || 0) * (Number(item.quantity) || 0),
      0,
    );
  }

  function updatePlanBadges() {
    const count = quantityCount();
    const candidates = all("header button, header a, nav button, nav a").filter((node) => {
      const label = `${text(node)} ${node.getAttribute("aria-label") || ""} ${node.getAttribute("title") || ""}`;
      return /shopping cart|\bcart\b|sepet|alım planı|alim plani/i.test(label);
    });

    candidates.forEach((trigger) => {
      trigger.dataset.pbPlanTrigger = "";
      const existing = trigger.querySelector("[data-pb-plan-count]");
      const badge = existing || document.createElement("span");
      badge.dataset.pbPlanCount = "";
      badge.textContent = String(count);
      badge.hidden = count === 0;
      if (!existing) trigger.append(badge);
    });
  }

  function summaryValues() {
    const total = plannedTotal();
    const budget = Number(state.budget) || 0;
    const remaining = budget - total;
    const percent = budget > 0 ? Math.min(100, (total / budget) * 100) : 0;
    return { total, budget, remaining, percent, over: budget > 0 && remaining < 0 };
  }

  function renderSummary() {
    const dialog = ensurePlanDialog();
    const values = summaryValues();
    const totalNode = dialog.querySelector("[data-pb-plan-total]");
    const balanceNode = dialog.querySelector("[data-pb-plan-balance]");
    const progress = dialog.querySelector("[data-pb-plan-progress]");
    const budgetInput = dialog.querySelector("[data-pb-plan-budget]");

    if (totalNode) totalNode.textContent = money(values.total);
    if (budgetInput && document.activeElement !== budgetInput) budgetInput.value = state.budget || "";
    if (balanceNode) {
      balanceNode.dataset.state = values.over ? "over" : values.budget > 0 ? "ok" : "unset";
      balanceNode.textContent = values.budget <= 0
        ? "Bütçe girilmedi"
        : values.over
          ? `${money(Math.abs(values.remaining))} limit aşıldı`
          : `${money(values.remaining)} kaldı`;
    }
    if (progress) {
      progress.style.width = `${values.percent}%`;
      progress.dataset.state = values.over ? "over" : "ok";
    }
  }

  function itemMarkup(item) {
    const quantity = Math.max(1, Math.min(MAX_QUANTITY, Number(item.quantity) || 1));
    const subtotal = (Number(item.unitPrice) || 0) * quantity;
    const image = item.imageUrl
      ? `<img src="${escapeHtml(item.imageUrl)}" alt="${escapeHtml(item.title)}" loading="lazy">`
      : `<span class="pb-plan-item__fallback" aria-hidden="true">${escapeHtml(item.title.slice(0, 2).toUpperCase())}</span>`;

    return `
      <article class="pb-plan-item" data-pb-plan-item="${escapeHtml(item.key)}">
        <a class="pb-plan-item__image" href="${escapeHtml(item.detailUrl || "#")}">${image}</a>
        <div class="pb-plan-item__body">
          <div class="pb-plan-item__topline">
            <h3><a href="${escapeHtml(item.detailUrl || "#")}">${escapeHtml(item.title)}</a></h3>
            <button type="button" data-pb-plan-remove="${escapeHtml(item.key)}" aria-label="${escapeHtml(item.title)} ürününü plandan kaldır">×</button>
          </div>
          ${item.subtitle ? `<p>${escapeHtml(item.subtitle)}</p>` : ""}
          <strong>${escapeHtml(item.unitPriceLabel || money(item.unitPrice))}</strong>
          <div class="pb-plan-item__controls">
            <div class="pb-plan-quantity" aria-label="Adet">
              <button type="button" data-pb-plan-decrease="${escapeHtml(item.key)}" aria-label="Adedi azalt">−</button>
              <output>${quantity}</output>
              <button type="button" data-pb-plan-increase="${escapeHtml(item.key)}" aria-label="Adedi artır">+</button>
            </div>
            <span>${escapeHtml(money(subtotal))}</span>
          </div>
        </div>
      </article>`;
  }

  function renderPlan() {
    const dialog = ensurePlanDialog();
    dialog.dataset.pbPlanDrawer = "";
    dialog.setAttribute("aria-label", "Alım Planı");
    const items = itemValues();

    dialog.innerHTML = `
      <div class="pb-plan-shell">
        <header class="pb-plan-header">
          <div>
            <span>PriceBridge</span>
            <h2>Alım Planı</h2>
            <p>Tarayıcıda saklanan seyahat satın alma listesi</p>
          </div>
          <button type="button" data-pb-plan-close aria-label="Alım planını kapat">×</button>
        </header>

        <section class="pb-plan-budget" aria-labelledby="pb-plan-budget-title">
          <div class="pb-plan-budget__heading">
            <div>
              <span id="pb-plan-budget-title">Toplam bütçe</span>
              <small>${escapeHtml(currency)} olarak kaydedilir</small>
            </div>
            <label>
              <span class="sr-only">Bütçe</span>
              <input data-pb-plan-budget type="number" min="0" step="100" inputmode="decimal" value="${state.budget || ""}" placeholder="0">
              <b>${escapeHtml(currency)}</b>
            </label>
          </div>
          <div class="pb-plan-progress"><span data-pb-plan-progress></span></div>
          <div class="pb-plan-summary">
            <div><span>Planlanan</span><strong data-pb-plan-total>${money(plannedTotal())}</strong></div>
            <div><span>Bütçe durumu</span><strong data-pb-plan-balance></strong></div>
          </div>
        </section>

        <section class="pb-plan-items" aria-live="polite">
          ${items.length
            ? items.map(itemMarkup).join("")
            : `<div class="pb-plan-empty"><strong>Alım planın boş</strong><p>Bir fırsatı eklediğinde burada bütçe ve adet hesabı yapılacak.</p></div>`}
        </section>

        <footer class="pb-plan-footer">
          <div><span>${quantityCount()} ürün</span><strong>${money(plannedTotal())}</strong></div>
          <button type="button" data-pb-plan-clear ${items.length ? "" : "disabled"}>Planı temizle</button>
        </footer>
      </div>`;

    dialog.querySelector("[data-pb-plan-close]")?.addEventListener("click", closePlan);
    dialog.querySelector("[data-pb-plan-budget]")?.addEventListener("input", (event) => {
      state.budget = Math.max(0, Number(event.target.value) || 0);
      saveState();
      renderSummary();
    });
    renderSummary();
    updatePlanBadges();
  }

  function addItem(key) {
    const record = records.get(key);
    if (!record) return;
    const item = normalizedItem(record);
    if (!item.unitPrice) {
      window.alert("Bu fırsat için önerilen alım fiyatı henüz hesaplanmamış.");
      return;
    }

    const existing = state.items[key];
    state.items[key] = existing
      ? { ...existing, ...item, quantity: Math.min(MAX_QUANTITY, (Number(existing.quantity) || 0) + 1) }
      : item;
    saveState();
    renderPlan();
    openPlan();
  }

  function changeQuantity(key, delta) {
    const item = state.items[key];
    if (!item) return;
    const next = Math.max(1, Math.min(MAX_QUANTITY, (Number(item.quantity) || 1) + delta));
    item.quantity = next;
    saveState();
    renderPlan();
  }

  function removeItem(key) {
    delete state.items[key];
    saveState();
    renderPlan();
  }

  function clearPlan() {
    if (!itemValues().length) return;
    if (!window.confirm("Alım planındaki tüm ürünler kaldırılsın mı?")) return;
    state.items = {};
    saveState();
    renderPlan();
  }

  function makeAddButton(record, compact = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.pbAddPlan = opportunityKey(record);
    button.className = compact ? "pb-plan-add pb-plan-add--compact" : "pb-plan-add";
    button.textContent = "Alım Planına Ekle";
    return button;
  }

  function installAddButtons() {
    if (Array.isArray(payload.cards)) {
      payload.cards.forEach((record) => {
        const key = opportunityKey(record);
        const candidates = all(`[data-pb-opportunity-card="${CSS.escape(String(record.pk))}"]`);
        const card = candidates.find((node) => node.querySelector(`a[href="${CSS.escape(record.detail_url || "")}"]`)) || candidates[0];
        const meta = card?.querySelector("[data-pb-opportunity-meta]");
        if (meta && !meta.querySelector("[data-pb-add-plan]")) meta.append(makeAddButton(record, true));
      });
    }

    if (payload.opportunity) {
      const record = payload.opportunity;
      const key = opportunityKey(record);
      const main = document.querySelector("main") || document.body;
      const primaryCta = all("button,a", main).find((node) => /fırsat detaylarını incele|add to cart|buy now|sepete ekle|satın al/i.test(text(node)));
      if (primaryCta) {
        primaryCta.dataset.pbAddPlan = key;
        primaryCta.textContent = "Alım Planına Ekle";
        if (primaryCta.tagName === "A") primaryCta.setAttribute("href", "#");
      }
      const panelCard = document.querySelector("#pricebridge-opportunity-details .pb-bagisto-panel-card");
      if (panelCard && !panelCard.querySelector("[data-pb-add-plan]")) panelCard.append(makeAddButton(record));
    }
  }

  function installTriggers() {
    all("button,a").forEach((node) => {
      const label = `${text(node)} ${node.getAttribute("aria-label") || ""} ${node.getAttribute("title") || ""}`;
      if (!/shopping cart|\bcart\b|sepet|alım planı|alim plani/i.test(label)) return;
      node.dataset.pbPlanTrigger = "";
    });
  }

  document.addEventListener("click", (event) => {
    const add = event.target.closest?.("[data-pb-add-plan]");
    if (add) {
      event.preventDefault();
      event.stopImmediatePropagation();
      addItem(add.dataset.pbAddPlan);
      return;
    }

    const trigger = event.target.closest?.("[data-pb-plan-trigger]");
    if (trigger) {
      event.preventDefault();
      event.stopImmediatePropagation();
      openPlan();
      return;
    }

    const decrease = event.target.closest?.("[data-pb-plan-decrease]");
    if (decrease) return changeQuantity(decrease.dataset.pbPlanDecrease, -1);
    const increase = event.target.closest?.("[data-pb-plan-increase]");
    if (increase) return changeQuantity(increase.dataset.pbPlanIncrease, 1);
    const remove = event.target.closest?.("[data-pb-plan-remove]");
    if (remove) return removeItem(remove.dataset.pbPlanRemove);
    if (event.target.closest?.("[data-pb-plan-clear]")) return clearPlan();
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePlan();
  });

  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    state = readState();
    renderPlan();
  });

  function init() {
    ensurePlanDialog();
    installAddButtons();
    installTriggers();
    renderPlan();
    updatePlanBadges();

    const observer = new MutationObserver(() => {
      installAddButtons();
      installTriggers();
      updatePlanBadges();
    });
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
