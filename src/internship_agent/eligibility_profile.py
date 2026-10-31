"""Bounded, in-memory eligibility declarations without contact profile data.

Source references are opaque labels. Nothing in this module reads files, fetches
references, infers legal status, or changes the original private profile.
"""
from calendar import monthrange
from datetime import date
import json
import re


MAX_FACTS = 200
MAX_PROFILE_BYTES = 1_048_576
MAX_TEXT_LENGTH = 1000
DEGREE_LEVELS = frozenset({"associate", "bachelor", "master", "doctoral"})
BOOLEAN_FIELDS = frozenset({"enrolled", "returning_student", "work_authorized", "needs_sponsorship", "availability"})
LIST_FIELDS = frozenset({"completed_degrees", "majors", "skills", "coursework", "work_locations", "work_modes"})
FACT_FIELDS = BOOLEAN_FIELDS | LIST_FIELDS | {
    "degree_level", "academic_year", "completed_academic_years", "residence_country", "graduation"}
COUNTRIES = frozenset("""AD AE AF AG AI AL AM AO AQ AR AS AT AU AW AX AZ BA BB BD BE BF BG BH BI BJ BL BM BN BO BQ BR BS BT BV BW BY BZ
CA CC CD CF CG CH CI CK CL CM CN CO CR CU CV CW CX CY CZ DE DJ DK DM DO DZ EC EE EG EH ER ES ET FI FJ FK FM FO FR
GA GB GD GE GF GG GH GI GL GM GN GP GQ GR GS GT GU GW GY HK HM HN HR HT HU ID IE IL IM IN IO IQ IR IS IT JE JM JO JP
KE KG KH KI KM KN KP KR KW KY KZ LA LB LC LI LK LR LS LT LU LV LY MA MC MD ME MF MG MH MK ML MM MN MO MP MQ MR MS MT MU MV MW MX MY MZ
NA NC NE NF NG NI NL NO NP NR NU NZ OM PA PE PF PG PH PK PL PM PN PR PS PT PW PY QA RE RO RS RU RW SA SB SC SD SE SG SH SI SJ SK SL SM SN SO SR SS ST SV SX SY SZ
TC TD TF TG TH TJ TK TL TM TN TO TR TT TV TW TZ UA UG UM US UY UZ VA VC VE VG VI VN VU WF WS YE YT ZA ZM ZW""".split())
_ERROR = "Invalid eligibility profile"


def date_bounds(value: str) -> tuple[date, date]:
    """Return inclusive bounds for an exact ISO year, month, or calendar date."""
    try:
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?", value):
            raise ValueError
        parts = [int(part) for part in value.split("-")]
        year = parts[0]
        if len(parts) == 1:
            return date(year, 1, 1), date(year, 12, 31)
        month = parts[1]
        if len(parts) == 2:
            return date(year, month, 1), date(year, month, monthrange(year, month)[1])
        exact = date(year, month, parts[2])
        return exact, exact
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Invalid eligibility date") from None


def _text(value, limit=MAX_TEXT_LENGTH):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(_ERROR)
    if any(ord(char) < 32 for char in value):
        raise ValueError(_ERROR)
    return value.strip()


def _country(value):
    value = _text(value, 2).upper()
    if value not in COUNTRIES:
        raise ValueError(_ERROR)
    return value


