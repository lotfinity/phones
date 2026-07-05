/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: [
    "./market/templates/**/*.html",
    "./templates/**/*.html",
    "./market/**/*.py",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Monaco", "Consolas", "monospace"],
      },
      boxShadow: {
        soft: "0 18px 45px -30px rgb(15 23 42 / 0.45)",
      },
    },
  },
  plugins: [],
};
