"""Offline, operator-imported correspondence and suggestion-only follow-ups.

Headers supplied by an operator are not authenticated recruiter responses. HTML
is inert private text; attachments, URLs and account credentials are never read.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
from uuid import uuid4

from .outreach import Outreach, email_address


VERSION = 1
MAX_BODY = 16000
DETAIL_BODY = 8000
SOURCE = 'manual_import_unverified'
_FIELDS = {'message_id', 'thread_id', 'from_email', 'to_email', 'cc', 'in_reply_to',
           'references', 'sent_at', 'subject', 'body', 'text_format', 'forwarded', 'bounce', 'optout'}


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _text(value, limit, *, empty=False):
    if (not isinstance(value, str) or len(value) > limit or (not empty and not value)
            or any(ord(ch) < 32 or ord(ch) == 127 or 0xD800 <= ord(ch) <= 0xDFFF for ch in value)):
        raise ValueError('Invalid bounded correspondence field')
    return value


def _email(value):
    return email_address(value)


def _address_hash(value):
    # Local-part variants never establish a strong match. Treat them as the
    # same potential correspondent for suppression and privacy redaction.
    return _hash(value.casefold())


def _message_id(value, *, empty=False):
    value = _text(value, 254, empty=empty)
    if value and not re.fullmatch(r'<[^<>\s@]+@[^<>\s@]+>', value):
        raise ValueError('An RFC message ID is required')
    return value


def _recipients(value):
    # Keep explicit multi-recipient imports for review and suppression. Strong
    # association below still requires one exact recipient and no Cc addresses.
    value = _text(value, 8000)
    parts = value.split(',')
    if len(parts) > 30:
        raise ValueError('Too many message recipients')
    return ','.join(_email(part.strip()) for part in parts)


def _date(value):
    try:
        parsed = datetime.fromisoformat(_text(value, 64).replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError('Timezone required')
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError('A valid timezone-aware correspondence timestamp is required') from exc


def _normalize(raw):
    if not isinstance(raw, dict) or set(raw) - _FIELDS:
        raise ValueError('Only documented manual message fields are accepted')
    required = {'message_id', 'thread_id', 'from_email', 'to_email', 'sent_at', 'body'}
    if not required <= set(raw):
        raise ValueError('Missing manual message identity or content')
    result = {
        'message_id': _message_id(raw['message_id']),
        'thread_id': _text(raw['thread_id'], 254),
        'from_email': _email(raw['from_email']), 'to_email': _recipients(raw['to_email']),
        'in_reply_to': _message_id(raw.get('in_reply_to', ''), empty=True),
        'sent_at': _date(raw['sent_at']).isoformat(),
        'subject': _text(raw.get('subject', ''), 500, empty=True),
        'text_format': raw.get('text_format', 'plain'),
    }
    for key, converter in [('cc', _email), ('references', _message_id)]:
        values = raw.get(key, [])
        if not isinstance(values, list) or len(values) > 30:
            raise ValueError('Too many message recipients or references')
        result[key] = [converter(item) for item in values]
    body = raw['body']
    if (not isinstance(body, str) or len(body) > MAX_BODY or '\x00' in body
            or any(0xD800 <= ord(ch) <= 0xDFFF for ch in body)):
        raise ValueError('Message body exceeds the private text limit')
    result['body'] = body
    if result['text_format'] not in ('plain', 'html'):
        raise ValueError('Only inert plain or HTML message text is accepted')
    for key in ('forwarded', 'bounce', 'optout'):
        result[key] = raw.get(key, False)
        if not isinstance(result[key], bool):
            raise ValueError('Message flags must be explicit booleans')
    return result


class Correspondence:
    def __init__(self, root, clock=None):
        self.core = Outreach(root, clock=clock)

    def _schema(self, c, *, create=False):
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='outreach_messages_schema'").fetchone()
        if exists:
            rows = c.execute('SELECT version FROM outreach_messages_schema').fetchall()
            if len(rows) != 1 or rows[0][0] != VERSION:
                raise ValueError('Unsupported correspondence schema version')
            return True
        if not create:
            return False
        # Individual statements keep schema, operation checkpoint and import atomic.
        statements = [
            'CREATE TABLE outreach_messages_schema(version INTEGER NOT NULL)',
            'INSERT INTO outreach_messages_schema VALUES(1)',
            '''CREATE TABLE outreach_messages(
                id TEXT PRIMARY KEY, key_hash TEXT NOT NULL UNIQUE, content_hash TEXT NOT NULL,
                message_id TEXT NOT NULL,thread_id TEXT NOT NULL,from_email TEXT NOT NULL,
                to_email TEXT NOT NULL,from_hash TEXT NOT NULL,sent_at TEXT NOT NULL,
                subject TEXT NOT NULL,raw_json TEXT NOT NULL,match_state TEXT NOT NULL,
                contact_id TEXT,send_id TEXT,reason TEXT NOT NULL,
                collided INTEGER NOT NULL DEFAULT 0,redacted INTEGER NOT NULL DEFAULT 0,
                imported_at TEXT NOT NULL)''',
            'CREATE INDEX outreach_messages_from ON outreach_messages(from_hash)',
            '''CREATE TABLE outreach_message_operations(
                operation_id TEXT PRIMARY KEY,key_hash TEXT NOT NULL,content_hash TEXT NOT NULL,
                checkpoint TEXT NOT NULL,created_at TEXT NOT NULL)''',
            '''CREATE TABLE outreach_message_collisions(
                key_hash TEXT NOT NULL,content_hash TEXT NOT NULL,from_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,PRIMARY KEY(key_hash,content_hash))''',
            '''CREATE TABLE outreach_message_suppressions(
                key_hash TEXT NOT NULL,send_id TEXT NOT NULL,contact_id TEXT NOT NULL,
                reason TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(key_hash,send_id))''',
            '''CREATE TABLE outreach_followup_policy(
                contact_id TEXT PRIMARY KEY,interval_days INTEGER NOT NULL,
                min_days INTEGER NOT NULL,enabled INTEGER NOT NULL,updated_at TEXT NOT NULL)''',
            '''CREATE TABLE outreach_followup_dismissed(
                id TEXT PRIMARY KEY,send_id TEXT NOT NULL UNIQUE,contact_id TEXT NOT NULL,
                dismissed_at TEXT NOT NULL)''',
        ]
        for sql in statements:
            c.execute(sql)
        return True

    def _event(self, c, entity, kind):
        # Never include headers, bodies, subject, addresses or operator evidence.
        c.execute('INSERT INTO outreach_events(entity_id,kind,created_at,detail_json) VALUES(?,?,?,?)',
                  (entity, kind, self.core._now(), '{}'))

    def _row(self, c, identity):
        identity = _text(identity, 128)
        row = c.execute('SELECT * FROM outreach_messages WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Unknown local correspondence message')
        return dict(row)

    def _matching_send(self, c, row):
        if row.get('collided') or row.get('redacted'):
            return None
        raw = json.loads(row['raw_json'])
        if (raw['forwarded'] or raw['cc'] or ',' in raw['to_email']
                or re.match(r'^\s*(?:fw|fwd)\s*:', raw['subject'], re.IGNORECASE)
                or re.search(r'-{2,}\s*forwarded message\s*-{2,}', raw['body'], re.IGNORECASE)
                or _date(raw['sent_at']) > _date(self.core._now())):
            return None
        if c.execute('SELECT 1 FROM outreach_sends WHERE message_id=?', (raw['message_id'],)).fetchone():
            return None
        sends = c.execute('SELECT * FROM outreach_sends WHERE thread_id=? AND from_email=? AND to_email=?',
                          (raw['thread_id'], raw['to_email'], raw['from_email'])).fetchall()
        candidates = []
        for send_row in sends:
            send = dict(send_row)
            try:
                contact = self.core._contact(c, send['contact_id'], usable=True)
                _message_id(send['message_id'])
                if (_date(send['sent_at']) > _date(raw['sent_at'])
                        or contact['email'] != raw['from_email']
                        or contact['job_id'] != send['job_id']
                        or send['to_email'] != contact['email']
                        or send['certainty'] != 'confirmed' or not send['evidence'].strip()):
                    continue
                job = c.execute('SELECT company FROM jobs WHERE id=?', (send['job_id'],)).fetchone()
                if job is None or job['company'] != contact['employer']:
                    continue
                if (raw['in_reply_to'] == send['message_id']
                        or send['message_id'] in raw['references']):
                    candidates.append(send)
            except (ValueError, KeyError, TypeError):
                continue
        # Address reuse or conflicting identity never chooses one employer by chance.
        contacts = c.execute('SELECT contact_id FROM outreach_contacts WHERE email=?',
                             (raw['from_email'],)).fetchall()
        return candidates[0] if len(candidates) == 1 and len(contacts) == 1 else None

    def _reply_binding(self, c, message_id, contact_id):
        if not self._schema(c):
            raise ValueError('A matched local message is required for a reply')
        row = self._row(c, message_id)
        send = self._matching_send(c, row)
        if (row['match_state'] != 'matched_unverified' or not send
                or row['contact_id'] != contact_id or send['contact_id'] != contact_id):
            raise ValueError('Reply message association needs current review')
        raw = json.loads(row['raw_json'])
        if raw['bounce'] or raw['optout']:
            raise ValueError('Cannot draft a reply to a bounce or opt-out')
        return {'message_id': row['id'], 'message_digest': row['content_hash'],
                'send_id': send['send_id'], 'source': SOURCE}

    def _redact(self, c, identity):
        c.execute("""UPDATE outreach_messages SET message_id='',thread_id='',from_email='',
            to_email='',subject='',raw_json='{}',redacted=1,match_state='review_only',
            reason='operator_redacted' WHERE id=?""", (identity,))
        self._event(c, identity, 'message_redacted')

    def _redact_contact(self, c, contact_id):
        """Participate in the caller's contact-redaction transaction, without DDL.

        Call before clearing the contact email so unmatched imports are scrubbed too.
        Association and private digests remain to preserve suppression/history.
        """
        if not self._schema(c):
            return
        contact = self.core._contact(c, contact_id)
        rows = c.execute('''SELECT id FROM outreach_messages WHERE contact_id=? OR from_hash=?
            OR key_hash IN (SELECT key_hash FROM outreach_message_suppressions WHERE contact_id=?)''',
                         (contact_id, _address_hash(contact['email']), contact_id)).fetchall()
        for row in rows:
            self._redact(c, row['id'])

    @staticmethod
    def _projection(row, *, detail=False):
        result = {key: row[key] for key in ('id', 'from_email', 'to_email', 'subject', 'sent_at',
                  'match_state', 'contact_id', 'send_id', 'reason')}
        result.update(redacted=bool(row['redacted']), collided=bool(row['collided']), source=SOURCE)
        raw = json.loads(row['raw_json'])
        for key in ('optout', 'bounce', 'forwarded'):
            result[key] = bool(raw.get(key, False))
        if detail:
            body = raw.get('body', '')
            result.update(body=body[:DETAIL_BODY], body_truncated=len(body) > DETAIL_BODY,
                          text_format=raw.get('text_format', 'plain'),
                          message_id=row['message_id'], thread_id=row['thread_id'],
                          in_reply_to=raw.get('in_reply_to', ''), references=raw.get('references', []))
        return result

    def _import(self, c, payload):
        raw = _normalize(payload.get('message'))
        encoded = _canonical(raw)
        key_hash, content_hash = _hash(raw['message_id']), _hash(encoded)
        operation = payload.get('operation_id')
        checkpoint = payload.get('checkpoint', '')
        if operation is not None:
            _text(operation, 128)
            _text(checkpoint, 128, empty=True)
            previous = c.execute('SELECT * FROM outreach_message_operations WHERE operation_id=?', (operation,)).fetchone()
            if previous and (previous['key_hash'], previous['content_hash'], previous['checkpoint']) != (key_hash, content_hash, checkpoint):
                raise ValueError('Import operation identity conflicts with its immutable checkpoint')
        elif checkpoint:
            raise ValueError('A checkpoint requires an import operation ID')
        existing = c.execute('SELECT * FROM outreach_messages WHERE key_hash=?', (key_hash,)).fetchone()
        idempotent = bool(existing and existing['content_hash'] == content_hash)
        if existing:
            identity = existing['id']
            if not idempotent:
                c.execute('''INSERT OR IGNORE INTO outreach_message_collisions
                    VALUES(?,?,?,?)''', (key_hash, content_hash, _address_hash(raw['from_email']), self.core._now()))
                c.execute("UPDATE outreach_messages SET collided=1,match_state='review_only',reason='immutable_id_collision',contact_id=NULL,send_id=NULL WHERE id=?", (identity,))
                self._event(c, identity, 'message_id_collision')
        else:
            identity = uuid4().hex
            row = dict(raw_json=encoded, collided=False, redacted=False)
            send = self._matching_send(c, row)
            state = 'matched_unverified' if send else 'review_only'
            c.execute('''INSERT INTO outreach_messages
                (id,key_hash,content_hash,message_id,thread_id,from_email,to_email,from_hash,
                 sent_at,subject,raw_json,match_state,contact_id,send_id,reason,imported_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (identity, key_hash, content_hash, raw['message_id'], raw['thread_id'], raw['from_email'],
                 raw['to_email'], _address_hash(raw['from_email']), raw['sent_at'], raw['subject'], encoded,
                 state, send['contact_id'] if send else None, send['send_id'] if send else None,
                 'operator_headers_unverified' if send else 'headers_need_review', self.core._now()))
            self._event(c, identity, 'manual_message_imported')
        if operation is not None:
            c.execute('INSERT OR IGNORE INTO outreach_message_operations VALUES(?,?,?,?,?)',
                      (operation, key_hash, content_hash, checkpoint, self.core._now()))
        # An unknown mailer-daemon, alias or forwarded reply cannot authenticate
        # a recruiter. Exact recorded reply references still establish enough
        # uncertainty to stop suggesting more mail, without a positive match.
        reference_ids = set(raw['references'])
        if raw['in_reply_to']:
            reference_ids.add(raw['in_reply_to'])
        if reference_ids:
            candidates = c.execute('SELECT send_id,contact_id,message_id FROM outreach_sends WHERE thread_id=? AND from_email=?',
                                   (raw['thread_id'], raw['to_email'])).fetchall()
            for candidate in candidates:
                if candidate['message_id'] in reference_ids:
                    c.execute('INSERT OR IGNORE INTO outreach_message_suppressions VALUES(?,?,?,?,?)',
                              (key_hash, candidate['send_id'], candidate['contact_id'],
                               'unverified_referenced_correspondence', self.core._now()))
        # Explicit operator-classified opt-outs/bounces persist in the shared
        # suppression registry even after a message/contact privacy redaction.
        if raw['optout'] or raw['bounce']:
            contacts = c.execute('SELECT contact_id,address_hash FROM outreach_contacts WHERE lower(email)=?',
                                 (raw['from_email'].casefold(),)).fetchall()
            for contact in contacts:
                c.execute('INSERT OR IGNORE INTO outreach_suppressions VALUES(?,?,?)',
                          (contact['address_hash'], 'manual_message_optout' if raw['optout'] else
                           'manual_message_bounce', self.core._now()))
        return {'message': self._projection(self._row(c, identity)), 'idempotent': idempotent}

    def _followups(self, c):
        now = _date(self.core._now())
        items = []
        policies = c.execute('SELECT * FROM outreach_followup_policy WHERE enabled=1 ORDER BY contact_id').fetchall()
        for policy in policies:
            try:
                contact = self.core._contact(c, policy['contact_id'], usable=True)
                if contact['permission'] != 'allowed':
                    continue
                application = c.execute('SELECT a.status,j.company FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.job_id=?', (contact['job_id'],)).fetchone()
                if application is None or application['company'] != contact['employer'] or application['status'] in ('rejected', 'withdrawn', 'offer', 'closed', 'archived'):
                    continue
                sends = [dict(r) for r in c.execute('SELECT * FROM outreach_sends WHERE contact_id=?', (contact['contact_id'],))]
                if not sends:
                    continue
                send = max(sends, key=lambda s: (_date(s['sent_at']), s['send_id']))
                sent = _date(send['sent_at'])
                _message_id(send['message_id'])
                _text(send['thread_id'], 254)
                _email(send['from_email'])
                if (send['certainty'] != 'confirmed' or not send['evidence'].strip() or sent > now
                        or send['to_email'] != contact['email'] or send['job_id'] != contact['job_id']
                        or send['from_email'] == send['to_email']):
                    continue
                from_hash = _address_hash(contact['email'])
                # Even an unclear incoming message can be an opt-out or reply. Keep
                # hashes after redaction, and retain collision senders conservatively.
                if c.execute('SELECT 1 FROM outreach_messages WHERE from_hash=? OR contact_id=? LIMIT 1',
                             (from_hash, contact['contact_id'])).fetchone():
                    continue
                if c.execute('SELECT 1 FROM outreach_message_collisions WHERE from_hash=? LIMIT 1', (from_hash,)).fetchone():
                    continue
                if c.execute('SELECT 1 FROM outreach_message_suppressions WHERE contact_id=? OR send_id=? LIMIT 1',
                             (contact['contact_id'], send['send_id'])).fetchone():
                    continue
                if c.execute('SELECT 1 FROM outreach_followup_dismissed WHERE send_id=?', (send['send_id'],)).fetchone():
                    continue
                days = max(policy['interval_days'], policy['min_days'])
                if not (7 <= days <= 90):
                    continue
                due = sent + timedelta(days=days)
                if due > now:
                    continue
                identity = _hash(_canonical([send['send_id'], due.isoformat(), days]))
                items.append({'id': identity, 'contact_id': contact['contact_id'], 'job_id': send['job_id'],
                              'send_id': send['send_id'], 'due_at': due.isoformat(), 'kind': 'suggestion_only'})
            except (ValueError, KeyError, TypeError):
                continue
        return sorted(items, key=lambda item: (item['due_at'], item['id']))

    def get(self, view, query=None):
        query = query or {}
        if view not in ('messages', 'message', 'followups') or not isinstance(query, dict):
            raise ValueError('Unknown correspondence view')
        allowed = {'id'} if view == 'message' else {'contact_id', 'limit'}
        if set(query) - allowed:
            raise ValueError('Unknown correspondence query field')
        limit = query.get('limit', 25)
        if isinstance(limit, list):
            limit = limit[0] if len(limit) == 1 else None
        try:
            limit = int(limit)
        except (ValueError, TypeError) as exc:
            raise ValueError('Invalid correspondence result limit') from exc
        if not 1 <= limit <= 100:
            raise ValueError('Invalid correspondence result limit')
        def scalar(key):
            value = query.get(key)
            if isinstance(value, list):
                value = value[0] if len(value) == 1 else None
            return _text(value, 128)
        with self.core._connection() as (c, exists):
            if not exists or not self._schema(c):
                if view == 'message':
                    raise ValueError('Unknown local correspondence message')
                return {'items': [], 'limit': limit}
            if view == 'message':
                return self._projection(self._row(c, scalar('id')), detail=True)
            if view == 'followups':
                items = self._followups(c)
                if 'contact_id' in query:
                    cid = scalar('contact_id')
                    items = [item for item in items if item['contact_id'] == cid]
                return {'items': items[:limit], 'limit': limit}
            sql, args = 'SELECT * FROM outreach_messages', []
            if 'contact_id' in query:
                sql += ' WHERE contact_id=?'
                args.append(scalar('contact_id'))
            args.append(limit)
            rows = c.execute(sql + ' ORDER BY imported_at DESC,id DESC LIMIT ?', args).fetchall()
            return {'items': [self._projection(dict(row)) for row in rows], 'limit': limit}

    def action(self, action, payload):
        fields = {
            'import-message': {'confirm', 'message', 'operation_id', 'checkpoint'},
            'match-message': {'confirm', 'id'}, 'redact-message': {'confirm', 'id'},
            'followup-policy': {'confirm', 'contact_id', 'interval_days', 'min_days', 'enabled'},
            'dismiss-followup': {'confirm', 'id'},
            'prune-messages': {'confirm', 'retention_days'},
        }
        if action not in fields or not isinstance(payload, dict) or set(payload) - fields[action]:
            raise ValueError('Unknown correspondence action or field')
        if payload.get('confirm') != action:
            raise ValueError('Explicit correspondence action confirmation is required')
        # Parse input before installing any additive schema.
        if action == 'import-message':
            _normalize(payload.get('message'))
        with self.core._connection(write=True, create=True) as (c, _):
            self._schema(c, create=True)
            if action == 'import-message':
                return self._import(c, payload)
            if action == 'prune-messages':
                days = payload.get('retention_days')
                if type(days) is not int or not 30 <= days <= 3650:
                    raise ValueError('Explicit message retention must be 30 to 3650 days')
                cutoff = (_date(self.core._now()) - timedelta(days=days)).isoformat()
                rows = c.execute('''SELECT id FROM outreach_messages
                    WHERE redacted=0 AND imported_at<? ORDER BY imported_at,id LIMIT 100''', (cutoff,)).fetchall()
                for row in rows:
                    self._redact(c, row['id'])
                remaining = bool(c.execute('SELECT 1 FROM outreach_messages WHERE redacted=0 AND imported_at<? LIMIT 1',
                                           (cutoff,)).fetchone())
                return {'redacted_count': len(rows), 'more_eligible': remaining,
                        'retention_days': days, 'batch_limit': 100}
            if action == 'followup-policy':
                contact = self.core._contact(c, _text(payload.get('contact_id'), 128))
                days, minimum = payload.get('interval_days', 14), payload.get('min_days', 7)
                enabled = payload.get('enabled', True)
                if (type(days) is not int or type(minimum) is not int or not 7 <= days <= 90
                        or not 7 <= minimum <= 90 or type(enabled) is not bool):
                    raise ValueError('Follow-up policy needs intervals of 7 to 90 days and explicit enabled flag')
                c.execute('''INSERT INTO outreach_followup_policy VALUES(?,?,?,?,?)
                    ON CONFLICT(contact_id) DO UPDATE SET interval_days=excluded.interval_days,
                    min_days=excluded.min_days,enabled=excluded.enabled,updated_at=excluded.updated_at''',
                    (contact['contact_id'], days, minimum, int(enabled), self.core._now()))
                self._event(c, contact['contact_id'], 'followup_policy_reviewed')
                return {'contact_id': contact['contact_id'], 'interval_days': days, 'min_days': minimum,
                        'enabled': enabled, 'kind': 'suggestion_only'}
            if action == 'dismiss-followup':
                identity = _text(payload.get('id'), 128)
                existing = c.execute('SELECT 1 FROM outreach_followup_dismissed WHERE id=?', (identity,)).fetchone()
                if existing:
                    return {'id': identity, 'dismissed': True}
                item = next((item for item in self._followups(c) if item['id'] == identity), None)
                if not item:
                    raise ValueError('Follow-up suggestion is unavailable; refresh the queue')
                c.execute('INSERT INTO outreach_followup_dismissed VALUES(?,?,?,?)',
                          (identity, item['send_id'], item['contact_id'], self.core._now()))
                self._event(c, identity, 'followup_dismissed')
                return {'id': identity, 'dismissed': True}
            row = self._row(c, payload.get('id'))
            if action == 'redact-message':
                self._redact(c, row['id'])
            else:
                send = self._matching_send(c, row)
                if not send:
                    raise ValueError('Message headers or current contact cannot establish one strong association')
                c.execute("UPDATE outreach_messages SET match_state='matched_unverified',contact_id=?,send_id=?,reason='operator_headers_unverified' WHERE id=?",
                          (send['contact_id'], send['send_id'], row['id']))
                self._event(c, row['id'], 'message_match_reviewed')
            return {'message': self._projection(self._row(c, row['id']))}
