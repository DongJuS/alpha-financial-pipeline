/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Toss 스타일 컬러 팔레트
      colors: {
        brand: {
          DEFAULT: "#0019FF",
          50: "#EAF1FF",
          100: "#DDE7FF",
          500: "#0019FF",
          600: "#0013CC",
          700: "#000E99",
        },
        positive: "#0019FF",
        negative: "#E03131",
        surface: {
          DEFAULT: "#FFFFFF",
          muted: "#F2F4F6",
          border: "#E8EBEF",
        },
      },
      fontFamily: {
        sans: [
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
      },
      borderRadius: {
        xl: "16px",
        "2xl": "24px",
      },
    },
  },
  plugins: [],
};
