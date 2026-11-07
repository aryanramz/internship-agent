"""Offline, evidence-backed contacts and reviewed drafts. This module never sends mail.

Verification and send records are operator attestations, not authenticated ownership,
permission, delivery, or employer receipt. Only explicit writes create the schema.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import SMTP
import json
import math
import re
import secrets
import sqlite3
from urllib.parse import urlsplit

from .dashboard_data import DashboardData
from .document_profile import digest, normalize_document_profile
from .profile_io import read_profile

TTL_DAYS = 90
PAGE_SIZE = 25
NOTE = 'Local operator evidence only; ownership, willingness and delivery are not verified. No email is sent.'
FREE_DOMAINS = {'gmail.com', 'googlemail.com', 'outlook.com', 'hotmail.com', 'live.com', 'yahoo.com',
                'icloud.com', 'aol.com', 'proton.me', 'protonmail.com', 'mail.com', 'gmx.com', 'yandex.com'}
ACTIONS = {'register-contact', 'verify-contact', 'edit-contact', 'optout', 'redact-contact',
           'create-draft', 'edit-draft', 'review-draft', 'export-draft', 'record-send'}


def text(value, limit=500, *, empty=False, multiline=False):
    if (not isinstance(value, str) or len(value) > limit or (not empty and not value.strip())
            or any((ord(ch) < 32 and not (multiline and ch in '\r\n\t')) or ord(ch) == 127
                   or 0xD800 <= ord(ch) <= 0xDFFF for ch in value)):
        raise ValueError('Invalid bounded local text')
    return value


def email_address(value):
    value = text(value, 254)
    if not re.fullmatch(r'[A-Za-z0-9]+(?:[._+-][A-Za-z0-9]+)*@(?:[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*\.)+[A-Za-z]{2,63}', value):
        raise ValueError('A single explicit ASCII email address is required')
    if len(value.split('@')[0]) > 64:
        raise ValueError('Invalid email address')
    local, domain = value.rsplit('@', 1)
    return local + '@' + domain.lower()


def utc(value):
    text(value, 40)
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if dt.tzinfo is None or dt.utcoffset() != timedelta(0):
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ValueError('An explicit UTC timestamp is required') from exc
    return dt.astimezone(timezone.utc).isoformat(timespec='seconds')


class Outreach:
    def __init__(self, root, clock=None):
        self.dashboard = DashboardData(root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _datetime(self):
        value = self.clock()
        if not isinstance(value, datetime):
            value = datetime.fromtimestamp(float(value), timezone.utc)
        if value.tzinfo is None:
            raise ValueError('Clock must have a timezone')
        if not math.isfinite(value.timestamp()):
            raise ValueError('Invalid clock')
        return value.astimezone(timezone.utc)

    def _now(self):
        return self._datetime().isoformat(timespec='seconds')

    @contextmanager
    def _connection(self, *, write=False, create=False):
        if create and not write:
            raise ValueError('Schema creation requires an explicit write')
        self.dashboard._check_paths()
        path = self.dashboard.data / 'agent.db'
        if not path.is_file():
            raise ValueError('An existing local job ledger is required')
        c = sqlite3.connect(path.as_uri() + ('?mode=rw' if write else '?mode=ro'), uri=True)
        c.row_factory = sqlite3.Row
        c.create_function('outreach_fold', 1, lambda value: value.casefold(), deterministic=True)
        try:
            c.execute('PRAGMA foreign_keys=ON')
            c.execute('PRAGMA busy_timeout=3000')
            c.execute('BEGIN IMMEDIATE' if write else 'PRAGMA query_only=ON')
            exists = bool(c.execute("SELECT 1 FROM sqlite_master WHERE name='outreach_schema'").fetchone())
            if exists:
                versions = c.execute('SELECT version FROM outreach_schema').fetchall()
                if len(versions) != 1 or versions[0][0] != 1:
                    raise ValueError('Unsupported outreach journal version; no changes made')
            elif create:
                self._install(c)
                exists = True
            elif write:
                raise ValueError('Explicitly register a contact first')
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='outreach_messages_schema'").fetchone():
                versions = c.execute('SELECT version FROM outreach_messages_schema').fetchall()
                if len(versions) != 1 or versions[0][0] != 1:
                    raise ValueError('Unsupported correspondence journal version; no changes made')
            yield c, exists
            if write:
                c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def _install(c):
        statements = [
            'CREATE TABLE outreach_schema(version INTEGER NOT NULL)',
            'INSERT INTO outreach_schema VALUES(1)',
            '''CREATE TABLE outreach_contacts(contact_id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),
                employer_id TEXT NOT NULL,employer TEXT NOT NULL,employer_domain TEXT NOT NULL,
                name TEXT NOT NULL,role TEXT NOT NULL,email TEXT NOT NULL,address_hash TEXT NOT NULL UNIQUE,
                state TEXT NOT NULL,source_url TEXT NOT NULL,documentation TEXT NOT NULL,observed_at TEXT NOT NULL,
                verifier TEXT NOT NULL,method TEXT NOT NULL,permission TEXT NOT NULL,created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,verified_at TEXT)''',
            '''CREATE TABLE outreach_drafts(draft_id TEXT PRIMARY KEY,contact_id TEXT NOT NULL REFERENCES outreach_contacts(contact_id),
                job_id TEXT NOT NULL REFERENCES jobs(id),purpose TEXT NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,
                revision INTEGER NOT NULL,binding_json TEXT NOT NULL,content_hash TEXT NOT NULL,review_token TEXT,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''',
            '''CREATE TABLE outreach_draft_revisions(draft_id TEXT NOT NULL REFERENCES outreach_drafts(draft_id),
                revision INTEGER NOT NULL,subject TEXT NOT NULL,body TEXT NOT NULL,content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,PRIMARY KEY(draft_id,revision))''',
            '''CREATE TABLE outreach_sends(send_id TEXT PRIMARY KEY,contact_id TEXT NOT NULL REFERENCES outreach_contacts(contact_id),
                job_id TEXT NOT NULL REFERENCES jobs(id),draft_id TEXT NOT NULL REFERENCES outreach_drafts(draft_id),
                sent_at TEXT NOT NULL,message_id TEXT NOT NULL UNIQUE,thread_id TEXT NOT NULL,from_email TEXT NOT NULL,
                to_email TEXT NOT NULL,evidence TEXT NOT NULL,certainty TEXT NOT NULL,
                draft_revision INTEGER NOT NULL,draft_content_hash TEXT NOT NULL,recipient_hash TEXT NOT NULL,
                binding_hash TEXT NOT NULL,evidence_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL)''',
            '''CREATE TABLE outreach_events(id INTEGER PRIMARY KEY,entity_id TEXT NOT NULL,kind TEXT NOT NULL,
                created_at TEXT NOT NULL,detail_json TEXT NOT NULL)''',
            '''CREATE TABLE outreach_suppressions(address_hash TEXT PRIMARY KEY,reason TEXT NOT NULL,created_at TEXT NOT NULL)''',
        ]
        for sql in statements:
            c.execute(sql)

    def _event(self, c, entity, kind, detail=None):
        c.execute('INSERT INTO outreach_events(entity_id,kind,created_at,detail_json) VALUES(?,?,?,?)',
                  (entity, kind, self._now(), json.dumps(detail or {}, ensure_ascii=True)))

    @staticmethod
    def _row(c, table, key, identity):
        text(identity, 128)
        row = c.execute(f'SELECT * FROM {table} WHERE {key}=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Unknown local record')
        return dict(row)

    def _contact(self, c, cid, usable=False):
        row = self._row(c, 'outreach_contacts', 'contact_id', cid)
        if row['state'] == 'verified' and self._datetime() >= datetime.fromisoformat(row['observed_at']) + timedelta(days=TTL_DAYS):
            row['state'] = 'stale'
        if usable and (row['state'] != 'verified' or row['permission'] == 'denied'
                       or c.execute('SELECT 1 FROM outreach_suppressions WHERE address_hash=?', (row['address_hash'],)).fetchone()):
            raise ValueError('Contact evidence is stale, unverified, conflicting or suppressed')
        return row

    @staticmethod
    def _contact_hash(row):
        keys = ('contact_id', 'job_id', 'employer_id', 'employer', 'employer_domain', 'name', 'role',
                'email', 'source_url', 'documentation', 'observed_at', 'verifier', 'method', 'permission')
        return digest({k: row[k] for k in keys})

    def _contact_public(self, c, row):
        result = {k: row[k] for k in ('contact_id', 'job_id', 'employer_id', 'employer', 'employer_domain',
                  'name', 'role', 'email', 'state', 'source_url', 'documentation', 'observed_at', 'verifier',
                  'method', 'permission', 'created_at', 'updated_at', 'verified_at')}
        result['contact_hash'] = self._contact_hash(row)
        suppression = c.execute('SELECT reason FROM outreach_suppressions WHERE address_hash=?', (row['address_hash'],)).fetchone()
        result['suppressed'] = bool(suppression) or row['permission'] == 'denied'
        result['suppression_reason'] = suppression['reason'][:128] if suppression else 'permission_denied' if row['permission'] == 'denied' else None
        result['warnings'] = []
        if result['suppressed']:
            result['warnings'].append('This address is suppressed (' + result['suppression_reason'] + '). Drafting and follow-up suggestions are blocked; suppression is not automatically cleared by redaction.')
        if row['state'] in ('stale', 'conflict', 'unverified', 'redacted'):
            result['warnings'].append('Contact evidence is ' + row['state'] + '; it cannot authorize outreach.')
        result['note'] = NOTE
        return result

    def _source(self, payload, old=None):
        values = dict(old or {})
        values.update({k: payload[k] for k in ('employer', 'employer_domain', 'name', 'role', 'email', 'source_url',
                       'documentation', 'observed_at', 'verifier', 'method', 'permission') if k in payload})
        for key, default in [('role', ''), ('source_url', ''), ('documentation', ''), ('verifier', ''), ('permission', 'unknown')]:
            values.setdefault(key, default)
        for key, width in [('employer', 300), ('name', 200), ('role', 200), ('source_url', 1000), ('documentation', 3000), ('verifier', 200)]:
            values[key] = text(values.get(key), width, empty=key in {'role', 'source_url', 'documentation', 'verifier'})
        domain = text(values.get('employer_domain'), 253).lower()
        if (not re.fullmatch(r'(?:[a-z]+(?:-[a-z]+)*\.)+[a-z]{2,63}', domain)
                or any(part.startswith('xn--') for part in domain.split('.')) or domain in FREE_DOMAINS):
            raise ValueError('An explicit non-lookalike employer domain is required')
        values['employer_domain'] = domain
        values['email'] = email_address(values.get('email'))
        if values['email'].rsplit('@', 1)[1] != domain:
            raise ValueError('Address must exactly match the attested employer domain')
        values['observed_at'] = utc(values.get('observed_at'))
        if datetime.fromisoformat(values['observed_at']) > self._datetime():
            raise ValueError('Contact observation cannot be in the future')
        if values.get('method') not in ('official', 'manual') or values['permission'] not in ('allowed', 'unknown', 'denied'):
            raise ValueError('Explicit evidence method and permission state required')
        if payload.get('guessed') or payload.get('inferred'):
            raise ValueError('Inferred or guessed addresses are not evidence')
        if values['method'] == 'official':
            parsed = urlsplit(values['source_url'])
            if (parsed.scheme != 'https' or parsed.hostname != domain or parsed.username or parsed.password
                    or parsed.port not in (None, 443) or parsed.fragment):
                raise ValueError('Official source must use the exact employer HTTPS domain')
        elif not (values['email'] in values['documentation'] and values['employer'] in values['documentation']):
            raise ValueError('Manual documentation must explicitly identify employer and exact address')
        values['employer_id'] = digest({'employer': values['employer'].strip().casefold()})
        values['address_hash'] = digest(values['email'].casefold())
        return values

    @staticmethod
    def _job(c, jid):
        text(jid, 128)
        row = c.execute('SELECT j.*,a.status FROM jobs j JOIN applications a ON a.job_id=j.id WHERE j.id=?', (jid,)).fetchone()
        if row is None:
            raise ValueError('An existing job identity is required')
        return dict(row)

    def get(self, view, query=None):
        query = query or {}
        if not isinstance(query, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in query.items()):
            raise ValueError('Text query fields required')
        if view not in ('contacts', 'contact', 'drafts', 'draft'):
            raise ValueError('Unknown outreach view')
        if not (self.dashboard.data / 'agent.db').is_file():
            if view in ('contacts', 'drafts'):
                return {view: [], 'total': 0, 'page': 1, 'pages': 0, 'note': NOTE, 'warnings': ['Local job ledger is not initialized.']}
            raise ValueError('Unknown local record')
        with self._connection() as (c, exists):
            if view in ('contact', 'draft'):
                if not exists:
                    raise ValueError('Unknown local record')
                if view == 'contact':
                    return self._contact_public(c, self._contact(c, query.get('id')))
                return self._draft_public(c, self._row(c, 'outreach_drafts', 'draft_id', query.get('id')))
            try:
                page = int(query.get('page', '1'))
            except ValueError as exc:
                raise ValueError('Invalid page') from exc
            if not 1 <= page <= 100000:
                raise ValueError('Invalid page')
            if not exists:
                return {view: [], 'total': 0, 'page': page, 'pages': 0, 'note': NOTE}
            table = 'outreach_contacts' if view == 'contacts' else 'outreach_drafts'
            clauses, params = [], []
            for key in ('job_id', 'contact_id'):
                if query.get(key):
                    clauses.append(key + '=?')
                    params.append(text(query[key], 128))
            where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            total = c.execute('SELECT COUNT(*) FROM ' + table + where, params).fetchone()[0]
            rows = c.execute('SELECT * FROM ' + table + where + ' ORDER BY rowid DESC LIMIT ? OFFSET ?',
                             (*params, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
            projected = [self._contact_public(c, self._contact(c, row['contact_id'])) if view == 'contacts'
                         else self._draft_public(c, dict(row)) for row in rows]
            return {view: projected, 'total': total, 'page': page, 'pages': math.ceil(total / PAGE_SIZE), 'note': NOTE}

    def _binding(self, c, contact, token, purpose, source_message_id=None):
        self._contact(c, contact['contact_id'], usable=True)
        job, binding, _ = self.dashboard._checked(c, contact['job_id'], token)
        if binding['approved_token'] != token or token is None:
            raise ValueError('An explicitly approved current managed packet is required')
        if job['company'] != contact['employer']:
            raise ValueError('Contact employer differs from current job')
        model = normalize_document_profile(read_profile(self.dashboard.profile))
        claims = {k: v for k, v in model['claims'].items() if k in ('/name', '/email')}
        if '/email' not in claims:
            raise ValueError('An exact locally verified sender email claim is required')
        sender = email_address(claims['/email']['value'])
        source = None
        if purpose == 'reply':
            from .outreach_messages import Correspondence
            source = Correspondence(self.dashboard.root, clock=self.clock)._reply_binding(c, source_message_id, contact['contact_id'])
        return {'contact_hash': digest(contact), 'recipient_hash': digest(contact['email']),
                'job_sha256': binding['job_sha'], 'profile_sha256': binding['profile_sha'],
                'packet_sha256': binding['packet_sha'], 'packet_review_token': token,
                'from_email': sender, 'to_email': contact['email'], 'claims': claims, 'source_message': source}

    def _check_draft(self, c, row, *, reviewed=False):
        contact = self._contact(c, row['contact_id'], usable=True)
        bound = json.loads(row['binding_json'])
        source = (bound.get('source_message') or {}).get('message_id')
        current = self._binding(c, contact, bound['packet_review_token'], row['purpose'], source)
        if bound != current or row['content_hash'] != self._content(row):
            raise ValueError('Draft identity or evidence changed; create and review a fresh draft')
        if reviewed and not row['review_token']:
            raise ValueError('Review the exact current draft before export or recording')
        return contact, bound

    @staticmethod
    def _content(row):
        return digest({k: row[k] for k in ('contact_id', 'job_id', 'purpose', 'subject', 'body', 'revision', 'binding_json')})

    def _draft_public(self, c, row):
        contact = self._contact(c, row['contact_id'])
        result = {k: row[k] for k in ('draft_id', 'contact_id', 'job_id', 'purpose', 'subject', 'body',
                    'revision', 'content_hash', 'review_token', 'created_at', 'updated_at')}
        result['contact'] = {k: contact[k] for k in ('contact_id', 'name', 'email', 'employer', 'state')}
        result['warnings'] = [NOTE, 'Profile facts are locally attested; edited text requires independent human fact review.']
        try:
            _, binding = self._check_draft(c, row)
            result['facts'] = list(binding['claims'].values())
            result['binding'] = {k: binding[k] for k in ('packet_sha256', 'job_sha256', 'profile_sha256', 'source_message')}
            result['current'] = True
        except (ValueError, OSError, KeyError):
            result['current'] = False
            result['review_token'] = None
            result['warnings'].append('Evidence changed or is suppressed; this draft cannot be exported or recorded.')
        result['sent'] = False
        return result

    def action(self, name, payload):
        if name not in ACTIONS or not isinstance(payload, dict) or payload.get('confirm') != name:
            raise ValueError('Explicit per-action confirmation required')
        with self._connection(write=True, create=True) as (c, _):
            if name == 'register-contact':
                values = self._source(payload)
                job = self._job(c, payload.get('job_id'))
                if values['employer'] != job['company']:
                    raise ValueError('Exact employer must match the existing job company')
                if c.execute('SELECT 1 FROM outreach_contacts WHERE address_hash=?', (values['address_hash'],)).fetchone():
                    raise ValueError('Address already registered; inspect the existing identity')
                if c.execute('SELECT 1 FROM outreach_suppressions WHERE address_hash=?', (values['address_hash'],)).fetchone():
                    raise ValueError('Address is suppressed')
                cid = secrets.token_hex(16)
                conflict = c.execute('SELECT contact_id FROM outreach_contacts WHERE employer_id=? '
                                     'AND (outreach_fold(name)=outreach_fold(?) OR employer_domain!=?) AND state!=?',
                                     (values['employer_id'], values['name'], values['employer_domain'], 'redacted')).fetchall()
                for previous in conflict:
                    c.execute("UPDATE outreach_contacts SET state=CASE WHEN state='opted_out' THEN state ELSE 'conflict' END,verified_at=NULL,updated_at=? WHERE contact_id=?",
                              (self._now(), previous['contact_id']))
                    c.execute('UPDATE outreach_drafts SET review_token=NULL WHERE contact_id=?', (previous['contact_id'],))
                    self._event(c, previous['contact_id'], 'contact_identity_conflict', {'related_contact_id': cid})
                values.update(contact_id=cid, job_id=job['id'], state='conflict' if conflict else 'unverified',
                              created_at=self._now(), updated_at=self._now(), verified_at=None)
                keys = ('contact_id', 'job_id', 'employer_id', 'employer', 'employer_domain', 'name', 'role', 'email',
                        'address_hash', 'state', 'source_url', 'documentation', 'observed_at', 'verifier', 'method',
                        'permission', 'created_at', 'updated_at', 'verified_at')
                c.execute('INSERT INTO outreach_contacts(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')',
                          tuple(values[k] for k in keys))
                self._event(c, cid, 'contact_registered', {'evidence_digest': digest(values)})
                return self._contact_public(c, self._contact(c, cid))
            if name in {'verify-contact', 'edit-contact', 'optout', 'redact-contact'}:
                return self._contact_action(c, name, payload)
            return self._draft_action(c, name, payload)

    def _contact_action(self, c, name, payload):
        cid = payload.get('id', payload.get('contact_id'))
        contact = self._contact(c, cid)
        if name == 'verify-contact':
            if payload.get('expected_contact_hash') != self._contact_hash(contact):
                raise ValueError('Contact changed since preview; inspect current evidence before verification')
            if payload.get('phrase') != 'VERIFY ' + cid or contact['state'] in ('opted_out', 'redacted'):
                raise ValueError('Exact verification phrase and an unsuppressed contact are required')
            values = self._source(payload, contact)
            text(values['verifier'], 200)
            if contact['state'] == 'conflict':
                text(payload.get('resolution'), 1000)
                if c.execute('SELECT 1 FROM outreach_contacts WHERE employer_id=? AND contact_id!=? '
                             'AND (outreach_fold(name)=outreach_fold(?) OR employer_domain!=?) AND state!=?',
                             (contact['employer_id'], cid, contact['name'], contact['employer_domain'], 'redacted')).fetchone():
                    raise ValueError('Unresolved conflicting identities; redact the incorrect identity first')
            if datetime.fromisoformat(values['observed_at']) + timedelta(days=TTL_DAYS) <= self._datetime():
                raise ValueError('Source evidence is stale; reobserve before verification')
            if any(values[k] != contact[k] for k in ('email', 'employer', 'name', 'employer_domain')):
                raise ValueError('Edit contact identity separately before verification')
            keys = ('source_url', 'documentation', 'observed_at', 'verifier', 'method', 'permission')
            c.execute('UPDATE outreach_contacts SET ' + ','.join(k + '=?' for k in keys) +
                      ",state='verified',verified_at=?,updated_at=? WHERE contact_id=?",
                      (*[values[k] for k in keys], self._now(), self._now(), cid))
        elif name == 'edit-contact':
            if contact['state'] in ('opted_out', 'redacted'):
                raise ValueError('Suppressed contacts cannot be edited back into use')
            values = self._source(payload, contact)
            if values['employer'] != self._job(c, contact['job_id'])['company']:
                raise ValueError('Employer mismatch')
            if c.execute('SELECT 1 FROM outreach_contacts WHERE address_hash=? AND contact_id!=?',
                         (values['address_hash'], cid)).fetchone() or c.execute('SELECT 1 FROM outreach_suppressions WHERE address_hash=?',
                                                                              (values['address_hash'],)).fetchone():
                raise ValueError('Address collision or suppression')
            changed = values['email'] != contact['email'] or values['employer_domain'] != contact['employer_domain']
            if values['address_hash'] != contact['address_hash']:
                c.execute('INSERT OR IGNORE INTO outreach_suppressions VALUES(?,?,?)',
                          (contact['address_hash'], 'address_changed', self._now()))
            collisions = c.execute('SELECT contact_id FROM outreach_contacts WHERE employer_id=? AND contact_id!=? '
                                   'AND (outreach_fold(name)=outreach_fold(?) OR employer_domain!=?) AND state!=?',
                                   (values['employer_id'], cid, values['name'], values['employer_domain'], 'redacted')).fetchall()
            for previous in collisions:
                c.execute("UPDATE outreach_contacts SET state=CASE WHEN state='opted_out' THEN state ELSE 'conflict' END,verified_at=NULL,updated_at=? WHERE contact_id=?",
                          (self._now(), previous['contact_id']))
                c.execute('UPDATE outreach_drafts SET review_token=NULL WHERE contact_id=?', (previous['contact_id'],))
                self._event(c, previous['contact_id'], 'contact_identity_conflict', {'related_contact_id': cid})
            keys = ('employer_id', 'employer', 'employer_domain', 'name', 'role', 'email', 'address_hash', 'source_url',
                    'documentation', 'observed_at', 'verifier', 'method', 'permission')
            c.execute('UPDATE outreach_contacts SET ' + ','.join(k + '=?' for k in keys) +
                      ',state=?,verified_at=NULL,updated_at=? WHERE contact_id=?',
                      (*[values[k] for k in keys], 'conflict' if changed or collisions or contact['state'] == 'conflict' else 'unverified', self._now(), cid))
        else:
            phrase = ('OPTOUT ' if name == 'optout' else 'REDACT ') + cid
            if payload.get('phrase') != phrase:
                raise ValueError('Exact contact suppression phrase required')
            c.execute('INSERT OR IGNORE INTO outreach_suppressions VALUES(?,?,?)',
                      (contact['address_hash'], name, self._now()))
            state = 'opted_out' if name == 'optout' and contact['state'] != 'redacted' else 'redacted'
            c.execute('UPDATE outreach_contacts SET state=?,permission=?,verified_at=NULL,updated_at=? WHERE contact_id=?',
                      (state, 'denied', self._now(), cid))
            if name == 'redact-contact':
                from .outreach_messages import Correspondence
                Correspondence(self.dashboard.root, clock=self.clock)._redact_contact(c, cid)
                self._event(c, cid, 'contact_redaction_digest', {'digest': digest(contact)})
                c.execute("UPDATE outreach_contacts SET name='',role='',email='',source_url='',documentation='',verifier='' WHERE contact_id=?", (cid,))
                # Original content survives only as audit digests after explicit privacy redaction.
                c.execute("UPDATE outreach_draft_revisions SET subject='',body='' WHERE draft_id IN (SELECT draft_id FROM outreach_drafts WHERE contact_id=?)", (cid,))
                c.execute("UPDATE outreach_drafts SET subject='',body='',binding_json='{}' WHERE contact_id=?", (cid,))
                c.execute("UPDATE outreach_sends SET from_email='',to_email='',evidence='',message_id='redacted:'||send_id,thread_id='' WHERE contact_id=?", (cid,))
        c.execute('UPDATE outreach_drafts SET review_token=NULL WHERE contact_id=?', (cid,))
        self._event(c, cid, name, {'previous_digest': digest(contact),
                                  'resolution_digest': digest(payload.get('resolution', ''))})
        return self._contact_public(c, self._contact(c, cid))

    def _draft_action(self, c, name, payload):
        if name == 'create-draft':
            contact = self._contact(c, payload.get('contact_id'), usable=True)
            purpose = payload.get('purpose')
            if purpose not in ('intro', 'application_followup', 'reply'):
                raise ValueError('An explicit supported draft purpose is required')
            binding = self._binding(c, contact, payload.get('packet_review_token'), purpose, payload.get('source_message_id'))
            job = self._job(c, contact['job_id'])
            applicant = binding['claims'].get('/name', {}).get('value', '[YOUR VERIFIED NAME]')
            subject = text('Question about ' + job['title'], 200)
            body = ('Hello,\n\nI am interested in the ' + job['title'] + ' role at ' + job['company'] + '.\n\n'
                    + ('[ADD YOUR QUESTION ABOUT THE ROLE]' if purpose == 'intro' else
                       '[REVIEW SOURCE MESSAGE AND WRITE YOUR REPLY]' if purpose == 'reply' else
                       '[ADD YOUR QUESTION; VERIFY ANY PRIOR SUBMISSION BEFORE MENTIONING IT]')
                    + '\n\nThank you,\n' + applicant)
            text(body, 10000, multiline=True)
            row = dict(draft_id=secrets.token_hex(16), contact_id=contact['contact_id'], job_id=contact['job_id'],
                       purpose=purpose, subject=subject, body=body, revision=1,
                       binding_json=json.dumps(binding, sort_keys=True), review_token=None,
                       created_at=self._now(), updated_at=self._now())
            row['content_hash'] = self._content(row)
            keys = tuple(row)
            c.execute('INSERT INTO outreach_drafts(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')',
                      tuple(row[k] for k in keys))
            self._event(c, row['draft_id'], 'draft_created', {'binding_digest': digest(binding)})
            return self._draft_public(c, row)
        row = self._row(c, 'outreach_drafts', 'draft_id', payload.get('id', payload.get('draft_id')))
        contact, binding = self._check_draft(c, row, reviewed=name in ('export-draft', 'record-send'))
        if name == 'edit-draft':
            subject = text(payload.get('subject'), 200)
            body = text(payload.get('body'), 10000, multiline=True)
            c.execute('INSERT INTO outreach_draft_revisions VALUES(?,?,?,?,?,?)',
                      (row['draft_id'], row['revision'], row['subject'], row['body'], row['content_hash'], self._now()))
            row.update(subject=subject, body=body, revision=row['revision'] + 1, review_token=None, updated_at=self._now())
            row['content_hash'] = self._content(row)
            c.execute('UPDATE outreach_drafts SET subject=?,body=?,revision=?,content_hash=?,review_token=NULL,updated_at=? WHERE draft_id=?',
                      (subject, body, row['revision'], row['content_hash'], row['updated_at'], row['draft_id']))
        elif name == 'review-draft':
            if (type(payload.get('expected_revision')) is not int or payload['expected_revision'] != row['revision']
                    or payload.get('expected_content_hash') != row['content_hash']):
                raise ValueError('Draft changed since preview; inspect the current revision before review')
            if payload.get('phrase') != 'REVIEW ' + row['draft_id']:
                raise ValueError('Exact draft review phrase required')
            if re.search(r'\[[A-Z][A-Z _;]+\]', row['body']):
                raise ValueError('Resolve editor-required prompts before review')
            row['review_token'] = secrets.token_hex(32)
            c.execute('UPDATE outreach_drafts SET review_token=? WHERE draft_id=?', (row['review_token'], row['draft_id']))
        elif name in ('export-draft', 'record-send'):
            supplied_token = payload.get('review_token')
            if (not isinstance(supplied_token, str) or not re.fullmatch('[a-f0-9]{64}', supplied_token)
                    or supplied_token != row['review_token']):
                raise ValueError('Exact current draft review token required')
            # Validate all header values even if a trusted local caller modified the database.
            text(row['subject'], 200)
            sender, recipient = email_address(binding['from_email']), email_address(contact['email'])
            if digest(recipient) != binding['recipient_hash'] or recipient != binding['to_email']:
                raise ValueError('Draft recipient binding changed')
            if name == 'export-draft':
                msg = EmailMessage(policy=SMTP)
                msg['From'], msg['To'], msg['Subject'] = sender, recipient, row['subject']
                msg.set_content(text(row['body'], 10000, multiline=True))
                self._event(c, row['draft_id'], 'draft_exported', {'content_hash': row['content_hash'], 'sent': False})
                return {'draft_id': row['draft_id'], 'rfc822': msg.as_string(), 'sent': False, 'note': NOTE}
            return self._record_send(c, row, binding, payload)
        self._event(c, row['draft_id'], name, {'revision': row['revision'], 'content_hash': row['content_hash']})
        return self._draft_public(c, row)

    def _record_send(self, c, row, binding, payload):
        sent_at = utc(payload.get('sent_at'))
        if datetime.fromisoformat(sent_at) > self._datetime():
            raise ValueError('Recorded send cannot be in the future')
        message_id = text(payload.get('message_id'), 254)
        thread_id = text(payload.get('thread_id'), 254)
        if not re.fullmatch(r'<[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~@-]+>', message_id):
            raise ValueError('An exact RFC message ID in angle brackets is required')
        certainty = payload.get('certainty')
        if certainty not in ('confirmed', 'uncertain'):
            raise ValueError('Explicit operator certainty is required')
        evidence = text(payload.get('evidence'), 2000)
        values = dict(contact_id=row['contact_id'], job_id=row['job_id'], draft_id=row['draft_id'], sent_at=sent_at,
                      message_id=message_id, thread_id=thread_id, from_email=binding['from_email'],
                      to_email=binding['to_email'], evidence=evidence, certainty=certainty,
                      draft_revision=row['revision'], draft_content_hash=row['content_hash'],
                      recipient_hash=binding['recipient_hash'], binding_hash=digest(binding))
        fingerprint = digest(values)
        existing = c.execute('SELECT * FROM outreach_sends WHERE message_id=? OR evidence_hash=?', (message_id, fingerprint)).fetchall()
        if existing:
            if len(existing) != 1 or existing[0]['evidence_hash'] != fingerprint:
                raise ValueError('Contradictory immutable send evidence; inspect existing record')
            return {'send_id': existing[0]['send_id'], 'recorded': True, 'idempotent': True, 'externally_verified': False, 'note': NOTE}
        if c.execute('SELECT 1 FROM outreach_sends WHERE draft_id=?', (row['draft_id'],)).fetchone():
            raise ValueError('This draft already has send evidence; inspect before retrying')
        values.update(send_id=secrets.token_hex(16), evidence_hash=fingerprint, created_at=self._now())
        keys = tuple(values)
        c.execute('INSERT INTO outreach_sends(' + ','.join(keys) + ') VALUES(' + ','.join('?' for _ in keys) + ')', tuple(values[k] for k in keys))
        self._event(c, row['draft_id'], 'send_evidence_recorded', {'send_id': values['send_id'], 'digest': fingerprint, 'certainty': certainty})
        return {'send_id': values['send_id'], 'recorded': True, 'idempotent': False, 'externally_verified': False, 'note': NOTE}
