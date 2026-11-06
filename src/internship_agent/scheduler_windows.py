"""Owned Windows scheduling adapter. Rendering/preview has no native side effects."""
from dataclasses import asdict
import csv
import hashlib
import io
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET

from .scheduler import Config, Journal, RunLock, clean_result, load_config, supervise

NAMESPACE = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
NS = {'t':NAMESPACE}
IDENTITY_PATHS = ('RegistrationInfo/Description','RegistrationInfo/URI',
    'Principals/Principal/UserId','Principals/Principal/LogonType','Principals/Principal/RunLevel',
    'Actions/Exec/Command','Actions/Exec/Arguments','Actions/Exec/WorkingDirectory')


def local_path(value):
    if not isinstance(value,str) or any(ord(c)<32 for c in value) or any(c in value for c in '\"%&|<>^!`'):
        raise ValueError('Invalid local Windows path')
    path = PureWindowsPath(value)
    if not path.is_absolute() or not re.fullmatch('[A-Za-z]:',path.drive) or '..' in path.parts or any(':' in part or part.endswith((' ','.')) or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',part,re.I) for part in path.parts[1:]):
        raise ValueError('Absolute local Windows path required')
    return str(path)


def render_task(root, python, sid, *, at='09:00', timeout_seconds=1800, battery=True, wake=False, network_required=False):
    root, python = local_path(root), local_path(python)
    if not re.fullmatch(r'S-1-\d+(?:-\d+)+',sid):
        raise ValueError('Current user SID required')
    # Cross-platform validation of bounds without treating Windows paths as POSIX.
    Config(root=str(Path.cwd()),at=at,timeout_seconds=timeout_seconds,battery=battery,wake=wake,network_required=network_required)
    identity = hashlib.sha256((root.casefold()+'\0'+sid).encode()).hexdigest()[:20]
    name = 'InternshipAgent-Daily-'+identity
    task = ET.Element('Task', {'xmlns':NAMESPACE,'version':'1.4'})
    def add(parent,name,value=None,**attrs):
        node = ET.SubElement(parent,name,attrs)
        node.text = value
        return node
    info = add(task,'RegistrationInfo')
    add(info,'Description',f'Internship Agent daily scheduler v1; {root}; {sid}')
    add(info,'URI','\\'+name)
    triggers = add(task,'Triggers')
    calendar = add(triggers,'CalendarTrigger')
    repeat = add(calendar,'Repetition')
    add(repeat,'Interval','PT5M')
    add(repeat,'Duration','P1D')
    add(repeat,'StopAtDurationEnd','false')
    add(calendar,'StartBoundary','2026-01-01T'+at+':00')
    add(calendar,'Enabled','true')
    add(add(calendar,'ScheduleByDay'),'DaysInterval','1')
    logon = add(triggers,'LogonTrigger')
    add(logon,'Enabled','true'); add(logon,'UserId',sid)
    principal = add(add(task,'Principals'),'Principal',id='Owner')
    for key,value in [('UserId',sid),('LogonType','InteractiveToken'),('RunLevel','LeastPrivilege')]:
        add(principal,key,value)
    settings = add(task,'Settings')
    for key,value in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries',str(not battery).lower()),
        ('StopIfGoingOnBatteries',str(not battery).lower()),('AllowHardTerminate','true'),('StartWhenAvailable','true'),
        ('RunOnlyIfNetworkAvailable',str(network_required).lower()),('AllowStartOnDemand','true'),('Enabled','true'),
        ('Hidden','false'),('WakeToRun',str(wake).lower()),('ExecutionTimeLimit',f'PT{timeout_seconds+30}S'),('Priority','7')]:
        add(settings,key,value)
    action = add(add(task,'Actions',Context='Owner'),'Exec')
    add(action,'Command',python)
    add(action,'Arguments',subprocess.list2cmdline(['-m','internship_agent.scheduler','run','--root',root]))
    add(action,'WorkingDirectory',root)
    return {'name':name,'xml':ET.tostring(task,encoding='unicode'),'root':root,'python':python,'sid':sid}


def assert_owned_task(actual, expected):
    try:
        actual, expected = ET.fromstring(actual), ET.fromstring(expected)
        for path in IDENTITY_PATHS:
            query = '/'.join('t:'+part for part in path.split('/'))
            if actual.findtext(query,namespaces=NS) != expected.findtext(query,namespaces=NS):
                raise ValueError('Task identity/action drift; refusing operation')
        for path in ('Actions','Principals'):
            if len(actual.find('t:'+path,NS)) != 1:
                raise ValueError('Unexpected task actions/principals')
    except (ET.ParseError,TypeError,AttributeError):
        raise ValueError('Invalid task ownership') from None


def native(operation, definition):
    if os.name != 'nt':
        raise ValueError('Native Windows controls require Windows')
    script = Path(__file__).with_name('scheduler_control.ps1')
    executable = str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
    result = subprocess.run([executable,'-NoLogo','-NoProfile','-NonInteractive','-File',str(script),'-Operation',operation],
                            input=json.dumps(definition,ensure_ascii=True).encode('utf-8'),capture_output=True,timeout=30)
    if result.returncode:
        raise ValueError('Owned task operation refused; inspect Task Scheduler and configuration')
    return json.loads(result.stdout.decode('utf-8-sig'))


def current_sid():
    if os.name != 'nt':
        raise ValueError('Current user Windows SID unavailable')
    result = subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/whoami.exe'),'/user','/fo','csv','/nh'],
                            capture_output=True,check=True,timeout=10)
    # Only the ASCII SID column is used; user names never enter diagnostics.
    rows = list(csv.reader(io.StringIO(result.stdout.decode('utf-8',errors='replace'))))
    return rows[-1][-1].strip()


