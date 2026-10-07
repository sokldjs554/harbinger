// 데모 GIF 녹화 — `node scripts/record_demo.cjs http://localhost:8020 /tmp/demo /` 뒤 ffmpeg 로 GIF 변환 (Makefile: make demo-gif)
// 흐름: 오늘(현장 앱 미리보기) → 과거 재현(전체 → 사이트) → 설비(What-if) → 메모 읽기 → 모델·가정
const { chromium } = require("playwright");
const { mkdirSync } = require("node:fs");

(async () => {
  const base = process.argv[2] || "http://localhost:8000";
  const out = process.argv[3] || "/tmp/demo";
  const pagePath = process.argv[4] || "/console/";
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, recordVideo: { dir: out, size: { width: 1280, height: 800 } }, colorScheme: "light" });
  const page = await ctx.newPage();
  const pause = (ms) => page.waitForTimeout(ms);
  const wait = (sel, t = 90000) => page.waitForSelector(sel, { timeout: t });
  const tab = async (name, ready) => { await page.click(`nav.tabs button[data-tab="${name}"]`); await wait(ready); };

  await page.goto(`${base}${pagePath}`, { waitUntil: "networkidle" });
  await wait("#today-kpis .tile");
  await wait("#ph-list .pcard");
  await pause(2400);
  // 오늘 — 점검자 폰 미리보기에서 한 건 펼치고 확인 표시
  await page.locator("#ph-list .pcard .head").first().click();
  await pause(1600);
  await page.locator("#ph-list .pcard input[type=checkbox]").first().check();
  await pause(1400);
  await page.mouse.wheel(0, 520);
  await pause(1800);
  // 과거 재현 — 전체 → 한 사이트
  await tab("replay", "#replay-chart svg");
  await pause(3000);
  await page.click("#scope-site");
  await wait("#replay-detail .rlist");
  await pause(3000);
  // 설비 — 상위 설비 하나, What-if 시나리오 전환
  await tab("assets", "#asset-table tr.clickable");
  await pause(1000);
  await page.locator("#asset-table tr.clickable").first().click();
  await wait("#asset-detail .hero");
  await pause(2200);
  await page.mouse.wheel(0, 640);
  await wait("#whatif .scn", 120000).catch(() => {});
  await pause(1800);
  const scn = page.locator("#whatif .scn");
  const n = await scn.count();
  for (let i = 1; i < Math.min(n, 3); i++) { await scn.nth(i).click(); await pause(1800); }
  // 메모 읽기 — 직접 입력
  await tab("memo", "#sig-judge svg");
  await pause(1200);
  await page.fill("#memo-in", "");
  await page.type("#memo-in", "운전 중 약간의 소음, 미세 진동 있음. 특이사항 없음", { delay: 45 });
  await pause(2800);
  await page.mouse.wheel(0, 480);
  await pause(2200);
  // 모델·가정
  await tab("model", "#model-info dl");
  await pause(2600);
  await page.mouse.wheel(0, 700);
  await pause(2400);
  const video = page.video();
  await ctx.close();
  const path = await video.path();
  await browser.close();
  console.log(path);
})().catch((e) => { console.error(e); process.exit(1); });
