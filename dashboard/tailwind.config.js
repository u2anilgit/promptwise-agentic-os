/** Semantic status colours (pass/warn/block) are deliberately separate from the brand accent. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        accent: { DEFAULT: "#4f46e5", fg: "#ffffff" },
        status: { pass: "#15803d", warn: "#b45309", block: "#b91c1c", unknown: "#475569" },
      },
    },
  },
  plugins: [],
};
