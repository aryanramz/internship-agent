"""Local evidence comparisons, independent of fit score and legal determinations."""
from __future__ import annotations

from datetime import date
import json
import unicodedata

from .eligibility_profile import normalize_profile, date_bounds

OUTCOMES = {"pass": "satisfied", "fail": "not_satisfied", "unknown": "uncertain"}
LIMITATIONS = [
    "Compares declared evidence only; this is not an employer hiring decision or guarantee.",
    "Does not determine citizenship, immigration, legal work authorization or clearance.",
    "Controlled requirement extraction is incomplete; verify original posting and candidate declarations locally.",
]
_MAJOR_ALIASES = {"cs": "computer science", "computer science": "computer science",
    "is": "information systems", "information systems": "information systems",
    "it": "information technology", "information technology": "information technology",
    "ee": "electrical engineering", "electrical engineering": "electrical engineering",
    "computer engineering": "computer engineering", "software engineering": "software engineering",
    "data science": "data science", "mathematics": "mathematics", "math": "mathematics",
    "engineering": "engineering", "business": "business", "economics": "economics"}


def _text(value):
    return " ".join(unicodedata.normalize("NFKC", str(value)).casefold().split())


def _scalar(value):
    if isinstance(value, str):
        return _text(value)
    if isinstance(value, list):
        return sorted({_scalar(item) for item in value}, key=lambda item:json.dumps(item,sort_keys=True))
    return value


def _date(value):
    return date.fromisoformat(value)


def _bounds(node):
    constraint = node["constraint"]
    op = constraint["op"]
    if op == "date_range":
        low = _date(constraint["min"]) if constraint.get("min") else date.min
        high = _date(constraint["max"]) if constraint.get("max") else date.max
        return low.toordinal() + (not constraint.get("min_inclusive", True)), high.toordinal() - (not constraint.get("max_inclusive", True))
    value = constraint.get("value")
    if node["kind"] == "graduation":
        lo, hi = date_bounds(value)
        # A strict after/before month excludes that whole imprecise month.
        n = (hi if op in {"gt", "lte"} else lo).toordinal()
        return {"gte": (n,date.max.toordinal()), "gt": (n+1,date.max.toordinal()),
                "lte": (date.min.toordinal(),n), "lt": (date.min.toordinal(),n-1)}.get(op)
    if op in {"gte", "gt", "lte", "lt", "eq"} and type(value) is int:
        return {"gte": (value,float("inf")), "gt": (value+1,float("inf")),
                "lte": (float("-inf"),value), "lt": (float("-inf"),value-1), "eq": (value,value)}[op]
    return None


def _conjunctive_leaves(node):
    if node.get("strength", "required") != "required" or node.get("issues"):
        return []
    if "operator" in node:
        if node["operator"] != "all":
            return []
        return [leaf for child in node["children"] for leaf in _conjunctive_leaves(child)]
    return [node]


def _requirement_conflicts(tree):
    buckets = {}
    for node in _conjunctive_leaves(tree):
        if node["kind"] not in {"enrolled","degree_level","residence_country","work_authorized",
            "needs_sponsorship","returning_student","graduation","academic_year","completed_academic_years"}:
            continue
        key = (node["kind"], json.dumps(node.get("qualifiers", {}), sort_keys=True))
        buckets.setdefault(key, []).append(node)
    conflicts = {}
    for nodes in buckets.values():
        allowed = None
        low, high = float("-inf"), float("inf")
        for node in nodes:
            c = node["constraint"]
            if node["kind"] != "graduation" and c["op"] in {"eq","one_of"}:
                values = c.get("value") if c["op"] == "one_of" else [c.get("value")]
                values = {json.dumps(_scalar(v), sort_keys=True) for v in values}
                allowed = values if allowed is None else allowed & values
            bounds = _bounds(node)
            if bounds:
                low, high = max(low,bounds[0]), min(high,bounds[1])
        if allowed is not None and nodes[0]["kind"] in {"academic_year","completed_academic_years"}:
            allowed = {value for value in allowed if low <= json.loads(value) <= high}
        if allowed == set() or low > high:
            ids = sorted(n["id"] for n in nodes)
            for node in nodes:
                conflicts[node["id"]] = {"requirement_ids":ids,"reason":"Mandatory posting constraints conflict; verify their scope."}
    # Each conjunction inside an alternative has its own conflict scope. Never
    # combine mutually exclusive OR branches into one mandatory intersection.
    for child in tree.get("children",[]):
        if "operator" in child:
            conflicts.update(_requirement_conflicts(child))
    return conflicts


def _current(fact, as_of):
    q = fact["qualifiers"]
    return not ((q.get("valid_from") and as_of < _date(q["valid_from"])) or
                (q.get("valid_until") and as_of > _date(q["valid_until"])))


def _verified(fact):
    p = fact["provenance"]
    return fact["status"] == "known" and p["verified"] is True and p["kind"] in {"user_declared","verified_document"}


