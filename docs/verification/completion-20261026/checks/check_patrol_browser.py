import json
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright, expect

out=Path('/workspace/harbinger-runs/completion-20261026/browser-patrol')
out.mkdir(exist_ok=True)
base='http://127.0.0.1:18031'
client=httpx.Client(base_url=base,trust_env=False,timeout=120)
chosen=None
for day in ['2025-07-31']:
    r=client.get('/v1/sites/S04/patrol/today',params={'as_of':day,'k':1,'explain':False})
    r.raise_for_status()
    data=r.json()
    if data['budget_overflow']>0:
        chosen=(day,data);break
assert chosen is not None
day,data=chosen
assert data['selected_count']==len(data['items'])==data['round_robin_selected_count']
assert data['selected_count']-data['requested_k']==data['budget_overflow']
with sync_playwright() as p:
    browser=p.chromium.launch(args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1000})
    errors=[]
    page.on('pageerror',lambda e: errors.append(str(e)))
    page.goto(base+'/console/advanced.html#today')
    expect(page.locator('#today-head h2')).to_be_visible(timeout=120000)
    page.select_option('#site','S04');page.fill('#asof',day);page.fill('#k','1');page.click('#apply')
    expect(page.locator('#today-head')).to_contain_text(f"예산 초과 {data['budget_overflow']}개",timeout=120000)
    page.screenshot(path=str(out/'patrol-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(out/'patrol-mobile.png'),full_page=True)
    page.fill('#asof','2022-01-01');page.click('#apply')
    expect(page.locator('#today-head')).to_contain_text('순찰 비교를 보류합니다',timeout=120000)
    assert 'undefined' not in page.locator('#today-head').inner_text()
    page.screenshot(path=str(out/'patrol-empty-mobile.png'),full_page=True)
    assert not errors,errors
    browser.close()
(out/'checks.json').write_text(json.dumps({'as_of':day,'patrol':data,'empty_cohort':'withheld; no undefined','page_errors':errors},ensure_ascii=False,indent=2))
print('Actual patrol overflow/paired baseline and desktop/mobile/empty rendering passed')
