"""Real fictional outreach browser workflow. Never connects to an email service."""
import json
import os
from pathlib import Path
import threading
import pytest

pw=pytest.importorskip('playwright.sync_api',reason='Optional browser extra; dedicated Chromium CI qualifies outreach')
from test_outreach import outreach
from internship_agent.dashboard import DashboardServer


def test_keyboard_contact_draft_reply_optout_and_responsive(outreach,tmp_path):
    core,_,_=outreach
    server=DashboardServer(core.dashboard.root,port=0,secret='fictional-outreach-secret')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    screenshots=Path(os.getenv('IA_DASHBOARD_SCREENSHOTS',str(tmp_path/'screens')));screenshots.mkdir(parents=True,exist_ok=True)
    try:
        with pw.sync_playwright() as p:
            options={'headless':True}
            if os.getenv('IA_BROWSER_EXECUTABLE'):options['executable_path']=os.environ['IA_BROWSER_EXECUTABLE']
            browser=p.chromium.launch(**options);context=browser.new_context(viewport={'width':1440,'height':1000})
            external=[];writes=[]
            def block(route):
                if route.request.url.startswith(server.origin+'/'):
                    if route.request.method=='POST' and '/api/outreach' in route.request.url:writes.append(route.request.post_data_json.get('action'))
                    route.continue_()
                else:external.append(route.request.url);route.abort()
            context.route('**/*',block)
            page=context.new_page();page.set_default_timeout(15000);page.goto(server.origin)
            page.locator('#secret').fill('fictional-outreach-secret');page.locator('#secret').press('Tab');page.keyboard.press('Enter')
            page.get_by_role('heading',name='Make room for what’s next.').wait_for()
            page.get_by_role('link',name='Outreach',exact=False).focus();page.keyboard.press('Enter')
            page.locator('#outreach-register-contact').wait_for();assert writes==[]
            def fill(values):
                for key,value in values.items():
                    field=page.locator('#outreach-field-'+key)
                    if field.evaluate('n=>n.tagName')=='SELECT':field.select_option(str(value))
                    else:field.fill(str(value))
            def confirm(phrase=None):
                if phrase:page.locator('#outreach-confirm-phrase').fill(phrase)
                page.locator('#outreach-confirm-checkbox').check()
                page.locator('#outreach-confirm-submit').focus();page.keyboard.press('Enter')
                page.locator('#outreach-dialog').wait_for(state='detached')
            page.locator('#outreach-register-contact').click()
            fill({'job-choice':'fixture','employer_domain':'employer.test','name':'Fictional Recruiter','role':'Recruiter','email':'recruiter@employer.test','source_url':'https://employer.test/team','observed_at':'2026-11-01T00:00:00Z','method':'official','permission':'allowed'})
            confirm();page.locator('#outreach-verify-contact').wait_for()
            contact=core.get('contacts',{})['contacts'][0];cid=contact['contact_id']
            page.locator('#outreach-verify-contact').click();fill({'verifier':'Fictional operator'})
            confirm('VERIFY '+cid)
            page.screenshot(path=str(screenshots/'outreach-contact.png'),full_page=True)
            page.locator('#outreach-followup-policy').click();fill({'interval_days':'7','min_days':'7','enabled':'true'});confirm()
            page.locator('#outreach-contact-create-draft').click()
            page.locator('#outreach-packet-binding').get_by_text('approved',exact=False).first.wait_for()
            confirm();page.locator('#outreach-edit-draft').wait_for()
            draft=core.get('drafts',{})['drafts'][0];did=draft['draft_id']
            page.locator('#outreach-edit-draft').click()
            fill({'subject':'Question about Software Intern','body':'Hello Fictional Recruiter,\n\nI am Fictional Candidate. Could you clarify the location of the Software Intern role?\n\nFictional Candidate'})
            confirm()
            assert page.locator('#outreach-export-draft').is_disabled()
            page.locator('#outreach-review-draft').click();confirm('REVIEW '+did)
            assert core.get('draft',{'id':did})['review_token'] not in page.locator('#outreach-root').text_content()
            page.screenshot(path=str(screenshots/'outreach-draft.png'),full_page=True)
            page.locator('#outreach-export-draft').click()
            with page.expect_download() as downloaded:confirm()
            assert downloaded.value.suggested_filename.endswith('.eml')
            with core._connection() as (c,_):assert c.execute('SELECT COUNT(*) FROM outreach_sends').fetchone()[0]==0
            page.locator('#outreach-record-send').click()
            fill({'sent_at':'2026-10-20T12:00:00Z','message_id':'<fictional-sent@example.test>','thread_id':'fictional-thread','evidence':'Fictional manually reviewed external sent copy, exact content attested','certainty':'confirmed'})
            confirm()
            page.locator('#outreach-tab-followups').click()
            page.get_by_text('Follow-up for human review',exact=True).wait_for()
            page.screenshot(path=str(screenshots/'outreach-followup.png'),full_page=True)
            page.locator('#outreach-tab-messages').click();page.locator('#outreach-import-message').click()
            incoming={'message_id':'<fictional-reply@employer.test>','thread_id':'fictional-thread','from_email':'recruiter@employer.test','to_email':'candidate@example.test','in_reply_to':'<fictional-sent@example.test>','references':[],'cc':[],'sent_at':'2026-11-05T12:00:00Z','subject':'Fictional reply','body':'<img src="https://outside.example/pixel" onerror="window.injected=true"> Fictional reply only.','text_format':'html','forwarded':False,'bounce':False,'optout':True}
            fill({'fixture':json.dumps(incoming)});confirm()
            page.get_by_text('matched_unverified',exact=False).first.wait_for()
            assert page.evaluate('window.injected') is None
            page.screenshot(path=str(screenshots/'outreach-reply.png'),full_page=True)
            page.locator('#outreach-tab-followups').click();page.get_by_role('heading',name='No follow-up suggestions').wait_for()
            page.set_viewport_size({'width':390,'height':844})
            page.locator('#outreach-tab-contacts').click();page.locator('[data-contact-id]').first.click()
            page.locator('#outreach-optout-contact').click();confirm('OPTOUT '+cid)
            page.get_by_text('opted_out',exact=True).first.wait_for()
            page.screenshot(path=str(screenshots/'outreach-mobile.png'),full_page=True)
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not external
            assert core.dashboard.store.get_job('fixture')['status']=='approved'
            browser.close()
    finally:server.shutdown();server.server_close();thread.join()
