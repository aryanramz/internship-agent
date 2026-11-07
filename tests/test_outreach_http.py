"""Outreach reuses the dashboard access boundary; no sending route exists."""
from test_dashboard_http import running,request,login

def test_outreach_requires_session_and_explicit_action(running):
    assert request(running,'GET','/api/outreach?view=contacts')[0]==401
    cookie,csrf=login(running)
    assert request(running,'POST','/api/outreach',{'action':'register-contact'},headers={'Cookie':cookie})[0]==403
    status,_,body=request(running,'POST','/api/outreach',{'action':'register-contact'},headers={'Cookie':cookie,'X-CSRF-Token':csrf})
    assert status==400

def test_outreach_has_no_send_gmail_or_file_endpoints(running):
    cookie,csrf=login(running)
    assert request(running,'GET','/api/outreach?view=credentials',headers={'Cookie':cookie})[0]==400
    assert request(running,'POST','/api/outreach',{'action':'send','confirm':'send'},headers={'Cookie':cookie,'X-CSRF-Token':csrf})[0]==400
    for url in ['/outreach/profile.json','/api/gmail','/data/agent.db']:
        assert request(running,'GET',url,headers={'Cookie':cookie})[0]==404


from test_outreach_messages import correspondence,message

def test_correspondence_api_and_cli_dispatch_preserve_strong_matching(correspondence,capsys):
    import json,threading
    from internship_agent.dashboard import DashboardServer
    from internship_agent.outreach_cli import main
    _,core,_=correspondence
    server=DashboardServer(core.dashboard.root,port=0,secret='synthetic-secret')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        cookie,_=login(server)
        def post(payload):
            csrf=json.loads(request(server,'GET','/api/session',headers={'Cookie':cookie})[2])['csrf']
            status,_,body=request(server,'POST','/api/outreach',payload,headers={'Cookie':cookie,'X-CSRF-Token':csrf})
            assert status==200,body
            return json.loads(body)
        post({'action':'followup-policy','confirm':'followup-policy','contact_id':'contact','interval_days':7,'min_days':7,'enabled':True})
        assert main(['--root',str(core.dashboard.root),'get','messages'])==0
        assert json.loads(capsys.readouterr().out)['items']==[]
        imported=post({'action':'import-message','confirm':'import-message','message':message()})
        assert imported['message']['match_state']=='matched_unverified'
        assert main(['--root',str(core.dashboard.root),'get','followups'])==0
        assert json.loads(capsys.readouterr().out)['items']==[]
    finally:server.shutdown();server.server_close();thread.join()
