"""Bounded local ranking preferences; no profile rewriting or external services."""
from __future__ import annotations

DEFAULT_WEIGHTS = dict(role=35, skills=25, location=15, recency=10, compensation=10, employer=5)
_ERROR = 'Invalid ranking configuration'
MODES = frozenset({'remote', 'hybrid', 'onsite'})


def strings(value, *, limit=100, width=120):
    if not isinstance(value,list) or len(value)>limit:
        raise ValueError(_ERROR)
    result=[]
    seen=set()
    for item in value:
        if (not isinstance(item,str) or len(item)>width or
                any(ord(c)<32 for c in item)):
            raise ValueError(_ERROR)
        item=item.strip()
        if item and item.casefold() not in seen:
            result.append(item)
            seen.add(item.casefold())
    return result


def configuration(profile: dict) -> dict:
    if not isinstance(profile,dict):
        raise ValueError(_ERROR)
    raw=profile.get('ranking',{})
    if not isinstance(raw,dict) or raw.keys()-{'version','weights','preferences'}:
        raise ValueError(_ERROR)
    if type(raw.get('version',1)) is not int or raw.get('version',1)!=1:
        raise ValueError(_ERROR)
    weights=DEFAULT_WEIGHTS.copy()
    supplied=raw.get('weights',{})
    if (not isinstance(supplied,dict) or supplied.keys()-weights.keys() or
            any(type(v) is not int or not 0<=v<=100 for v in supplied.values())):
        raise ValueError(_ERROR)
    weights.update(supplied)
    if sum(weights.values())!=100:
        raise ValueError(_ERROR)
    roles=strings(profile.get('target_roles',[]))
    skills=strings(profile.get('skills',[]))
    locations=strings(profile.get('preferred_locations',[]))
    employers=strings(profile.get('preferred_employers',[]))
    preferences=raw.get('preferences',{})
    list_keys={'work_modes','avoid_work_modes','avoid_locations','avoid_employers'}
    bool_keys={'prefer_compensation','use_experience'}
    if not isinstance(preferences,dict) or preferences.keys()-(list_keys|bool_keys):
        raise ValueError(_ERROR)
    prefs={key:strings(preferences.get(key,[])) for key in sorted(list_keys)}
    for key in ('work_modes','avoid_work_modes'):
        prefs[key]=[v.casefold() for v in prefs[key]]
        if set(prefs[key])-MODES:
            raise ValueError(_ERROR)
    for key in bool_keys:
        value=preferences.get(key,key=='prefer_compensation')
        if type(value) is not bool:
            raise ValueError(_ERROR)
        prefs[key]=value
    for preferred,avoided in ((prefs['work_modes'],prefs['avoid_work_modes']),
                              (locations,prefs['avoid_locations']),
                              (employers,prefs['avoid_employers'])):
        if {v.casefold() for v in preferred}&{v.casefold() for v in avoided}:
            raise ValueError(_ERROR)
    experience=[]
    if prefs['use_experience']:
        raw_experience=profile.get('experience',[])
        if not isinstance(raw_experience,list) or len(raw_experience)>100:
            raise ValueError(_ERROR)
        total=0
        for item in raw_experience:
            if not isinstance(item,dict):
                raise ValueError(_ERROR)
            title=item.get('title','')
            if not isinstance(title,str) or len(title)>2000:
                raise ValueError(_ERROR)
            parts=[title]+strings(item.get('bullets',[]),width=2000)+strings(item.get('stack',[]),width=2000)
            total+=sum(map(len,parts))
            if total>100_000:
                raise ValueError(_ERROR)
            experience.append(' '.join(parts))
    return dict(weights=weights,preferences=prefs,roles=roles,skills=skills,
                locations=locations,employers=employers,experience=experience)
