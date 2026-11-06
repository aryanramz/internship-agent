"""Private local sandbox assistance journal. No browser or network operations.

A fixture observation is not evidence of an application or employer receipt.
Only explicit creation installs this additive schema in the existing ledger.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
import secrets
import sqlite3

from .dashboard_data import DashboardData
from .document_profile import digest, normalize_document_profile
from .profile_io import read_profile

FORM = {'version': 1, 'method': 'POST', 'fields': [
    {'name': 'name', 'type': 'text', 'max_length': 200},
    {'name': 'email', 'type': 'email', 'max_length': 254},
    {'name': 'legal', 'type': 'manual'}, {'name': 'eeo', 'type': 'manual'},
    {'name': 'work_authorization', 'type': 'manual'}]}
FORM_FINGERPRINT = digest(FORM)
TTL_SECONDS = 900
_OPEN = ('plan', 'filled', 'handoff', 'needs_manual_reconciliation', 'reconciled_submitted')


class Assistance:
    def __init__(self, root, origin, session, enabled=False, clock=None):
        if not isinstance(origin, str) or not re.fullmatch(r'http://127\.0\.0\.1:[0-9]{1,5}', origin):
            raise ValueError('Assistance requires the numeric loopback HTTP origin')
        if not 1 <= int(origin.rsplit(':', 1)[1]) <= 65535:
            raise ValueError('Invalid sandbox port')
        if not isinstance(session, str) or not 1 <= len(session) <= 256:
            raise ValueError('An authenticated local session is required')
        self.dashboard = DashboardData(root)
        self.origin, self.session, self.enabled = origin, session, enabled
        self.session_hash = digest(session)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _now(self):
        value = self.clock()
        return value.timestamp() if isinstance(value, datetime) else float(value)

    @contextmanager
    def _connection(self, *, write=False, create=False):
        self.dashboard._check_paths()
        path = self.dashboard.data / 'agent.db'
        if not path.is_file():
            raise ValueError('A current approved managed packet is required')
        c = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True)
        c.row_factory = sqlite3.Row
        try:
            c.execute('PRAGMA foreign_keys=ON')
            c.execute('PRAGMA busy_timeout=3000')
            if write:
                c.execute('BEGIN IMMEDIATE')
            else:
                c.execute('PRAGMA query_only=ON')
            exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='assistance_schema'").fetchone()
            if create and not exists:
                # executescript would commit the writer lock; individual DDL stays atomic.
                c.execute('CREATE TABLE assistance_schema (version INTEGER NOT NULL)')
                c.execute('INSERT INTO assistance_schema VALUES(1)')
                c.execute('''CREATE TABLE assistance_plans (
                    plan_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                    snapshot_json TEXT NOT NULL, plan_digest TEXT NOT NULL,
                    state TEXT NOT NULL, session_hash TEXT NOT NULL, nonce TEXT NOT NULL,
                    token_hash TEXT NOT NULL, expires_at REAL NOT NULL,
                    challenge_resolved INTEGER NOT NULL, observed INTEGER NOT NULL DEFAULT 0,
                    may_observe INTEGER NOT NULL DEFAULT 0)''')
                c.execute('''CREATE TABLE assistance_events (
                    id INTEGER PRIMARY KEY, plan_id TEXT NOT NULL REFERENCES assistance_plans(plan_id),
                    kind TEXT NOT NULL, created_at REAL NOT NULL, detail_json TEXT NOT NULL)''')
                exists = True
            if exists:
                versions = c.execute('SELECT version FROM assistance_schema').fetchall()
                if len(versions) != 1 or versions[0][0] != 1:
                    raise ValueError('Unsupported assistance journal version')
            elif write:
                raise ValueError('No assistance journal; explicitly create a plan')
            yield c, bool(exists)
            if write:
                c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def _token(self, plan_id, nonce, purpose='action'):
        return hmac.new(self.session.encode(), (plan_id + ':' + nonce + ':' + purpose).encode(),
                        hashlib.sha256).hexdigest()

    def _event(self, c, pid, kind, detail=None):
        c.execute('INSERT INTO assistance_events(plan_id,kind,created_at,detail_json) VALUES(?,?,?,?)',
                  (pid, kind, self._now(), json.dumps(detail or {})))

    def _row(self, c, pid):
        if not isinstance(pid, str) or not re.fullmatch('[a-f0-9]{32}', pid):
            raise ValueError('Invalid assistance plan ID')
        row = c.execute('SELECT * FROM assistance_plans WHERE plan_id=?', (pid,)).fetchone()
        if row is None:
            raise ValueError('Unknown assistance plan')
        if digest(json.loads(row['snapshot_json'])) != row['plan_digest']:
            raise ValueError('Assistance plan integrity changed')
        return row

    def _binding(self, c, jid, token):
        job, binding, _ = self.dashboard._checked(c, jid, token)
        if job['status'] != 'approved' or binding['approved_token'] != token:
            raise ValueError('A current approved managed packet is required')
        if binding['profile_path'] != str(self.dashboard.profile):
            raise ValueError('The fixed local profile must match the approved packet')
        profile = read_profile(self.dashboard.profile)
        model = normalize_document_profile(profile)
        fields = []
        for spec in FORM['fields']:
            name = spec['name']
            claim = model['claims'].get('/' + name)
            allowed = (name in ('name', 'email') and claim is not None
                       and len(claim['value']) <= spec['max_length']
                       and bool(claim['value'].strip())
                       and not any(ord(ch) < 32 or ord(ch) == 127 for ch in claim['value']))
            if allowed and name == 'email':
                # Deliberately conservative fixture syntax; unsupported addresses stay manual.
                allowed = bool(re.fullmatch(r'[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*@(?:[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\.)+[A-Za-z]{2,63}', claim['value']))
            item = {'name': name, 'manual': not allowed}
            if allowed:
                item.update(value=claim['value'], provenance=claim)
            fields.append(item)
        return {'job_id': jid, 'company': job['company'][:500],
                'title': job['title'][:500], 'provider': job['provider'][:100],
                'source_id': job['source_id'][:128],
                'freshness': self.dashboard._availability(c, jid),
                'job_sha256': binding['job_sha'], 'profile_sha256': binding['profile_sha'],
                'packet_sha256': binding['packet_sha'], 'review_token': token, 'fields': fields}

    def _public(self, c, row):
        snapshot = json.loads(row['snapshot_json'])
        out = {**snapshot, 'plan_id': row['plan_id'], 'plan_digest': row['plan_digest'],
               'state': row['state'], 'expires_at': row['expires_at'], 'action_token': '',
               'expired': self._now() >= row['expires_at'],
               'challenge_resolved': bool(row['challenge_resolved']),
               'fixture_ui_observed': bool(row['observed']), 'form_schema': FORM, 'can_observe': False,
               'employer_receipt_verified': False,
               'note': 'LOCAL SANDBOX ONLY. No application is submitted or employer receipt verified.'}
        owner = row['session_hash'] == self.session_hash
        if row['state'] in ('needs_manual_reconciliation', 'plan', 'filled', 'handoff'):
            out['action_token'] = self._token(row['plan_id'], row['nonce'],
                                              'reconcile' if row['state'] == 'needs_manual_reconciliation' else 'action')
        out['reconciliation_only'] = not owner or out['expired']
        out['history'] = [{'kind': r['kind'], 'created_at': r['created_at'], **json.loads(r['detail_json'])}
                          for r in c.execute('SELECT kind,created_at,detail_json FROM assistance_events '
                                             'WHERE plan_id=? ORDER BY id DESC LIMIT 100', (row['plan_id'],))]
        return out

    def create(self, job_id, review_token, challenge='none'):
        if not self.enabled:
            raise ValueError('Local sandbox assistance is disabled')
        if challenge not in ('none', 'mfa', 'captcha'):
            raise ValueError('Unknown manual challenge')
        with self._connection(write=True, create=True) as (c, _):
            binding = self._binding(c, job_id, review_token)
            placeholders = ','.join('?' for _ in _OPEN)
            if c.execute(f'SELECT 1 FROM assistance_plans WHERE job_id=? AND state IN ({placeholders})',
                         (job_id, *_OPEN)).fetchone():
                raise ValueError('An existing plan or submission intent blocks a new plan; inspect and reconcile')
            pid, nonce = secrets.token_hex(16), secrets.token_hex(32)
            snapshot = {**binding, 'origin': self.origin,
                        'target_url': self.origin + '/sandbox/application/' + pid,
                        'form_fingerprint': FORM_FINGERPRINT, 'challenge': challenge,
                        'created_at': self._now()}
            c.execute('INSERT INTO assistance_plans(plan_id,job_id,snapshot_json,plan_digest,state,'
                      'session_hash,nonce,token_hash,expires_at,challenge_resolved) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      (pid, job_id, json.dumps(snapshot), digest(snapshot), 'plan', self.session_hash,
                       nonce, digest(self._token(pid, nonce)), self._now() + TTL_SECONDS, int(challenge == 'none')))
            self._event(c, pid, 'plan_created')
            return self._public(c, self._row(c, pid))

    def review(self, plan_id):
        with self._connection() as (c, exists):
            if not exists:
                raise ValueError('No assistance journal; explicitly create a plan')
            return self._public(c, self._row(c, plan_id))

    def list_for_job(self, job_id):
        with self._connection() as (c, exists):
            if not exists:
                return []
            rows = c.execute('SELECT * FROM assistance_plans WHERE job_id=? ORDER BY rowid DESC LIMIT 100', (job_id,))
            return [self._public(c, row) for row in rows]

    def act(self, plan_id, action, token, payload=None):
        if not self.enabled:
            raise ValueError('Local sandbox assistance is disabled')
        payload = {} if payload is None else payload
        if not isinstance(payload, dict) or action not in ('fill', 'handoff', 'resume', 'intent', 'observe', 'revoke', 'reconcile'):
            raise ValueError('Invalid assistance action')
        failure = None
        with self._connection(write=True) as (c, _):
            row = self._row(c, plan_id)
            ambiguous = row['state'] == 'needs_manual_reconciliation'
            reconcile = action == 'reconcile' and ambiguous
            foreign_revoke = (action == 'revoke' and row['state'] in ('plan', 'filled', 'handoff')
                              and row['session_hash'] != self.session_hash
                              and payload.get('phrase') == 'REVOKE ' + plan_id)
            expected = self._token(plan_id, row['nonce'],
                                   'reconcile' if reconcile else 'observe' if action == 'observe' else 'action')
            if (not isinstance(token, str) or not re.fullmatch('[a-f0-9]{64}', token)
                    or not hmac.compare_digest(token, expected)
                    or (not (reconcile or foreign_revoke) and (row['session_hash'] != self.session_hash
                                          or (action != 'observe' and digest(token) != row['token_hash'])))):
                raise ValueError('A current session-bound one-use action token is required')
            if action == 'revoke':
                if ambiguous:
                    raise ValueError('A submission intent requires explicit reconciliation')
                if row['state'] not in ('plan', 'filled', 'handoff'):
                    raise ValueError('Plan is terminal')
                state, event, detail = 'revoked', 'plan_revoked', {}
            elif reconcile:
                outcome, provenance = payload.get('outcome'), payload.get('provenance')
                if (payload.get('phrase') != 'RECONCILE ' + plan_id
                        or outcome not in ('submitted', 'not_submitted', 'unknown')
                        or not isinstance(provenance, str) or not provenance.strip()
                        or len(provenance) > 500 or any(ord(ch) < 32 for ch in provenance)):
                    raise ValueError('Explicit reconciliation outcome and bounded operator provenance are required')
                state = 'needs_manual_reconciliation' if outcome == 'unknown' else 'reconciled_' + outcome
                event, detail = 'operator_reconciled', {'outcome': outcome, 'provenance': provenance,
                                                       'evidence_kind': 'operator_report_unverified'}
            else:
                if ambiguous and action != 'observe':
                    raise ValueError('Intent cannot be retried; explicitly reconcile')
                if action == 'observe' and (not ambiguous or row['observed'] or not row['may_observe']):
                    raise ValueError('No unobserved fixture intent')
                if self._now() >= row['expires_at']:
                    failure = 'Plan expired; explicitly create a new plan or reconcile the intent'
                snapshot = json.loads(row['snapshot_json'])
                if not failure:
                    try:
                        current = self._binding(c, row['job_id'], snapshot['review_token'])
                        if (any(current[key] != snapshot[key] for key in current)
                                or snapshot['origin'] != self.origin
                                or snapshot['form_fingerprint'] != FORM_FINGERPRINT
                                or payload.get('form_fingerprint') != FORM_FINGERPRINT):
                            raise ValueError('Plan inputs or fixed form changed')
                    except (ValueError, OSError, KeyError):
                        failure = 'Plan inputs, approved packet or fixed form changed; review again'
                if failure:
                    # Keep ambiguous submission intents blocked even when their inputs expire.
                    c.execute('UPDATE assistance_plans SET state=?,token_hash=?,may_observe=0 WHERE plan_id=?',
                              ('needs_manual_reconciliation' if ambiguous else 'invalidated', '', plan_id))
                    self._event(c, plan_id, 'action_invalidated')
                else:
                    transitions = {'fill': ('plan', 'filled'), 'handoff': ('filled', 'handoff'),
                                   'resume': ('handoff', 'filled'), 'intent': ('handoff', 'needs_manual_reconciliation'),
                                   'observe': ('needs_manual_reconciliation', 'needs_manual_reconciliation')}
                    before, state = transitions[action]
                    if row['state'] != before:
                        raise ValueError('Invalid plan state for action')
                    if action == 'resume' and payload.get('challenge_ack') is not True:
                        raise ValueError('Explicit manual challenge acknowledgement is required')
                    if action == 'intent' and (payload.get('phrase') != 'AUTHORIZE FIXTURE ' + plan_id
                                               or not row['challenge_resolved']):
                        raise ValueError('Exact fixture authorization and resolved manual challenge are required')
                    event = {'fill': 'fixture_fields_prepared', 'handoff': 'manual_handoff',
                             'resume': 'manual_challenge_acknowledged', 'intent': 'submission_intent',
                             'observe': 'fixture_ui_observed'}[action]
                    detail = {}
            if not failure:
                nonce = secrets.token_hex(32)
                c.execute('UPDATE assistance_plans SET state=?,session_hash=?,nonce=?,token_hash=?, '
                          'challenge_resolved=?,observed=?,may_observe=? WHERE plan_id=?',
                          (state, self.session_hash, nonce, digest(self._token(plan_id, nonce)),
                           int(bool(row['challenge_resolved']) or action == 'resume'),
                           int(bool(row['observed']) or action == 'observe'),
                           int(action == 'intent' or (bool(row['may_observe']) and action not in ('reconcile', 'observe', 'revoke'))),
                           plan_id))
                self._event(c, plan_id, event, detail)
                result = self._public(c, self._row(c, plan_id))
                if action == 'intent':
                    result.update(observe_token=self._token(plan_id, nonce, 'observe'), can_observe=True)
        if failure:
            raise ValueError(failure)
        return result