def _relevant(fact, node):
    q, required = fact["qualifiers"], node.get("qualifiers", {})
    if node["kind"] not in {"availability","returning_student"}:
        timeframe = required.get("timeframe", "current")
        if q.get("timeframe", "current") not in {timeframe,"both"}:
            return False
    if node["kind"] in {"work_authorized", "needs_sponsorship"}:
        if not required.get("country") or q.get("country") != required["country"]:
            return False
        timeframe = required.get("timeframe", "current")
        if node["kind"] == "needs_sponsorship" and q.get("timeframe", "current") not in {timeframe,"both"}:
            return False
    return True


def _period_compare(fact, node):
    c, q = node["constraint"], fact["qualifiers"]
    required = c["value"] if c["op"] in {"term","interval"} else node.get("qualifiers", {})
    if c["op"] == "term" or (required.get("season") and required.get("year")):
        if (q.get("season"),q.get("year")) != (required.get("season"),required.get("year")):
            return "unknown"
        expected = c["value"] if type(c.get("value")) is bool else True
        return "pass" if fact["value"] == expected else "fail"
    if c["op"] == "interval":
        if not q.get("start") or not q.get("end"):
            return "unknown"
        start,end = _date(required["start"]),_date(required["end"])
        first,last = _date(q["start"]),_date(q["end"])
        overlap = first <= end and last >= start
        if not fact["value"] and overlap:
            return "fail"
        return "pass" if fact["value"] and first <= start and last >= end else "unknown"
    # A timeless return-to-school assertion is not evidence about this internship.
    if node["kind"] == "returning_student":
        expected = node.get("qualifiers", {})
        if not expected.get("year") or not expected.get("season"):
            return "unknown"
        return "pass" if (q.get("season"),q.get("year")) == (expected["season"],expected["year"]) and fact["value"] == c.get("value") else "unknown"
    return "unknown"


def _compare(fact, node):
    c, field, value = node["constraint"], node["kind"], fact["value"]
    op, expected = c["op"], c.get("value")
    if field in {"availability","returning_student"}:
        return _period_compare(fact,node)
    if field == "graduation":
        if op == "eq":
            first,last = date_bounds(expected)
            wanted = first.toordinal(),last.toordinal()
        else:
            wanted = _bounds(node)
        if not wanted:
            return "unknown"
        first,last = _date(value["earliest"]).toordinal(),_date(value["latest"]).toordinal()
        if first >= wanted[0] and last <= wanted[1]:
            return "pass"
        return "fail" if last < wanted[0] or first > wanted[1] else "unknown"
    if op in {"gte","gt","lte","lt"}:
        if type(value) is not int or type(expected) is not int:
            return "unknown"
        return "pass" if {"gte":value>=expected,"gt":value>expected,"lte":value<=expected,"lt":value<expected}[op] else "fail"
    if op == "eq":
        return "pass" if _scalar(value) == _scalar(expected) else "fail"
    if op in {"one_of","all_of"}:
        actual = set(_scalar(value) if isinstance(value,list) else [_scalar(value)])
        wanted = set(_scalar(expected) if isinstance(expected,list) else [_scalar(expected)])
        if field == "majors":
            actual = {_MAJOR_ALIASES.get(v,v) for v in actual}
            wanted = {_MAJOR_ALIASES.get(v,v) for v in wanted}
        matches = bool(actual & wanted) if op == "one_of" else wanted <= actual
        if matches:
            return "pass"
        if field in {"skills","coursework","work_locations"}:
            return "unknown"  # Omission or unrecognized geographic spelling is not inability.
        if field == "majors" and any(v not in _MAJOR_ALIASES.values() for v in actual | wanted):
            return "unknown"
        return "fail"
    return "unknown"


