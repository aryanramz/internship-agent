"""Native task definitions and mocked lifecycle only: no task registration."""
import json
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from internship_agent.scheduler_windows import render_task, assert_owned_task, notification_text, manage

NS = {'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}


def task(**kw):
    values = dict(root=r'C:\Synthetic Ω Workspace\agent', python=r'C:\Synthetic Ω Workspace\agent\.venv\Scripts\python.exe', sid='S-1-5-21-1000')
    values.update(kw)
    return render_task(**values)


def test_task_is_current_user_bounded_non_shell_and_stable():
    t = task()
    xml = ET.fromstring(t['xml'])
    def field(path):
        return xml.findtext('/'.join('t:'+part for part in path.split('/')),namespaces=NS)
    assert field('Principals/Principal/LogonType') == 'InteractiveToken'
    assert field('Principals/Principal/RunLevel') == 'LeastPrivilege'
    assert field('Settings/MultipleInstancesPolicy') == 'IgnoreNew'
    assert field('Settings/ExecutionTimeLimit') == 'PT1830S'
    assert field('Settings/WakeToRun') == 'false'
    assert field('Settings/RunOnlyIfNetworkAvailable') == 'false'
    assert field('Actions/Exec/Command').endswith('python.exe')
    assert field('Actions/Exec/Arguments').startswith('-m internship_agent.scheduler run --root ')
    assert field('Triggers/CalendarTrigger/Repetition/Interval') == 'PT5M'
    assert task()['name'] == t['name']
    assert task(sid='S-1-5-21-2000')['name'] != t['name']


@pytest.mark.parametrize('old,new', [('LeastPrivilege','HighestAvailable'), ('InteractiveToken','Password'),
    ('internship_agent.scheduler','unrelated'),('S-1-5-21-1000','S-1-5-21-2000'),('python.exe','other.exe'),
    ('</Actions>','<Exec><Command>unrelated</Command></Exec></Actions>')])
def test_mutations_refuse_foreign_task(old,new):
    expected = task()['xml']
    with pytest.raises(ValueError):
        assert_owned_task(expected.replace(old,new),expected)
    assert_owned_task(expected,expected)


@pytest.mark.parametrize('value', ['relative',r'\\server\share',r'C:\bad"name', 'C:\\bad\nname',r'C:\bad\..\name',r'C:\bad%path'])
def test_invalid_windows_paths_refused(value):
    with pytest.raises(ValueError):
        task(root=value)


def test_notifications_project_only_allowlisted_counts_and_categories():
    text = notification_text({'status':'partial','category':'provider','counts':{'added':2,'title':'PRIVATE','token':'SECRET'},'raw':'PRIVATE'})
    assert 'PRIVATE' not in text and 'SECRET' not in text
    assert '2' in text and 'source-health' in text


def test_preview_does_not_call_native_adapter_or_write(tmp_path):
    before = list(tmp_path.iterdir())
    value = manage('preview', root=tmp_path, sid='S-1-5-21-1000', python=r'C:\Python\python.exe',native=lambda *args:pytest.fail())
    assert value['name'].startswith('InternshipAgent-Daily-')
    assert list(tmp_path.iterdir()) == before


@pytest.mark.parametrize('value',[r'C:\safe\agent:ads',r'C:\safe\CON',r'C:\safe\trailing.',r'C:\safe\trailing '])
def test_ads_and_ambiguous_device_paths_are_rejected(value):
    with pytest.raises(ValueError):
        task(root=value)


@pytest.mark.skipif(sys.platform!='win32',reason='Windows COM definition/PowerShell ownership validation requires Windows; never installs tasks')
def test_native_xml_and_actual_powershell_ownership_function(tmp_path):
    from internship_agent import scheduler_windows
    path=tmp_path/'definition.json'
    path.write_text(json.dumps(task(),ensure_ascii=True),encoding='ascii')
    script=r'''
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$d=Get-Content -Raw -LiteralPath $args[0] | ConvertFrom-Json
$tokens=$null; $errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile($args[1],[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw 'Adapter syntax failed' }
$fn=$ast.Find({param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Assert-OwnedTask'},$true)
. ([scriptblock]::Create($fn.Extent.Text))
Assert-OwnedTask ([xml]$d.xml) ([xml]$d.xml)
$rejected=$false
try { Assert-OwnedTask ([xml]$d.xml.Replace('LeastPrivilege','HighestAvailable')) ([xml]$d.xml) } catch { $rejected=$true }
if (-not $rejected) { throw 'Foreign task accepted' }
# NewTask creates an in-memory definition only. RegisterTask is never called.
$s=New-Object -ComObject 'Schedule.Service'
$s.Connect()
$t=$s.NewTask(0)
$t.XmlText=$d.xml
Assert-OwnedTask ([xml]$t.XmlText) ([xml]$d.xml)
Write-Output 'Validated in-memory XML and actual ownership verifier; no registration'
'''
    # -File avoids quoting command strings and supports argument paths/Unicode.
    harness=tmp_path/'qualify-definition.ps1'
    harness.write_text(script,encoding='utf-8-sig')
    result=subprocess.run(['powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-File',str(harness),str(path),str(Path(scheduler_windows.__file__).with_name('scheduler_control.ps1'))],capture_output=True,timeout=30)
    assert result.returncode==0,result.stderr.decode('utf-8',errors='replace')


def test_reviewed_install_update_and_owned_controls_preserve_unrelated_state(tmp_path,monkeypatch):
    import internship_agent.scheduler_windows as windows
    from internship_agent.scheduler import Config
    (tmp_path/'pyproject.toml').write_text('[project]\nname="fictional"\n')
    (tmp_path/'config').mkdir()
    (tmp_path/'config/sources.json').write_text('{"boards":[]}')
    render=windows.render_task
    monkeypatch.setattr(windows,'render_task',lambda root,python,sid,**kw:render(r'C:\Synthetic\agent',r'C:\Synthetic\python.exe',sid,**kw))
    registry={'unrelated':{'xml':'sentinel','enabled':True}}
    calls=[]
    def adapter(operation,definition):
        calls.append(operation)
        current=registry.get(definition['name'])
        if current:
            windows.assert_owned_task(current['xml'],definition['xml'])
        if operation=='install': registry[definition['name']]={'xml':definition['xml'],'enabled':True}
        if operation=='disable': current['enabled']=False
        if operation=='start': current['enabled']=True
        if operation=='remove': registry.pop(definition['name'],None)
        return {'exists':current is not None}
    args=dict(root=tmp_path,sid='S-1-5-21-1000',python=sys.executable,native=adapter)
    preview=windows.manage('preview',**args)
    assert calls==[]
    with pytest.raises(ValueError): windows.manage('install',**args,approve='incorrect')
    assert calls==[] and not (tmp_path/'data').exists()
    for _ in range(2):
        windows.manage('install',**args,approve='INSTALL '+preview['name'])
    assert len(registry)==2
    windows.manage('disable',**args)
    assert registry[preview['name']]['enabled'] is False
    # A foreign action drift is refused before touching even local controls.
    registry[preview['name']]['xml']=registry[preview['name']]['xml'].replace('internship_agent.scheduler','foreign')
    with pytest.raises(ValueError): windows.manage('start',**args)
    registry[preview['name']]['xml']=preview['xml']
    (tmp_path/'config/sources.json').unlink()
    windows.manage('remove',**args)
    assert registry=={'unrelated':{'xml':'sentinel','enabled':True}}
    assert (tmp_path/'data/scheduler/journal.db').is_file()