def definition(config, python, sid):
    return render_task(config.root,python,sid,at=config.at,timeout_seconds=config.timeout_seconds,
                       battery=config.battery,wake=config.wake,network_required=config.network_required)


def manage(operation, *, root, sid=None, python=None, native=native, approve=None, config=None):
    root = Path(root).resolve()
    sid = sid or current_sid()
    python = python or sys.executable
    config = config or (Config(root=str(root)) if operation in {'preview','install'} else load_config(root))
    # Synthetic preview accepts native Windows paths on any host, without filesystem writes.
    selected_root = str(root) if os.name == 'nt' else 'C:\\Synthetic\\'+root.name
    selected = render_task(selected_root,python,sid,at=config.at,timeout_seconds=config.timeout_seconds,
                           battery=config.battery,wake=config.wake,network_required=config.network_required)
    if operation == 'preview':
        return {**selected, 'configuration':asdict(config), 'simulation':os.name != 'nt'}
    if operation == 'install':
        if approve != 'INSTALL '+selected['name']:
            raise ValueError('Preview and exact installation approval required')
        if not root.is_dir() or not (root/'pyproject.toml').is_file() or not Path(python).is_file() or not (root/'config/sources.json').is_file():
            raise ValueError('Workspace, configured sources and Python must exist')
        # A task action must resolve this installed package, not an arbitrary PATH command.
        subprocess.run([python,'-c','import internship_agent.scheduler'],check=True,capture_output=True,timeout=10,cwd=root)
        # Installation/update is serialized with workers. A live worker is never replaced.
        with RunLock(config.directory/'worker.lock'):
            journal = Journal(config,create=True)
            native('install',selected)
            path = config.directory/'config.json'
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(asdict(config),ensure_ascii=True),encoding='utf-8')
            os.replace(temporary,path)
            journal.control('start')
        return {'status':'installed','name':selected['name']}
    if operation not in {'start','stop','disable','remove','status'}:
        raise ValueError('Unknown scheduling operation')
    # Adapter verifies all ownership fields before any control mutation.
    result = native('inspect',selected)
    if operation == 'status':
        return {'native':result,'journal':Journal(config).status()}
    if not result.get('exists') and operation != 'remove':
        raise ValueError('Owned task missing')
    Journal(config).control(operation)
    if operation == 'start':
        native('start',selected)
    elif operation in {'disable','remove'}:
        # Do not Task.Stop(): let the supervisor terminate only its exact child.
        native(operation,selected)
    return {'status':operation,'native':result,'journal':Journal(config).status()}


def notification_text(result):
    result = clean_result(result)
    advice = {'provider':'Review source-health; bounded retries respect cooldowns.',
              'partial':'Review source-health; scan incomplete.', 'configuration':'Check local source/profile configuration.',
              'database':'Stop competing writers; inspect compatible database/backup.',
              'interrupted':'Interrupted run; inspect scheduler status.', 'timeout':'Run timed out; inspect scheduler status.',
              'cancelled':'Stopped by operator.', 'internal':'Inspect scheduler status before retrying.', 'none':'See scheduler status.'}
    counts = ', '.join(f'{key}={value}' for key,value in sorted(result['counts'].items()))
    return f"Internship Agent: {result['status']}. {counts}. {advice[result['category']]}"


def notify_windows(result):
    if os.name != 'nt':
        raise OSError('Windows notification unavailable')
    # Fixed script, stdin text; no shell interpolation of paths, job content or errors.
    script = """$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$n=New-Object System.Windows.Forms.NotifyIcon
try {
$n.Icon=[System.Drawing.SystemIcons]::Information
$n.Visible=$true
$n.ShowBalloonTip(3000,'Internship Agent',[Console]::In.ReadToEnd(),[System.Windows.Forms.ToolTipIcon]::Info)
Start-Sleep -Seconds 3
} finally { $n.Dispose() }
"""
    subprocess.run([str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'),
                    '-NoLogo','-NoProfile','-NonInteractive','-Command',script],
                   input=notification_text(result).encode('ascii'),capture_output=True,check=True,timeout=10)


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(prog='internship-agent scheduler')
    p.add_argument('operation',choices=['setup','preview','install','start','stop','status','disable','remove','run'])
    p.add_argument('--root',default=str(Path.cwd()))
    p.add_argument('--at',default='09:00')
    p.add_argument('--timeout-seconds',type=int,default=1800)
    p.add_argument('--no-battery',action='store_true')
    p.add_argument('--wake',action='store_true')
    p.add_argument('--network-required',action='store_true')
    p.add_argument('--no-notifications',action='store_true')
    p.add_argument('--approve')
    args = p.parse_args(argv)
    try:
        root = Path(args.root).resolve()
        if args.operation == 'run':
            result = supervise(load_config(root))
        else:
            config = None
            if args.operation in {'setup','preview','install'}:
                config = Config(root=str(root),at=args.at,timeout_seconds=args.timeout_seconds,battery=not args.no_battery,
                                wake=args.wake,network_required=args.network_required,notifications=not args.no_notifications)
            if args.operation == 'setup':
                selected = manage('preview',root=root,config=config)
                print(json.dumps(selected,indent=2,ensure_ascii=True))
                print(json.dumps(asdict(config),indent=2,ensure_ascii=True))
                print('Current user only; runs while signed in, including locked desktop. No Google or application actions.')
                args.approve = input('To install/update, type INSTALL '+selected['name']+': ')
                args.operation = 'install'
            result = manage(args.operation,root=root,config=config,approve=args.approve)
        print(json.dumps(result,indent=2,ensure_ascii=True))
    except (ValueError,OSError,subprocess.SubprocessError,TypeError,KeyError,sqlite3.Error):
        p.exit(2,'Scheduler control failed; check local settings, task ownership and journal. No raw error logged.\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
