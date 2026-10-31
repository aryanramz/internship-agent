"""Offline page contracts: coverage, resumable cursors and explicit evidence."""
from datetime import datetime, timezone
import json

import pytest

from internship_agent import sources
from internship_agent.models import stable_id


NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def board(provider, **extra):
    return {"provider": provider, "token": "example", "company": "Example", **extra}


def posting(provider, sid=1, title="Engineering Intern"):
    if provider == "greenhouse":
        return {"id": sid, "title": title, "absolute_url": f"https://example.com/jobs/{sid}"}
    if provider == "lever":
        return {"id": str(sid), "text": title, "hostedUrl": f"https://jobs.lever.co/example/{sid}"}
    if provider == "ashby":
        return {"id": str(sid), "title": title, "jobUrl": f"https://jobs.ashbyhq.com/example/{sid}"}
    return {"id": str(sid), "name": title}


def payload(provider, items):
    return items if provider == "lever" else {"jobs": items}


def transport(monkeypatch, *responses):
    pending, calls = list(responses), []

    def get_bytes(url, headers=None, post_json=None):
        calls.append((url, headers, post_json))
        response = pending.pop(0)
        if isinstance(response, Exception):
            raise response
        return response if isinstance(response, bytes) else json.dumps(response).encode()

    monkeypatch.setattr(sources, "get_bytes", get_bytes)
    return calls


@pytest.mark.parametrize("provider", ["greenhouse", "lever", "ashby"])
@pytest.mark.parametrize("empty", [False, True])
def test_validated_ats_snapshot_is_authoritative_with_one_read(monkeypatch, provider, empty):
    calls = transport(monkeypatch, payload(provider, [] if empty else [posting(provider)]))
    page = sources.retrieve_page(board(provider), now=NOW)
    assert (page.complete, page.authoritative, page.next_cursor) == (True, True, None)
    assert (len(page.jobs), page.raw_count, page.rejected_count) == ((0, 0, 0) if empty else (1, 1, 0))
    assert page.closed == ()
    assert len(calls) == 1


@pytest.mark.parametrize("provider", ["greenhouse", "lever", "ashby"])
def test_filtered_snapshot_never_supplies_authoritative_absence(monkeypatch, provider):
    transport(monkeypatch, payload(provider, [posting(provider), posting(provider, 2, "Staff Engineer")]))
    page = sources.retrieve_page(board(provider, intern_only=True), now=NOW)
    assert [job.source_id for job in page.jobs] == ["1"]
    assert (page.complete, page.authoritative, page.raw_count, page.rejected_count) == (True, False, 2, 1)


def test_greenhouse_deadline_boundary_uses_same_clock_for_jobs_and_evidence(monkeypatch):
    expired = posting("greenhouse", 1)
    expired["application_deadline"] = "2026-10-28T20:00:00-04:00"
    future = posting("greenhouse", 2)
    future["application_deadline"] = "2026-10-29T00:00:01Z"
    transport(monkeypatch, {"jobs": [expired, future]})
    page = sources.retrieve_page(board("greenhouse"), now=NOW)
    assert [job.source_id for job in page.jobs] == ["2"]
    assert page.closed == ({"job_id": stable_id("greenhouse", "example", "1"),
                            "deadline": "2026-10-29T00:00:00+00:00"},)
    assert page.raw_count == 2


def test_deadline_evidence_requires_entire_snapshot_validation(monkeypatch):
    expired = {**posting("greenhouse"), "application_deadline": "2020-01-01T00:00:00Z"}
    transport(monkeypatch, {"jobs": [expired, {"id": 2}]})
    with pytest.raises(sources.SourceError, match="posting"):
        sources.retrieve_page(board("greenhouse"), now=NOW)


@pytest.mark.parametrize("provider", ["lever", "ashby"])
def test_unlisted_or_missing_posting_is_never_explicit_closure(monkeypatch, provider):
    items = [] if provider == "lever" else [{"isListed": False}]
    transport(monkeypatch, payload(provider, items))
    page = sources.retrieve_page(board(provider), now=NOW)
    assert page.jobs == []
    assert page.closed == ()


@pytest.mark.parametrize("provider", ["greenhouse", "lever", "ashby"])
def test_malformed_ats_cannot_be_healthy_empty(monkeypatch, provider):
    transport(monkeypatch, {})
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board(provider))
    assert error.value.code == "invalid_payload"


