(() => {
  "use strict";

  const BAGISTO_HOSTS = new Set([
    "bagisto-headless-electronic.vercel.app",
    "nextjs.bagisto.com",
    "www.nextjs.bagisto.com",
  ]);

  const dataNode = document.getElementById("pricebridge-opportunity-data");
  if (!dataNode) {
    document.documentElement.classList.remove("pb-bagisto-hydrating");
    return;
  }

  let payload;
  try {
    payload = JSON.parse(dataNode.textContent || "{}");
  } catch (error) {
    console.error("PriceBridge Bagisto payload could not be parsed", error);
    document.documentElement.classList.remove("pb-bagisto-hydrating");
    return;
  }

  const all = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
  const lower = (node) => text(node).toLocaleLowerCase("tr-TR");
  const productSelector = 'a[href="#pb-product"], a[href*="/products/"], a[href*="/product/"]';
  const pricePattern = /(?:[$€£₺]|\b(?:USD|EUR|TRY|TL|DZD)\b)\s*[\d.,]+|[\d.,]+\s*(?:[$€£₺]|\b(?:USD|EUR|TRY|TL|DZD)\b)/i;
  const capturedDetailPattern = /HD Computer Monitor|VisionCraft|UltraView|Display Size|Full HD 1920x1080|Panel Type|Refresh Rate|Response Time|Connectivity|Mount Support|Matte Black/i;

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function svgFallback(title) {
    const initials = String(title || "PB")
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join("")
      .toUpperCase() || "PB";
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="900" height="900" viewBox="0 0 900 900">
        <rect width="900" height="900" fill="#eef3f7"/>
        <circle cx="700" cy="180" r="220" fill="#cce9e7"/>
        <circle cx="160" cy="760" r="180" fill="#d9e4f2"/>
        <text x="450" y="505" text-anchor="middle" font-family="Archivo,Arial,sans-serif" font-size="180" font-weight="750" fill="#123b5d">${escapeHtml(initials)}</text>
      </svg>`;
    return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`;
  }

  function safeUrl(value, fallback = "#") {
    if (!value) return fallback;
    try {
      const url = new URL(value, window.location.origin);
      if (["http:", "https:"].includes(url.protocol)) return url.href;
    } catch (_) {
      return fallback;
    }
    return fallback;
  }

  function mapCapturedHref(value, label = "") {
    const raw = String(value || "").trim();
    const normalizedLabel = String(label || "").toLocaleLowerCase("tr-TR");

    if (!raw || raw.startsWith("mailto:") || raw.startsWith("tel:") || raw.startsWith("javascript:")) {
      return null;
    }
    if (raw === "#pb-product") return raw;
    if (raw.startsWith("/estore/")) return raw;

    let url;
    try {
      url = new URL(raw, window.location.origin);
    } catch (_) {
      return null;
    }

    const isCapturedHost = BAGISTO_HOSTS.has(url.hostname.toLowerCase());
    const isLocalCapturedPath = url.origin === window.location.origin && !url.pathname.startsWith("/estore/");
    if (!isCapturedHost && !isLocalCapturedPath) return null;

    const path = url.pathname.toLowerCase().replace(/\/$/, "") || "/";
    const combined = `${path}?${url.searchParams.toString().toLowerCase()} ${normalizedLabel}`;

    if (path.startsWith("/product/") || path.startsWith("/products/")) return "#pb-product";
    if (/smartphone|phone|mobile|telefon/.test(combined)) return payload.urls?.phone || "/estore/?category=phone";
    if (/laptop|computer|notebook/.test(combined)) return payload.urls?.laptop || "/estore/?category=laptop";
    if (/console|gaming|konsol/.test(combined)) return payload.urls?.console || "/estore/?category=console";
    return payload.urls?.index || "/estore/";
  }

  function rewriteShellLinks() {
    all("a[href]").forEach((anchor) => {
      const href = anchor.getAttribute("href") || "";
      if (href === "#pb-product") return;
      const mapped = mapCapturedHref(href, lower(anchor));
      if (mapped && mapped !== href) anchor.setAttribute("href", mapped);
    });
    all("form[action]").forEach((form) => {
      const mapped = mapCapturedHref(form.getAttribute("action") || "", lower(form));
      if (mapped) form.setAttribute("action", payload.urls?.index || mapped);
    });
  }

  function cardDetailUrl(card) {
    return card.frontend_detail_url || card.detail_url || "#";
  }

  function rewriteBranding() {
    all("header, footer").forEach((region) => {
      all("a,span,strong,p", region).forEach((node) => {
        if (node.children.length) return;
        const current = text(node);
        if (/^your store name$/i.test(current) || /^bagisto headless$/i.test(current)) {
          node.textContent = "PriceBridge";
        }
      });
      all("img", region).forEach((image) => {
        const alt = image.getAttribute("alt") || "";
        if (/logo|store/i.test(alt)) image.alt = "PriceBridge";
      });
    });
  }

  function renderBrandFilters() {
    // Keep the captured Bagisto filter/sort controls in place. Injecting
    // dynamic brand filters changes the reference layout too aggressively.
  }

  function relocateMobileBottomNav() {
    const mobileNav = document.querySelector('header div[class*="inset-x-0"][class*="bottom-0"][class*="lg:hidden"]');
    if (!mobileNav || mobileNav.dataset.pbMobileBottomNav === "1") return;
    mobileNav.dataset.pbMobileBottomNav = "1";
    document.body.append(mobileNav);
  }

  function installCapturedLinkGuard() {
    document.addEventListener(
      "click",
      (event) => {
        const anchor = event.target.closest?.("a[href]");
        if (!anchor) return;
        const href = anchor.getAttribute("href") || "";
        if (href === "#pb-product") {
          event.preventDefault();
          return;
        }
        const mapped = mapCapturedHref(href, lower(anchor));
        if (!mapped || mapped === href) return;
        event.preventDefault();
        window.location.assign(mapped);
      },
      true,
    );
  }

  function searchInputs() {
    return all('input[type="search"], input[role="searchbox"], input[placeholder]').filter((input) => {
      const haystack = `${input.type || ""} ${input.getAttribute("role") || ""} ${input.placeholder || ""}`;
      return /search|ara/i.test(haystack);
    });
  }

  function searchDestination(value) {
    const url = new URL(payload.urls?.index || "/estore/", window.location.origin);
    const query = String(value || "").trim();
    if (query) url.searchParams.set("q", query);
    if (payload.active_category) url.searchParams.set("category", payload.active_category);
    return `${url.pathname}${url.search}`;
  }

  function submitSearch(input) {
    window.location.assign(searchDestination(input?.value || ""));
  }

  function bindSearchInput(input) {
    if (input.dataset.pbSearchBound === "1") return;
    input.dataset.pbSearchBound = "1";
    input.name = "q";
    input.placeholder = "Fırsatlarda ara";
    if (payload.query) input.value = payload.query;

    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      submitSearch(input);
    });

    const form = input.closest("form");
    if (form && form.dataset.pbSearchBound !== "1") {
      form.dataset.pbSearchBound = "1";
      form.method = "get";
      form.action = payload.urls?.index || "/estore/";
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitSearch(input);
      });
    }

    let container = input.parentElement;
    for (let depth = 0; container && depth < 4; depth += 1, container = container.parentElement) {
      const buttons = all('button, [role="button"]', container);
      const searchButton = buttons.find((button) => {
        const value = `${text(button)} ${button.getAttribute("aria-label") || ""} ${button.getAttribute("title") || ""}`;
        return /search|ara/i.test(value) || button.querySelector('svg, [class*="search"]');
      });
      if (searchButton) {
        searchButton.type = "button";
        searchButton.addEventListener("click", (event) => {
          event.preventDefault();
          submitSearch(input);
        });
        break;
      }
    }
  }

  function configureSearch() {
    searchInputs().forEach(bindSearchInput);

    // Captured drawers can be inserted or toggled after initial load.
    const observer = new MutationObserver(() => searchInputs().forEach(bindSearchInput));
    observer.observe(document.body, { childList: true, subtree: true });
  }

  function replaceCatalogHeading() {
    const candidates = all("main h1, main h2, main h3");
    const target = candidates.find((node) => /smartphone|product|category/i.test(text(node))) || candidates[0];
    if (target && payload.page === "opportunity-index") target.textContent = "PriceBridge Opportunities";

    all("main a, main p, main span, main li").forEach((node) => {
      const current = text(node);
      if (node.children.length) return;
      if (/^smartphones$/i.test(current)) node.textContent = "Fırsatlar";
      if (/^home$/i.test(current)) node.textContent = "Ana sayfa";
      if (/\b\d+\s+(products?|items?)\b/i.test(current)) {
        node.textContent = `${payload.total_count || 0} clean opportunities`;
      }
    });
  }

  function directProductChildren(parent) {
    return [...parent.children].filter((child) => child.querySelector?.(productSelector));
  }

  function findCatalogGrid() {
    const main = document.querySelector("main") || document.body;
    const anchors = all(productSelector, main);
    const candidates = new Map();

    anchors.forEach((anchor) => {
      let node = anchor;
      let depth = 0;
      while (node?.parentElement && node !== main && depth < 12) {
        const parent = node.parentElement;
        const productChildren = directProductChildren(parent);
        if (productChildren.length >= 2) {
          const existing = candidates.get(parent) || { grid: parent, cards: productChildren, score: 0 };
          existing.cards = productChildren;
          existing.score = Math.max(existing.score, productChildren.length * 100 - depth);
          candidates.set(parent, existing);
        }
        node = parent;
        depth += 1;
      }
    });

    return [...candidates.values()].sort((a, b) => b.score - a.score)[0] || null;
  }

  function leafTextCandidates(scope) {
    return all("h1,h2,h3,h4,h5,h6,a,p,span,strong", scope)
      .filter((node) => !node.querySelector("img,svg"))
      .filter((node) => {
        const value = text(node);
        return value.length >= 3 && value.length <= 160;
      });
  }

  function findTitleNode(scope) {
    const headings = all("h1,h2,h3,h4,h5,h6", scope).filter((node) => text(node).length >= 3);
    if (headings.length) return headings.sort((a, b) => text(b).length - text(a).length)[0];
    return leafTextCandidates(scope).find((node) => {
      const value = text(node);
      return !pricePattern.test(value) && !/add to cart|wishlist|compare|buy now|view/i.test(value);
    }) || null;
  }

  function isVisibleNode(node) {
    if (!node || node.hidden || node.getAttribute("aria-hidden") === "true") return false;
    const styles = window.getComputedStyle(node);
    if (styles.display === "none" || styles.visibility === "hidden") return false;
    return !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
  }

  function isDetailContentNode(node) {
    return !node.closest("header,footer,[role='dialog'],[aria-hidden='true']");
  }

  function findDetailHeading(scope) {
    const headings = all("h1,h2", scope)
      .filter(isDetailContentNode)
      .filter((node) => text(node).length >= 3);
    return headings.find(isVisibleNode) || headings[0] || null;
  }

  function priceNodes(scope) {
    return all("span,strong,p,div", scope)
      .filter((node) => node.children.length === 0)
      .filter((node) => pricePattern.test(text(node)))
      .sort((a, b) => {
        const aOld = /line-through|old|compare/i.test(a.className || "") ? 1 : 0;
        const bOld = /line-through|old|compare/i.test(b.className || "") ? 1 : 0;
        return aOld - bOld;
      });
  }

  function replacePrices(scope, card) {
    const nodes = priceNodes(scope);
    nodes.forEach((node) => {
      node.dataset.pbCapturedPrice = "";
      node.textContent = "";
      node.hidden = true;
    });
  }

  function hideNode(node) {
    if (!node) return;
    node.dataset.pbSuppressedCapturedCommerce = "";
    node.hidden = true;
    node.setAttribute("aria-hidden", "true");
  }

  function suppressCapturedCardSemantics(scope) {
    all("button,a,span,p,div", scope).forEach((node) => {
      if (node.dataset.pbAddPlan !== undefined) return;
      if (node.closest("[data-pb-opportunity-meta]")) return;
      const value = text(node);
      const label = `${value} ${node.getAttribute("aria-label") || ""} ${node.getAttribute("title") || ""}`;
      const normalized = label.toLocaleLowerCase("tr-TR");
      const isLeafish = node.children.length <= 2;
      if (/^\(?\s*0\s*\)?$/.test(value) && node.querySelectorAll("svg").length >= 3) {
        hideNode(node);
        return;
      }
      if (/^starting at$/i.test(value)) {
        hideNode(node);
        return;
      }
      if (/add to cart|buy now|sepete ekle|satın al|starting at|reviews?|\(\s*0\s*\)/i.test(label)) {
        const command = node.closest("button,a");
        if (command && scope.contains(command)) hideNode(command);
        else if (node.children.length === 0) hideNode(node);
        return;
      }
      if (isLeafish && /[★☆]\s*[★☆]/.test(value)) {
        hideNode(node);
        return;
      }
      if (isLeafish && /customer|rating|review/.test(normalized)) hideNode(node);
    });
  }

  function confidenceStars(card) {
    const score = Number(card.confidence_score) || 0;
    const stars = Math.max(1, Math.min(5, Number(card.confidence_stars) || Math.round(score / 20) || 1));
    const wrapper = document.createElement("span");
    wrapper.className = "pb-confidence-stars";
    wrapper.setAttribute("aria-label", card.confidence_aria_label || `Veri güveni ${score} / 100`);
    wrapper.setAttribute("title", card.confidence_title || `Veri güveni: %${score}`);
    wrapper.innerHTML = `${"★".repeat(stars)}${"☆".repeat(5 - stars)}<span class="sr-only"> ${score} / 100</span>`;
    return wrapper;
  }

  function availabilityBadge(card) {
    const badge = document.createElement("span");
    badge.dataset.pbAvailability = card.availability_state || "verification_required";
    badge.textContent = card.availability_label || "Güncellik doğrulanmalı";
    return badge;
  }

  function pricingBlock(card) {
    const wrapper = document.createElement("div");
    wrapper.className = "pb-card-pricing";
    wrapper.dataset.pbCardPricing = "";

    const current = document.createElement("strong");
    current.className = "pb-card-pricing__current";
    current.textContent = card.buyer_offer || "Teklif fiyatı hesaplanmadı";
    wrapper.append(current);

    const label = document.createElement("small");
    label.textContent = "PriceBridge teklif fiyatı";
    wrapper.append(label);

    if (card.supplier_price) {
      const supplier = document.createElement("span");
      supplier.className = "pb-card-pricing__supplier";
      supplier.innerHTML = `<s>${escapeHtml(card.supplier_price)}</s> tedarikçi liste fiyatı`;
      wrapper.append(supplier);
    }

    if (card.supplier_discount_label) {
      const discount = document.createElement("span");
      discount.className = "pb-card-pricing__discount";
      discount.textContent = card.supplier_discount_label;
      wrapper.append(discount);
    }

    if (card.turkiye_avg) {
      const market = document.createElement("span");
      market.textContent = `Türkiye piyasa değeri: ${card.turkiye_avg}`;
      wrapper.append(market);
    }
    if (card.buyer_gain) {
      const gain = document.createElement("span");
      gain.textContent = `Tahmini mağaza kazancı: ${card.buyer_gain}${card.buyer_gain_percent ? ` (${card.buyer_gain_percent})` : ""}`;
      wrapper.append(gain);
    }
    return wrapper;
  }

  function setProductImage(scope, card) {
    const images = all("img", scope).filter((image) => {
      const source = `${image.getAttribute("src") || ""} ${image.getAttribute("alt") || ""}`;
      return !/logo|icon|flag|avatar/i.test(source);
    });
    const source = card.has_image && card.image_url ? card.image_url : (card.brand_logo_url || svgFallback(card.title));

    images.slice(0, 6).forEach((image, index) => {
      image.src = source;
      image.removeAttribute("srcset");
      image.alt = index === 0 ? card.title : `${card.title} görseli`;
      image.loading = index === 0 ? "eager" : "lazy";
      image.addEventListener("error", () => {
        image.src = svgFallback(card.title);
      }, { once: true });
    });
  }

  function opportunityMeta(card) {
    const wrapper = document.createElement("div");
    wrapper.dataset.pbOpportunityMeta = "";

    const top = document.createElement("div");
    top.className = "pb-card-topline";
    top.append(availabilityBadge(card), confidenceStars(card));
    wrapper.append(top);

    const spec = [card.subtitle, card.condition, card.battery_health ? `Batarya %${card.battery_health}` : ""]
      .filter(Boolean)
      .join(" · ");
    if (spec) {
      const specNode = document.createElement("small");
      specNode.textContent = spec;
      wrapper.append(specNode);
    }

    wrapper.append(pricingBlock(card));

    const count = document.createElement("small");
    count.textContent = `${card.turkiye_count ?? 0} Türkiye karşılaştırması`;
    wrapper.append(count);
    return wrapper;
  }

  function populateCard(cardNode, card) {
    cardNode.dataset.pbOpportunityCard = String(card.pk);
    all("a[href]", cardNode).forEach((anchor) => {
      anchor.href = cardDetailUrl(card);
      anchor.removeAttribute("target");
    });

    setProductImage(cardNode, card);
    const titleNode = findTitleNode(cardNode);
    if (titleNode) titleNode.textContent = card.title;
    replacePrices(cardNode, card);
    suppressCapturedCardSemantics(cardNode);
    cardNode.querySelector("[data-pb-opportunity-meta]")?.remove();

    const body = all("div", cardNode)
      .filter((node) => node !== cardNode && node.querySelector("a,button,span,strong,p"))
      .at(-1) || cardNode;
    body.append(opportunityMeta(card));
  }

  function fallbackCatalog(cards) {
    const main = document.querySelector("main") || document.body;
    const grid = document.createElement("section");
    grid.className = "pb-bagisto-fallback-grid";
    grid.dataset.pbFallbackCatalog = "";

    cards.forEach((card) => {
      const article = document.createElement("article");
      article.className = "pb-bagisto-fallback-card";
      article.innerHTML = `
        <a href="${escapeHtml(cardDetailUrl(card))}">
          <img src="${escapeHtml(card.has_image && card.image_url ? card.image_url : svgFallback(card.title))}" alt="${escapeHtml(card.title)}">
        </a>
        <div><h3><a href="${escapeHtml(cardDetailUrl(card))}">${escapeHtml(card.title)}</a></h3></div>`;
      article.querySelector("div")?.append(opportunityMeta(card));
      grid.append(article);
    });
    main.append(grid);
  }

  function renderCatalog() {
    const cards = payload.cards || [];
    replaceCatalogHeading();
    const found = findCatalogGrid();
    if (!found?.cards?.length) {
      fallbackCatalog(cards);
      return;
    }

    const template = found.cards[0].cloneNode(true);
    found.cards.forEach((card) => card.remove());
    cards.forEach((card) => {
      const clone = template.cloneNode(true);
      populateCard(clone, card);
      found.grid.append(clone);
    });

    if (!cards.length) {
      const empty = document.createElement("div");
      empty.className = "col-span-full py-16 text-center";
      empty.innerHTML = "<h2>Eşleşen fırsat bulunamadı</h2><p>Arama veya kategori filtresini değiştir.</p>";
      found.grid.append(empty);
    }
  }

  function setDetailIdentity(opportunity) {
    document.title = `${opportunity.title} · PriceBridge`;
    const main = document.querySelector("main") || document.body;
    const heading = findDetailHeading(main) || findTitleNode(main);
    if (heading) heading.textContent = opportunity.title;
    setProductImage(main, opportunity);
    replacePrices(main, opportunity);
    suppressCapturedDetailCopy(main);
    renderDetailSummary(main, heading, opportunity);

    all("button,a", main).forEach((node) => {
      const label = lower(node);
      if (!/add to cart|buy now|sepete ekle|satın al/.test(label)) return;
      node.textContent = /buy now|satın al/.test(label) ? "Hemen Ayır" : "Alım planına ekle";
      node.dataset.pbAddPlan = `${opportunity.category || "opportunity"}:${opportunity.pk ?? opportunity.snapshot_id}`;
      if (/buy now|satın al/.test(label)) node.dataset.pbImmediateClose = "1";
      if (node.tagName === "A") node.href = "#";
    });
  }

  function suppressCapturedDetailCopy(scope) {
    all("h1,h2,h3,h4,h5,h6,p,span,strong,li,dt,dd", scope).forEach((node) => {
      if (node.closest("[data-pb-opportunity-panel]")) return;
      if (!capturedDetailPattern.test(text(node))) return;
      hideNode(node);
    });
  }

  function detailSpecLine(opportunity) {
    return [
      opportunity.subtitle,
      opportunity.condition,
      opportunity.battery_health ? `Batarya %${opportunity.battery_health}` : "",
    ].filter(Boolean).join(" · ");
  }

  function renderDetailSummary(scope, heading, opportunity) {
    scope.querySelector("[data-pb-detail-summary]")?.remove();
    const summary = document.createElement("div");
    summary.className = "pb-detail-summary";
    summary.dataset.pbDetailSummary = "";

    const specLine = detailSpecLine(opportunity);
    summary.innerHTML = `
      <div class="pb-card-topline">
        ${availabilityBadge(opportunity).outerHTML}
        ${confidenceStars(opportunity).outerHTML}
      </div>
      ${specLine ? `<p>${escapeHtml(specLine)}</p>` : ""}
    `;
    summary.append(pricingBlock(opportunity));

    const anchor = heading?.parentElement && scope.contains(heading.parentElement) && isDetailContentNode(heading.parentElement)
      ? heading.parentElement
      : all("main section, main div", scope).find((node) => isDetailContentNode(node) && node.querySelector("img") && text(node).length > 8) || scope;
    anchor.append(summary);
  }

  function metric(label, value) {
    if (!value) return "";
    return `<div class="pb-bagisto-metric"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
  }

  function evidenceList(rows, emptyText) {
    if (!rows?.length) return `<p>${escapeHtml(emptyText)}</p>`;
    return `<div class="pb-bagisto-evidence">${rows.map((row) => {
      const title = row.title || "Kaynak ilan";
      const href = safeUrl(row.listing_url, "#");
      const secondary = [row.country_label, row.source_name, row.price_eur, row.condition].filter(Boolean).join(" · ");
      const image = row.image_url ? `<img src="${escapeHtml(row.image_url)}" alt="${escapeHtml(title)}" loading="lazy">` : "";
      return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${image}<span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(secondary)}</small></span></a>`;
    }).join("")}</div>`;
  }

  function renderDetailPanel(opportunity) {
    document.getElementById("pricebridge-opportunity-details")?.remove();
    const main = document.querySelector("main") || document.body;
    const panel = document.createElement("section");
    panel.id = "pricebridge-opportunity-details";
    panel.dataset.pbOpportunityPanel = "";

    const specs = (opportunity.specs || []).map((spec) => metric(spec.label, spec.value)).join("");
    const internalMetric = payload.can_view_internal_gain && opportunity.my_gain ? metric("İç kazanç", opportunity.my_gain) : "";

    panel.innerHTML = `
      <div class="pb-bagisto-panel-grid">
        <section class="pb-bagisto-panel-card">
          <span data-pb-opportunity-badge data-state="${escapeHtml(opportunity.recommendation_value || "watch")}">${escapeHtml(opportunity.recommendation || "Fırsat")}</span>
          <h2>${escapeHtml(opportunity.title)}</h2>
          <div class="pb-bagisto-metrics">
            ${metric("PriceBridge teklif fiyatı", opportunity.buyer_offer)}
            ${metric("Tedarikçi liste fiyatı", opportunity.supplier_price)}
            ${metric("Tedarikçi avantajı", opportunity.supplier_discount_label)}
            ${metric("Türkiye piyasa değeri", opportunity.turkiye_avg)}
            ${metric("Tahmini mağaza kazancı", opportunity.buyer_gain)}
            ${metric("Kazanç oranı", opportunity.buyer_gain_percent)}
            ${metric("İlan durumu", opportunity.availability_label)}
            ${internalMetric}${specs}
          </div>
          <h3>Türkiye karşılaştırma ilanları</h3>
          <p>Beklenen Türkiye satış değerini belirlemek için kullanılan benzer ilanlar.</p>
          ${evidenceList(payload.turkiye_rows, "Türkiye karşılaştırma ilanı bulunamadı.")}
        </section>
        <aside class="pb-bagisto-panel-card">
          <h2>Alım planı</h2>
          <p>Bu plan en fazla 6 telefon içerebilir. Laptop ve konsollar için mevcut bir sınır uygulanmıyor.</p>
          <div class="pb-detail-actions">
            <button type="button" data-pb-add-plan="${escapeHtml(`${opportunity.category || "opportunity"}:${opportunity.pk ?? opportunity.snapshot_id}`)}">Alım planına ekle</button>
            <button type="button" data-pb-add-plan="${escapeHtml(`${opportunity.category || "opportunity"}:${opportunity.pk ?? opportunity.snapshot_id}`)}" data-pb-immediate-close="1">Hemen Ayır</button>
          </div>
          <button type="button" class="pb-future-offer" disabled>Teklif oluştur yakında</button>
          ${payload.can_view_internal_gain ? `<h3>Cezayir alım kanıtları</h3>${evidenceList(payload.algeria_rows, "Cezayir alım kanıtı bulunamadı.")}` : ""}
        </aside>
      </div>`;

    const footer = document.querySelector("footer");
    if (footer?.parentElement) footer.parentElement.insertBefore(panel, footer);
    else main.append(panel);
  }

  function renderDetail() {
    const opportunity = payload.opportunity;
    if (!opportunity) return;
    setDetailIdentity(opportunity);
    renderDetailPanel(opportunity);
  }

  function suppressCapturedCommerceSemantics() {
    all("input,button,span,label,a,p,h1,h2,h3,h4,h5,h6").forEach((node) => {
      if (node.children.length > 2) return;
      if (node.closest(productSelector)) return;
      const value = lower(node);
      if (/qty|quantity|free shipping|shipping|checkout|review|frequently bought|bundle|add all to cart|delivery|courier/.test(value)) {
        const group = node.closest("section,form,article,li") || node.parentElement || node;
        if (group.querySelector?.(productSelector)) return;
        group.dataset.pbSuppressedCommerce = "";
        group.hidden = true;
      }
    });
    all('input[type="number"]').forEach((input) => {
      const label = lower(input.closest("label,div,form") || input);
      if (/qty|quantity|adet/.test(label)) input.closest("label,div,form").hidden = true;
    });
  }

  function run() {
    try {
      rewriteBranding();
      relocateMobileBottomNav();
      renderBrandFilters();
      rewriteShellLinks();
      installCapturedLinkGuard();
      configureSearch();
      suppressCapturedCommerceSemantics();
      if (payload.page === "opportunity-index") renderCatalog();
      else if (payload.page === "opportunity-detail") renderDetail();
      rewriteShellLinks();
      document.documentElement.dataset.pbFrontend = "preserved-bagisto-port";
    } catch (error) {
      console.error("PriceBridge Bagisto adaptation failed", error);
    } finally {
      document.documentElement.classList.remove("pb-bagisto-hydrating");
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run, { once: true });
  else run();
})();
