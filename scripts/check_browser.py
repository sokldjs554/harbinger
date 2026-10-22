"""Browser regression checks for the full live and saved equipment workflow."""

import argparse
import csv
import io
import json
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from check_mobile_filters import check_mobile_filters


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/console/")
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("docs/verification/browser"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            record_video_dir=str(args.out / "video") if args.record else None,
        )
        page = context.new_page()
        errors, sessions = [], []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def capture(response):
            if response.ok and (
                response.url.endswith("/workbench/example") or "/workbench/upload?" in response.url
            ):
                sessions.append(response.json()["session_id"])

        page.on("response", capture)

        def nav(view):
            page.locator(f'.app-bar [data-view="{view}"]').click()

        def shot(name, full=False):
            page.screenshot(path=str(args.out / (name + ".png")), full_page=full)

        def download(fmt, filename=None):
            with page.expect_download() as d:
                page.click(f'[data-format="{fmt}"]')
            path = args.out / (filename or "result." + fmt)
            d.value.save_as(str(path))
            return path

        page.goto(args.url)
        expect(page.locator("[data-asset]").first).to_be_visible(timeout=120000)
        shot("list")
        assert not page.locator(".rail,.stats,.analysis-grid").count()
        page.fill("#search", "no-such-equipment-zzzz")
        expect(page.locator("#empty")).to_be_visible()
        page.click("#reset-filters")
        first_id = page.locator("[data-asset]").first.get_attribute("data-asset")
        page.select_option("#sort", "inspection")
        dates = page.locator(".date-cell").all_text_contents()
        assert dates == sorted(dates)
        page.click("#reset-filters")
        page.locator("[data-asset]").first.click()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        expect(page.locator("#list-screen")).to_be_hidden()
        if page.locator("[data-inspection]").count() > 1:
            page.locator("[data-inspection]").nth(1).click()
            expect(page.locator("[data-inspection]").nth(1)).to_have_attribute("aria-pressed", "true")
            page.locator("[data-inspection]").first.click()
        shot("detail", True)
        page.click("#back-list")
        expect(page.locator("#list-screen")).to_be_visible()
        assert page.evaluate("document.activeElement.dataset.asset") == first_id
        nav("validation")
        expect(page.locator("#comparison-rows tr").first).to_be_visible(timeout=120000)
        applied_date = page.locator("#report-date").input_value()
        shot("validation")
        if args.static:
            page.select_option("#report-date", index=1)
        else:
            page.fill("#report-date", page.locator("#report-date").get_attribute("max"))
        expect(page.locator("#report-pending")).to_contain_text("적용 전")
        nav("downloads")
        original = json.loads(download("json", "unchanged-query.json").read_text())
        assert original["as_of"].startswith(applied_date)
        chosen = next(m for m in original["comparisons"] if m["method"] == "current_model")
        nav("validation")
        displayed = page.locator("[data-outcome-asset]").evaluate_all(
            "els=>els.map(e=>e.dataset.outcomeAsset)"
        )
        assert set(displayed) == set(chosen["selected_asset_ids"])
        page.click("#report-apply")
        expect(page.locator("#evaluation-note")).to_contain_text("평가 보류", timeout=120000)
        assert all("평가 보류" in r for r in page.locator("#comparison-rows tr").all_text_contents())
        assert "미확정" in page.locator("#outcome-rows").inner_text()
        shot("withheld")
        nav("customers")
        expect(page.locator("#customer-rows tr").first).to_be_visible()
        expect(page.locator("#loso-content")).not_to_be_empty(timeout=30000)
        shot("customers")
        nav("downloads")
        for fmt in ["md", "csv", "json"]:
            download(fmt)
        assert "평가 보류" in (args.out / "result.md").read_text()
        withheld = json.loads((args.out / "result.json").read_text())
        assert withheld["evaluation_status"] == "withheld"
        assert all(a["failed_within_30d"] is None for a in withheld["assets"])
        shot("downloads")
        page.select_option("#report-site", index=1)
        page.click("#report-apply")
        expect(page.locator("#report-pending")).to_have_text("", timeout=120000)
        selected_site = page.locator("#report-site").input_value()
        scoped = json.loads(download("json", "site.json").read_text())
        assert {a["site_id"] for a in scoped["assets"]} == {selected_site}
        nav("data")
        shot("data")
        with page.expect_download() as d:
            page.click("#sample-csv")
        d.value.save_as(str(args.out / "example.csv"))
        if args.static:
            expect(page.locator("#upload-submit")).to_be_disabled()
            assert "저장된 합성" in page.locator("#data-mode-note").inner_text()
        else:
            page.set_input_files(
                "#csv-file", {"name": "bad.csv", "mimeType": "text/csv", "buffer": b"wrong\n1"}
            )
            page.check("#observation-confirm")
            page.click("#upload-submit")
            expect(page.locator("#data-error")).to_contain_text("필수 열", timeout=120000)
            shot("upload-error")
            nav("list")
            expect(page.locator("[data-asset]").first).to_be_visible()
            assert page.locator("[data-asset]").first.get_attribute("data-asset") == first_id
            nav("data")
            records = list(
                csv.DictReader(io.StringIO((args.out / "example.csv").read_text(encoding="utf-8-sig")))
            )
            for r in records:
                if r["record_type"] == "inspection":
                    r["memo"] = "=1+1"
            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=list(records[0]))
            writer.writeheader()
            writer.writerows(records)
            page.set_input_files(
                "#csv-file",
                {"name": "example.csv", "mimeType": "text/csv", "buffer": output.getvalue().encode()},
            )
            # A valid upload must not replace the active records until scoring succeeds.
            failed_analysis = "**/workbench/sessions/*/analysis?*"
            page.route(
                failed_analysis,
                lambda route: route.fulfill(
                    status=503,
                    content_type="application/json",
                    body='{"detail":"검증용 분석 실패"}',
                ),
            )
            page.click("#upload-submit")
            expect(page.locator("#data-error")).to_contain_text("검증용 분석 실패", timeout=120000)
            nav("list")
            expect(page.locator("[data-asset]").first).to_be_visible()
            assert page.locator("[data-asset]").first.get_attribute("data-asset") == first_id
            page.unroute(failed_analysis)
            nav("data")
            page.click("#upload-submit")
            expect(page.locator("#mode")).to_contain_text("업로드 기록", timeout=120000)
            expect(page.locator("#list-screen")).to_be_visible()
            nav("downloads")
            expect(page.locator("#applied-conditions")).to_contain_text("적용된 조건", timeout=120000)
            exported = list(
                csv.DictReader(io.StringIO(download("csv", "uploaded.csv").read_text(encoding="utf-8-sig")))
            )
            assert all(r["memo"] == "'=1+1" for r in exported)
            page.reload()
            expect(page.locator("#data-screen")).to_be_visible()
            assert "다시 불러와" in page.locator("#data-status").inner_text()
            page.click("#load-example")
            expect(page.locator("[data-asset]").first).to_be_visible(timeout=120000)
        nav("list")
        page.set_viewport_size({"width": 390, "height": 844})
        check_mobile_filters(page, args.static, args.out)
        shot("mobile-list")
        page.locator("[data-asset]").first.click()
        expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
        shot("mobile-detail", True)
        page.click("#back-list")
        expect(page.locator("#list-screen")).to_be_visible()
        for view in ["validation", "customers", "downloads", "data"]:
            nav(view)
            page.wait_for_timeout(150)
            assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"), view
            shot("mobile-" + view)
        page.click("#close-session")
        expect(page.locator("#dataset-source")).to_have_text("열린 기록 없음", timeout=30000)
        assert not errors, errors
        if not args.static:
            base = urlsplit(args.url)
            for token in sessions:
                page.request.delete(f"{base.scheme}://{base.netloc}/v1/workbench/sessions/{token}")
        context.close()
        browser.close()
        checks = [
            "list/detail and record dates",
            "back/focus",
            "same selected identities as backend metrics",
            "pending condition export isolation",
            "withheld outcomes",
            "customer scope",
            "three downloads",
            "CSV sample",
            "mobile all views",
            "mobile filter disclosure, applied summary, pending date and history/scroll restoration",
            "readable direction labels and exact live/saved mode at 320/390/650px",
            "session close",
        ]
        if not args.static:
            checks += [
                "invalid CSV preserves active records",
                "valid CSV actual model",
                "scoring failure preserves previous records",
                "formula-safe CSV",
                "upload reload never switches silently to example",
            ]
        (args.out / "checks.json").write_text(
            json.dumps(
                {"url": args.url, "static": args.static, "page_errors": errors, "checks": checks},
                ensure_ascii=False,
                indent=2,
            )
        )
        print("full workflow browser checks passed")


if __name__ == "__main__":
    main()