def test_smartrecruiters_resumes_by_raw_count_and_one_request_per_page(monkeypatch):
    calls = transport(monkeypatch,
        {"totalFound": 4, "content": [posting("smartrecruiters", 1, "Staff Engineer"), posting("smartrecruiters", 2)]},
        {"totalFound": 4, "content": [posting("smartrecruiters", 3), posting("smartrecruiters", 4)]})
    first = sources.retrieve_page(board("smartrecruiters", intern_only=True))
    assert [job.source_id for job in first.jobs] == ["2"]
    assert (first.raw_count, first.rejected_count, first.complete, first.authoritative) == (2, 1, False, False)
    assert first.next_cursor == {"offset": 2, "total": 4}
    assert len(calls) == 1
    last = sources.retrieve_page(board("smartrecruiters", intern_only=True), cursor=first.next_cursor)
    assert [job.source_id for job in last.jobs] == ["3", "4"]
    assert (last.complete, last.authoritative, last.next_cursor) == (True, False, None)
    assert [call[0] for call in calls] == [
        "https://api.smartrecruiters.com/v1/companies/example/postings?limit=100&offset=0",
        "https://api.smartrecruiters.com/v1/companies/example/postings?limit=100&offset=2"]


@pytest.mark.parametrize("cursor", [{}, {"offset": True, "total": 2}, {"offset": 1, "total": False},
    {"offset": -1, "total": 3}, {"offset": 4, "total": 3}, {"offset": 1.0, "total": 3},
    {"offset": 1, "total": "3"}, {"offset": 1, "total": 3, "url": "https://private.example"},
    "https://private.example", {"offset": 3, "total": 3}])
def test_cursor_rejected_before_network(monkeypatch, cursor):
    calls = transport(monkeypatch)
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"), cursor=cursor)
    assert error.value.code == "invalid_cursor"
    assert calls == []


@pytest.mark.parametrize("data", [{}, {"content": [], "totalFound": True}, {"content": [], "totalFound": -1},
    {"content": [], "totalFound": "0"}, {"content": None, "totalFound": 0},
    {"content": [None], "totalFound": 1}, {"content": [posting("smartrecruiters")], "totalFound": 0},
    {"content": [], "totalFound": 1}, {"content": [{}] * 101, "totalFound": 200}])
def test_smartrecruiters_rejects_unproven_counts_and_shapes(monkeypatch, data):
    transport(monkeypatch, data)
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"))
    assert error.value.code == "invalid_payload"


def test_changed_total_prevents_cross_snapshot_resume(monkeypatch):
    transport(monkeypatch, {"totalFound": 4, "content": [posting("smartrecruiters", 2)]})
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"), cursor={"offset": 1, "total": 3})
    assert error.value.code == "snapshot_changed"


def test_provider_failure_retains_safe_retry_metadata(monkeypatch):
    transport(monkeypatch, sources.SourceError("rate_limited", "Wait", http_status=429, retry_after="3600"))
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"))
    assert (error.value.code, error.value.http_status, error.value.retry_after) == ("rate_limited", 429, "3600")


@pytest.mark.parametrize("data", [b"{not-json", b"\xff"])
def test_invalid_json_is_safe_failure(monkeypatch, data):
    transport(monkeypatch, data)
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"))
    assert error.value.code == "invalid_payload"


def test_other_bounded_reader_is_partial_even_with_empty_valid_array(monkeypatch):
    transport(monkeypatch, {"jobs": []})
    page = sources.retrieve_page(board("remotive"))
    assert (page.complete, page.authoritative, page.next_cursor, page.closed) == (False, False, None, ())


@pytest.mark.parametrize("data", [{}, {"jobs": [None]}])
def test_legacy_malformed_payload_is_not_healthy_empty(monkeypatch, data):
    transport(monkeypatch, data)
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("remotive"))
    assert error.value.code == "invalid_payload"


def test_nonpaged_reader_rejects_cursor_without_fetch(monkeypatch):
    calls = transport(monkeypatch)
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("greenhouse"), cursor={"offset": 1, "total": 2})
    assert error.value.code == "invalid_cursor"
    assert calls == []


def test_workday_legacy_reaches_bounded_post_reader(monkeypatch):
    calls = transport(monkeypatch, {"jobPostings": [{"title": "Engineering Intern", "externalPath": "/job/Intern_1"}]})
    jobs = sources.retrieve_board(board("workday", host="example.wd5.myworkdayjobs.com", site="External", search_terms=["intern"]))
    assert len(jobs) == 1
    assert calls[0][2] == {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "intern"}


def test_usajobs_legacy_reaches_existing_authorized_reader(monkeypatch):
    monkeypatch.setenv("USAJOBS_API_KEY", "synthetic")
    monkeypatch.setenv("USAJOBS_EMAIL", "synthetic@example.invalid")
    calls = transport(monkeypatch, {"SearchResult": {"SearchResultItems": []}})
    assert sources.retrieve_board(board("usajobs")) == []
    assert calls[0][0] == "https://data.usajobs.gov/api/search?Keyword=internship&ResultsPerPage=100"
    assert calls[0][1] == {"Authorization-Key": "synthetic", "User-Agent": "synthetic@example.invalid"}


