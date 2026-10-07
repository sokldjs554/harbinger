// 콘솔 스모크 — 모든 탭을 열어 보고, 콘솔 오류·페이지 오류·실패한 요청(4xx/5xx)이 있으면 실패한다. 스크린샷을 남긴다.
//   node scripts/smoke_console.cjs http://localhost:8000 /console/ /tmp/shots        (라이브)
//   node scripts/smoke_console.cjs http://localhost:8020 /        /tmp/shots        (정적 데모)
const { chromium } = require("playwright");
const { mkdirSync } = require("node:fs");

(async () => {
  const base = process.argv[2] || "http://localhost:8000", pagePath = process.argv[3] || "/console/", out = process.argv[4] || "/tmp/shots";
  mkdirSync(out, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
  const problems = [];
  async function run(name, viewport, scheme, fn) {
    const ctx = await browser.newContext({ viewport, deviceScaleFactor: 1.5, colorScheme: scheme });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => problems.push(`[${name}] pageerror: ${e.message}`));
    page.on("console", (m) => { if (m.type() === "error") problems.push(`[${name}] console.error: ${m.text()}`); });
    page.on("response", (r) => { if (r.status() >= 400 && !r.url().includes("favicon")) problems.push(`[${name}] HTTP ${r.status()} ${r.url()}`); });
    await fn(page);
    await ctx.close();
  }
  const url = `${base}${pagePath}`;
  const wait = async (page, sel, t = 90000) => page.waitForSelector(sel, { timeout: t });

  await run("desktop", { width: 1280, height: 860 }, "light", async (page) => {
    await page.goto(url, { waitUntil: "networkidle" });
    await wait(page, "#today-kpis .tile");
    await wait(page, "#ph-list .pcard");
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${out}/01-today.png` });
    // 현장 앱 카드 펼치기 + 확인
    await page.locator("#ph-list .pcard .head").first().click();
    await page.locator("#ph-list .pcard input[type=checkbox]").first().check();
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${out}/01b-today-phone.png` });
    // 과거 재현
    await page.click('nav.tabs button[data-tab="replay"]');
    await wait(page, "#replay-chart svg");
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/02-replay-all.png`, fullPage: true });
    await page.click("#scope-site");
    await wait(page, "#replay-detail .rlist");
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/02b-replay-site.png`, fullPage: true });
    // 설비 + what-if
    await page.click('nav.tabs button[data-tab="assets"]');
    await wait(page, "#asset-table tr.clickable");
    await page.locator("#asset-table tr.clickable").first().click();
    await wait(page, "#asset-detail .hero");
    await wait(page, "#whatif .scn", 120000).catch(() => problems.push("[desktop] what-if 시나리오가 나타나지 않음"));
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${out}/03-assets.png`, fullPage: true });
    // 시나리오 선택이 바뀌는지
    const scn = page.locator("#whatif .scn");
    if ((await scn.count()) >= 4) { await scn.nth(3).click(); await page.waitForTimeout(200); if (!(await scn.nth(3).getAttribute("class")).includes("selected")) problems.push("[desktop] 시나리오 선택이 반영되지 않음"); }
    // 메모 읽기
    await page.click('nav.tabs button[data-tab="memo"]');
    await wait(page, "#sig-judge svg");
    await page.fill("#memo-in", "누유 심함, 긴급 수리 필요");
    await page.waitForTimeout(300);
    if (!(await page.locator("#memo-out mark.m-strong").count())) problems.push("[desktop] 메모 분석기가 강신호를 표시하지 않음");
    await page.screenshot({ path: `${out}/04-memo.png`, fullPage: true });
    for (const t of ["quality", "energy", "model"]) {
      await page.click(`nav.tabs button[data-tab="${t}"]`);
      await wait(page, { quality: "#quality-table table", energy: "#energy-line svg", model: "#model-info dl" }[t]);
      await page.waitForTimeout(600);
      await page.screenshot({ path: `${out}/0${{ quality: 5, energy: 6, model: 7 }[t]}-${t}.png`, fullPage: true });
    }
  });
  await run("dark", { width: 1280, height: 860 }, "dark", async (page) => {
    await page.goto(`${url}#replay`, { waitUntil: "networkidle" });
    await wait(page, "#replay-chart svg");
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/08-dark-replay.png`, fullPage: true });
  });
  await run("mobile", { width: 390, height: 820 }, "light", async (page) => {
    await page.goto(url, { waitUntil: "networkidle" });
    await wait(page, "#ph-list .pcard");
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/09-mobile-today.png` });
    const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    if (over > 4) problems.push(`[mobile] 가로 스크롤 ${over}px`);
  });
  await browser.close();
  if (problems.length) { console.error("PROBLEMS:\n" + [...new Set(problems)].join("\n")); process.exit(1); }
  console.log("smoke ok → " + out);
})().catch((e) => { console.error(e); process.exit(1); });