def _evaluate_leaf(node, candidate, as_of, conflicts):
    result = {key:node.get(key) for key in ("id","kind","strength","constraint","qualifiers","evidence")}
    result.update(candidate_facts=[],missing_facts=[],conflicts=[],manual_verification=[])
    def finish(value, reason):
        result.update(outcome=OUTCOMES[value],reason=reason)
        if value == "unknown":
            result["manual_verification"].append("Verify this requirement and applicable candidate facts locally; do not guess.")
        return value,result
    if node["id"] in conflicts:
        result["conflicts"].append(conflicts[node["id"]])
        return finish("unknown","Posting requirements conflict.")
    if node.get("issues") or node["strength"] == "ambiguous" or node["kind"] == "manual_review" or node["constraint"]["op"] == "manual":
        return finish("unknown","Requirement is ambiguous or outside the supported comparison rules.")
    facts = [f for f in candidate["facts"] if f["field"] == node["kind"] and _current(f,as_of) and _relevant(f,node)]
    result["candidate_facts"] = facts
    if any(f["status"] == "conflicting" for f in facts):
        result["conflicts"].append({"fact_ids":sorted(f["id"] for f in facts),"reason":"Candidate facts are explicitly conflicting."})
        return finish("unknown","Candidate facts conflict.")
    known = [f for f in facts if _verified(f)]
    if not known:
        result["missing_facts"] = [node["kind"]]
        return finish("unknown","No applicable, explicitly verified candidate fact is available.")
    if node["kind"] == "availability" and node["constraint"]["op"] == "interval":
        required = node["constraint"]["value"]
        intervals = [(f,max(required["start"],f["qualifiers"]["start"]),
                      min(required["end"],f["qualifiers"]["end"])) for f in known
                     if {"start","end"} <= f["qualifiers"].keys()]
        disagree = set()
        for index,(first,start,end) in enumerate(intervals):
            for second,other_start,other_end in intervals[index+1:]:
                if first["value"] != second["value"] and max(start,other_start) <= min(end,other_end):
                    disagree.update((first["id"],second["id"]))
        if disagree:
            result["conflicts"].append({"fact_ids":sorted(disagree),"reason":"Verified availability declarations disagree over a required interval."})
            return finish("unknown","Applicable verified availability declarations overlap and disagree.")
    if node["kind"] in {"availability","returning_student"}:
        applicable = [f for f in known if _period_compare(f,node) != "unknown"]
    else:
        applicable = known
    if not applicable:
        result["missing_facts"] = [node["kind"]]
        return finish("unknown","The supplied evidence does not establish the required date, term or scope.")
    distinct = {json.dumps(_scalar(f["value"]),sort_keys=True) for f in applicable}
    if len(distinct) > 1:
        result["conflicts"].append({"fact_ids":sorted(f["id"] for f in applicable),"reason":"Applicable verified declarations disagree."})
        return finish("unknown","Applicable verified candidate facts disagree.")
    values = [_compare(f,node) for f in applicable]
    value = "fail" if "fail" in values else "pass" if "pass" in values else "unknown"
    return finish(value,{"pass":"Verified declaration satisfies the explicit comparison.",
                         "fail":"Verified declaration directly conflicts with the explicit requirement.",
                         "unknown":"The evidence is insufficient for a definite comparison."}[value])


def evaluate_requirements(candidate: dict, requirements: dict, *, as_of: date) -> dict:
    """Compare canonical records; never use score, execution or external services."""
    from .eligibility_requirements import validate_requirements
    if type(as_of) is not date:
        raise ValueError("Eligibility evaluation requires an explicit date")
    # Revalidate canonical facts too, so callers cannot forge a trusted projection.
    if not isinstance(candidate,dict) or candidate.get("schema_version") != 2:
        raise ValueError("Invalid eligibility profile")
    normalized = normalize_profile({"profile_version":2,"candidate_facts":candidate.get("facts",[])})
    validate_requirements(requirements)
    conflicts = _requirement_conflicts(requirements)
    def walk(node):
        if "operator" not in node:
            return _evaluate_leaf(node,normalized,as_of,conflicts)
        children = [walk(child) for child in node["children"]]
        required = [value for child,(value,_) in zip(node["children"],children) if child.get("strength","required") != "preferred"]
        if node.get("strength") == "ambiguous":
            outcome = "unknown"
        elif not required:
            outcome = "unknown"
        elif node["operator"] == "all":
            outcome = "fail" if "fail" in required else "unknown" if "unknown" in required else "pass"
        else:
            outcome = "pass" if "pass" in required else "unknown" if "unknown" in required else "fail"
        if node.get("issues") and outcome != "fail":
            outcome = "unknown"
        return outcome,{"id":node.get("id","root"),"operator":node["operator"],"strength":node.get("strength","required"),
                        "outcome":OUTCOMES[outcome],"evidence":node.get("evidence",[]),"issues":node.get("issues",[]),
                        "reason":"Compare mandatory alternatives using three-state logic; preferred rules do not block.",
                        "rules":[r for _,r in children]}
    outcome,tree = walk(requirements)
    all_rules = []
    def collect(node, *, material=False):
        if node.get("strength") == "preferred":
            return
        if "rules" in node:
            if material and node.get("operator") == "any" and node["outcome"] == "satisfied":
                return
            for child in node["rules"]:
                collect(child,material=material)
        else:
            all_rules.append(node)
    collect(tree)
    required_count = sum(r["strength"] == "required" for r in all_rules)
    all_rules = []
    collect(tree,material=True)
    if not required_count or (requirements.get("issues") and outcome != "fail"):
        outcome = "unknown"
    return {"schema_version":1,"outcome":{"pass":"eligible","fail":"ineligible","unknown":"uncertain"}[outcome],
            "as_of":as_of.isoformat(),"rules":tree.get("rules",[]),"required_rule_count":required_count,
            "missing_information":sorted({f for r in all_rules for f in r.get("missing_facts",[])}),
            "conflicts":list({json.dumps(c,sort_keys=True):c for r in all_rules for c in r.get("conflicts",[])}.values()),
            "manual_verification":list(dict.fromkeys([m for r in all_rules for m in r.get("manual_verification",[])] +
                (["Review the full posting; no reliable mandatory requirement was identified."] if not required_count else []))),
            "profile_source_version":candidate.get("source_version",2),"profile_warnings":candidate.get("warnings",[]),
            "limitations":list(LIMITATIONS)}


def evaluate_eligibility(profile: dict, job: dict, *, as_of: date) -> dict:
    from .eligibility_requirements import parse_requirements
    return evaluate_requirements(normalize_profile(profile),parse_requirements(job),as_of=as_of)
