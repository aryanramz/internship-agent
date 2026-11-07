"""Finite offline outreach facade; no integration or sending capability."""
from .outreach import Outreach
from .outreach_messages import Correspondence

CONTACT_ACTIONS=frozenset({'register-contact','verify-contact','edit-contact','optout','create-draft','edit-draft','review-draft','export-draft','record-send','redact-contact'})
MESSAGE_ACTIONS=frozenset({'import-message','match-message','followup-policy','dismiss-followup','redact-message','prune-messages'})

def read(root,view,query):
    if view in {'contacts','contact','drafts','draft'}:return Outreach(root).get(view,query)
    if view in {'messages','message','followups'}:return Correspondence(root).get(view,query)
    raise ValueError('Unknown outreach view')

def mutate(root,payload):
    action=payload.get('action')
    if not isinstance(action,str) or payload.get('confirm')!=action:
        raise ValueError('Explicit action confirmation required')
    payload={k:v for k,v in payload.items() if k!='action'}
    if action in CONTACT_ACTIONS:return Outreach(root).action(action,payload)
    if action in MESSAGE_ACTIONS:return Correspondence(root).action(action,payload)
    raise ValueError('Unknown outreach action')
