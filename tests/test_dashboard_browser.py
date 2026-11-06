"""Actual Chromium and keyboard smoke; optional browser tooling, synthetic data only."""
import json
import os
from pathlib import Path
import threading
import re
import pytest

playwright=pytest.importorskip('playwright.sync_api',reason='Optional browser extra not installed; separate browser CI qualifies this')
from internship_agent.dashboard import DashboardServer
from internship_agent.service import Agent
from internship_agent.models import Job


def test_browser_keyboard_prepare_review_and_responsive(tmp_path):
    root=tmp_path/'Fictional Workspace';(root/'config').mkdir(parents=True)
    (root/'config/profile.json').write_text(json.dumps({'name':'Fictional Candidate','skills':['Python'],'target_roles':['software engineer'],'documents':{'version':1,'facts':[{'id':'name','path':'/name','value':'Fictional Candidate','verified':True,'source':'Fictional review','reviewed_on':'2026-11-01'}]}}),encoding='utf-8')
    (root/'config/sources.json').write_text('{"boards":[]}')
    agent=Agent(str(root/'data'))
    agent.import_external_jobs([{'id':str(i),'company':company,'title':title,'location':location,'job_url':'https://example.test/jobs/'+str(i),'description':'Fictional Python internship. <script>window.injected=true</script>'} for i,company,title,location in [(1,'Northwind Studio (fictional)','Software Engineering Intern','New York · Hybrid'),(2,'Contoso Labs (fictional)','Cloud Infrastructure Intern','Remote'),(3,'Fabrikam Systems (fictional)','Security Intern','Boston')]])
    server=DashboardServer(root,port=0,secret='fictional-browser-secret')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    output=Path(os.environ.get('IA_DASHBOARD_SCREENSHOTS',str(tmp_path/'screenshots')));output.mkdir(parents=True,exist_ok=True)
    try:
        with playwright.sync_playwright() as p:
            options={'headless':True}
            if os.environ.get('IA_BROWSER_EXECUTABLE'):options['executable_path']=os.environ['IA_BROWSER_EXECUTABLE']
            browser=p.chromium.launch(**options)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            blocked=[]
            def route(request):
                if request.request.url.startswith(server.origin+'/'):request.continue_()
                else:blocked.append(request.request.url);request.abort()
            page.route('**/*',route)
            page.goto(server.origin)
            page.locator('#secret').fill('fictional-browser-secret')
            page.locator('#secret').press('Tab')
            assert page.locator(':focus').inner_text().startswith('Unlock workspace')
            page.keyboard.press('Enter')
            page.get_by_role('heading',name='Make room for what’s next.').wait_for()
            page.screenshot(path=str(output/'dashboard-overview.png'),full_page=True)
            # Keyboard activation of actual navigation link, not a synthetic click.
            page.get_by_role('link',name='Opportunities',exact=False).first.focus();page.keyboard.press('Enter')
            page.get_by_role('heading',name='Find something worth exploring.').wait_for()
            assert page.evaluate('window.injected') is None
            page.locator('.job-title').first.focus();page.keyboard.press('Enter')
            page.locator('#detail-dialog').wait_for(state='visible')
            page.get_by_role('button',name='Prepare documents').click()
            page.locator('#confirm-dialog').wait_for(state='visible')
            page.locator('[name=confirmed]').check()
            page.locator('#confirm-submit').click()
            page.get_by_role('button',name='Approve reviewed revision').wait_for()
            page.get_by_text('Read Resume text',exact=True).focus();page.keyboard.press('Enter')
            page.get_by_text('Fictional Candidate',exact=False).first.wait_for()
            page.screenshot(path=str(output/'dashboard-review.png'),full_page=True)
            page.get_by_role('button',name='Approve reviewed revision').click()
            label=page.locator('label[for=field-phrase]').inner_text()
            phrase=label.removeprefix('Type ').removesuffix(' to confirm')
            page.locator('#field-phrase').fill(phrase)
            page.locator('[name=confirmed]').check();page.locator('#confirm-submit').click()
            page.get_by_role('button',name='Record external submission').wait_for()
            page.get_by_role('button',name='Record external submission').click()
            page.locator('#field-evidence').fill('Fictional operator report; no employer verification')
            page.locator('[name=confirmed]').check();page.locator('#confirm-submit').click()
            page.get_by_role('button',name='Record an outcome').wait_for()
            page.get_by_role('button',name='Record an outcome').click()
            page.locator('#field-evidence').fill('Fictional interview invitation')
            page.locator('[name=confirmed]').check();page.locator('#confirm-submit').click()
            page.get_by_text('Fictional interview invitation',exact=False).first.wait_for()

            assert page.evaluate('window.injected') is None
            page.keyboard.press('Escape')
            agent.store.upsert_job(Job(id='unsafe',provider='synthetic',company='Fictional <img src=x onerror=window.injected=true>',source_id='unsafe',title='Unsafe link fixture',location='Remote',description='<script>window.injected=true</script>',job_url='http://127.1/private',apply_url='javascript:alert(1)'))
            page.reload()
            page.get_by_role('link',name='Opportunities',exact=False).first.click()
            page.get_by_role('button',name=re.compile('Review Unsafe link fixture')).click()
            assert page.get_by_role('link',name=re.compile('Original posting')).count()==0
            assert page.evaluate('window.injected') is None
            page.keyboard.press('Escape')
            page.set_viewport_size({'width':390,'height':844})
            page.screenshot(path=str(output/'dashboard-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert not blocked
            browser.close()
    finally:
        server.shutdown();server.server_close();thread.join()
