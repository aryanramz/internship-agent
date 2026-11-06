"""Browser assistance remains off unless explicitly enabled; normal auth/CSRF applies."""
from test_dashboard_http import running, request, login
from test_browser_assistance import sandbox

def test_assistance_disabled_and_no_arbitrary_fixture(running):
    cookie,csrf=login(running)
    auth={'Cookie':cookie,'X-CSRF-Token':csrf}
    assert request(running,'GET','/api/assistance?job_id=fictional',headers=auth)[0]==403
    assert request(running,'POST','/api/assistance',{'action':'create','confirm':'create','id':'fictional'},headers=auth)[0]==403
    assert request(running,'GET','/sandbox/application/arbitrary',headers=auth)[0]==403

def test_assistance_requires_same_authenticated_mutation_boundary(running):
    assert request(running,'POST','/api/assistance',{'action':'create','confirm':'create'})[0]==401
    cookie,csrf=login(running)
    assert request(running,'POST','/api/assistance',{'action':'create','confirm':'create'},headers={'Cookie':cookie})[0]==403


def test_enabled_fixture_binds_url_and_never_accepts_arbitrary_target(sandbox):
    import threading,json
    from internship_agent.dashboard import DashboardServer
    server=DashboardServer(sandbox[0].dashboard.root,port=0,secret='synthetic-secret',sandbox_assistance=True)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        cookie,csrf=login(server)
        headers={'Cookie':cookie,'X-CSRF-Token':csrf}
        status,_,body=request(server,'POST','/api/assistance',{'action':'create','confirm':'create','id':'fixture','review_token':sandbox[1],'url':'https://outside.example/apply'},headers=headers)
        assert status==200
        plan=json.loads(body)
        path='/sandbox/application/'+plan['plan_id']
        assert plan['target_url']==server.origin+path
        assert request(server,'GET',path,headers={'Cookie':cookie})[0]==200
        assert request(server,'GET',path+'?redirect=https://outside.example',headers={'Cookie':cookie})[0]==400
        assert request(server,'GET',path+'/../different',headers={'Cookie':cookie})[0]==400
    finally:server.shutdown();server.server_close();thread.join()
