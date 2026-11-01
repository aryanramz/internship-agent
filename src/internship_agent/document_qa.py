"""DOCX extraction checks and local packet identities; rendering is a separate check."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import zipfile
from docx import Document
from docx.oxml.ns import qn


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect_docx(path, expected):
    doc = Document(path)
    extracted = [p.text for p in doc.paragraphs]
    root = doc.element
    external = [r.target_ref for r in doc.part.rels.values() if r.is_external]
    warnings = []
    if any(len(word) > 80 for p in extracted for word in p.split()):
        warnings.append('Long unbroken text: inspect wrapping/overflow in a renderer')
    if any(len(p) > 1200 for p in extracted):
        warnings.append('Long paragraph: inspect pagination in a renderer')
    checks = {
        'reading_order_matches_trace': extracted == expected,
        'single_column': all(s._sectPr.find(qn('w:cols')) is None or
                             s._sectPr.find(qn('w:cols')).get(qn('w:num'), '1') == '1'
                             for s in doc.sections),
        'no_tables': not bool(root.findall('.//' + qn('w:tbl'))),
        'no_text_boxes': not bool(root.findall('.//' + qn('w:txbxContent'))),
        'no_external_relationships': not external,
        'selectable_text': bool(extracted) and any(extracted),
        'headings_present': any(p.style.name.startswith(('Heading', 'Title')) for p in doc.paragraphs),
        'heading_keep_with_next': all(p.paragraph_format.keep_with_next is True
                                      for p in doc.paragraphs if p.style.name.startswith('Heading')),
    }
    with zipfile.ZipFile(path) as archive:
        checks['no_macros_or_embedded_objects'] = not any(
            'vbaProject' in name or name.startswith('word/embeddings/') for name in archive.namelist())
    return {'sha256': file_sha256(path), 'checks': checks, 'warnings': warnings,
            'extracted_paragraphs': extracted,
            'pagination': 'Requires rendered inspection; DOCX extraction does not measure pages'}


def verify_packet(resume_path):
    """Reject modified new-format review artifacts before explicit approval.

    Legacy packets have no manifest and retain their existing approval behavior.
    Local disk is trusted; this detects accidental edits, not a malicious owner.
    """
    root = Path(resume_path).parent
    qa_path = root / 'qa.json'
    if not qa_path.exists():
        if root.name.startswith('revision-'):
            raise ValueError('Missing document QA report; regenerate and review')
        return
    qa = json.loads(qa_path.read_text(encoding='utf-8'))
    if not qa.get('structural_pass'):
        raise ValueError('Document QA failed; regenerate and review')
    expected = {'resume.docx', 'cover_letter_DRAFT.docx', 'application_answers_DRAFT.docx', 'claims.json'}
    if set(qa.get('files', {})) != expected:
        raise ValueError('Incomplete document identity; regenerate and review')
    for name, info in qa['files'].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or file_sha256(path) != info['sha256']:
            raise ValueError('Document packet changed; regenerate and review')
