"""Fictional complete packet fixtures for tests that need historical approvals."""
import hashlib
import json
from internship_agent.application_workflow import Workflow


def approve_current(store, jid):
    token = store.review(jid)['review_token']
    store.approve(jid, 'APPROVE ' + jid, review_token=token)
    return token


def prepare_current(store, jid):
    profile = {'name': 'Fictional Test Candidate'}
    path = store.path.parent / ('synthetic-profile-' + hashlib.sha256(jid.encode()).hexdigest()[:16] + '.json')
    path.write_text(json.dumps(profile), encoding='utf-8')
    return Workflow(store).prepare(jid, str(path), profile)


def prepare_approved(store, jid):
    prepare_current(store, jid)
    return approve_current(store, jid)


def record_submission(store, jid, evidence):
    token = store.review(jid)['review_token']
    return store.mark_submitted(jid, evidence, approval_token=token)
