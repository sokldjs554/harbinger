"""Exercise mobile filter disclosure and history against real/saved responses."""

from playwright.sync_api import expect


def check_mobile_filters(page, saved, out):
    def shot(name):
        page.screenshot(path=str(out / (name + ".png")))

    def set_date(value):
        if saved:
            page.select_option("#as-of", value)
        else:
            page.fill("#as-of", value)

    expect(page.locator("#search")).to_be_visible()
    expect(page.locator("#filter-toggle")).to_have_attribute("aria-expanded", "false")
    expect(page.locator("#customer")).to_be_hidden()
    expect(page.locator("#filter-summary")).to_contain_text("전체 고객사")
    mode = "합성 예제 · 저장 결과 재생" if saved else "합성 예제 · Python 계산 완료"
    expect(page.locator("#mode")).to_have_text(mode)
    for width in [320, 390, 650]:
        page.set_viewport_size({"width": width, "height": 844})
        assert page.locator("#mode").bounding_box()["height"] < 40
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
    page.set_viewport_size({"width": 390, "height": 844})
    shot("mobile-filter-collapsed")
    page.click("#filter-toggle")
    expect(page.locator("#customer")).to_be_visible()
    page.select_option("#customer", index=1)
    page.select_option("#category", "chiller")
    page.select_option("#sort", "inspection")
    page.fill("#search", "냉동기")
    original_date = page.locator("#as-of").input_value()
    new_date = (
        page.locator("#as-of option").last.get_attribute("value")
        or page.locator("#as-of option").last.inner_text()
        if saved
        else page.locator("#as-of").get_attribute("max")
    )
    set_date(new_date)
    expect(page.locator("#filter-summary")).to_contain_text(original_date)
    expect(page.locator("#filter-summary")).to_contain_text("기준일 변경 미적용")
    page.click("#calculate")
    expect(page.locator("#filter-summary")).not_to_contain_text("미적용", timeout=120000)
    expect(page.locator("[data-asset]").first).to_be_visible()
    values = {
        k: page.locator("#" + k).input_value() for k in ["search", "customer", "category", "sort", "as-of"]
    }
    for text in ["냉동기", "점검 오래된 순", new_date]:
        expect(page.locator("#filter-summary")).to_contain_text(text)
    shot("mobile-filter-expanded")
    page.click("#filter-toggle")
    expect(page.locator("#customer")).to_be_hidden()
    shot("mobile-filter-applied")
    page.evaluate("scrollTo(0,420)")
    page.wait_for_timeout(150)
    y = page.evaluate("scrollY")
    selected = page.locator("[data-asset]").evaluate_all(
        "els=>els.find(e=>{const r=e.getBoundingClientRect();return r.top>0 && r.bottom<innerHeight}).dataset.asset"
    )
    page.locator(f'[data-asset="{selected}"]').click()
    expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
    page.click("#back-list")
    expect(page.locator("#list-screen")).to_be_visible()
    page.wait_for_function("y=>Math.abs(scrollY-y)<3", arg=y)
    assert page.evaluate("document.activeElement.dataset.asset") == selected
    for k, v in values.items():
        assert page.locator("#" + k).input_value() == v
    expect(page.locator("#filter-toggle")).to_have_attribute("aria-expanded", "false")
    page.go_forward()
    expect(page.locator("#detail-screen")).to_be_visible()
    page.go_back()
    expect(page.locator("#list-screen")).to_be_visible()
    page.click("#filter-toggle")
    page.locator("[data-asset]").first.click()
    expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
    page.click("#back-list")
    expect(page.locator("#filter-toggle")).to_have_attribute("aria-expanded", "true")
    page.click("#reset-filters")
    set_date(original_date)
    page.click("#calculate")
    expect(page.locator("#list-context")).to_contain_text(original_date, timeout=120000)
    page.click("#filter-toggle")
    page.locator("[data-asset]").first.click()
    expect(page.locator("#record-memo")).to_be_visible(timeout=120000)
    direction = page.locator(".reason-row .direction")
    expect(direction.first).to_be_visible()
    assert all(
        t in ["위험 추정을 높인 항목", "위험 추정을 낮춘 항목", "영향 없음"]
        for t in direction.all_text_contents()
    )
    for width in [320, 390, 650]:
        page.set_viewport_size({"width": width, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
        assert all(
            h < 40 for h in direction.evaluate_all("els=>els.map(e=>e.getBoundingClientRect().height)")
        )
    page.set_viewport_size({"width": 390, "height": 844})
    page.locator(".reason-section").screenshot(path=str(out / "mobile-reasons.png"))
    page.click("#back-list")
    expect(page.locator("#list-screen")).to_be_visible()
    page.evaluate("scrollTo(0,0)")
