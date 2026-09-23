/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#08090a", 900: "#0d0f11", 850: "#131619", 800: "#1a1e22", 700: "#252b31" },
        spike: { DEFAULT: "#ccff00", dim: "#9bc400", glow: "#e4ff5c" },
        up: "#3ddc84",
        down: "#ff5c5c",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "monospace"],
      },
    },
  },
  plugins: [],
};
