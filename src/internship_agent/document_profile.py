"""Bounded local attestations for document claims, separate from eligibility/ranking."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import re
from urllib.parse import urlsplit

from .role_taxonomy import ALIASES

ERROR = "Invalid document profile"
SCALARS = ("name", "email", "phone", "location", "linkedin", "github")
EDUCATION = ("school", "degree", "graduation", "gpa")
ITEM_FIELDS = ("name", "title", "company", "dates")


def clean_text(value, width=2000):
    if (not isinstance(value, str) or len(value) > width or
            any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF or
                ord(c) in (0xFFFE, 0xFFFF) for c in value)):
        raise ValueError(ERROR)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalize_document_profile(profile: dict) -> dict:
    """Return allowed leaves and usable claims; no implicit promotion of legacy data.

    Each fact attests one exact JSON pointer AND value. All declarations of a
    conflicting value withhold the path, even when one declaration is unverified.
    This is local user attestation, never independent source authentication.
    """
    if not isinstance(profile, dict):
        raise ValueError(ERROR)
    try:
        if len(json.dumps(profile, ensure_ascii=True, allow_nan=False)) > 1_048_576:
            raise ValueError(ERROR)
    except (TypeError, OverflowError, RecursionError) as exc:
        raise ValueError(ERROR) from exc
    leaves = {}

    def leaf(path, value):
        clean_text(value)
        if value.strip():
            leaves[path] = value

    def sequence(value):
        if not isinstance(value, list) or len(value) > 100:
            raise ValueError(ERROR)
        return value

    for key in SCALARS:
        if key in profile:
            leaf('/' + key, profile[key])
    edu = profile.get('education', {})
    if not isinstance(edu, dict):
        raise ValueError(ERROR)
    for key in EDUCATION:
        if key in edu:
            leaf('/education/' + key, edu[key])
    for key in ('skills', 'certifications'):
        for i, value in enumerate(sequence(profile.get(key, []))):
            leaf(f'/{key}/{i}', value)
    for key in ('experience', 'projects'):
        for i, item in enumerate(sequence(profile.get(key, []))):
            if not isinstance(item, dict):
                raise ValueError(ERROR)
            for field in ITEM_FIELDS:
                if field in item:
                    leaf(f'/{key}/{i}/{field}', item[field])
            for field in ('bullets', 'stack'):
                for j, value in enumerate(sequence(item.get(field, []))):
                    leaf(f'/{key}/{i}/{field}/{j}', value)
    if sum(map(len, leaves.values())) > 100_000:
        raise ValueError(ERROR)
    raw = profile.get('documents', {})
    if (not isinstance(raw, dict) or raw.keys() - {'version', 'facts', 'tracks'} or
            type(raw.get('version', 1)) is not int or raw.get('version', 1) != 1):
        raise ValueError(ERROR)
    facts = raw.get('facts', [])
    if not isinstance(facts, list) or len(facts) > 2000:
        raise ValueError(ERROR)
    by_path, ids = {}, set()
    path_pattern = (r'/(?:name|email|phone|location|linkedin|github|education/(?:school|degree|graduation|gpa)'
                    r'|(?:skills|certifications)/(?:0|[1-9][0-9]?)'
                    r'|(?:experience|projects)/(?:0|[1-9][0-9]?)/(?:name|title|company|dates|(?:bullets|stack)/(?:0|[1-9][0-9]?)))')
    for fact in facts:
        if (not isinstance(fact, dict) or set(fact) !=
                {'id', 'path', 'value', 'verified', 'source', 'reviewed_on'}):
            raise ValueError(ERROR)
        fid = clean_text(fact['id'], 80)
        path = clean_text(fact['path'], 120)
        if not re.fullmatch(r'[A-Za-z0-9_-]+', fid) or fid in ids or not re.fullmatch(path_pattern, path):
            raise ValueError(ERROR)
        ids.add(fid)
        clean_text(fact['value'])
        if not fact['value'].strip() or type(fact['verified']) is not bool:
            raise ValueError(ERROR)
        if not clean_text(fact['source'], 300).strip():
            raise ValueError(ERROR)
        try:
            if date.fromisoformat(fact['reviewed_on']).isoformat() != fact['reviewed_on']:
                raise ValueError(ERROR)
        except (ValueError, TypeError) as exc:
            raise ValueError(ERROR) from exc
        by_path.setdefault(path, []).append(fact)
    tracks = raw.get('tracks', {})
    if not isinstance(tracks, dict) or tracks.keys() - ALIASES.keys():
        raise ValueError(ERROR)
    for paths in tracks.values():
        if (not isinstance(paths, list) or len(paths) > 100 or
                any(not isinstance(p, str) or p not in leaves for p in paths) or
                len(set(paths)) != len(paths)):
            raise ValueError(ERROR)
    claims, unresolved = {}, []
    # Preserve profile/list order; lexical pointer order puts index 10 before 2.
    for path in [*leaves, *sorted(by_path.keys() - leaves.keys())]:
        value = leaves.get(path)
        declarations = by_path.get(path, [])
        reason = None
        if len({f['value'] for f in declarations}) > 1:
            reason = 'conflicting'
        elif declarations and any(f['value'] != value for f in declarations):
            reason = 'stale'
        elif not declarations or not any(f['verified'] for f in declarations):
            reason = 'unverified'
        elif path in ('/linkedin', '/github'):
            parsed = urlsplit(value)
            if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                reason = 'unsafe_link'
        if reason:
            unresolved.append({'path': path, 'reason': reason})
        elif value is not None:
            fact = next(f for f in declarations if f['verified'])
            claims[path] = {'fact_id': fact['id'], 'path': path, 'value': value,
                            'verification': 'locally_attested', 'source': fact['source'],
                            'reviewed_on': fact['reviewed_on']}
    # A bullet without a verified role/project identity loses its context.
    for key in ('experience', 'projects'):
        for i, _ in enumerate(profile.get(key, [])):
            prefix = f'/{key}/{i}/'
            if not any(prefix + field in claims for field in ('name', 'title')):
                for path in list(claims):
                    if path.startswith(prefix):
                        del claims[path]
                        unresolved.append({'path': path, 'reason': 'missing_item_identity'})
    return {'claims': claims, 'leaves': leaves, 'unresolved': unresolved,
            'tracks': tracks, 'profile_sha256': digest(profile)}
