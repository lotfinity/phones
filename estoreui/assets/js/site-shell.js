(() => {
  "use strict";

  const root = document.documentElement;
  const THEME_KEY = "bagisto-theme";

  const all = (selector, scope = document) => [...scope.querySelectorAll(selector)];
  const normalizedText = (element) => element?.textContent?.replace(/\s+/g, " ").trim() || "";

  function themeSwitches() {
    return all('input[type="checkbox"][role="switch"]');
  }

  function storedTheme() {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === "light" || stored === "dark") return stored;

    if (root.classList.contains("dark")) return "dark";
    if (root.classList.contains("light")) return "light";

    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function applyTheme(theme, persist = true) {
    const dark = theme === "dark";

    root.classList.toggle("dark", dark);
    root.classList.toggle("light", !dark);
    root.style.colorScheme = dark ? "dark" : "light";

    themeSwitches().forEach((input) => {
      input.checked = dark;
      input.setAttribute("aria-checked", String(dark));

      const label = input.closest("label");
      if (label) label.dataset.selected = String(dark);
    });

    if (persist) localStorage.setItem(THEME_KEY, theme);
  }

  function initTheme() {
    applyTheme(storedTheme(), false);

    themeSwitches().forEach((input) => {
      input.addEventListener("change", () => {
        applyTheme(input.checked ? "dark" : "light");
      });
    });
  }

  function dialogs() {
    return all('[role="dialog"]');
  }

  function dialogHeading(dialog) {
    return normalizedText(dialog.querySelector("h1, h2, h3"));
  }

  function findDialog(name) {
    const expected = name.toLowerCase();
    return dialogs().find((dialog) => dialogHeading(dialog).toLowerCase() === expected);
  }

  function overlayFor(dialog) {
    const previous = dialog?.previousElementSibling;
    if (!previous) return null;

    return previous.classList.contains("fixed") && previous.classList.contains("inset-0")
      ? previous
      : null;
  }

  function setOverlayState(overlay, open) {
    if (!overlay) return;

    overlay.classList.toggle("opacity-0", !open);
    overlay.classList.toggle("opacity-100", open);
    overlay.classList.toggle("pointer-events-none", !open);
    overlay.hidden = false;
  }

  function openDialog(dialog) {
    if (!dialog) return;

    dialog.hidden = false;
    dialog.classList.remove("translate-x-full");
    dialog.classList.add("translate-x-0");
    dialog.setAttribute("aria-hidden", "false");

    setOverlayState(overlayFor(dialog), true);
    document.body.style.overflow = "hidden";

    const focusTarget = dialog.querySelector("input, button, [href], select, textarea");
    window.setTimeout(() => focusTarget?.focus(), 50);
  }

  function closeDialog(dialog) {
    if (!dialog) return;

    dialog.classList.remove("translate-x-0");
    dialog.classList.add("translate-x-full");
    dialog.setAttribute("aria-hidden", "true");

    setOverlayState(overlayFor(dialog), false);
    document.body.style.overflow = "";
  }

  function initDialogs() {
    dialogs().forEach((dialog) => {
      closeDialog(dialog);

      const overlay = overlayFor(dialog);
      overlay?.addEventListener("click", () => closeDialog(dialog));

      const firstButton = dialog.querySelector("button");
      firstButton?.addEventListener("click", () => closeDialog(dialog));
    });

    all("header button").forEach((button) => {
      let sibling = button.nextElementSibling;

      while (sibling && sibling.getAttribute("role") !== "dialog") {
        sibling = sibling.nextElementSibling;
      }

      if (sibling?.getAttribute("role") === "dialog") {
        button.addEventListener("click", () => openDialog(sibling));
      }
    });
  }

  function initMobileNavigation() {
    const cartDialog = findDialog("Shopping Cart");
    const categoryDestination = all('header a[href]').find(
      (link) => normalizedText(link) === "All",
    )?.href || "/search";

    all("button").forEach((button) => {
      const text = normalizedText(button);

      if (text === "Cart") {
        button.addEventListener("click", () => openDialog(cartDialog));
      }

      if (text === "Categories") {
        button.addEventListener("click", () => {
          window.location.href = categoryDestination;
        });
      }

      if (text === "Account") {
        button.addEventListener("click", () => {
          window.location.href = "https://bagisto-headless-electronic.vercel.app/customer-details";
        });
      }
    });
  }

  function listboxes() {
    return all('[role="listbox"]');
  }

  function triggerForListbox(listbox) {
    const previous = listbox.previousElementSibling;
    if (previous?.tagName === "BUTTON") return previous;

    const parent = listbox.parentElement;
    if (!parent) return null;

    return parent.querySelector('button[aria-haspopup="listbox"]')
      || [...parent.children].find((child) => child.tagName === "BUTTON")
      || null;
  }

  function listboxIsOpen(listbox) {
    return !listbox.classList.contains("pointer-events-none")
      && !listbox.classList.contains("opacity-0");
  }

  function setListboxState(listbox, open) {
    const trigger = triggerForListbox(listbox);

    listbox.hidden = false;
    listbox.classList.toggle("pointer-events-none", !open);
    listbox.classList.toggle("opacity-0", !open);
    listbox.classList.toggle("-translate-y-1", !open);
    listbox.classList.toggle("opacity-100", open);
    listbox.classList.toggle("translate-y-0", open);

    trigger?.setAttribute("aria-expanded", String(open));

    const icon = trigger?.querySelector("svg:last-child");
    icon?.classList.toggle("rotate-180", open);
  }

  function closeListboxes(except = null) {
    listboxes().forEach((listbox) => {
      if (listbox !== except) setListboxState(listbox, false);
    });
  }

  function selectListboxOption(listbox, option) {
    const trigger = triggerForListbox(listbox);
    if (!trigger) return;

    const value = normalizedText(option.querySelector("span") || option);
    const label = trigger.querySelector("span.truncate, span.flex-1, span");

    if (label) label.textContent = value;

    trigger.classList.remove("text-neutral-400", "dark:text-neutral-500");
    trigger.classList.add("text-neutral-900", "dark:text-white");

    all('[role="option"]', listbox).forEach((candidate) => {
      const selected = candidate === option;
      candidate.setAttribute("aria-selected", String(selected));
      candidate.classList.toggle("bg-emerald-50", selected);
      candidate.classList.toggle("dark:bg-emerald-900/20", selected);
      candidate.classList.toggle("text-emerald-700", selected);
      candidate.classList.toggle("dark:text-emerald-400", selected);
      candidate.classList.toggle("font-medium", selected);
    });

    setListboxState(listbox, false);
    trigger.focus();
  }

  function initListboxes() {
    listboxes().forEach((listbox) => {
      const trigger = triggerForListbox(listbox);
      if (!trigger) return;

      trigger.setAttribute("aria-haspopup", "listbox");
      setListboxState(listbox, false);

      trigger.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();

        const willOpen = !listboxIsOpen(listbox);
        closeListboxes(listbox);
        setListboxState(listbox, willOpen);
      });

      all('[role="option"]', listbox).forEach((option) => {
        option.addEventListener("click", (event) => {
          event.preventDefault();
          event.stopPropagation();
          selectListboxOption(listbox, option);
        });
      });
    });

    document.addEventListener("click", (event) => {
      listboxes().forEach((listbox) => {
        const trigger = triggerForListbox(listbox);
        if (listbox.contains(event.target) || trigger?.contains(event.target)) return;
        setListboxState(listbox, false);
      });
    });
  }

  function initProductGallery() {
    const mainImage = document.querySelector("main img.object-cover.transition-transform");
    if (!mainImage) return;

    const thumbnailButtons = all("main button").filter((button) => {
      return Boolean(button.querySelector("img")) && button.classList.contains("aspect-square");
    });

    thumbnailButtons.forEach((button) => {
      button.addEventListener("click", () => {
        const image = button.querySelector("img");
        if (!image?.src) return;

        mainImage.src = image.src;
        mainImage.srcset = image.srcset || "";

        thumbnailButtons.forEach((item) => {
          item.classList.remove("border-neutral-900", "dark:border-white", "ring-2");
          item.classList.add("border-transparent");
        });

        button.classList.remove("border-transparent");
        button.classList.add("border-neutral-900", "dark:border-white", "ring-2");
      });
    });
  }

  function initQuantityControls() {
    all("main").forEach((main) => {
      all("div", main).forEach((container) => {
        const buttons = [...container.children].filter((child) => child.tagName === "BUTTON");
        if (buttons.length !== 2) return;

        const valueNode = [...container.children].find((child) => {
          return child.tagName === "DIV" && /^\d+$/.test(normalizedText(child));
        });

        if (!valueNode) return;

        const [decrease, increase] = buttons;
        decrease.addEventListener("click", () => {
          const current = Number.parseInt(normalizedText(valueNode), 10) || 1;
          valueNode.textContent = String(Math.max(1, current - 1));
        });

        increase.addEventListener("click", () => {
          const current = Number.parseInt(normalizedText(valueNode), 10) || 1;
          valueNode.textContent = String(current + 1);
        });
      });
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;

    dialogs()
      .filter((dialog) => !dialog.classList.contains("translate-x-full"))
      .forEach(closeDialog);

    closeListboxes();
  });

  document.addEventListener("DOMContentLoaded", () => {
    initTheme();
    initDialogs();
    initMobileNavigation();
    initListboxes();
    initProductGallery();
    initQuantityControls();
  });
})();
