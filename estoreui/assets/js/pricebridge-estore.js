(() => {
  const root = document.documentElement;
  const storageKey = "pricebridge-estore-theme";
  const savedTheme = window.localStorage.getItem(storageKey);
  const preferredDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  const initialTheme = savedTheme || (preferredDark ? "dark" : "light");

  const applyTheme = (theme) => {
    root.dataset.theme = theme;
    root.classList.toggle("dark", theme === "dark");
    root.classList.toggle("light", theme !== "dark");
    root.style.colorScheme = theme;
  };

  applyTheme(initialTheme);

  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.addEventListener("click", () => {
      const nextTheme = root.dataset.theme === "dark" ? "light" : "dark";
      applyTheme(nextTheme);
      window.localStorage.setItem(storageKey, nextTheme);
    });
  });

  document.querySelectorAll("[data-listing-image]").forEach((image) => {
    image.addEventListener("error", () => {
      image.hidden = true;
      const parent = image.parentElement;
      const fallback = parent?.querySelector("[data-image-fallback]");
      fallback?.classList.remove("is-hidden");
    });
  });
})();
