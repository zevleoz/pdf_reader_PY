import animate from "tailwindcss-animate";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        popover: { DEFAULT: "hsl(var(--popover))", foreground: "hsl(var(--popover-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        ink: { DEFAULT: "hsl(var(--ink))", 2: "hsl(var(--ink-2))" },
        mute: "hsl(var(--mute))",
        sunk: "hsl(var(--sunk))",
        line: "hsl(var(--line))",
        rule: "hsl(var(--rule))",
        shell: { DEFAULT: "hsl(var(--shell))", foreground: "hsl(var(--shell-foreground))" },
        on: { DEFAULT: "hsl(var(--on))", foreground: "hsl(var(--on-foreground))" },
        attention: "hsl(var(--attention))",
        tint: "hsl(var(--tint))",
        "rail-m1": "hsl(var(--rail-m1))",
        "rail-e4": "hsl(var(--rail-e4))",
      },
      fontFamily: {
        sans: ["Archivo", '"PingFang SC"', '"Hiragino Sans GB"', '"Microsoft YaHei"', '"Noto Sans SC"', "sans-serif"],
      },
      fontSize: {
        title: ["52px", { lineHeight: "1.05", letterSpacing: "-0.02em", fontWeight: "700" }],
        "title-sm": ["30px", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "700" }],
      },
      borderRadius: { none: "0", sm: "0", DEFAULT: "0", md: "0", lg: "0", xl: "0", "2xl": "0", "3xl": "0" },
      boxShadow: { sm: "none", DEFAULT: "none", md: "none", lg: "none", xl: "none", "2xl": "none", inner: "none" },
      height: { row: "54px" },
      width: { rail: "216px" },
    },
  },
  plugins: [animate],
};
