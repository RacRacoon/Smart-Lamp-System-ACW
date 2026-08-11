const { defineConfig } = require("vitest/config");

module.exports = defineConfig({
  test: {
    // jsdom, bukan default "node": script.js akses `document`/`location`/`sessionStorage`
    // di level atas file (di luar fungsi) - tanpa jsdom, sekadar require('../script.js')
    // langsung ReferenceError sebelum sempat sampai ke fungsi yang mau ditest.
    environment: "jsdom",
    // describe/it/expect global (gaya Jest) - tanpa ini tiap file test harus
    // `import { describe, it, expect } from "vitest"` manual satu-satu.
    globals: true,
  },
});
