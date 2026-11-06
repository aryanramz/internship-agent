"""Bounded, local dashboard facade over the authoritative application workflow.

This module does not accept configuration paths, integrate with Google, or submit
applications. Its responses are explicit projections, never internal Store rows.
"""
from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import stat
import sqlite3
import zipfile
from xml.etree import ElementTree

from .application_workflow import FILES, Workflow
from .eligibility import evaluate_eligibility
from .role_taxonomy import ALIASES, tracks
from .scoring import evaluate
from .service import Agent
from .store import STATUSES, Store

PAGE_SIZE = 25
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
KINDS = {'resume': 'resume_path', 'letter': 'letter_path', 'answers': 'answers_path'}
NOTE = 'Submission records are user supplied; employer receipt is not independently verified.'
_ANALYSIS_FIELDS = ('id', 'title', 'description', 'location', 'work_mode', 'published_at',
                    'compensation', 'company', 'job_url', 'apply_url')


def _text(value, limit=500):
    return str(value or '')[:limit]


def _bounded(value, depth=0):
    if depth > 7:
        return None
    if isinstance(value, str):
        return value[:1000]
    if isinstance(value, list):
        return [_bounded(item, depth + 1) for item in value[:100]]
    if isinstance(value, dict):
        return {_text(key, 100): _bounded(item, depth + 1) for key, item in list(value.items())[:40]}
    return value if value is None or isinstance(value, (bool, int, float)) else None


def _id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or any(ord(c) < 32 for c in value):
        raise ValueError('A valid job ID is required')
    return value


class _NestedConnection:
    """Let existing Store commands share an already-held writer transaction."""
    def __init__(self, connection):
        self.connection = connection

    def execute(self, sql, parameters=()):
        if sql.strip().upper() == 'BEGIN IMMEDIATE':
            return self.connection.execute('SELECT 1')
        return self.connection.execute(sql, parameters)


class _TransactionStore(Store):
    def __init__(self, original, connection):
        self.path = original.path
        self.read_only = False
        self._connection = connection

    @contextmanager
    def connection(self):
        yield _NestedConnection(self._connection)


