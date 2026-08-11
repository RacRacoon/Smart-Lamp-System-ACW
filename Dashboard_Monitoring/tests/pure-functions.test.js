// Test buat 3 fungsi murni di script.js yang jadi lapis pertahanan XSS (escapeHtml,
// escapeJsString - lihat commit 01e8a3b) dan pembersih markdown balasan AI
// (stripMarkdownNoise). script.js sendiri masih file global-script biasa (bukan ES
// module) supaya semua onclick="..." inline di index.html tetap jalan apa adanya -
// diakses di sini lewat module.exports yang ditambahkan khusus buat test (lihat
// komentar di ujung script.js), bukan lewat import/refactor.
const { escapeHtml, escapeJsString, stripMarkdownNoise } = require("../script.js");

describe("escapeHtml", () => {
  it("meng-escape lima karakter HTML berbahaya", () => {
    expect(escapeHtml(`&<>"'`)).toBe("&amp;&lt;&gt;&quot;&#39;");
  });

  it("null/undefined jadi string kosong, bukan 'null'/'undefined'", () => {
    expect(escapeHtml(null)).toBe("");
    expect(escapeHtml(undefined)).toBe("");
  });

  it("teks polos tidak berubah", () => {
    expect(escapeHtml("L-101")).toBe("L-101");
  });

  it("angka ikut ke-stringify aman", () => {
    expect(escapeHtml(123)).toBe("123");
  });

  // Payload persis dari catatan commit 01e8a3b ("2 elemen <img onerror> hidup" sebelum
  // diperbaiki) - regresi buat celah XSS tersimpan lewat device_id/alert message.
  it("menutup payload img onerror", () => {
    const out = escapeHtml('<img src=x onerror=alert(1)>');
    expect(out).not.toContain("<img");
    expect(out).toContain("&lt;img");
  });
});

describe("escapeJsString", () => {
  it("meng-escape backslash dan kutip buat aman di dalam string literal JS", () => {
    expect(escapeJsString(`back\\slash 'single' "double"`))
      .toBe(`back\\\\slash \\'single\\' \\"double\\"`);
  });

  it("meng-escape '<' jadi \\x3C - penting di posisi onclick='...(\\'X\\')'", () => {
    // Setelah entity HTML di-decode browser, '<' polos masih bisa buka tag baru kalau
    // tidak ikut di-escape di lapis JS-string ini (beda dari escapeHtml yang cuma jalan
    // di lapis HTML, bukan di dalam atribut onclick).
    expect(escapeJsString("<script>")).toBe("\\x3Cscript>");
  });

  it("null/undefined jadi string kosong", () => {
    expect(escapeJsString(null)).toBe("");
    expect(escapeJsString(undefined)).toBe("");
  });

  it("meng-escape newline/carriage-return", () => {
    expect(escapeJsString("baris1\nbaris2\r")).toBe("baris1\\nbaris2\\r");
  });
});

describe("stripMarkdownNoise", () => {
  it("buang penanda bold **...**", () => {
    expect(stripMarkdownNoise("teks **tebal** biasa")).toBe("teks tebal biasa");
  });

  it("buang penanda underline __...__", () => {
    expect(stripMarkdownNoise("teks __tebal__ biasa")).toBe("teks tebal biasa");
  });

  it("buang heading #", () => {
    expect(stripMarkdownNoise("# Judul Besar")).toBe("Judul Besar");
  });

  it("ubah bullet -/* jadi bullet titik", () => {
    expect(stripMarkdownNoise("- poin pertama")).toBe("• poin pertama");
    expect(stripMarkdownNoise("* poin kedua")).toBe("• poin kedua");
  });

  it("teks kosong/null dibalikin apa adanya, tidak meledak", () => {
    expect(stripMarkdownNoise("")).toBe("");
    expect(stripMarkdownNoise(null)).toBe(null);
  });
});
