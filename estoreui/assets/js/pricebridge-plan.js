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
  const STORAGE_KEY = "pricebridge_acquisition_plan_v1";
  const MAX_PHONES = 6;
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
    return { version: 1, currency, items: [] };
  }

  function readState() {
    try {
      const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
      if (!parsed || typeof parsed !== "object") return emptyState();
      const rawItems = Array.isArray(parsed.items)
        ? parsed.items
        : parsed.items && typeof parsed.items === "object"
          ? Object.values(parsed.items)
          : [];
      const seen = new Set();
      const items = rawItems
        .filter((item) => item && typeof item === "object")
        .map((item) => ({ ...item, id: String(item.id || item.key || "") }))
        .filter((item) => item.id && !seen.has(item.id) && seen.add(item.id));
      return {
        version: 1,
        currency,
        items,
      };
    } catch (_) {
      return emptyState();
    }
  }

  let state = readState();

  function saveState() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 1, currency, items: state.items }));
    } catch (error) {
      console.warn("PriceBridge plan could not be saved to localStorage", error);
    }
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
      id: key,
      category: record.category || record.device_type || "opportunity",
      opportunity_id: record.pk ?? record.snapshot_id,
      source_listing_id: record.source_listing_id || null,
      title: record.title || `${record.brand || ""} ${record.model || ""}`.trim() || "Fırsat",
      subtitle: record.subtitle || record.spec || "",
      image_url: record.has_image && record.image_url ? record.image_url : "",
      detail_url: record.detail_url || window.location.pathname,
      buyer_offer: record.buyer_offer || "",
      supplier_price: record.supplier_price || "",
      buyer_gain: record.buyer_gain || "",
      buyer_gain_percent: record.buyer_gain_percent || "",
      availability: record.availability_state || "verification_required",
      availability_label: record.availability_label || "Güncellik doğrulanmalı",
      added_at: new Date().toISOString(),
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
    return Array.isArray(state.items) ? state.items.filter((item) => item && item.id) : [];
  }

  function totalCount() {
    return itemValues().length;
  }

  function plannedTotal() {
    return itemValues().reduce(
      (sum, item) => sum + parseMoney(item.buyer_offer),
      0,
    );
  }

  function planTriggerCandidates() {
    return all("header button, header a, nav button, nav a").filter((node) => {
      if (node.closest("[data-pb-plan-drawer]")) return false;
      if (node.matches("[data-pb-add-plan], [data-pb-plan-close]")) return false;
      const label = `${text(node)} ${node.getAttribute("aria-label") || ""} ${node.getAttribute("title") || ""}`;
      return /shopping cart|\bcart\b|sepet|alım planı|alim plani/i.test(label);
    });
  }

  function updatePlanBadges() {
    const count = totalCount();
    planTriggerCandidates().forEach((trigger) => {
      trigger.dataset.pbPlanTrigger = "";
      const existing = trigger.querySelector("[data-pb-plan-count]");
      const badge = existing || document.createElement("span");
      badge.dataset.pbPlanCount = "";
      if (badge.textContent !== String(count)) badge.textContent = String(count);
      badge.hidden = count === 0;
      if (!existing) trigger.append(badge);
    });
  }

  function categoryCounts() {
    const counts = { phone: 0, laptop: 0, console: 0 };
    itemValues().forEach((item) => {
      if (Object.prototype.hasOwnProperty.call(counts, item.category)) counts[item.category] += 1;
    });
    return counts;
  }

  function renderSummary() {
    const dialog = ensurePlanDialog();
    const totalNode = dialog.querySelector("[data-pb-plan-total]");
    if (totalNode) totalNode.textContent = money(plannedTotal());
  }

  function itemMarkup(item) {
    const image = item.image_url
      ? `<img src="${escapeHtml(item.image_url)}" alt="${escapeHtml(item.title)}" loading="lazy">`
      : `<span class="pb-plan-item__fallback" aria-hidden="true">${escapeHtml(item.title.slice(0, 2).toUpperCase())}</span>`;

    return `
      <article class="pb-plan-item" data-pb-plan-item="${escapeHtml(item.id)}">
        <a class="pb-plan-item__image" href="${escapeHtml(item.detail_url || "#")}">${image}</a>
        <div class="pb-plan-item__body">
          <div class="pb-plan-item__topline">
            <h3><a href="${escapeHtml(item.detail_url || "#")}">${escapeHtml(item.title)}</a></h3>
            <button type="button" data-pb-plan-remove="${escapeHtml(item.id)}" aria-label="${escapeHtml(item.title)} fırsatını plandan kaldır">×</button>
          </div>
          ${item.subtitle ? `<p>${escapeHtml(item.subtitle)}</p>` : ""}
          <strong>${escapeHtml(item.buyer_offer || "Teklif fiyatı yok")}</strong>
          ${item.supplier_price ? `<small><s>${escapeHtml(item.supplier_price)}</s> tedarikçi liste fiyatı</small>` : ""}
          <div class="pb-plan-item__controls"><span>${escapeHtml(item.availability_label || "Güncellik doğrulanmalı")}</span></div>
        </div>
      </article>`;
  }

  function renderPlan() {
    const dialog = ensurePlanDialog();
    dialog.dataset.pbPlanDrawer = "";
    dialog.setAttribute("aria-label", "Alım Planı");
    const items = itemValues();
    const counts = categoryCounts();

    dialog.innerHTML = `
      <div class="pb-plan-shell">
        <header class="pb-plan-header">
          <div>
            <span>PriceBridge</span>
            <h2>Alım planı</h2>
            <p>Tekil ikinci el fırsatlar tarayıcıda saklanır.</p>
          </div>
          <button type="button" data-pb-plan-close aria-label="Alım planını kapat">×</button>
        </header>

        <section class="pb-plan-budget" aria-labelledby="pb-plan-budget-title">
          <div class="pb-plan-budget__heading">
            <div>
              <span id="pb-plan-budget-title">Plan kapasitesi</span>
              <small>Telefonlar: ${counts.phone} / ${MAX_PHONES} · Kalan ${Math.max(0, MAX_PHONES - counts.phone)}</small>
            </div>
            <div class="pb-plan-capacity">
              <span>Laptoplar: ${counts.laptop}</span>
              <span>Konsollar: ${counts.console}</span>
            </div>
          </div>
          <div class="pb-plan-summary">
            <div><span>Plan özeti</span><strong data-pb-plan-total>${money(plannedTotal())}</strong></div>
            <div><span>Teklif / fatura</span><strong>Yakında</strong></div>
          </div>
        </section>

        <section class="pb-plan-items" aria-live="polite">
          ${items.length
            ? items.map(itemMarkup).join("")
            : `<div class="pb-plan-empty"><strong>Alım planın boş</strong><p>Bir fırsatı eklediğinde burada plan özeti görünecek.</p></div>`}
        </section>

        <footer class="pb-plan-footer">
          <div><span>${totalCount()} fırsat</span><strong>${money(plannedTotal())}</strong></div>
          <button type="button" data-pb-plan-clear ${items.length ? "" : "disabled"}>Planı temizle</button>
        </footer>
      </div>`;

    dialog.querySelector("[data-pb-plan-close]")?.addEventListener("click", closePlan);
    renderSummary();
    updatePlanBadges();
  }

  function planMessage(message) {
    let node = document.querySelector("[data-pb-plan-message]");
    if (!node) {
      node = document.createElement("div");
      node.dataset.pbPlanMessage = "";
      document.body.append(node);
    }
    node.textContent = message;
    node.hidden = false;
    window.clearTimeout(planMessage.timer);
    planMessage.timer = window.setTimeout(() => { node.hidden = true; }, 2800);
  }

  function canAdd(record) {
    if (!record) return { ok: false, message: "Fırsat bulunamadı." };
    if (record.availability_is_actionable === false) {
      return { ok: false, message: record.availability_label || "Bu ilan güncel olmadığı için plana eklenemez." };
    }
    const key = opportunityKey(record);
    if (state.items.some((item) => item.id === key)) {
      return { ok: true, existing: true, message: "Bu fırsat zaten planda." };
    }
    if ((record.category || record.device_type) === "phone" && categoryCounts().phone >= MAX_PHONES) {
      return { ok: false, message: `Telefon limiti dolu: ${MAX_PHONES} / ${MAX_PHONES}` };
    }
    return { ok: true };
  }

  function updateAddButtonStates() {
    all("[data-pb-add-plan]").forEach((button) => {
      const record = records.get(button.dataset.pbAddPlan);
      const key = record ? opportunityKey(record) : button.dataset.pbAddPlan;
      const isPlanned = state.items.some((item) => item.id === key);
      const allowed = canAdd(record);
      button.textContent = isPlanned ? "Planda" : button.dataset.pbImmediateClose === "1" ? "Hemen Ayır" : "Alım planına ekle";
      button.disabled = !isPlanned && !allowed.ok;
      button.title = !isPlanned && !allowed.ok ? allowed.message : "";
      button.dataset.pbPlanned = isPlanned ? "1" : "0";
    });
  }

  function addItem(key, immediate = false) {
    const record = records.get(key);
    if (!record) return;
    const allowed = canAdd(record);
    if (!allowed.ok) {
      planMessage(allowed.message);
      openPlan();
      return;
    }
    if (allowed.existing) {
      planMessage(allowed.message);
      openPlan();
      return;
    }
    const item = normalizedItem(record);
    if (!item.buyer_offer) {
      planMessage("Bu fırsat için önerilen alım fiyatı henüz hesaplanmamış.");
      return;
    }
    state.items = [...state.items, item];
    saveState();
    renderPlan();
    updateAddButtonStates();
    if (immediate) planMessage("Tekil ilan plana eklendi. İlan her an kapanabilir.");
    openPlan();
  }

  function removeItem(key) {
    state.items = state.items.filter((item) => item.id !== key);
    saveState();
    renderPlan();
    updateAddButtonStates();
  }

  function clearPlan() {
    if (!itemValues().length) return;
    if (!window.confirm("Alım planındaki tüm ürünler kaldırılsın mı?")) return;
    state.items = [];
    saveState();
    renderPlan();
    updateAddButtonStates();
  }

  function makeAddButton(record, compact = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.pbAddPlan = opportunityKey(record);
    button.className = compact ? "pb-plan-add pb-plan-add--compact" : "pb-plan-add";
    button.textContent = "Alım planına ekle";
    return button;
  }

  function installAddButtons() {
    if (Array.isArray(payload.cards)) {
      payload.cards.forEach((record) => {
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
        primaryCta.textContent = primaryCta.dataset.pbImmediateClose === "1" ? "Hemen Ayır" : "Alım planına ekle";
        if (primaryCta.tagName === "A") primaryCta.setAttribute("href", "#");
      }
      const panelCard = document.querySelector("#pricebridge-opportunity-details .pb-bagisto-panel-card");
      if (panelCard && !panelCard.querySelector("[data-pb-add-plan]")) panelCard.append(makeAddButton(record));
    }
  }

  function installTriggers() {
    planTriggerCandidates().forEach((node) => {
      node.dataset.pbPlanTrigger = "";
    });
  }

  document.addEventListener("click", (event) => {
    const add = event.target.closest?.("[data-pb-add-plan]");
    if (add) {
      event.preventDefault();
      event.stopImmediatePropagation();
      addItem(add.dataset.pbAddPlan, add.dataset.pbImmediateClose === "1");
      return;
    }

    const close = event.target.closest?.("[data-pb-plan-close]");
    if (close) {
      event.preventDefault();
      event.stopImmediatePropagation();
      closePlan();
      return;
    }

    const trigger = event.target.closest?.("[data-pb-plan-trigger]");
    if (trigger) {
      event.preventDefault();
      event.stopImmediatePropagation();
      window.setTimeout(openPlan, 0);
      return;
    }

    const remove = event.target.closest?.("[data-pb-plan-remove]");
    if (remove) {
      event.preventDefault();
      removeItem(remove.dataset.pbPlanRemove);
      return;
    }
    if (event.target.closest?.("[data-pb-plan-clear]")) {
      event.preventDefault();
      clearPlan();
    }
  }, true);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closePlan();
  });

  document.addEventListener("pricebridge:plan-changed", () => {
    state = readState();
    updatePlanBadges();
    updateAddButtonStates();
  });

  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY) return;
    state = readState();
    renderPlan();
    updateAddButtonStates();
  });

  function init() {
    ensurePlanDialog();
    installAddButtons();
    installTriggers();
    renderPlan();
    updatePlanBadges();
    updateAddButtonStates();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
  else init();
})();