class DashboardData:
    """The root fixes all private inputs and the managed output directory."""
    def __init__(self, root: Path):
        raw = Path(root).absolute()
        if any(p.is_symlink() for p in (raw, *raw.parents)):
            raise ValueError('Dashboard root must not contain symbolic links')
        self.root = raw.resolve()
        self.data = self.root / 'data'
        self.profile = self.root / 'config' / 'profile.json'
        self.sources = self.root / 'config' / 'sources.json'
        self._check_paths()
        # Browsing must never initialize or migrate the authoritative ledger.
        self.agent = Agent(str(self.data), read_only=True) if (self.data / 'agent.db').is_file() else None
        self.store = self.agent.store if self.agent else None

    def _check_paths(self):
        for path in (self.data, self.data / 'agent.db', self.profile, self.sources):
            if any(p.is_symlink() for p in (path, *path.parents)):
                raise ValueError('Dashboard inputs must not contain symbolic links')

    def _profile(self):
        self._check_paths()
        if not self.profile.is_file():
            return None
        return self.agent._eligibility_profile(str(self.profile))

    def _analysis(self, job, profile):
        if profile is None:
            return ({'score': None, 'components': {}, 'kind': 'heuristic_fit',
                     'missing_information': ['profile']},
                    {'outcome': 'unknown', 'required_rule_count': 0,
                     'missing_information': ['profile'], 'manual_verification': ['Configure and review the local profile.'],
                     'limitations': ['Eligibility is independent of fit score.']})
        fit = evaluate(job, profile, as_of=self.agent.clock())
        eligibility = evaluate_eligibility(profile, job, as_of=self.agent.clock().date())
        safe_eligibility = {k: eligibility[k] for k in ('outcome', 'required_rule_count')}
        for key in ('missing_information', 'manual_verification', 'limitations'):
            safe_eligibility[key] = [_text(value, 500) for value in eligibility[key][:50]]
        safe_eligibility['rules'] = self._rules(eligibility['rules'])
        explanation = fit['ranking_explanation']
        safe_explanation = _bounded({key: explanation[key] for key in (
            'schema_version', 'score_kind', 'analysis', 'as_of', 'eligibility', 'weights', 'units',
            'contributions', 'rounding', 'role', 'preference_effects', 'missing_information',
            'confidence', 'observed_evidence', 'limitations')})
        return ({'score': fit['score'], 'components': fit['components'], 'kind': 'heuristic_fit',
                 'flags': [_text(v) for v in fit['flags'][:20]],
                 'missing_information': fit['ranking_explanation']['missing_information'][:30],
                 'role_relation': explanation['role']['relation'], 'ranking_explanation': safe_explanation},
                safe_eligibility)

    @staticmethod
    def _rules(rules):
        """Keep requirement reasoning and posting evidence; omit candidate facts."""
        output = []
        def walk(nodes, depth=0):
            if depth > 8:
                return
            for node in nodes:
                if len(output) >= 50:
                    return
                if 'rules' in node:
                    walk(node['rules'], depth + 1)
                else:
                    item = {k: _text(node.get(k), 500) for k in ('id', 'kind', 'strength', 'outcome', 'reason')}
                    evidence = node.get('evidence') or []
                    if isinstance(evidence, dict):
                        evidence = [evidence]
                    item['evidence'] = [{k: _text(e.get(k), 1000) for k in ('source', 'text')}
                                        for e in evidence[:5] if isinstance(e, dict)]
                    output.append(item)
        walk(rules)
        return output

    @staticmethod
    def _availability(c, jid):
        rows = c.execute('SELECT source_id,status,reason,last_seen_at,status_at FROM discovery_job_sources '
                         'WHERE job_id=? ORDER BY source_id LIMIT 20', (jid,)).fetchall()
        sources = [{k: _text(r[k], 100) for k in r.keys()} for r in rows]
        totals = c.execute('SELECT status,COUNT(*) n FROM discovery_job_sources WHERE job_id=? GROUP BY status', (jid,)).fetchall()
        states = {r['status'] for r in totals}
        status = next((s for s in ('reopened', 'available', 'unknown', 'closed') if s in states), 'unknown')
        return {'status': status, 'sources': sources, 'total_sources': sum(r['n'] for r in totals), 'source_limit': 20,
                'note': 'Posting availability is separate from application status; unknown is not closed.'}

    def _project_job(self, c, job, profile, *, detail=False):
        ranking, eligibility = self._analysis(job, profile)
        result = {k: _text(job.get(k), 1000 if k.endswith('_url') else 500)
                  for k in ('id', 'title', 'company', 'location', 'provider', 'source_id', 'status', 'work_mode', 'job_url', 'apply_url')}
        result.update(job_id=result['id'], ranking=ranking, eligibility=eligibility,
                      tracks=sorted(tracks(job['title'], title=True)), availability=self._availability(c, job['id']))
        if detail:
            result.update({k: _text(job.get(k), 20000 if k == 'description' else 500)
                           for k in ('description', 'compensation', 'published_at', 'discovered_at', 'last_seen_at')})
        return result

    def get(self, route: str, query: dict[str, str] | None = None) -> dict:
        self._check_paths()
        query = query or {}
        if not isinstance(query, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in query.items()):
            raise ValueError('Query parameters must be text')
        route = route.strip('/')
        if route == 'overview':
            counts = {status: 0 for status in STATUSES}
            source_counts = {}
            eligibility_counts = dict.fromkeys(('eligible', 'uncertain', 'ineligible', 'unknown'), 0)
            if self.store:
                counts.update({k: v for k, v in self.store.count().items() if k in counts})
                profile = self._profile()
                with self.store.connection() as c:
                    source_counts = {_text(r['status'], 50): r['n'] for r in c.execute(
                        'SELECT status,COUNT(*) n FROM discovery_sources GROUP BY status LIMIT 30')}
                    fields = ','.join('j.' + k for k in _ANALYSIS_FIELDS)
                    c.create_function('dashboard_eligibility', len(_ANALYSIS_FIELDS), lambda *values:
                        evaluate_eligibility(profile, dict(zip(_ANALYSIS_FIELDS, values)), as_of=self.agent.clock().date())['outcome']
                        if profile is not None else 'unknown')
                    for row in c.execute(f'SELECT dashboard_eligibility({fields}) outcome,COUNT(*) n FROM jobs j GROUP BY outcome'):
                        eligibility_counts[row['outcome']] = row['n']
            return {'counts': counts, 'total_jobs': sum(counts.values()), 'prepared': counts['prepared'],
                    'awaiting_approval': counts['prepared'], 'submitted': counts['submitted'],
                    'outcomes': {s: counts[s] for s in ('assessment', 'interview', 'offer', 'rejected', 'withdrawn')},
                    'profile_available': self.profile.is_file(), 'sources': source_counts, 'eligibility_counts': eligibility_counts,
                    'definitions': {'total_jobs': 'All locally recorded postings, including closed or unknown availability.',
                                    'awaiting_approval': 'Current application status is prepared; integrity still requires review.',
                                    'submitted': 'Current status is submitted; later outcomes have separate counts.',
                                    'unknown': 'Missing evidence is unknown; fit score does not establish eligibility.'},
                    'note': NOTE}
        if route == 'jobs':
            return self._jobs(query)
        if route == 'job':
            if not self.store:
                raise ValueError('Unknown job ID')
            return self._detail(_id(query.get('id')))
        if route == 'review':
            if not self.store:
                raise ValueError('A managed preparation is required')
            return self._review(_id(query.get('id')))
        if route == 'operations':
            return self._operations()
        raise ValueError('Unknown dashboard route')

    def _jobs(self, query):
        if set(query) - {'search', 'status', 'eligibility', 'track', 'location', 'page'}:
            raise ValueError('Unknown jobs filter')
        filters = {key: query.get(key, '').strip() for key in ('search', 'status', 'eligibility', 'track', 'location')}
        if any(len(v) > 200 for v in filters.values()):
            raise ValueError('Filter is too long')
        if filters['status'] not in ('', 'all', *STATUSES):
            raise ValueError('Unknown status filter')
        if filters['eligibility'] not in ('', 'all', 'eligible', 'ineligible', 'uncertain', 'unknown'):
            raise ValueError('Unknown eligibility filter')
        if filters['track'] not in ('', 'all', *ALIASES):
            raise ValueError('Unknown track filter')
        page_text = query.get('page', '1')
        if not re.fullmatch(r'[0-9]{1,8}', page_text) or int(page_text) < 1:
            raise ValueError('Page must be a positive integer')
        page = int(page_text)
        if not self.store:
            return {'jobs': [], 'total': 0, 'page': page, 'page_size': PAGE_SIZE, 'pages': 1, 'filters': filters}
        profile = self._profile()
        clauses, params = [], []
        for key, column in (('search', "j.title || ' ' || j.company"), ('location', 'j.location')):
            if filters[key]:
                clauses.append(f"instr(lower({column}),lower(?))>0")
                params.append(filters[key])
        if filters['status'] not in ('', 'all'):
            clauses.append('a.status=?')
            params.append(filters['status'])
        if filters['track'] not in ('', 'all'):
            clauses.append('dashboard_track(j.title,?)=1')
            params.append(filters['track'])
        fields = ','.join('j.' + k for k in _ANALYSIS_FIELDS)
        if filters['eligibility'] not in ('', 'all'):
            clauses.append(f'dashboard_eligibility({fields})=?')
            params.append(filters['eligibility'])
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        base = ' FROM jobs j JOIN applications a ON a.job_id=j.id'
        with self.store.connection() as c:
            c.create_function('dashboard_track', 2, lambda title, track: int(track in tracks(title, title=True)))
            c.create_function('dashboard_eligibility', len(_ANALYSIS_FIELDS),
                              lambda *values: self._analysis(dict(zip(_ANALYSIS_FIELDS, values)), profile)[1]['outcome'])
            total = c.execute('SELECT COUNT(*)' + base + where, params).fetchone()[0]
            rows = c.execute('SELECT j.*,a.status' + base + where +
                             ' ORDER BY j.last_seen_at DESC,j.id LIMIT ? OFFSET ?',
                             (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
            jobs = [self._project_job(c, dict(r), profile) for r in rows]
        return {'jobs': jobs, 'total': total, 'page': page, 'page_size': PAGE_SIZE,
                'pages': max(1, math.ceil(total / PAGE_SIZE)), 'filters': filters}

    def _detail(self, jid):
        job = self.store.get_job(jid)
        profile = self._profile()
        with self.store.connection() as c:
            projected = self._project_job(c, job, profile, detail=True)
            rows = c.execute('SELECT event_type,created_at,payload_json FROM events WHERE job_id=? ORDER BY id DESC LIMIT 100', (jid,)).fetchall()
            history = []
            for row in reversed(rows):
                entry = {k: _text(row[k], 100) for k in ('event_type', 'created_at')}
                if row['event_type'] in {'submitted', 'status_updated'} and len(row['payload_json']) <= 8192:
                    payload = json.loads(row['payload_json'])
                    entry['evidence'] = _text(payload.get('evidence'), 4000)
                    entry['evidence_kind'] = 'user_supplied'
                    if row['event_type'] == 'status_updated':
                        entry['status'] = _text(payload.get('new_status'), 30)
                history.append(entry)
            preparations = self._preparations(c, jid)
        application = {k: job.get(k) for k in ('status', 'approved_at', 'submitted_at', 'submission_evidence_kind')}
        application['employer_receipt_verified'] = False
        application['submission_evidence'] = _text(job.get('submission_evidence'), 4000)
        return {'job': projected, 'ranking': projected['ranking'], 'eligibility': projected['eligibility'],
                'application': application, 'history': history, 'availability': projected['availability'],
                'preparations': preparations, 'history_limit': 100, 'note': NOTE}

    @staticmethod
    def _preparations(c, jid=None):
        where = ' WHERE job_id=?' if jid else ''
        rows = c.execute('SELECT operation_id,job_id,state,created_at,completed_at FROM preparation_operations' +
                         where + ' ORDER BY created_at DESC,operation_id LIMIT 100', (jid,) if jid else ()).fetchall()
        return [{k: _text(r[k], 128) for k in r.keys()} for r in rows]

    def _operations(self):
        if not self.store:
            return {'preparations': [], 'sources': [], 'runs': [], 'counts': {}, 'limit': 100,
                    'scheduler': self._scheduler(), 'integrations': self._integrations()}
        with self.store.connection() as c:
            preparations = self._preparations(c)
            sources = [{k: _text(r[k], 128) if r[k] is not None else None for k in r.keys()} for r in c.execute(
                'SELECT source_id,provider,status,last_attempt_at,last_success_at,next_retry_at,failure_count,error_code,http_status '
                'FROM discovery_sources ORDER BY last_attempt_at DESC,source_id LIMIT 100')]
            runs = [{k: r[k] if isinstance(r[k], int) or r[k] is None else _text(r[k], 128) for k in r.keys()}
                    for r in c.execute('SELECT run_id,source_id,provider,status,started_at,completed_at,page_count,'
                    'accepted_count,rejected_count,error_code FROM discovery_runs ORDER BY started_at DESC,run_id LIMIT 100')]
            counts = {r['state']: r['n'] for r in c.execute('SELECT state,COUNT(*) n FROM preparation_operations GROUP BY state')}
        return {'preparations': preparations, 'sources': sources, 'runs': runs, 'counts': counts, 'limit': 100,
                'scheduler': self._scheduler(), 'integrations': self._integrations()}

    def _scheduler(self):
        directory = self.data / 'scheduler'
        journal = directory / 'journal.db'
        result = {'configuration_present': (directory / 'config.json').is_file(),
                  'journal_present': journal.is_file(), 'native_task': 'not_checked', 'latest': None}
        if any(p.is_symlink() for p in (directory, journal, directory / 'config.json')):
            result['status'] = 'unavailable'
            return result
        result['status'] = 'not_configured'
        if not journal.is_file():
            return result
        try:
            connection = sqlite3.connect(journal.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                connection.execute('PRAGMA query_only=ON')
                row = connection.execute('SELECT enabled,stopped FROM controls WHERE id=1').fetchone()
                result['status'] = 'disabled' if not row[0] else 'stopped' if row[1] else 'enabled'
                latest = connection.execute('SELECT status,category,started,retry_at FROM windows ORDER BY window DESC LIMIT 1').fetchone()
                if latest:
                    result['latest'] = {k: _text(value, 100) for k, value in zip(('status', 'category', 'started', 'retry_at'), latest)}
            finally:
                connection.close()
        except (sqlite3.Error, TypeError):
            result['status'] = 'unavailable'
        return result

    @staticmethod
    def _integrations():
        return {'google': {'status': 'unconnected', 'qualification': 'not_checked'},
                'mcp': {'status': 'unqualified', 'qualification': 'no_authenticated_invocation_verified'},
                'note': 'This dashboard does not connect to Google or qualify external integrations.'}

    def _packet_preflight(self, c, jid):
        binding = c.execute('SELECT packet_json,profile_path,operation_id FROM application_bindings WHERE job_id=?', (jid,)).fetchone()
        if binding is None or len(binding['packet_json']) > 16384:
            raise ValueError('A current managed preparation is required')
        if Path(binding['profile_path']) != self.profile.resolve():
            raise ValueError('Preparation must use the configured dashboard profile')
        packet = json.loads(binding['packet_json'])
        operation = binding['operation_id']
        if not re.fullmatch('[a-f0-9]{32}', operation):
            raise ValueError('Invalid managed preparation')
        managed = self.data / 'generated' / 'operations' / operation
        parent = None
        for key, name in FILES.items():
            path = Path(packet.get(key, ''))
            if (not path.is_absolute() or path.name != name or not path.is_relative_to(managed)
                    or not path.resolve().is_relative_to(managed.resolve())
                    or any(p.is_symlink() for p in (path, *path.parents))):
                raise ValueError('Unsafe document packet')
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DOCUMENT_BYTES:
                raise ValueError('Document packet exceeds the review limit')
            if parent is not None and path.parent != parent:
                raise ValueError('Invalid document packet')
            parent = path.parent
        return packet

    def _checked(self, c, jid, token=None):
        self._check_paths()
        self._packet_preflight(c, jid)
        job, binding, packet = Workflow(self.store)._check_binding(c, jid)
        if token is not None and (not isinstance(token, str) or token != binding['review_token']):
            raise ValueError('The current review token is required')
        return job, binding, packet

    def _review(self, jid):
        with self.store.connection() as c:
            job, binding, packet = self._checked(c, jid)
            token = binding['review_token']
        # Workflow.review is the source of the QA information, after preflight.
        review = self.store.review(jid)
        if review['review_token'] != token:
            raise ValueError('Preparation changed during review; refresh')
        documents = []
        for kind in KINDS:
            data, filename = self.document(jid, token, kind)
            documents.append({'kind': kind, 'filename': filename, **self._document_text(data)})
        qa = review['qa']
        from .document_profile import normalize_document_profile
        model = normalize_document_profile(self.agent._ranking_profile(str(self.profile)))
        gaps = []
        for gap in model['unresolved'][:100]:
            parts = gap['path'].strip('/').split('/')
            gaps.append({'field': _text(parts[0], 80), 'reason': _text(gap['reason'], 200),
                         'item': int(parts[1]) + 1 if len(parts) > 1 and parts[1].isdigit() else None})
        file_checks = []
        for kind, key in KINDS.items():
            filename = FILES[key]
            info = qa.get('files', {}).get(filename, {})
            file_checks.append({'kind': kind, 'filename': filename, 'sha256': _text(info.get('sha256'), 64),
                                'checks': {k: value is True for k, value in list(info.get('checks', {}).items())[:30]},
                                'warnings': [_text(w, 500) for w in info.get('warnings', [])[:20]]})
        with self.store.connection() as c:
            self._checked(c, jid, token)
        return {'job_id': jid, 'status': job['status'], 'review_token': token, 'documents': documents,
                'revision': _text(packet.get('revision'), 80), 'variant': _text(packet.get('variant'), 30),
                'track': _text(packet.get('track'), 30), 'job_sha256': _text(binding['job_sha'], 64),
                'packet_sha256': _text(binding['packet_sha'], 64),
                'qa': {'structural_pass': qa.get('structural_pass') is True, 'review_required': True,
                       'unresolved_count': min(100000, max(0, int(qa.get('unresolved_count', 0)))),
                       'unresolved': gaps, 'files': file_checks,
                       'rendering': {'status': _text(qa.get('rendering', {}).get('status'), 50)},
                       'ats_guarantee': False},
                'note': 'Inspect every document and original posting. Approval is separate from recording manual submission.'}

    @staticmethod
    def _document_text(data):
        with zipfile.ZipFile(BytesIO(data)) as archive:
            if len(archive.infolist()) > 256:
                raise ValueError('Document archive exceeds the review limit')
            info = archive.getinfo('word/document.xml')
            if info.file_size > MAX_DOCUMENT_BYTES:
                raise ValueError('Document text exceeds the review limit')
            raw = archive.read(info)
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise ValueError('Unsupported document XML')
        root = ElementTree.fromstring(raw)
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        lines = []
        remaining = 40000
        truncated = False
        for paragraph in root.iter(ns + 'p'):
            if len(lines) >= 500 or remaining <= 0:
                truncated = True
                break
            full = ''.join(node.text or '' for node in paragraph.iter(ns + 't'))
            text = full[:min(4000, remaining)]
            truncated = truncated or len(text) < len(full)
            lines.append(text)
            remaining -= len(text) + 1
        return {'text': '\n'.join(lines), 'text_truncated': truncated,
                'warning': 'Preview truncated. Download and inspect the full DOCX before approval.' if truncated else ''}

    def document(self, jid, review_token, kind):
        jid = _id(jid)
        if not self.store:
            raise ValueError('A managed preparation is required')
        if kind not in KINDS or not isinstance(review_token, str) or not re.fullmatch('[a-f0-9]{64}', review_token):
            raise ValueError('A current review token and document kind are required')
        with self.store.connection() as c:
            _, _, packet = self._checked(c, jid, review_token)
            path = Path(packet[KINDS[kind]])
            descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            with os.fdopen(descriptor, 'rb') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError('Invalid document file')
                data = stream.read(MAX_DOCUMENT_BYTES + 1)
            if len(data) > MAX_DOCUMENT_BYTES:
                raise ValueError('Document exceeds the download limit')
            # Bind the returned bytes as well as the file checked by Workflow.
            from hashlib import sha256
            qa = json.loads(Path(packet['qa_path']).read_text(encoding='utf-8'))
            if sha256(data).hexdigest() != qa['files'][path.name]['sha256']:
                raise ValueError('Document changed during download')
            self._checked(c, jid, review_token)
        return data, path.name

    def action(self, name: str, payload: dict) -> dict:
        self._check_paths()
        if name not in {'discover', 'prepare', 'approve', 'submitted', 'status', 'recover'} or not isinstance(payload, dict):
            raise ValueError('Unknown dashboard action')
        if name != 'approve' and payload.get('confirm') != name:
            raise ValueError('Explicit action confirmation is required')
        # Schema creation and migrations are authorized only by an explicit write.
        self.agent = Agent(str(self.data))
        self.store = self.agent.store
        if name == 'discover':
            result = self.agent.discover(str(self.sources), max_pages=3, max_sources=20)
            return {'ok': True, 'action': name, 'summary': {k: result[k] for k in ('added', 'updated', 'duplicate')},
                    'error_count': len(result['errors']), 'skipped_count': len(result['skipped'])}
        if name == 'recover':
            jid = _id(payload['id']) if payload.get('id') else None
            result = self.agent.recover(jid)
            return {'ok': True, 'action': name, 'operations': [
                {'operation_id': _text(op.get('operation_id'), 32), 'state': _text(op.get('state'), 20)}
                for op in result['operations'][:100]]}
        jid = _id(payload.get('id'))
        if name == 'prepare':
            if payload.get('variant', 'job') not in {'job', 'track', 'master'}:
                raise ValueError('Unknown preparation variant')
            if payload.get('track') is not None and payload['track'] not in ALIASES:
                raise ValueError('Unknown preparation track')
            if ((payload.get('variant') == 'track' and not payload.get('track'))
                    or (payload.get('variant') == 'master' and payload.get('track') is not None)):
                raise ValueError('Track preparation requires a track; master does not accept one')
            if type(payload.get('new_revision', False)) is not bool:
                raise ValueError('New revision must be boolean')
            self.agent.prepare(jid, str(self.profile), variant=payload.get('variant', 'job'),
                               track=payload.get('track'), request_id=payload.get('request_id'),
                               new_revision=payload.get('new_revision', False))
            return {'ok': True, 'action': name, 'review': self._review(jid)}
        token = payload.get('review_token')
        if not isinstance(token, str) or not re.fullmatch('[a-f0-9]{64}', token):
            raise ValueError('The current review token is required')
        with Workflow(self.store).writer() as c:
            self._checked(c, jid, token)
            bound = _TransactionStore(self.store, c)
            if name == 'approve':
                bound.approve(jid, payload.get('phrase'), review_token=token)
            elif name == 'submitted':
                bound.mark_submitted(jid, payload.get('evidence'), approval_token=token)
            else:
                evidence = payload.get('evidence', '')
                if not isinstance(evidence, str) or len(evidence) > 4000 or any(ord(ch) < 32 for ch in evidence):
                    raise ValueError('Outcome evidence must be short text')
                bound.update_status(jid, payload.get('status'), evidence)
        return {'ok': True, 'action': name, 'job': self._detail(jid)['job'], 'note': NOTE}
