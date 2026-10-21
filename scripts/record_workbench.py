"""Record an 80-second walkthrough of real browser interactions (live or saved)."""

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/console/")
    ap.add_argument("--out", type=Path, default=Path("docs/verification/video"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        ctx = b.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(a.out),
            record_video_size={"width": 1440, "height": 1000},
        )
        page = ctx.new_page()
        video = page.video
        start = time.monotonic()
        page.goto(a.url)
        page.wait_for_function("!document.getElementById('mode').textContent.includes('확인 중')")
        page.evaluate(
            """() => { const el=document.createElement('div'); el.id='walkthrough-caption'; el.style.cssText='position:fixed;bottom:16px;left:5%;right:5%;padding:16px 24px;background:#173c39;color:white;border-radius:12px;font:600 20px system-ui;z-index:999;box-shadow:0 2px 12px #0003'; document.body.appendChild(el); }"""
        )

        def cue(text, until):
            page.locator("#walkthrough-caption").evaluate("(el,text)=>el.textContent=text", text)
            delay = start + until - time.monotonic()
            if delay > 0:
                page.wait_for_timeout(delay * 1000)

        mode = page.locator("#mode").inner_text()
        cue("점검 기록에서 우선 확인할 설비를 찾습니다. 모든 예제는 합성 데이터입니다.", 8)
        page.click("#example")
        page.wait_for_selector("[data-asset]", timeout=120000)
        page.locator("#workspace").scroll_into_view_if_needed()
        cue("예제를 불러오고 고객사·과거 기준일·점검 예산을 정합니다. 현재 모드: " + mode, 19)
        page.locator("[data-asset]").first.click()
        page.wait_for_function(
            "document.getElementById('evidence').innerText.includes('점검 원문')", timeout=120000
        )
        page.locator("#priority").scroll_into_view_if_needed()
        cue("설비를 누르면 당시 점검 원문과 고장 이력, 모델 기여도를 확인할 수 있습니다.", 32)
        page.click('[data-tab="comparison"]')
        page.locator("#comparison").scroll_into_view_if_needed()
        cue("같은 날짜와 예산에서 규칙·로지스틱·현재 모델·메모/이력 제거 모델을 비교합니다.", 43)
        page.click('[data-tab="customers"]')
        page.locator("#loso").scroll_into_view_if_needed()
        cue("현재 고객사별 결과와 처음 보는 고객사 8곳의 LOSO 실험을 구분합니다.", 54)
        page.locator("#analysis-form").scroll_into_view_if_needed()
        if page.locator("#static-date").is_visible():
            page.select_option("#static-date", index=1)
        else:
            page.fill("#date", page.locator("#date").get_attribute("max"))
        page.locator("#analysis-form button").click()
        page.wait_for_function("!document.getElementById('status').classList.contains('busy')")
        page.click('[data-tab="comparison"]')
        page.locator("#evaluation-note").scroll_into_view_if_needed()
        assert "평가 보류" in page.locator("#evaluation-note").inner_text()
        cue("관측 30일이 부족하면 평가 보류입니다. 미확정 결과를 정상이나 성능 숫자로 채우지 않습니다.", 67)
        page.click('[data-tab="downloads"]')
        page.locator("#downloads").scroll_into_view_if_needed()
        with page.expect_download() as result:
            page.click('[data-format="md"]')
        result.value.save_as(str(a.out / "walkthrough-report.md"))
        cue(
            "결과·모델 버전·평가 보류 사유를 함께 다운로드합니다. 실제 고객 성능을 입증한 결과는 아닙니다.",
            80,
        )
        elapsed = time.monotonic() - start
        if elapsed > 90:
            raise RuntimeError(f"Walkthrough exceeds 90 seconds: {elapsed:.1f}; rerun on a warmed server")
        ctx.close()
        path = video.path()
        b.close()
        (a.out / "recording.json").write_text(
            json.dumps(
                {
                    "url": a.url,
                    "mode": mode,
                    "duration_target_seconds": 80,
                    "elapsed_seconds": elapsed,
                    "raw_video": str(path),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print(path)


if __name__ == "__main__":
    main()
