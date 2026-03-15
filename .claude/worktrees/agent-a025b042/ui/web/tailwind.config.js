/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: "#3485FA",
          50: "rgba(52, 133, 250, 0.2)",
          100: "rgba(52, 133, 250, 0.3)",
          500: "#3485FA",
          600: "#2A6DD6",
          light: "#449BFF",
        },
        positive: "#449BFF",
        negative: "#FA616D",
        surface: {
          DEFAULT: "#101013",
          body: "#17171C",
          elevated: "rgba(217, 217, 255, 0.07)",
          input: "rgba(217, 217, 255, 0.11)",
        },
        ink: {
          900: "rgba(253, 253, 254, 0.89)",
          700: "#E4E4E5",
          500: "#C3C3C6",
          300: "rgba(242, 242, 255, 0.47)",
          200: "#9E9EA4",
        },
      },
      fontFamily: {
        sans: [
          "Toss Product Sans",
          "Pretendard Variable",
          "Pretendard",
          "-apple-system",
          "system-ui",
          "Noto Sans KR",
          "sans-serif",
        ],
      },
      borderRadius: {
        sm: "4px",
        DEFAULT: "6px",
        md: "6px",
        lg: "8px",
        xl: "10px",
      },
    },
  },
  plugins: [],
};
