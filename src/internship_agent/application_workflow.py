"""Recoverable local drafts and exact-revision approvals. Never submits anything."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
from uuid import uuid4

from .document_profile import digest, normalize_document_profile
from .document_qa import file_sha256, verify_packet
from .models import Job, now_iso
from .profile_io import read_profile

COMPLETED = frozenset({'submitted', 'assessment', 'interview', 'offer', 'rejected', 'withdrawn'})
FILES = {'resume_path': 'resume.docx', 'letter_path': 'cover_letter_DRAFT.docx',
         'answers_path': 'application_answers_DRAFT.docx', 'trace_path': 'claims.json', 'qa_path': 'qa.json'}


def job_snapshot(job):
    # Ignore ledger fields and discovery timestamps, not changes to posting content.
    return {key: job[key] for key in Job.__dataclass_fields__ if key != 'discovered_at'}


def _job(c, jid):
    row = c.execute('SELECT j.*,a.status,a.resume_path,a.letter_path,a.approved_at '
                    'FROM jobs j JOIN applications a ON a.job_id=j.id WHERE j.id=?', (jid,)).fetchone()
    if row is None:
        raise ValueError('Unknown job ID')
    return dict(row)


def _eligible(job):
    if job['status'] in COMPLETED:
        raise ValueError('Cannot prepare documents for a completed application')


def _packet_identity(packet):
    resume = Path(packet['resume_path'])
    root = resume.parent
    # PR #27 supplies the structural/claim checks; bind qa.json itself as well.
    try:
        verify_packet(resume)
    except (AttributeError, TypeError, KeyError) as exc:
        raise ValueError('Invalid document QA report; regenerate and review') from exc
    hashes = {}
    for key, name in FILES.items():
        path = Path(packet[key])
        if path.parent != root or path.name != name or path.is_symlink() or not path.is_file():
            raise ValueError('Incomplete document packet; regenerate and review')
        hashes[name] = file_sha256(path)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError('Unsafe document packet path')
    return digest(hashes)


class Workflow:
    def __init__(self, store):
        self.store = store
        self.root = store.path.parent.resolve()

    @contextmanager
    def writer(self):
        with self.store.connection() as c:
            c.execute('PRAGMA busy_timeout=30000')
            c.execute('BEGIN IMMEDIATE')
            yield c

    def _operation_dir(self, operation_id):
        if not re.fullmatch('[a-f0-9]{32}', operation_id):
            raise ValueError('Invalid preparation operation')
        path = self.root / 'generated' / 'operations' / operation_id
        if any(p.is_symlink() for p in (path, path.parent, path.parent.parent)):
            raise ValueError('Unsafe preparation path')
        if not path.resolve().is_relative_to(self.root):
            raise ValueError('Unsafe preparation path')
        return path

    def _binding(self, c, jid):
        return c.execute('SELECT * FROM application_bindings WHERE job_id=?', (jid,)).fetchone()

    def _check_binding(self, c, jid):
        job = _job(c, jid)
        binding = self._binding(c, jid)
        if not binding:
            raise ValueError('Legacy or unbound preparation; regenerate and review')
        if c.execute("SELECT 1 FROM preparation_operations WHERE job_id=? AND state='pending'", (jid,)).fetchone():
            raise ValueError('Preparation pending; run recover before review or approval')
        packet = json.loads(binding['packet_json'])
        if (job['resume_path'] != packet['resume_path'] or job['letter_path'] != packet['letter_path']
                or digest(job_snapshot(job)) != binding['job_sha']):
            raise ValueError('Job revision changed; prepare and review again')
        if binding['profile_path'] and digest(read_profile(binding['profile_path'])) != binding['profile_sha']:
            raise ValueError('Profile changed; prepare and review again')
        if _packet_identity(packet) != binding['packet_sha']:
            raise ValueError('Document packet changed; prepare and review again')
        return job, binding, packet

    def _record_prepared(self, c, operation, packet):
        jid = operation['job_id']
        job = _job(c, jid)
        _eligible(job)
        if digest(job_snapshot(job)) != operation['job_sha']:
            raise ValueError('Job changed during preparation; retry with current inputs')
        identity = _packet_identity(packet)
        token = digest([operation['operation_id'], operation['job_sha'], identity])
        c.execute('''INSERT INTO application_bindings VALUES(?,?,?,?,?,?,?,?,?,NULL)
            ON CONFLICT(job_id) DO UPDATE SET operation_id=excluded.operation_id,
            input_sha=excluded.input_sha,job_sha=excluded.job_sha,profile_sha=excluded.profile_sha,
            profile_path=excluded.profile_path,packet_sha=excluded.packet_sha,
            packet_json=excluded.packet_json,review_token=excluded.review_token,approved_token=NULL''',
            (jid, operation['operation_id'], operation['input_sha'], operation['job_sha'],
             operation['profile_sha'], operation['profile_path'], identity, json.dumps(packet), token))
        c.execute("UPDATE applications SET status='prepared',approved_at=NULL,resume_path=?,letter_path=?,updated_at=? WHERE job_id=?",
                  (packet['resume_path'], packet['letter_path'], now_iso(), jid))
        c.execute("UPDATE preparation_operations SET state='committed',packet_json=?,completed_at=? WHERE operation_id=?",
                  (json.dumps(packet), now_iso(), operation['operation_id']))
        self.store.event(c, jid, 'prepared', {'operation_id': operation['operation_id'],
                                           'review_token': token, **packet})

    def _publish(self, operation, packet):
        directory = self._operation_dir(operation['operation_id'])
        # Flush packet contents before publishing the completion receipt. No old file is replaced.
        for key in FILES:
            with open(packet[key], 'r+b') as stream:
                os.fsync(stream.fileno())
        receipt = {'resume': Path(packet['resume_path']).relative_to(directory).as_posix(),
                   'packet_sha': _packet_identity(packet)}
        pending = directory / 'packet.json.tmp'
        with pending.open('x', encoding='utf-8') as stream:
            json.dump(receipt, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, directory / 'packet.json')

    def _read_receipt(self, operation):
        directory = self._operation_dir(operation['operation_id'])
        receipt_path = directory / 'packet.json'
        if receipt_path.is_symlink() or receipt_path.stat().st_size > 4096:
            raise ValueError('Invalid preparation receipt')
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        relative = receipt['resume']
        # Never follow paths supplied by a receipt outside this operation's directory.
        if (not isinstance(relative, str) or '\\' in relative or
                not re.fullmatch(r'[A-Za-z0-9_-]+/revision-[0-9]{6}/resume\.docx', relative)):
            raise ValueError('Invalid preparation receipt path')
        parent = (directory / relative).parent
        if (not parent.resolve().is_relative_to(directory.resolve()) or
                any(p.is_symlink() for p in (parent, parent.parent))):
            raise ValueError('Unsafe preparation receipt path')
        options = json.loads(operation['options_json'])
        packet = {key: str(parent / name) for key, name in FILES.items()}
        packet.update(revision=parent.name, **options)
        if _packet_identity(packet) != receipt['packet_sha']:
            raise ValueError('Incomplete or changed preparation packet')
        trace = json.loads(Path(packet['trace_path']).read_text(encoding='utf-8'))
        if trace['job_sha256'] != operation['job_sha'] or trace['profile_sha256'] != operation['profile_sha']:
            raise ValueError('Preparation inputs do not match receipt')
        return packet

    def recover(self, jid=None):
        results = []
        with self.writer() as c:
            query = "SELECT * FROM preparation_operations WHERE state='pending'"
            operations = c.execute(query + (' AND job_id=?' if jid else ''), (jid,) if jid else ()).fetchall()
            for operation in operations:
                c.execute('SAVEPOINT recover_operation')
                try:
                    packet = self._read_receipt(operation)
                    if digest(read_profile(operation['profile_path'])) != operation['profile_sha']:
                        raise ValueError('Profile changed')
                    self._record_prepared(c, operation, packet)
                    state = 'committed'
                except (ValueError, OSError, KeyError, TypeError):
                    c.execute('ROLLBACK TO SAVEPOINT recover_operation')
                    # Keep all partial artifacts and prior revisions. Never guess or regenerate.
                    c.execute("UPDATE preparation_operations SET state='failed',completed_at=? WHERE operation_id=?",
                              (now_iso(), operation['operation_id']))
                    self.store.event(c, operation['job_id'], 'preparation_failed',
                                     {'operation_id': operation['operation_id'], 'reason': 'incomplete_or_stale'})
                    state = 'failed'
                c.execute('RELEASE SAVEPOINT recover_operation')
                results.append({'operation_id': operation['operation_id'], 'state': state})
        return {'operations': results, 'note': 'Recovery never approves or submits; partial files are retained.'}

    def prepare(self, jid, profile_path, profile, *, variant='job', track=None, request_id=None, new_revision=False):
        from . import documents
        normalize_document_profile(profile)
        if request_id is not None and (not isinstance(request_id, str) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', request_id)):
            raise ValueError('Request ID must be 1-80 ASCII letters, digits, underscore or hyphen')
        # First state gate also prevents recovery from attaching anything to completed applications.
        with self.writer() as c:
            _eligible(_job(c, jid))
        self.recover(jid)
        with self.writer() as c:
            job = _job(c, jid)
            _eligible(job)
            snapshot = job_snapshot(job)
            job_sha, profile_sha = digest(snapshot), digest(profile)
            options = {'variant': variant, 'track': track}
            input_sha = digest([job_sha, profile_sha, options, str(Path(profile_path).resolve())])
            previous = c.execute('SELECT * FROM preparation_operations WHERE job_id=? AND request_key=?',
                                 (jid, request_id)).fetchone() if request_id else None
            binding = self._binding(c, jid)
            if previous and (previous['input_sha'] != input_sha or previous['state'] != 'committed'
                             or not binding or binding['operation_id'] != previous['operation_id']):
                raise ValueError('Request ID failed, changed or superseded; review recovery and use a new request ID')
            if previous or (request_id is None and not new_revision and binding and binding['input_sha'] == input_sha):
                _, _, packet = self._check_binding(c, jid)
                return {**job, **packet, 'operation_id': binding['operation_id'], 'reused': True}
            if c.execute("SELECT 1 FROM preparation_operations WHERE job_id=? AND state='pending'", (jid,)).fetchone():
                raise ValueError('Another preparation is pending; recover and retry')
            operation_id = uuid4().hex
            c.execute('INSERT INTO preparation_operations VALUES(?,?,?,?,?,?,?,?,?,NULL,?,NULL)',
                      (operation_id, jid, request_id or operation_id, input_sha, job_sha,
                       profile_sha, str(Path(profile_path).resolve()), json.dumps(options), 'pending', now_iso()))
            # A started replacement can never reuse the preceding approval after interruption.
            c.execute('UPDATE application_bindings SET approved_token=NULL WHERE job_id=?', (jid,))
            c.execute("UPDATE applications SET status=CASE WHEN status='approved' THEN 'prepared' ELSE status END,approved_at=NULL WHERE job_id=?", (jid,))
            self.store.event(c, jid, 'preparation_started', {'operation_id': operation_id})
        with self.writer() as c:
            operation = c.execute('SELECT * FROM preparation_operations WHERE operation_id=?', (operation_id,)).fetchone()
            if operation['state'] != 'pending':
                raise ValueError('Preparation was recovered by another process; retry')
            current = _job(c, jid)
            _eligible(current)
            if digest(job_snapshot(current)) != job_sha:
                raise ValueError('Job changed before generation; run recover and retry')
            directory = self._operation_dir(operation_id)
            directory.mkdir(parents=True, mode=0o700)
            packet = documents.create_packet(snapshot, profile, str(directory), **options)
            self._publish(operation, packet)
            self._record_prepared(c, operation, packet)
        return {**self.store.get_job(jid), **packet, 'operation_id': operation_id, 'reused': False}

    def import_prepared(self, jid, resume_path, letter_path):
        """Retain legacy draft paths without inventing job/profile provenance.

        Only managed, journal-backed preparation can create an approval binding.
        """
        with self.writer() as c:
            job = _job(c, jid)
            _eligible(job)
            if c.execute("SELECT 1 FROM preparation_operations WHERE job_id=? AND state='pending'", (jid,)).fetchone():
                raise ValueError('Preparation pending; run recover before replacing documents')
            c.execute('DELETE FROM application_bindings WHERE job_id=?', (jid,))
            c.execute("UPDATE applications SET status='prepared',approved_at=NULL,resume_path=?,letter_path=?,updated_at=? WHERE job_id=?",
                      (resume_path, letter_path, now_iso(), jid))
            self.store.event(c, jid, 'prepared', {'resume_path': resume_path, 'letter_path': letter_path,
                                               'binding': 'legacy_unbound'})
        return self.store.get_job(jid)

    def review(self, jid):
        with self.store.connection() as c:
            job, binding, packet = self._check_binding(c, jid)
            return {'job_id': jid, 'status': job['status'], 'review_token': binding['review_token'],
                    'job_sha256': binding['job_sha'], 'packet_sha256': binding['packet_sha'],
                    **packet, 'qa': json.loads(Path(packet['qa_path']).read_text(encoding='utf-8')),
                    'note': 'Inspect every document and original posting. This token is not independent fact verification.'}

    def approve(self, jid, phrase, review_token):
        if phrase != 'APPROVE ' + jid:
            raise ValueError('Approval requires exact phrase: APPROVE <job_id>')
        with self.writer() as c:
            job, binding, _ = self._check_binding(c, jid)
            if job['status'] not in {'prepared', 'approved'} or not review_token or review_token != binding['review_token']:
                raise ValueError('Approval requires the current reviewed revision token')
            if job['status'] == 'approved' and binding['approved_token'] == review_token:
                return self.store.get_job(jid)
            c.execute('UPDATE application_bindings SET approved_token=? WHERE job_id=?', (review_token, jid))
            c.execute("UPDATE applications SET status='approved',approved_at=?,updated_at=? WHERE job_id=?", (now_iso(), now_iso(), jid))
            self.store.event(c, jid, 'approved', {'review_token': review_token, 'mode': 'explicit confirmation phrase'})
        return self.store.get_job(jid)

    def mark_submitted(self, jid, evidence, approval_token):
        if not isinstance(evidence, str) or not 6 <= len(evidence.strip()) <= 4000 or any(ord(ch) < 32 for ch in evidence):
            raise ValueError('Provide a short user-supplied submission evidence reference')
        evidence = evidence.strip()
        with self.writer() as c:
            previous = c.execute('SELECT * FROM submission_records WHERE job_id=?', (jid,)).fetchone()
            if previous:
                if previous['evidence'] == evidence and previous['approval_token'] == approval_token:
                    return self.store.get_job(jid)
                raise ValueError('Submission already recorded; historical evidence was not replaced')
            job, binding, _ = self._check_binding(c, jid)
            if job['status'] != 'approved' or not approval_token or approval_token != binding['approved_token']:
                raise ValueError('Submission recording requires the exact current approval token')
            stamp = now_iso()
            c.execute('INSERT INTO submission_records VALUES(?,?,?,?,?,?)',
                      (jid, evidence, 'user_supplied', 'unverified', approval_token, stamp))
            c.execute("UPDATE applications SET status='submitted',submitted_at=?,submission_evidence=?,updated_at=? WHERE job_id=?", (stamp, evidence, stamp, jid))
            self.store.event(c, jid, 'submitted', {'evidence': evidence, 'kind': 'user_supplied',
                                                'verification': 'unverified', 'approval_token': approval_token})
        return self.store.get_job(jid)
