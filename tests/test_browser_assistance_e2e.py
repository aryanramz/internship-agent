"""Permitted local fixture only; real keyboard/browser, zero external contacts."""
import os
import json
import re
from pathlib import Path
import threading
import pytest

pw=pytest.importorskip('playwright.sync_api',reason='Optional browser extra; dedicated Chromium CI qualifies fixture')
from test_browser_assistance import sandbox
from internship_agent.dashboard import DashboardServer

@pytest.mark.parametrize('challenge',['mfa','captcha'])
def test_fixture_keyboard_handoff_and_uncertain_recovery(sandbox,challenge,tmp_path):
    adapter,_,_=sandbox
    server=DashboardServer(adapter.dashboard.root,port=0,secret='fictional-fixture-secret',sandbox_assistance=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    output=Path(os.environ.get('IA_DASHBOARD_SCREENSHOTS',str(tmp_path/'screens')));output.mkdir(parents=True,exist_ok=True)
    try:
        with pw.sync_playwright() as p:
            options={'headless':True}
            if os.getenv('IA_BROWSER_EXECUTABLE'):options['executable_path']=os.environ['IA_BROWSER_EXECUTABLE']
            browser=p.chromium.launch(**options);context=browser.new_context(viewport={'width':1280,'height':900})
            external=[]
            def block(route):
                if route.request.url.startswith(server.origin+'/'):route.continue_()
                else:external.append(route.request.url);route.abort()
            context.route('**/*',block)
            page=context.new_page();page.set_default_timeout(10000);page.goto(server.origin)
            page.locator('#secret').fill('fictional-fixture-secret');page.locator('#secret').press('Tab');page.keyboard.press('Enter')
            page.get_by_role('heading',name='Make room for what’s next.').wait_for()
            page.locator('.job-title').first.focus();page.keyboard.press('Enter')
            page.get_by_role('button',name='Review current packet').click()
            page.get_by_role('button',name='Review sandbox assistance').click()
            page.locator('#assistance-create-reviewed').check();page.locator('#assistance-challenge').select_option(challenge)
            page.locator('#assistance-create').focus();page.keyboard.press('Enter')
            link=page.get_by_role('link',name='Open this exact local fixture in a new tab')
            link.wait_for()
            with context.expect_page() as opened:link.click()
            fixture=opened.value;fixture.set_default_timeout(10000);fixture.wait_for_load_state()
            pid=fixture.url.rsplit('/',1)[1]
            assert fixture.locator('#fixture-form [name=name]').input_value()==''
            assert fixture.locator('[type=password]').count()==0
            def approve(action,phrase,extra=None):
                section=fixture.locator(f'[data-action-review="{action}"]')
                section.locator('[name=reviewed]').check()
                section.locator('[name=phrase]').fill(phrase)
                if extra:extra(section)
                fixture.locator('#assistance-'+action).focus();fixture.keyboard.press('Enter')
            # A dynamically injected field is rejected before any mapped value is applied.
            fixture.locator('#fixture-form').evaluate("form => {const i=document.createElement('input');i.name='unexpected';form.append(i)}")
            approve('fill','FILL FIXTURE '+pid)
            pw.expect(fixture.locator('#assistance-status')).to_contain_text(re.compile('changed|edited'))
            fixture.reload();fixture.locator('#assistance-fill').wait_for()
            approve('fill','FILL FIXTURE '+pid)
            fixture.locator('#assistance-handoff').wait_for()
            assert fixture.locator('#fixture-form [name=name]').input_value()=='Fictional Candidate'
            for field in ['legal','eeo','work_authorization']:assert fixture.locator('[name='+field+']').input_value()==''
            fixture.screenshot(path=str(output/('assistance-'+challenge+'-mapping.png')),full_page=True)
            approve('handoff','HANDOFF FIXTURE '+pid)
            fixture.locator('#assistance-resume').wait_for()
            assert fixture.locator('#fixture-submit').count()==0
            approve('resume','RESUME FIXTURE '+pid,lambda _:fixture.locator('#assistance-challenge-ack').check())
            fixture.locator('#assistance-handoff').wait_for();approve('handoff','HANDOFF FIXTURE '+pid)
            fixture.locator('#assistance-intent').wait_for();approve('intent','AUTHORIZE FIXTURE '+pid)
            fixture.locator('#fixture-submit').wait_for()
            if challenge=='captcha':
                # Lost acknowledgement after a possible click is never retried.
                fixture.route('**/api/assistance',lambda route: route.abort() if route.request.method=='POST' and route.request.post_data_json.get('action')=='observe' else route.continue_())
            fixture.locator('#fixture-submit').focus();fixture.keyboard.press('Enter')
            fixture.reload();fixture.locator('#assistance-reconcile').wait_for()
            assert fixture.locator('#fixture-submit').count()==0
            approve('reconcile','RECONCILE '+pid,lambda _:(fixture.locator('#assistance-outcome').select_option('unknown'),fixture.locator('#assistance-provenance').fill('Fictional local observation; uncertain result')))
            fixture.locator('#assistance-reconcile').wait_for()
            assert fixture.locator('#fixture-submit').count()==0
            fixture.screenshot(path=str(output/('assistance-'+challenge+'-reconcile.png')),full_page=True)
            # Recovery stays reachable from job detail even when packet review is stale.
            profile=json.loads(adapter.dashboard.profile.read_text())
            profile['name']='Changed fictional candidate'
            adapter.dashboard.profile.write_text(json.dumps(profile))
            page.reload();page.locator('.job-title').first.click()
            page.get_by_role('button',name='Inspect sandbox plans').click()
            page.get_by_role('button',name=re.compile('Review '+pid)).click()
            page.locator('#assistance-reconcile').wait_for()
            assert page.locator('#fixture-submit').count()==0
            assert adapter.dashboard.store.get_job('fixture')['status']=='approved'
            assert not external
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join()