def _full_date(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError(_ERROR)
    return date_bounds(value)[0].isoformat()


def _qualifiers(raw):
    allowed = {"country", "season", "year", "start", "end", "after", "valid_from", "valid_until", "timeframe"}
    if not isinstance(raw, dict) or raw.keys() - allowed:
        raise ValueError(_ERROR)
    result = {}
    for key, value in raw.items():
        if key == "country":
            result[key] = _country(value)
        elif key == "year":
            if type(value) is not int or not 1 <= value <= 9999:
                raise ValueError(_ERROR)
            result[key] = value
        elif key in {"season", "timeframe"}:
            normalized = _text(value, 16).lower()
            options = {"spring", "summer", "fall", "autumn", "winter"} if key == "season" else {"current", "future", "both"}
            if normalized not in options:
                raise ValueError(_ERROR)
            result[key] = "fall" if key == "season" and normalized == "autumn" else normalized
        else:
            result[key] = _full_date(value)
    if ("start" in result) != ("end" in result):
        raise ValueError(_ERROR)
    for first, last in (("start", "end"), ("valid_from", "valid_until")):
        if first in result and last in result and result[first] > result[last]:
            raise ValueError(_ERROR)
    return result


def _provenance(raw):
    if not isinstance(raw, dict) or raw.keys() - {"kind", "reference", "verified"}:
        raise ValueError(_ERROR)
    kind = raw.get("kind", "unknown")
    verified = raw.get("verified", False)
    if kind not in ("user_declared", "verified_document", "unknown") or type(verified) is not bool:
        raise ValueError(_ERROR)
    reference = raw.get("reference")
    if reference is not None:
        reference = _text(reference)
    if verified and (kind == "unknown" or reference is None):
        raise ValueError(_ERROR)
    return {"kind": kind, "reference": reference, "verified": verified}


def _value(field, value):
    if field in BOOLEAN_FIELDS:
        if type(value) is not bool:
            raise ValueError(_ERROR)
        return value
    if field in LIST_FIELDS:
        if not isinstance(value, list) or len(value) > MAX_FACTS:
            raise ValueError(_ERROR)
        items = [_text(item) for item in value]
        allowed = DEGREE_LEVELS if field == "completed_degrees" else {"remote", "hybrid", "onsite"} if field == "work_modes" else None
        if allowed is not None and any(item not in allowed for item in items):
            raise ValueError(_ERROR)
        return items
    if field == "degree_level":
        if not isinstance(value, str) or value not in DEGREE_LEVELS:
            raise ValueError(_ERROR)
        return value
    if field in {"academic_year", "completed_academic_years"}:
        minimum = 1 if field == "academic_year" else 0
        if type(value) is not int or not minimum <= value <= 8:
            raise ValueError(_ERROR)
        return value
    if field == "residence_country":
        return _country(value)
    if field == "graduation":
        if isinstance(value, str):
            earliest, latest = date_bounds(value)
        elif isinstance(value, dict) and value.keys() == {"earliest", "latest"}:
            earliest = date_bounds(value["earliest"])[0]
            latest = date_bounds(value["latest"])[1]
        else:
            raise ValueError(_ERROR)
        if earliest > latest:
            raise ValueError(_ERROR)
        return {"earliest": earliest.isoformat(), "latest": latest.isoformat()}
    raise ValueError(_ERROR)


def _fact(raw, index):
    if not isinstance(raw, dict) or raw.keys() - {"id", "field", "value", "status", "provenance", "qualifiers", "notes"}:
        raise ValueError(_ERROR)
    if "notes" in raw:
        _text(raw["notes"], 2000)
    field = raw.get("field")
    if not isinstance(field, str) or field not in FACT_FIELDS:
        raise ValueError(_ERROR)
    value = raw.get("value")
    status = raw.get("status", "unknown" if value is None else "known")
    if status not in ("known", "unknown", "conflicting"):
        raise ValueError(_ERROR)
    if status != "known" and value is not None:
        raise ValueError(_ERROR)
    qualifiers = _qualifiers(raw.get("qualifiers", {}))
    if status == "known":
        value = _value(field, value)
        if field in {"work_authorized", "needs_sponsorship"} and "country" not in qualifiers:
            raise ValueError(_ERROR)
        if field == "availability" and not (
            {"season", "year"} <= qualifiers.keys() or {"start", "end"} <= qualifiers.keys()
        ):
            raise ValueError(_ERROR)
    return {"id": _text(raw.get("id", f"fact-{index:03d}"), 128), "field": field,
            "value": value, "status": status, "provenance": _provenance(raw.get("provenance", {})), "qualifiers": qualifiers}


def _legacy(profile):
    """Adapt only explicitly typed legacy declarations, always unverified."""
    facts = []
    warnings = ["Legacy declarations are unverified; confirm structured candidate facts."]

    def add(field, value, qualifiers=None):
        raw = {"id": f"legacy-{field}", "field": field, "value": value,
               "provenance": {"kind": "unknown", "reference": "legacy profile", "verified": False},
               "qualifiers": qualifiers or {}}
        try:
            facts.append(_fact(raw, len(facts) + 1))
        except (ValueError, TypeError):
            warnings.append("A legacy declaration requires structured clarification.")

    for field in ("skills", "majors", "coursework", "work_locations", "work_modes", "completed_degrees",
                  "academic_year", "completed_academic_years", "residence_country", "degree_level", "enrolled", "returning_student"):
        if field in profile:
            add(field, profile[field])
    education = profile.get("education", {})
    if isinstance(education, dict) and education.get("graduation") is not None:
        graduation = education["graduation"]
        if isinstance(graduation, str):
            # English month labels are explicit precision, never a guessed day.
            months = {name.lower(): number for number, name in enumerate(
                ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"), 1)}
            match = re.fullmatch(r"([A-Za-z]+) ([0-9]{4})", graduation.strip())
            if match and match[1].lower() in months:
                graduation = f"{match[2]}-{months[match[1].lower()]:02d}"
        add("graduation", graduation)
    eligibility = profile.get("eligibility", {})
    if isinstance(eligibility, dict):
        if "current_undergraduate" in eligibility and "enrolled" not in profile:
            # An explicit legacy flag remains unverified, and does not imply a degree.
            add("enrolled", eligibility["current_undergraduate"])
        if "us_work_authorization" in eligibility:
            add("work_authorized", eligibility["us_work_authorization"], {"country": "US"})
        if "needs_sponsorship" in eligibility:
            # A generic legacy sponsorship answer establishes no jurisdiction.
            if eligibility["needs_sponsorship"] is None:
                add("needs_sponsorship", None)
            else:
                warnings.append("Legacy sponsorship requires an explicit country declaration.")
    return facts, list(dict.fromkeys(warnings))


def normalize_profile(profile: dict) -> dict:
    """Return a JSON-safe eligibility-only projection, without mutating input.

    Missing ``profile_version`` means legacy v1. Verified structured facts need
    explicit provenance and source labels; labels are never dereferenced.
    """
    try:
        if not isinstance(profile, dict):
            raise ValueError(_ERROR)
        serialized = json.dumps(profile, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValueError(_ERROR)
        version = profile.get("profile_version", 1)
        if type(version) is not int or version not in (1, 2):
            raise ValueError(_ERROR)
        if version == 1:
            if "candidate_facts" in profile:
                raise ValueError(_ERROR)
            facts, warnings = _legacy(profile)
        else:
            raw = profile.get("candidate_facts", [])
            if not isinstance(raw, list) or len(raw) > MAX_FACTS:
                raise ValueError(_ERROR)
            facts = [_fact(item, index) for index, item in enumerate(raw, 1)]
            warnings = []
        if len({item["id"] for item in facts}) != len(facts):
            raise ValueError(_ERROR)
        result = {"schema_version": 2, "source_version": version, "facts": facts, "warnings": warnings}
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValueError(_ERROR)
        return result
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        raise ValueError(_ERROR) from None
