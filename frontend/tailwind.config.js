/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display: ["'Playfair Display'", "Georgia", "serif"],
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["'JetBrains Mono'", "monospace"],
      },
      colors: {
        ink: "#0f1115",
        panel: "#161922",
        edge: "#262b38",
        muted: "#8b93a7",
        accent: "#C26B3C",
      },
    },
  },
  plugins: [],
};
