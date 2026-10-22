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
        page.wait_for_selector("[data-asset]", timeout=120000)
        page.evaluate(
            """() => { const el=document.createElement('div'); el.id='walkthrough-caption'; el.style.cssText='position:fixed;bottom:16px;left:24px;right:24px;padding:16px 24px;background:#252b33;color:white;border-left:4px solid #1559c5;font:500 18px system-ui;z-index:999'; document.body.appendChild(el); }"""
        )

        def cue(text, until):
            page.locator("#walkthrough-caption").evaluate("(el,text)=>el.textContent=text", text)
            delay = start + until - time.monotonic()
            if delay > 0:
                page.wait_for_timeout(delay * 1000)

        mode = page.locator("#mode").inner_text()
        cue("흰 작업 목록에서 점검할 설비를 찾습니다. 모든 예제는 합성 데이터입니다.", 8)
        page.fill("#search", "자동문")
        cue("설비 이름이나 점검 문구를 검색하고 고객사·종류·정렬로 대상을 좁힙니다. " + mode, 19)
        page.locator("[data-asset]").first.click()
        page.wait_for_selector("#record-memo", timeout=120000)
        if page.locator("[data-inspection]").count() > 1:
            page.locator("[data-inspection]").nth(1).click()
        cue("별도 설비 화면에서 점검일을 선택합니다. 원문과 판단에 쓰인 항목을 연결해 읽습니다.", 32)
        page.locator('.app-nav [data-view="validation"]').click()
        page.wait_for_selector("#comparison-rows tr", timeout=120000)
        cue("같은 날짜와 고객사별 점검 수에서 규칙·단순 모델·현재 모델을 비교합니다.", 43)
        page.locator('.app-nav [data-view="customers"]').click()
        page.locator("#loso-content").scroll_into_view_if_needed()
        cue("고객사별 현재 결과와 처음 보는 고객사 전체를 제외한 별도 실험을 구분합니다.", 54)
        page.locator("#report-form").scroll_into_view_if_needed()
        if page.locator("#report-date").evaluate("el=>el.tagName") == "SELECT":
            page.select_option("#report-date", index=1)
        else:
            page.fill("#report-date", page.locator("#report-date").get_attribute("max"))
        page.click("#report-apply")
        page.locator('.app-nav [data-view="validation"]').click()
        page.wait_for_function("document.getElementById('evaluation-note').textContent.includes('평가 보류')")
        page.locator("#evaluation-note").scroll_into_view_if_needed()
        cue("이후 30일 관측이 부족하면 평가 보류입니다. 미확정 결과를 성능 숫자로 채우지 않습니다.", 67)
        page.locator('.app-actions [data-view="downloads"]').click()
        with page.expect_download() as result:
            page.click('[data-format="md"]')
        result.value.save_as(str(a.out / "walkthrough-report.md"))
        cue("실제 적용된 조건·모델 버전·평가 보류 사유를 함께 다운로드합니다. 실제 고객 실증이 아닙니다.", 80)
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
