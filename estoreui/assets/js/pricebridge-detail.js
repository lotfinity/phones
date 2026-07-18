(() => {
  "use strict";

  const config = window.PriceBridgePage || {};
  if (config.page !== "opportunity-detail" || !config.api_url) return;

  const all = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const text = (node) => (node?.textContent || "").replace(/\s+/g, " ").trim();
  const lower = (node) => text(node).toLocaleLowerCase("tr-TR");
  const pricePattern = /(?:[$€£₺]|\b(?:USD|EUR|TRY|TL|DZD)\b)\s*[\d.,]+|[\d.,]+\s*(?:[$€£₺]|\b(?:USD|EUR|TRY|TL|DZD)\b)/i;
  const capturedDetailPattern = /HD Computer Monitor|VisionCraft|UltraView|Display Size|Full HD 1920x1080|Panel Type|Refresh Rate|Response Time|Connectivity|Mount Support|Matte Black|SoundNova|Stereo 2\.0 Speakers|USB-Powered|3\.5mm Aux/i;

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

  function leafTextCandidates(scope) {
    return all("h1,h2,h3,h4,h5,h6,a,p,span,strong", scope)
      .filter((node) => !node.querySelector("img,svg"))
      .filter((node) => {
        const value = text(node);
        return value.length >= 3 && value.length <= 180;
      });
  }

  function isDetailContentNode(node) {
    return !node.closest("header,footer,[role='dialog'],[aria-hidden='true']");
  }

  function isVisibleNode(node) {
    if (!node || node.hidden || node.getAttribute("aria-hidden") === "true") return false;
    const styles = window.getComputedStyle(node);
    if (styles.display === "none" || styles.visibility === "hidden") return false;
    return Boolean(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
  }

  function findDetailHeading(scope) {
    const headings = all("h1,h2", scope)
      .filter(isDetailContentNode)
      .filter((node) => text(node).length >= 3);
    return headings.find(isVisibleNode) || headings[0] || null;
  }

  function findTitleNode(scope) {
    const headings = all("h1,h2,h3,h4,h5,h6", scope).filter((node) => text(node).length >= 3);
    if (headings.length) return headings.sort((a, b) => text(b).length - text(a).length)[0];
    return leafTextCandidates(scope).find((node) => {
      const value = text(node);
      return !pricePattern.test(value) && !/add to cart|wishlist|compare|buy now|view/i.test(value);
    }) || null;
  }

  function hideNode(node) {
    if (!node) return;
    node.dataset.pbSuppressedCapturedCommerce = "";
    node.hidden = true;
    node.setAttribute("aria-hidden", "true");
  }

  function findTextNode(pattern, selector = "h1,h2,h3,h4,h5,h6,p,span,strong,label,a,button") {
    return all(selector, document).find((node) => pattern.test(text(node)));
  }

  function closestBlock(node) {
    return node?.closest("section,article,aside,div") || null;
  }

  function setLeafText(node, value) {
    if (!node) return;
    node.textContent = value;
  }

  function setLink(node, href, label) {
    if (!node) return;
    node.textContent = label;
    if (node.tagName === "A") {
      node.href = href || "#";
      if (href && href !== "#") {
        node.target = "_blank";
        node.rel = "noopener noreferrer";
      }
    }
  }

  function setProductImage(scope, opportunity) {
    const images = all("img", scope).filter((image) => {
      const source = `${image.getAttribute("src") || ""} ${image.getAttribute("alt") || ""}`;
      return !/logo|icon|flag|avatar/i.test(source);
    });
    const source = opportunity.has_image && opportunity.image_url
      ? opportunity.image_url
      : (opportunity.brand_logo_url || svgFallback(opportunity.title));

    images.slice(0, 6).forEach((image, index) => {
      image.src = source;
      image.removeAttribute("srcset");
      image.alt = index === 0 ? opportunity.title : `${opportunity.title} görseli`;
      image.loading = index === 0 ? "eager" : "lazy";
      image.addEventListener("error", () => {
        image.src = svgFallback(opportunity.title);
      }, {once: true});
    });
  }

  function priceNodes(scope) {
    return all("span,strong,p,div", scope)
      .filter((node) => node.children.length === 0)
      .filter((node) => pricePattern.test(text(node)));
  }

  function replacePrices(scope) {
    priceNodes(scope).forEach((node) => {
      node.dataset.pbCapturedPrice = "";
      node.textContent = "";
      node.hidden = true;
    });
  }

  function confidenceStars(opportunity) {
    const score = Number(opportunity.confidence_score) || 0;
    const stars = Math.max(1, Math.min(5, Number(opportunity.confidence_stars) || Math.round(score / 20) || 1));
    const wrapper = document.createElement("span");
    wrapper.className = "pb-confidence-stars";
    wrapper.setAttribute("aria-label", opportunity.confidence_aria_label || `Veri güveni ${score} / 100`);
    wrapper.setAttribute("title", opportunity.confidence_title || `Veri güveni: %${score}`);
    wrapper.innerHTML = `${"★".repeat(stars)}${"☆".repeat(5 - stars)}<span class="sr-only"> ${score} / 100</span>`;
    return wrapper;
  }

  function availabilityBadge(opportunity) {
    const badge = document.createElement("span");
    badge.dataset.pbAvailability = opportunity.availability_state || "verification_required";
    badge.textContent = opportunity.availability_label || "Güncellik doğrulanmalı";
    return badge;
  }

  function pricingBlock(opportunity) {
    const wrapper = document.createElement("div");
    wrapper.className = "pb-card-pricing";
    wrapper.dataset.pbCardPricing = "";

    const current = document.createElement("strong");
    current.className = "pb-card-pricing__current";
    current.textContent = opportunity.buyer_offer || "Teklif fiyatı hesaplanmadı";
    wrapper.append(current);

    const label = document.createElement("small");
    label.textContent = "PriceBridge teklif fiyatı";
    wrapper.append(label);

    if (opportunity.turkiye_avg) {
      const market = document.createElement("span");
      market.textContent = `Türkiye piyasa değeri: ${opportunity.turkiye_avg}`;
      wrapper.append(market);
    }
    if (opportunity.buyer_gain) {
      const gain = document.createElement("span");
      gain.textContent = `Tahmini kazanç: ${opportunity.buyer_gain}${opportunity.buyer_gain_percent ? ` (${opportunity.buyer_gain_percent})` : ""}`;
      wrapper.append(gain);
    }
    return wrapper;
  }

  function detailSpecLine(opportunity) {
    return [
      opportunity.subtitle,
      opportunity.condition,
      opportunity.battery_health ? `Batarya %${opportunity.battery_health}` : "",
    ].filter(Boolean).join(" · ");
  }

  function productDescriptionText(opportunity) {
    const rows = [
      ["Brand", opportunity.brand],
      ["Model", opportunity.model],
      ["Category", opportunity.category_label],
      ["Condition", opportunity.condition],
      ["Recommendation", opportunity.recommendation],
      ["Confidence", `${opportunity.confidence_score || 0}/100`],
      ["PriceBridge Offer", opportunity.buyer_offer],
      ["Offer DZD", opportunity.buyer_offer_dzd],
      ["Türkiye Average", opportunity.turkiye_avg],
      ["Buyer Gain", [opportunity.buyer_gain, opportunity.buyer_gain_percent].filter(Boolean).join(" · ")],
      ["Availability", opportunity.availability_label],
      ...(opportunity.detail_specs || opportunity.specs || []).map((spec) => [spec.label, spec.value]),
    ].filter((row) => row[1] !== null && row[1] !== undefined && row[1] !== "");

    return rows.map(([label, value]) => `${label}: ${value}`).join(",\n");
  }

  function detailSpecRows(opportunity) {
    if (Array.isArray(opportunity.detail_specs) && opportunity.detail_specs.length) {
      return opportunity.detail_specs.map((spec) => [spec.label, spec.value]);
    }
    return [
      ["Brand", opportunity.brand],
      ["Model", opportunity.model],
      ["Spec", opportunity.subtitle || opportunity.spec],
      ["Condition", opportunity.condition],
      ...(opportunity.specs || []).map((spec) => [spec.label, spec.value]),
      ["Original Price", opportunity.buyer_offer_dzd],
      ["Price in EUR", opportunity.algeria_min_eur],
    ];
  }

  function rewriteProductDescription(opportunity) {
    const paragraph = all("p.line-clamp-4, p").find((node) => {
      const value = text(node);
      return node.className?.includes?.("line-clamp-4")
        || /^Brand:\s*(Cryonix|SoundNova)/i.test(value);
    });
    if (!paragraph) return;
    paragraph.hidden = false;
    paragraph.removeAttribute("aria-hidden");
    delete paragraph.dataset.pbSuppressedCapturedCommerce;
    paragraph.dataset.pbProductDescription = "true";
    paragraph.textContent = productDescriptionText(opportunity);
  }

  function suppressCapturedDetailCopy(scope) {
    all("h1,h2,h3,h4,h5,h6,p,span,strong,li,dt,dd", scope).forEach((node) => {
      if (node.closest("[data-pb-opportunity-panel],[data-pb-detail-summary]")) return;
      if (node.matches("[data-pb-product-description]")) return;
      if (!capturedDetailPattern.test(text(node))) return;
      hideNode(node);
    });
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

  function renderDetailPanel(opportunity, evidence) {
    document.getElementById("pricebridge-opportunity-details")?.remove();
    const main = document.querySelector("main") || document.body;
    const panel = document.createElement("section");
    panel.id = "pricebridge-opportunity-details";
    panel.dataset.pbOpportunityPanel = "";

    const specs = (opportunity.specs || []).map((spec) => metric(spec.label, spec.value)).join("");
    panel.innerHTML = `
      <div class="pb-bagisto-panel-grid">
        <section class="pb-bagisto-panel-card">
          <span data-pb-opportunity-badge data-state="${escapeHtml(opportunity.recommendation_value || "watch")}">${escapeHtml(opportunity.recommendation || "Fırsat")}</span>
          <h2>${escapeHtml(opportunity.title)}</h2>
          <div class="pb-bagisto-metrics">
            ${metric("PriceBridge teklif fiyatı", opportunity.buyer_offer)}
            ${metric("Türkiye piyasa değeri", opportunity.turkiye_avg)}
            ${metric("Tahmini kazanç", opportunity.buyer_gain)}
            ${metric("Kazanç oranı", opportunity.buyer_gain_percent)}
            ${metric("İlan durumu", opportunity.availability_label)}
            ${specs}
          </div>
          <h3>Türkiye karşılaştırma ilanları</h3>
          <p>Beklenen Türkiye satış değerini belirlemek için kullanılan benzer ilanlar.</p>
          ${evidenceList(evidence?.turkiye, "Türkiye karşılaştırma ilanı bulunamadı.")}
        </section>
        <aside class="pb-bagisto-panel-card">
          <h2>Alım planı</h2>
          <p>Bu kayıt API üzerinden yüklendi. Harici frontendler aynı endpoint sözleşmesini kullanabilir.</p>
          <div class="pb-detail-actions">
            <button type="button" data-pb-add-plan="${escapeHtml(`${opportunity.category || "opportunity"}:${opportunity.pk ?? opportunity.snapshot_id}`)}">Alım planına ekle</button>
            <button type="button" data-pb-add-plan="${escapeHtml(`${opportunity.category || "opportunity"}:${opportunity.pk ?? opportunity.snapshot_id}`)}" data-pb-immediate-close="1">Hemen Ayır</button>
          </div>
        </aside>
      </div>`;

    const footer = document.querySelector("footer");
    if (footer?.parentElement) footer.parentElement.insertBefore(panel, footer);
    else main.append(panel);
  }

  function rewriteAvailabilityCard(opportunity) {
    const locationHeading = findTextNode(/^Location$/i);
    const card = closestBlock(locationHeading)?.parentElement || closestBlock(findTextNode(/^Available$/i));
    if (!card) return;
    card.dataset.pbRepurposedAvailability = "true";

    const sourceUrl = safeUrl(opportunity.source_listing_url, "#");
    const observed = opportunity.source_observed_at
      ? new Date(opportunity.source_observed_at).toLocaleString()
      : "Kaynak zamanı yok";
    const generated = opportunity.generated_at
      ? new Date(opportunity.generated_at).toLocaleString()
      : "";

    const locationBlock = closestBlock(locationHeading);
    if (locationBlock) {
      const headings = all("h1,h2,h3,h4,h5,h6,strong,p,span,a", locationBlock).filter((node) => text(node));
      setLeafText(headings[0], "Kaynak ilan");
      setLeafText(headings[1], [
        opportunity.source_listing_id ? `Clean listing #${opportunity.source_listing_id}` : "",
        opportunity.condition,
      ].filter(Boolean).join(" · ") || "Kaynak eşleşmesi");
      const link = all("a", locationBlock).find((node) => /map|view|open|source|ilan/i.test(text(node))) || all("a", locationBlock)[0];
      setLink(link, sourceUrl, sourceUrl === "#" ? "Kaynak link yok" : "Kaynak ilanı aç");
    }

    const availableHeading = findTextNode(/^Available$/i);
    const availableBlock = closestBlock(availableHeading);
    if (availableBlock) {
      const values = all("h1,h2,h3,h4,h5,h6,strong,p,span", availableBlock).filter((node) => text(node));
      setLeafText(values[0], opportunity.availability_label || "Güncellik doğrulanmalı");
      setLeafText(values[1], [
        observed,
        generated ? `Hesaplama ${generated}` : "",
      ].filter(Boolean).join(" · "));
    }

    const selectDate = findTextNode(/^Select Date$/i, "label,h1,h2,h3,h4,p,span");
    if (selectDate) setLeafText(selectDate, "PriceBridge teklif fiyatı");
    const dateInput = all("input", card).find((input) => /date/i.test(input.placeholder || input.value || input.name || ""));
    if (dateInput) {
      dateInput.value = opportunity.buyer_offer || "";
      dateInput.placeholder = opportunity.buyer_offer || "Teklif fiyatı yok";
      dateInput.readOnly = true;
    }

    const slots = findTextNode(/^Available Slots$/i, "label,h1,h2,h3,h4,p,span");
    if (slots) setLeafText(slots, "Türkiye piyasa değeri");
    const slotControl = all("button,select,input,span,p", card).find((node) => /select a date first/i.test(text(node) || node.placeholder || ""));
    if (slotControl) {
      if ("value" in slotControl) slotControl.value = opportunity.turkiye_avg || "";
      slotControl.textContent = opportunity.turkiye_avg || "Karşılaştırma yok";
      slotControl.setAttribute?.("aria-label", "Türkiye piyasa değeri");
    }
  }

  function rewriteQuantityAndUtilityRows(opportunity, evidence) {
    const qty = findTextNode(/^Qty:?$/i);
    if (qty) {
      setLeafText(qty, "Kanıt:");
      const row = closestBlock(qty)?.parentElement || closestBlock(qty);
      const numberNodes = all("span,strong,button", row).filter((node) => /^[-+\d]+$/.test(text(node)));
      if (numberNodes[0]) setLeafText(numberNodes[0], "DZ");
      if (numberNodes[1]) setLeafText(numberNodes[1], String(opportunity.algeria_count || 0));
      if (numberNodes[2]) setLeafText(numberNodes[2], "TR");
    }

    const wishlist = findTextNode(/Add to Wishlist/i, "a,button,span,p");
    if (wishlist) {
      const button = wishlist.closest("a,button") || wishlist;
      setLeafText(wishlist, "Takibe al");
      button.dataset.pbTrackOpportunity = opportunity.plan_key || "";
    }

    const compare = findTextNode(/Add to Compare/i, "a,button,span,p");
    if (compare) {
      const button = compare.closest("a,button") || compare;
      setLeafText(compare, `TR karşılaştırmaları (${evidence?.turkiye?.length || 0})`);
      button.addEventListener("click", (event) => {
        event.preventDefault();
        document.getElementById("pricebridge-opportunity-details")?.scrollIntoView({behavior: "smooth"});
      }, {once: true});
    }

    const share = findTextNode(/^Share:?$/i, "span,p,strong");
    if (share) setLeafText(share, "Kaynak:");
  }

  function rewriteShippingInfo(opportunity) {
    const heading = findTextNode(/^Shipping Info$/i, "h1,h2,h3,h4,strong,p,span");
    const card = closestBlock(heading);
    if (!card) return;
    card.dataset.pbRepurposedShipping = "true";
    setLeafText(heading, "Deal Math");

    const rows = all("p,span,strong", card).filter((node) => text(node));
    const labels = [
      ["PriceBridge teklif fiyatı", opportunity.buyer_offer || "-"],
      ["Türkiye piyasa değeri", opportunity.turkiye_avg || "-"],
      ["Tahmini alıcı avantajı", [opportunity.buyer_gain, opportunity.buyer_gain_percent].filter(Boolean).join(" · ") || "-"],
    ];

    labels.forEach(([label, value], index) => {
      const labelNode = rows[index * 2 + 1] || rows[index];
      const valueNode = rows[index * 2 + 2];
      setLeafText(labelNode, label);
      if (valueNode) setLeafText(valueNode, value);
    });
  }

  function rewriteAttributesTable(opportunity) {
    const attributeHeader = findTextNode(/^ATTRIBUTE$/i, "th,td,span,strong,p");
    const table = attributeHeader?.closest("table");
    if (!table) return;
    table.dataset.pbRepurposedAttributes = "true";

    const rows = detailSpecRows(opportunity)
      .filter((row) => row[1] !== null && row[1] !== undefined && row[1] !== "");

    table.innerHTML = `
      <thead class="bg-neutral-50 dark:bg-neutral-800/50">
        <tr>
          <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-500 dark:text-neutral-400">Attribute</th>
          <th class="px-4 py-3 text-left text-xs font-medium uppercase tracking-wider text-neutral-500 dark:text-neutral-400">Value</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-neutral-200 bg-white dark:divide-neutral-800 dark:bg-neutral-900">
        ${rows.map(([label, value]) => `
          <tr>
            <td class="px-4 py-3 text-sm text-neutral-700 dark:text-neutral-300">${escapeHtml(label)}</td>
            <td class="px-4 py-3 text-sm text-neutral-700 dark:text-neutral-300">${escapeHtml(value)}</td>
          </tr>
        `).join("")}
      </tbody>`;
  }

  function updateTabButton(button, active) {
    if (!button) return;
    button.classList.toggle("text-neutral-900", active);
    button.classList.toggle("dark:text-white", active);
    button.classList.toggle("text-neutral-400", !active);
    button.classList.toggle("dark:text-neutral-500", !active);
    button.setAttribute("aria-selected", active ? "true" : "false");
  }

  function comparableReviewRows(rows) {
    if (!rows?.length) {
      return `<p class="text-sm text-neutral-500 dark:text-neutral-400">Türkiye karşılaştırma ilanı bulunamadı.</p>`;
    }
    return `
      <div class="grid gap-3 md:grid-cols-2">
        ${rows.map((row) => {
          const title = row.title || "Türkiye karşılaştırması";
          const href = safeUrl(row.listing_url, "#");
          const secondary = [row.source_name, row.price_eur, row.condition].filter(Boolean).join(" · ");
          const image = row.image_url
            ? `<img src="${escapeHtml(row.image_url)}" alt="${escapeHtml(title)}" loading="lazy" class="h-16 w-16 rounded-lg object-cover bg-neutral-100 dark:bg-neutral-800">`
            : "";
          return `
            <a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" class="flex gap-3 rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 text-sm transition-colors hover:border-neutral-300 dark:hover:border-neutral-700">
              ${image}
              <span class="min-w-0">
                <strong class="block truncate text-neutral-900 dark:text-white">${escapeHtml(title)}</strong>
                <small class="block text-neutral-500 dark:text-neutral-400">${escapeHtml(secondary)}</small>
              </span>
            </a>`;
        }).join("")}
      </div>`;
  }

  function rewriteComparableReviewsTab(opportunity, evidence) {
    const rows = evidence?.turkiye || [];
    const table = document.querySelector("[data-pb-detail-spec-table]") || findTextNode(/^ATTRIBUTE$/i, "th,td,span,strong,p")?.closest("table");
    if (!table) return;

    const tabsSection = table.closest(".w-full") || table.closest("main");
    const tabBar = tabsSection
      ? all("button", tabsSection).find((button) => /^Description$/i.test(text(button)))?.parentElement
      : null;
    if (!tabBar) return;
    const descriptionButton = all("button", tabBar).find((button) => /^Description$/i.test(text(button)));
    const reviewsButton = all("button", tabBar).find((button) => /^(Reviews|Türkiye Comparables)/i.test(text(button)));
    const indicator = tabBar.parentElement?.querySelector("span.absolute.bottom-0");
    if (!descriptionButton || !reviewsButton) return;

    const descriptionPanel = table.closest("[data-pb-description-panel]")
      || table.closest(".overflow-x-auto")
      || table.parentElement;
    if (!descriptionPanel) return;
    descriptionPanel.dataset.pbDescriptionPanel = "true";

    const tabHost = descriptionPanel.parentElement || descriptionPanel;
    let comparablesPanel = document.querySelector("[data-pb-comparables-panel]");
    if (!comparablesPanel) {
      comparablesPanel = document.createElement("section");
      comparablesPanel.dataset.pbComparablesPanel = "";
      comparablesPanel.className = "mt-6 animate-in fade-in duration-300";
      tabHost.append(comparablesPanel);
    } else if (comparablesPanel.parentElement !== tabHost) {
      tabHost.append(comparablesPanel);
    }

    reviewsButton.type = "button";
    descriptionButton.type = "button";
    tabBar.setAttribute("role", "tablist");
    descriptionButton.setAttribute("role", "tab");
    reviewsButton.setAttribute("role", "tab");
    descriptionButton.style.cursor = "pointer";
    reviewsButton.style.cursor = "pointer";
    reviewsButton.textContent = `Türkiye Comparables (${rows.length || opportunity.turkiye_count || 0})`;
    comparablesPanel.innerHTML = `
      <div class="mb-4">
        <h3 class="text-base font-semibold text-neutral-900 dark:text-white">Türkiye karşılaştırma ilanları</h3>
        <p class="text-sm text-neutral-500 dark:text-neutral-400">Sahibinden ortalamasını oluşturan benzer ilanlar.</p>
      </div>
      ${comparableReviewRows(rows)}
    `;

    const activate = (mode) => {
      const showingDescription = mode === "description";
      descriptionPanel.hidden = !showingDescription;
      comparablesPanel.hidden = showingDescription;
      updateTabButton(descriptionButton, showingDescription);
      updateTabButton(reviewsButton, !showingDescription);
      if (indicator) {
        const activeButton = showingDescription ? descriptionButton : reviewsButton;
        indicator.style.left = `${activeButton.offsetLeft}px`;
        indicator.style.width = `${activeButton.offsetWidth}px`;
      }
    };

    descriptionButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      activate("description");
    });
    reviewsButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      activate("comparables");
    });
    activate("description");
  }

  function rewriteServiceCards(opportunity, evidence) {
    const serviceCards = all("footer ~ div, main > div").flatMap((scope) => all("p", scope))
      .filter((node) => /shipping|replacement|EMI|support/i.test(text(node)))
      .map((node) => closestBlock(node))
      .filter(Boolean);
    const unique = [...new Set(serviceCards)].slice(0, 4);
    const values = [
      `Veri güveni ${opportunity.confidence_score || 0}/100`,
      `${opportunity.availability_label || "Güncellik doğrulanmalı"}`,
      `DZ ${opportunity.algeria_count || 0} / TR ${opportunity.turkiye_count || 0}`,
      `${evidence?.turkiye?.length || 0} Türkiye karşılaştırması`,
    ];
    unique.forEach((card, index) => {
      const label = all("p,span,strong", card).find((node) => text(node));
      setLeafText(label, values[index]);
    });
  }

  function repurposeCapturedProductBlocks(opportunity, evidence) {
    rewriteAvailabilityCard(opportunity);
    rewriteQuantityAndUtilityRows(opportunity, evidence);
    rewriteShippingInfo(opportunity);
    rewriteAttributesTable(opportunity);
    rewriteComparableReviewsTab(opportunity, evidence);
    rewriteServiceCards(opportunity, evidence);
  }

  function rewriteActions(opportunity) {
    all("main button, main a").forEach((node) => {
      const label = lower(node);
      if (!/add to cart|buy now|sepete ekle|satın al/.test(label)) return;
      node.textContent = /buy now|satın al/.test(label) ? "Hemen Ayır" : "Alım planına ekle";
      node.dataset.pbAddPlan = `${opportunity.category || "opportunity"}:${opportunity.pk ?? opportunity.snapshot_id}`;
      if (/buy now|satın al/.test(label)) node.dataset.pbImmediateClose = "1";
      if (node.tagName === "A") node.href = "#";
    });
  }

  function render(payload) {
    const opportunity = payload.opportunity;
    if (!opportunity) return;

    document.title = `${opportunity.title} · PriceBridge`;
    const main = document.querySelector("main") || document.body;
    const heading = findDetailHeading(main) || findTitleNode(main);
    if (heading) heading.textContent = opportunity.title;
    setProductImage(main, opportunity);
    rewriteProductDescription(opportunity);
    replacePrices(main);
    suppressCapturedDetailCopy(main);
    repurposeCapturedProductBlocks(opportunity, payload.evidence || {});
    renderDetailSummary(main, heading, opportunity);
    renderDetailPanel(opportunity, payload.evidence || {});
    rewriteActions(opportunity);
    document.documentElement.dataset.pbFrontend = "api-driven-bagisto-port";
  }

  async function load() {
    try {
      const response = await fetch(config.api_url, {
        credentials: "include",
        headers: {"Accept": "application/json"},
      });
      if (!response.ok) throw new Error(`API returned ${response.status}`);
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || "API returned an error");
      render(payload);
      window.PriceBridgeOpportunityPayload = payload;
      document.dispatchEvent(new CustomEvent("pricebridge:opportunities-loaded", { detail: payload }));
    } catch (error) {
      const main = document.querySelector("main") || document.body;
      const node = document.createElement("div");
      node.className = "pb-bagisto-panel-card";
      node.textContent = `Could not load PriceBridge opportunity detail. ${error.message}`;
      main.prepend(node);
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load, {once: true});
  else load();
})();
