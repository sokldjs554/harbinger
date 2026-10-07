// 콘솔 스크린샷 — `node scripts/screenshot_console.cjs http://localhost:8000 docs/images /console/` (정적 데모는 마지막 인자에 "/")
// Playwright(Chromium)로 문서용 화면을 찍는다. 라이브 API 또는 정적 데모가 필요하다.
const { chromium } = require("playwright");
const { mkdirSync } = require("node:fs");

(async () => {
  const base = process.argv[2] || "http://localhost:8000";
  const out = process.argv[3] || "docs/images";
  const pagePath = process.argv[4] || "/console/";
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1.5, colorScheme: "light" });
  page.on("pageerror", (e) => console.error("pageerror", e.message));
  const wait = (sel, t = 90000) => page.waitForSelector(sel, { timeout: t });
  const tab = async (name, ready) => { await page.click(`nav.tabs button[data-tab="${name}"]`); await wait(ready); await page.waitForTimeout(700); };

  await page.goto(`${base}${pagePath}`, { waitUntil: "networkidle" });
  await wait("#today-kpis .tile");
  await wait("#ph-list .pcard");
  await page.locator("#ph-list .pcard .head").first().click();
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${out}/console.png` });

  await tab("replay", "#replay-chart svg");
  await page.screenshot({ path: `${out}/console-replay.png`, fullPage: true });

  await tab("assets", "#asset-table tr.clickable");
  await page.locator("#asset-table tr.clickable").first().click();
  await wait("#asset-detail .hero");
  await wait("#whatif .scn", 120000).catch(() => {});
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${out}/console-assets.png`, fullPage: true });

  await tab("memo", "#sig-judge svg");
  await page.fill("#memo-in", "운전 중 약간의 소음, 미세 진동 있음. 특이사항 없음");
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${out}/console-memo.png`, fullPage: true });

  await tab("model", "#model-info dl");
  await page.screenshot({ path: `${out}/console-model.png`, fullPage: true });

  await page.emulateMedia({ colorScheme: "dark" });
  await tab("replay", "#replay-chart svg");
  await page.screenshot({ path: `${out}/console-dark.png` });
  await browser.close();
  console.log("screenshots written to", out);
})().catch((e) => { console.error(e); process.exit(1); });
