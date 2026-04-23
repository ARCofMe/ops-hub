import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 4177,
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/setupTests.js",
  },
});
