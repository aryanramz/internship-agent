"""Deterministic, reviewable DOCX drafts using path-bound local attestations."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import re
import zipfile
from io import BytesIO

from docx import Document
from docx.shared import Inches, Pt
from .document_profile import normalize_document_profile, clean_text, digest
from .document_qa import inspect_docx, file_sha256
from .role_taxonomy import ALIASES, contains

NOTICE = 'DRAFT — REVIEW REQUIRED. Local attestations are not independent verification. No ATS outcome guarantee.'
MARKER = '[USER INPUT REQUIRED]'


def tailoring_report(job: dict, profile: dict) -> dict:
    model = normalize_document_profile(profile)
    text = job.get('title', '') + ' ' + job.get('description', '')
    # Keep the historical preview/MCP projection; it never authorizes document claims.
    # Its legacy field name is explicitly qualified below.
    skills = [s for s in profile.get('skills', []) if s]
    matching = [s for s in skills if contains(text, s)]
    return {'job_id': job['id'], 'title': job['title'], 'company': job['company'],
            'matching_verified_skills': matching,
            'other_verified_skills': [s for s in skills if s not in matching],
            'limitations': ['No ATS outcome guarantee', 'Review all draft content and check eligibility questions',
                            'Legacy matching_verified_skills may contain unverified profile labels; document generation requires explicit local attestation',
                            'Verified means explicit local attestation, not independent authentication'],
            'unresolved': model['unresolved']}


def _new_document():
    doc = Document()
    section = doc.sections[0]
    section.top_margin = section.bottom_margin = Inches(.65)
    section.left_margin = section.right_margin = Inches(.7)
    normal = doc.styles['Normal']
    normal.font.name = 'Calibri'
    normal.font.size = Pt(10)
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.widow_control = True
    # Remove author/template metadata and make binary output reproducible.
    props = doc.core_properties
    props.author = props.last_modified_by = ''
    props.created = props.modified = datetime(2000, 1, 1, tzinfo=timezone.utc)
    props.revision = 1
    return doc


def _save(doc, path):
    stream = BytesIO()
    doc.save(stream)
    with zipfile.ZipFile(stream) as original, zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as output:
        for name in sorted(original.namelist()):
            info = zipfile.ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, original.read(name))


def _revision(output_root, jid):
    base = Path(output_root).resolve()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    namespace = re.sub(r'[^A-Za-z0-9_-]', '_', jid)[:60] + '-' + digest(jid)[:16]
    root = base / namespace
    if root.is_symlink():
        raise ValueError('Unsafe document output path')
    root.mkdir(exist_ok=True, mode=0o700)
    if root.resolve().parent != base:
        raise ValueError('Unsafe document output path')
    # Atomic mkdir prevents collisions between concurrent local generations.
    for number in range(1, 100_001):
        revision = root / f'revision-{number:06d}'
        try:
            revision.mkdir(mode=0o700)
            return revision
        except FileExistsError:
            continue
    raise ValueError('Document revision limit reached')


def create_packet(job: dict, profile: dict, output_root: str, *, variant='job', track=None) -> dict:
    """Create a new local revision; never overwrite a prior file or grant approval."""
    model = normalize_document_profile(profile)
    if variant not in ('master', 'track', 'job') or (track is not None and track not in ALIASES):
        raise ValueError('Select master, track or job and a known taxonomy track')
    if (variant == 'track' and not track) or (variant == 'master' and track is not None):
        raise ValueError('Track variant requires a track; master does not accept one')
    for key in ('id', 'title', 'company'):
        if not clean_text(job.get(key), 500).strip():
            raise ValueError('Missing document job identity')
    description = clean_text(job.get('description', '').replace('\n', ' ').replace('\r', ' '), 200_000)
    claims = model['claims']
    skill_paths = [p for p in claims if p.startswith('/skills/')]
    matched = [p for p in skill_paths if contains(job['title'] + ' ' + description, claims[p]['value'])]
    emphasized = model['tracks'].get(track, []) if track else []

    def priority(path):
        return (0 if variant == 'job' and path in matched else 1,
                emphasized.index(path) if path in emphasized else len(emphasized))

    def ordered(paths):
        return sorted(paths, key=priority)

    docs = {key: _new_document() for key in ('resume', 'letter', 'answers')}
    rows = []

    def add(key, value, paths=(), style=None, kind='template'):
        used = [claims[p] for p in paths if p in claims]
        paragraph = docs[key].add_paragraph(value, style=style)
        if style and style.startswith('Heading'):
            paragraph.paragraph_format.keep_with_next = True
        rows.append({'document': key, 'paragraph': len(docs[key].paragraphs) - 1,
                     'text': value, 'kind': 'candidate_claim' if used else kind,
                     'claims': used})

    def values(key, paths, separator=' | ', style=None):
        paths = [p for p in paths if p in claims]
        if paths:
            add(key, separator.join(claims[p]['value'] for p in paths), paths, style)

    add('resume', NOTICE)
    if '/name' in claims:
        values('resume', ['/name'], style='Title')
    else:
        add('resume', MARKER + ' Verified name', style='Title')
    values('resume', ['/' + field for field in ('email', 'phone', 'location', 'linkedin', 'github')])
    for heading, paths in (
        ('EDUCATION', ['/education/' + key for key in ('school', 'degree', 'graduation', 'gpa')]),
        ('CERTIFICATIONS', [p for p in claims if p.startswith('/certifications/')]),
        ('TECHNICAL SKILLS', ordered(skill_paths)),
    ):
        if any(p in claims for p in paths):
            add('resume', heading, style='Heading 1')
            values('resume', paths, ', ' if heading == 'TECHNICAL SKILLS' else ' | ')
    for key in ('experience', 'projects'):
        items = []
        for i, _ in enumerate(profile.get(key, [])):
            prefix = f'/{key}/{i}/'
            paths = [p for p in claims if p.startswith(prefix)]
            if paths:
                material = ' '.join(claims[p]['value'] for p in paths)
                score = sum(contains(material, claims[p]['value']) for p in matched) if variant == 'job' else 0
                focus = sum(p in emphasized for p in paths)
                # A selected track skill can also emphasize a verified item that mentions it.
                focus += sum(contains(material, claims[p]['value']) for p in emphasized if p in claims and p.startswith('/skills/'))
                items.append((-score, -focus, i, prefix))
        if items:
            add('resume', key.upper(), style='Heading 1')
        for _, _, i, prefix in sorted(items):
            values('resume', [prefix + f for f in ('name', 'title', 'company', 'dates')], style='Heading 2')
            values('resume', ordered([p for p in claims if p.startswith(prefix + 'stack/')]), ', ')
            for p in ordered([p for p in claims if p.startswith(prefix + 'bullets/')]):
                values('resume', [p], style='List Bullet')
    if model['unresolved']:
        add('resume', 'REVIEW REQUIRED: Unverified, conflicting or stale profile facts were withheld. See claims.json.')

    add('letter', 'COVER LETTER DRAFT', style='Heading 1')
    add('letter', NOTICE)
    values('letter', ['/name', '/email'])
    add('letter', f"Posting title (untrusted): {job['title']}", kind='posting_context')
    add('letter', f"Posting employer (untrusted): {job['company']}", kind='posting_context')
    add('letter', 'Dear Hiring Team,')
    add('letter', 'I am applying for the position identified above.')
    supported = ordered(matched)
    if supported:
        add('letter', 'My listed skills include ' + ', '.join(claims[p]['value'] for p in supported) + '.', supported)
    else:
        add('letter', MARKER + ' Add relevant qualifications after verifying the supporting facts.')
    add('letter', 'Thank you for considering my application.')
    add('letter', 'Sincerely,')
    values('letter', ['/name'])

    add('answers', 'APPLICATION ANSWER DRAFTS', style='Heading 1')
    add('answers', NOTICE)
    questions = [('Full name', ['/name']),
                 ('Education', ['/education/school', '/education/degree', '/education/graduation']),
                 ('Relevant skills', ordered(matched)),
                 ('Project example', [p for p in claims if p.startswith('/projects/') and '/bullets/' in p][:1]),
                 ('Work authorization', []), ('Sponsorship', []), ('Availability', []),
                 ('Why this employer?', [])]
    for question, paths in questions:
        add('answers', question, style='Heading 2')
        if any(p in claims for p in paths):
            values('answers', paths)
        else:
            add('answers', MARKER + ' Confirm the exact question and supply a verified answer.')

    root = _revision(output_root, job['id'])
    names = {'resume': 'resume.docx', 'letter': 'cover_letter_DRAFT.docx',
             'answers': 'application_answers_DRAFT.docx'}
    result = {'revision': root.name, 'variant': variant, 'track': track}
    files = {}
    for key, doc in docs.items():
        path = root / names[key]
        _save(doc, path)
        result[key + '_path'] = str(path)
        files[path.name] = inspect_docx(path, [r['text'] for r in rows if r['document'] == key])
    trace = {'version': 1, 'revision': root.name, 'variant': variant, 'track': track,
             'profile_sha256': model['profile_sha256'], 'job_sha256': digest(job),
             'paragraphs': rows, 'unresolved': model['unresolved'],
             'limits': ['Local attestations do not authenticate truth.',
                        'Posting context is untrusted employer/title text, not candidate evidence.',
                        'Legal/authorization answers require separate human input.']}
    trace_path = root / 'claims.json'
    trace_path.write_text(json.dumps(trace, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    files[trace_path.name] = {'sha256': file_sha256(trace_path)}
    qa = {'version': 1, 'revision': root.name, 'files': files,
          'structural_pass': all(all(info['checks'].values()) for info in files.values() if 'checks' in info),
          'review_required': True, 'unresolved_count': len(model['unresolved']),
          'rendering': {'status': 'not_run', 'reason': 'Use a supported local renderer and inspect pages; extraction is not visual QA'},
          'supported_formats': ['DOCX'], 'ats_guarantee': False}
    qa_path = root / 'qa.json'
    qa_path.write_text(json.dumps(qa, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    result.update(trace_path=str(trace_path), qa_path=str(qa_path))
    return result


def create_documents(job: dict, profile: dict, output_root: str) -> tuple[str, str]:
    """Backward-compatible pair return; review evidence lives alongside the DOCX files."""
    packet = create_packet(job, profile, output_root)
    return packet['resume_path'], packet['letter_path']
