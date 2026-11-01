"""Conservative title-only role taxonomy, with explicit adjacent-track relevance."""
from __future__ import annotations
import re

ALIASES = {
    'cloud': ('cloud',),
    'infrastructure': ('infrastructure', 'platform engineering', 'platform engineer'),
    'devops': ('devops','dev ops','devsecops','site reliability','sre'),
    'security': ('cybersecurity','cyber security','information security','infosec',
                 'security engineer','security engineering','security analyst','security operations',
                 'application security','cloud security','network security'),
    'software': ('software','application development','web development','backend development','frontend development'),
    'systems': ('systems engineering','systems engineer','systems administration','systems administrator','systems analyst','systems intern'),
    'it': ('information technology','it support','it engineering','it intern','it operations'),
}
ADJACENT = frozenset({frozenset(pair) for pair in (
    ('cloud','infrastructure'),('cloud','devops'),('infrastructure','devops'),
    ('infrastructure','systems'),('devops','software'),('systems','software'),('systems','it'))})
# These title contexts do not establish a technical role merely from a track word.
NONTECH = re.compile(r'\b(sales|marketing|recruit(?:er|ing)|kitchen|physical security|security guard|hr|human resources|business systems|(?:food|national|homeland|international|social|economic|public|personal) security|civil|construction|electrical|mechanical|facilities)\b',re.I)


def contains(text, phrase):
    return bool(re.search(r'(?<!\w)'+re.escape(phrase.casefold())+r'(?!\w)',text.casefold()))


def tracks(value: str, *, title=False) -> set[str]:
    if NONTECH.search(value):
        return set()
    result={track for track,aliases in ALIASES.items() if any(contains(value,alias) for alias in aliases)}
    if title and 'cloud' in result and not any(contains(value,phrase) for phrase in (
            'cloud engineer','cloud engineering','cloud intern','cloud infrastructure',
            'cloud developer','cloud development','cloud operations','cloud platform',
            'cloud computing','cloud security','cloud architecture')):
        result.remove('cloud')
    # Preserve acronym case in titles: the ordinary pronoun "it" is not a track.
    if (re.search(r'(?<!\w)IT(?!\w)',value) if title else contains(value,'it')):
        result.add('it')
    if not title:
        if value.casefold().strip() in {'cloud','infrastructure','devops','software','systems','it'}:
            return {value.casefold().strip()}
        # An alias embedded in an unknown occupation is not an equivalent target.
        remainder=value.casefold()
        spans=[]
        for aliases in ALIASES.values():
            for alias in aliases:
                spans.extend(match.span() for match in re.finditer(r'(?<!\w)'+re.escape(alias)+r'(?!\w)',remainder))
        spans.extend(match.span() for match in re.finditer(r'(?<!\w)it(?!\w)',remainder))
        chars=list(remainder)
        for start,end in spans:
            chars[start:end]=' '*(end-start)
        extra=set(re.findall(r'[a-z]+',''.join(chars)))-{'intern','internship','engineering','engineer','analyst','developer','student','summer','co','op'}
        if extra:
            return set()
    return result


def role_match(title: str, targets: list[str]) -> dict:
    actual=tracks(title,title=True)
    matches=[]
    best=0.0
    relation='unmatched'
    for target in targets:
        wanted=tracks(target)
        informative=set(re.findall(r'[a-z]+',target.casefold()))-{'intern','internship','engineering','engineer','analyst','student','summer','co','op','security','technology','information'}
        direct=bool(actual&wanted) or (not wanted and bool(informative) and not NONTECH.search(title) and contains(title,target))
        adjacent=any(frozenset((a,b)) in ADJACENT for a in actual for b in wanted)
        value=1.0 if direct else .65 if adjacent else 0.0
        if value:
            matches.append(target)
        if value>best:
            best=value
            relation='direct' if direct else 'adjacent'
    if not best:
        broad=bool(actual) or (not NONTECH.search(title) and any(contains(title,w) for w in ('engineering','engineer','technology','security')))
        best=.5 if broad else .12
        relation='broad' if broad else 'unmatched'
    return dict(unit=best,relation=relation,title_tracks=sorted(actual),matched_targets=matches,
                evidence_source='title',adjacency_is_inferred=relation=='adjacent')
