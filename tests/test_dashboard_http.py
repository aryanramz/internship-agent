import http.client
import json
import threading
from pathlib import Path
import pytest
from internship_agent.dashboard import DashboardServer

@pytest.fixture
def running(tmp_path):
    server=DashboardServer(tmp_path,port=0,secret='synthetic-secret')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    yield server
    server.shutdown();server.server_close();thread.join()

def request(server,method,path,body=None,headers=None):
    connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
    origin=f'http://127.0.0.1:{server.server_port}'
    selected={'Host':f'127.0.0.1:{server.server_port}','Origin':origin,'Content-Type':'application/json'}
    selected.update(headers or {})
    connection.request(method,path,json.dumps(body) if isinstance(body,dict) else body,selected)
    response=connection.getresponse(); raw=response.read(); result=(response.status,dict(response.getheaders()),raw)
    connection.close();return result

def login(server):
    status,headers,body=request(server,'POST','/login',{'secret':'synthetic-secret'})
    assert status==200
    return headers['Set-Cookie'].split(';')[0],json.loads(body)['csrf']

def test_access_boundary_and_security_headers(running):
    assert request(running,'GET','/api/overview')[0]==401
    assert request(running,'GET','/',headers={'Host':'evil.example'})[0]==403
    assert request(running,'GET','/',headers={'Origin':'https://evil.example'})[0]==403
    assert request(running,'POST','/login',{'secret':'wrong'})[0]==401
    cookie,csrf=login(running)
    status,headers,body=request(running,'GET','/api/session',headers={'Cookie':cookie})
    assert status==200 and json.loads(body)['csrf']==csrf
    assert 'HttpOnly' in request(running,'POST','/login',{'secret':'synthetic-secret'})[1]['Set-Cookie']
    assert headers['Cache-Control']=='no-store'
    assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
    assert request(running,'GET','/data/agent.db',headers={'Cookie':cookie})[0]==404

def test_csrf_origin_methods_limits_and_replay(running):
    cookie,csrf=login(running)
    headers={'Cookie':cookie,'X-CSRF-Token':csrf}
    assert request(running,'POST','/api/action',{'action':'recover'},headers={'Cookie':cookie})[0]==403
    assert request(running,'POST','/api/action',{'action':'recover'},headers={**headers,'Origin':'null'})[0]==403
    assert request(running,'POST','/api/action',{},headers={**headers,'Referer':'http://evil.example/'})[0]==403
    assert request(running,'POST','/api/action','x',headers={**headers,'Content-Type':'text/plain'})[0]==415
    assert request(running,'POST','/api/action','x'*20000,headers=headers)[0]==413
    assert request(running,'PUT','/api/action',{},headers=headers)[0]==405
    status,response,body=request(running,'POST','/api/action',{'action':'invalid'},headers=headers)
    assert status==400
    assert request(running,'POST','/api/action',{'action':'invalid'},headers=headers)[0]==403

def test_session_expiry_and_logout(running):
    cookie,csrf=login(running)
    assert request(running,'POST','/logout',{},headers={'Cookie':cookie,'X-CSRF-Token':csrf})[0]==200
    assert request(running,'GET','/api/session',headers={'Cookie':cookie})[0]==401

def test_ipv6_public_binding_is_unavailable(tmp_path):
    with pytest.raises(TypeError):DashboardServer(tmp_path,host='0.0.0.0')

def test_expired_session_and_cross_session_csrf(running):
    cookie,csrf=login(running)
    other,other_csrf=login(running)
    assert request(running,'POST','/api/action',{},headers={'Cookie':other,'X-CSRF-Token':csrf})[0]==403
    with running.session_lock:
        for session in running.sessions.values():session['expires']=0
    assert request(running,'GET','/api/session',headers={'Cookie':cookie})[0]==401

def test_static_allowlist_traversal_and_duplicate_inputs(running):
    cookie,csrf=login(running)
    for path in ('/../pyproject.toml','/%2e%2e/data/agent.db','/api/document?path=/etc/passwd','/config/profile.json'):
        assert request(running,'GET',path,headers={'Cookie':cookie})[0]==404
    assert request(running,'POST','/api/action','{"action":"prepare","action":"approve"}',headers={'Cookie':cookie,'X-CSRF-Token':csrf})[0]==400
    assert request(running,'GET','/api/job?id=a&id=b',headers={'Cookie':cookie})[0]==400

def test_native_process_launch_unicode_and_stop(tmp_path):
    import subprocess,sys
    root=tmp_path/'Fictional Ω Workspace';root.mkdir()
    child=subprocess.Popen([sys.executable,'-m','internship_agent.dashboard','--root',str(root),'--port','0'],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        address=child.stdout.readline().decode('ascii').strip().split()[-1]
        assert address.startswith('http://127.0.0.1:')
        secretline=child.stdout.readline().decode('ascii')
        assert 'Access secret' in secretline
        connection=http.client.HTTPConnection('127.0.0.1',int(address.rsplit(':',1)[1]),timeout=5)
        connection.request('GET','/',headers={'Host':address[7:]})
        response=connection.getresponse();assert response.status==200;response.read();connection.close()
    finally:
        child.terminate();child.wait(timeout=10)
    assert child.poll() is not None
