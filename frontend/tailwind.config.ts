import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        ink: "#111827",
        mist: "#f3f4f6",
        sand: "#f8f4ec",
        pearl: "#fffdf9",
        clay: "#d97706",
        pine: "#14532d",
        ember: "#7c2d12",
        slate: "#475569",
        cloud: "#e2e8f0",
      },
      boxShadow: {
        card: "0 24px 70px -32px rgba(15, 23, 42, 0.35)",
        float: "0 18px 48px -24px rgba(15, 23, 42, 0.28)",
        insetGlow: "inset 0 1px 0 rgba(255, 255, 255, 0.7)",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "sans-serif"],
      },
      backgroundImage: {
        grid: "radial-gradient(circle at center, rgba(148, 163, 184, 0.15) 1px, transparent 1px)",
        halo:
          "radial-gradient(circle at top, rgba(251, 191, 36, 0.2), transparent 38%), radial-gradient(circle at 80% 20%, rgba(16, 185, 129, 0.16), transparent 32%), linear-gradient(180deg, rgba(255,255,255,0.72), rgba(255,255,255,0))",
      },
      keyframes: {
        rise: {
          "0%": { opacity: "0", transform: "translateY(14px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        rise: "rise 0.6s ease-out both",
      },
    },
  },
  plugins: [],
};

export default config;