def test_valid_local_import_can_be_complete_but_never_authoritative(tmp_path):
    (tmp_path / "jobs.json").write_text("[]", encoding="utf-8")
    page = sources.retrieve_page(board("json_import", path="jobs.json"), str(tmp_path))
    assert (page.complete, page.authoritative, page.raw_count) == (True, False, 0)


@pytest.mark.parametrize("item", [{}, {"id": True, "name": "Intern"}, {"id": "one", "name": []},
    {"id": "one", "name": "Intern", "postingUrl": "https://private.local/job"},
    {"id": "one", "name": "Intern", "jobAd": {"sections": []}}])
def test_malformed_smartrecruiters_posting_cannot_finish_as_healthy_empty(monkeypatch, item):
    transport(monkeypatch, {"totalFound": 1, "content": [item]})
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"))
    assert error.value.code == "invalid_posting"


def test_malformed_workday_response_is_not_silently_discarded(monkeypatch):
    transport(monkeypatch, {})
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("workday", host="example.wd5.myworkdayjobs.com", site="External", search_terms=["intern"]))
    assert error.value.code == "invalid_payload"


@pytest.mark.parametrize("xml", [b"<html></html>", b"<rss></rss>", b"not xml"])
def test_nonfeed_xml_response_is_not_empty_success(monkeypatch, xml):
    transport(monkeypatch, xml)
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("rss", feed_url="https://example.com/feed"))
    assert error.value.code == "invalid_payload"


@pytest.mark.parametrize("xml", [b"<rss><channel/></rss>", b'<feed xmlns="http://www.w3.org/2005/Atom"/>'])
def test_valid_empty_feed_remains_non_authoritative_partial(monkeypatch, xml):
    transport(monkeypatch, xml)
    page = sources.retrieve_page(board("rss", feed_url="https://example.com/feed"))
    assert (page.jobs, page.complete, page.authoritative, page.raw_count) == ([], False, False, 0)


def test_empty_smartrecruiters_page_requires_proven_zero_total(monkeypatch):
    transport(monkeypatch, {"content": [], "totalFound": 0})
    page = sources.retrieve_page(board("smartrecruiters"))
    assert (page.jobs, page.complete, page.authoritative, page.raw_count) == ([], True, False, 0)


def test_interrupted_pagination_keeps_checkpoint_reusable(monkeypatch):
    calls = transport(monkeypatch,
        {"content": [posting("smartrecruiters")], "totalFound": 2},
        sources.SourceError("network_error", "Connection failed"),
        {"content": [posting("smartrecruiters", 2)], "totalFound": 2})
    first = sources.retrieve_page(board("smartrecruiters"))
    with pytest.raises(sources.SourceError):
        sources.retrieve_page(board("smartrecruiters"), cursor=first.next_cursor)
    last = sources.retrieve_page(board("smartrecruiters"), cursor=first.next_cursor)
    assert first.next_cursor == {"offset": 1, "total": 2}
    assert last.complete and [job.source_id for job in last.jobs] == ["2"]
    assert len(calls) == 3


def test_naive_clock_is_rejected_before_fetch(monkeypatch):
    calls = transport(monkeypatch)
    with pytest.raises(ValueError, match="timezone"):
        sources.retrieve_page(board("greenhouse"), now=datetime(2026, 10, 29))
    assert calls == []


def test_smartrecruiters_cursor_rejects_excessive_integer_range_before_fetch(monkeypatch):
    calls = transport(monkeypatch, {"content": [posting("smartrecruiters")], "totalFound": 1_000_001})
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"), cursor={"offset": 1, "total": 1_000_001})
    assert error.value.code == "invalid_cursor"
    assert calls == []


def test_smartrecruiters_total_is_bounded(monkeypatch):
    transport(monkeypatch, {"content": [posting("smartrecruiters")], "totalFound": 1_000_001})
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"))
    assert error.value.code == "invalid_payload"


@pytest.mark.parametrize("offset", [0, True, 1.0, "1"])
def test_smartrecruiters_echoed_offset_must_match_requested_integer(monkeypatch, offset):
    transport(monkeypatch, {"content": [posting("smartrecruiters")], "totalFound": 2, "offset": offset})
    with pytest.raises(sources.SourceError) as error:
        sources.retrieve_page(board("smartrecruiters"), cursor={"offset": 1, "total": 2})
    assert error.value.code == "invalid_payload"
