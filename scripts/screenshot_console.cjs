// 콘솔 스크린샷 — `node scripts/screenshot_console.cjs http://localhost:8000 docs/images`
// Playwright(Chromium) 로 탭별 화면을 찍는다. 실행 중인 API 가 필요하다.
const { chromium } = require("playwright");
const { mkdirSync } = require("node:fs");

(async () => {

const base = process.argv[2] || "http://localhost:8000";
const out = process.argv[3] || "docs/images";
mkdirSync(out, { recursive: true });
const exe = process.env.CHROMIUM_PATH || undefined;
const browser = await chromium.launch({ executablePath: exe, args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1.5, colorScheme: "light" });
page.on("pageerror", (e) => console.error("pageerror", e.message));
await page.goto(`${base}/console/`, { waitUntil: "networkidle" });
await page.waitForSelector("#kpis .tile", { timeout: 60000 });
await page.waitForTimeout(600);
await page.screenshot({ path: `${out}/console.png`, fullPage: false });
const tabs = ["patrol", "assets", "energy", "quality", "model"];
for (const t of tabs) {
  await page.click(`nav.tabs button[data-tab="${t}"]`);
  const ready = { patrol: "#patrol-table table", assets: "#asset-table table", energy: "#energy-line svg", quality: "#quality-table table", model: "#model-info dl" };
  await page.waitForSelector(ready[t], { timeout: 90000 });
  await page.waitForTimeout(700);
  if (t === "assets") {
    const row = page.locator("#asset-table tr.clickable").first();
    if (await row.count()) { await row.click(); await page.waitForSelector("#asset-detail .hero", { timeout: 30000 }); await page.waitForTimeout(600); }
  }
  await page.screenshot({ path: `${out}/console-${t}.png`, fullPage: t === "assets" || t === "patrol" });
}
await page.emulateMedia({ colorScheme: "dark" });
await page.click(`nav.tabs button[data-tab="overview"]`);
await page.waitForTimeout(800);
await page.screenshot({ path: `${out}/console-dark.png`, fullPage: false });
await browser.close();
console.log("screenshots written to", out);
})().catch((e) => { console.error(e); process.exit(1); });
