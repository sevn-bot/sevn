"""Offline tests for the bundled ``job-ops`` skill (no live network)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sevn.skills.manifest import parse_skill_markdown, validate_script_paths

_SKILL_ROOT = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sevn"
    / "data"
    / "bundled_skills"
    / "core"
    / "job-ops"
)
_SCRIPTS_DIR = _SKILL_ROOT / "scripts"

# Bundled skill scripts import their sibling ``lib`` package with ``scripts/`` on
# ``sys.path`` (the runner sets ``sys.path[0]`` to the script directory).
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import cover_letter  # noqa: E402
import interview_prep  # noqa: E402
import list_jobs  # noqa: E402
import review  # noqa: E402
import score  # noqa: E402
import track  # noqa: E402
from lib import text  # noqa: E402
from lib.extractors import (  # noqa: E402
    adzuna,
    browser_board,
    golangjobs,
    himalayas,
    jobindex,
    jobnet,
    jobspy_source,
    registry,
    remoteco,
    remoteok,
    remotive,
    workingnomads,
)
from lib.extractors.base import ExtractorResult  # noqa: E402
from lib.llm import LlmUnavailable, _extract_json, _extract_text, complete_json  # noqa: E402
from lib.models import (  # noqa: E402
    TRACKING_STATUSES,
    JobPosting,
    Resume,
    ResumeReview,
    ScoreResult,
    SearchQuery,
)
from lib.store import JobStore  # noqa: E402

_EXPECTED_SOURCES = {
    "jobspy",
    "adzuna",
    "hiringcafe",
    "workingnomads",
    "golangjobs",
    "startupjobs",
    "jobindex",
    "gradcracker",
    "ukvisajobs",
    "remoteok",
    "remotive",
    "himalayas",
    "remoteco",
    "jobnet",
}
_DROPPED_SOURCES = {"seek", "naukri", "wazzuf", "fiveamsat"}


def test_manifest_parses_and_scripts_exist() -> None:
    text_md = (_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    manifest = parse_skill_markdown(text_md, "core")
    assert manifest.name == "job-ops"
    assert {s.path for s in manifest.scripts} == {
        "scripts/search.py",
        "scripts/score.py",
        "scripts/review.py",
        "scripts/tailor.py",
        "scripts/cover_letter.py",
        "scripts/interview_prep.py",
        "scripts/track.py",
        "scripts/list_jobs.py",
        "scripts/set_resume.py",
    }
    validate_script_paths(_SKILL_ROOT, manifest)


def test_registry_scope_is_global_plus_europe() -> None:
    sources = set(registry.available_sources())
    assert sources == _EXPECTED_SOURCES
    assert sources.isdisjoint(_DROPPED_SOURCES)


def test_job_posting_roundtrip_and_dedupe_key() -> None:
    job = JobPosting(
        source="adzuna", source_job_id="42", title="Dev", employer="Acme", job_url="https://x/y"
    )
    restored = JobPosting.model_validate_json(job.model_dump_json())
    assert restored == job
    # dedupe key is stable and id-based when source_job_id present
    assert job.dedupe_key() == restored.dedupe_key()
    other = JobPosting(
        source="adzuna", source_job_id="42", title="Dev2", employer="Acme", job_url="https://x/z"
    )
    assert job.dedupe_key() == other.dedupe_key()


def test_store_dedupes_and_preserves_enrichment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEVN_CONTENT_ROOT", str(tmp_path))
    store = JobStore(tmp_path)
    job = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    added, updated = store.upsert_many([job, job])
    assert (added, updated) == (1, 1)
    # add enrichment then re-upsert a bare copy; enrichment survives
    scored = store.load()[0]
    scored.suitability_score = 88
    scored.suitability_reason = "great"
    store.update(scored)
    bare = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    store.upsert_many([bare])
    final = store.load()
    assert len(final) == 1
    assert final[0].suitability_score == 88


def test_adzuna_map() -> None:
    row = {
        "id": 7,
        "title": "Backend Engineer",
        "redirect_url": "https://adzuna/redir/7",
        "company": {"display_name": "Globex"},
        "location": {"display_name": "London, UK"},
        "salary_min": 50000,
        "salary_max": 70000,
        "created": "2026-06-01T00:00:00Z",
        "contract_type": "permanent",
        "contract_time": "full_time",
    }
    job = adzuna._map(row)
    assert job is not None
    assert job.source == "adzuna"
    assert job.source_job_id == "7"
    assert job.employer == "Globex"
    assert job.salary == "50000-70000"
    assert job.job_type == "permanent / full_time"


def test_workingnomads_map_is_remote() -> None:
    job = workingnomads._map(
        {
            "id": 9,
            "slug": "cool-job",
            "title": "SRE",
            "company": "Initech",
            "tags": ["python", "aws"],
        }
    )
    assert job is not None
    assert job.job_url == "https://www.workingnomads.com/jobs/cool-job"
    assert job.is_remote is True
    assert job.skills == "python, aws"


def test_golangjobs_map() -> None:
    job = golangjobs._map(
        {
            "id": "abc",
            "slug": "go-dev",
            "title": "Go Dev",
            "company": "Hooli",
            "cities": {"name": "Remote", "country": "Germany"},
            "requirements": ["Go", "gRPC"],
        }
    )
    assert job is not None
    assert job.job_url.endswith("/go-dev")
    assert job.location == "Remote (Germany)"
    assert job.is_remote is True


def test_jobindex_store_data_extraction() -> None:
    html = (
        "<html><body><script>var Stash = {"
        '"jobsearch/result_app": {"storeData": {"searchResponse": {"total_pages": 1, "results": ['
        '{"tid": "t1", "headline": "DK Dev", "share_url": "/job/1", "companytext": "Novo", '
        '"firstdate": "2026-06-01", "html": "<p>Great role</p>"}'
        "]}}}};</script></body></html>"
    )
    store_data = jobindex._extract_store_data(html)
    results = store_data["searchResponse"]["results"]
    job = jobindex._map(results[0])
    assert job is not None
    assert job.source == "jobindex"
    assert job.title == "DK Dev"
    assert job.job_url == "https://www.jobindex.dk/job/1"
    assert job.job_description == "Great role"


def test_remoteok_map() -> None:
    job = remoteok._map(
        {
            "id": "1134472",
            "position": "Backend Engineer",
            "company": "Recruitlytics",
            "url": "https://remoteOK.com/remote-jobs/1134472",
            "apply_url": "https://remoteOK.com/apply/1134472",
            "location": "Worldwide",
            "salary_min": 90000,
            "salary_max": 120000,
            "date": "2026-07-04T08:21:16+00:00",
            "description": "<p>Great <b>role</b></p>",
            "tags": ["python", "django"],
        }
    )
    assert job is not None
    assert job.source == "remoteok"
    assert job.source_job_id == "1134472"
    assert job.salary == "90000-120000"
    assert job.is_remote is True
    assert job.job_description == "Great role"
    assert job.skills == "python, django"


def test_remotive_map() -> None:
    job = remotive._map(
        {
            "id": 1749306,
            "url": "https://remotive.com/remote-jobs/writing/copywriter-1749306",
            "title": "Copywriter",
            "company_name": "Coalition Technologies",
            "category": "Writing",
            "tags": ["seo", "content"],
            "job_type": "freelance",
            "publication_date": "2026-07-02T20:01:13",
            "candidate_required_location": "Worldwide",
            "salary": "$20k -$35k",
            "description": "<p>Write copy</p>",
        }
    )
    assert job is not None
    assert job.source == "remotive"
    assert job.source_job_id == "1749306"
    assert job.location == "Worldwide"
    assert job.job_type == "freelance"
    assert job.is_remote is True


def test_himalayas_map() -> None:
    job = himalayas._map(
        {
            "title": "Senior IT Project Manager",
            "companyName": "Fusion Consulting",
            "applicationLink": "https://himalayas.app/companies/fusion-consulting/jobs/senior-it-pm",
            "guid": "https://himalayas.app/companies/fusion-consulting/jobs/senior-it-pm",
            "employmentType": "Full Time",
            "minSalary": 80000,
            "maxSalary": 100000,
            "currency": "USD",
            "salaryPeriod": "annual",
            "locationRestrictions": ["Portugal"],
            "categories": ["IT-Project-Management"],
            "pubDate": 1783245659,
            "description": "<p>Lead projects</p>",
        }
    )
    assert job is not None
    assert job.source == "himalayas"
    assert job.job_url.endswith("/senior-it-pm")
    assert job.location == "Portugal"
    assert job.salary == "USD 80000-100000 / annual"
    assert job.date_posted is not None
    assert job.is_remote is True


def test_remoteco_build_urls_slugifies() -> None:
    urls = remoteco._build_urls(SearchQuery(search_terms=["Software Engineer", "python"]))
    assert urls == [
        "https://remote.co/remote-jobs/software-engineer",
        "https://remote.co/remote-jobs/python",
    ]


def test_jobspy_normalize_records() -> None:
    records = [
        {
            "site": "linkedin",
            "id": "li-1",
            "title": "ML Engineer",
            "company": "OpenAcme",
            "job_url": "https://linkedin/jobs/1",
            "location": "Berlin, Germany",
            "min_amount": 60000.0,
            "max_amount": 90000.0,
            "currency": "EUR",
            "is_remote": True,
        },
        {"site": "indeed", "job_url": None},  # dropped: no url
    ]
    jobs = jobspy_source.normalize_jobspy_records(records)
    assert len(jobs) == 1
    assert jobs[0].source == "linkedin"
    assert jobs[0].salary_max_amount == 90000.0
    assert jobs[0].is_remote is True


def test_browser_board_parse_listing() -> None:
    pytest.importorskip("selectolax")
    html = (
        '<html><body><a href="/12345-senior-dev-acme">Senior Dev at Acme</a>'
        '<a href="/about">About</a>'
        '<a href="/67890-backend-hooli">Backend at Hooli</a></body></html>'
    )
    jobs = browser_board.parse_listing(
        html, source="startupjobs", origin="https://startup.jobs", href_pattern=r"/\d+-"
    )
    assert {j.title for j in jobs} == {"Senior Dev at Acme", "Backend at Hooli"}
    assert all(j.job_url.startswith("https://startup.jobs/") for j in jobs)


def test_text_helpers() -> None:
    assert text.matches_search_term("Senior Python Engineer", "python engineer") is True
    assert text.matches_search_term("Frontend React role", "golang") is False
    assert text.looks_like_challenge("<html>cf-browser-verification</html>") is True
    assert text.strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_prepare_text_strips_html_and_truncates() -> None:
    assert text.prepare_text(None, 100) == ""
    assert text.prepare_text("<p>Hello   <b>world</b></p>", 100) == "Hello world"
    assert text.prepare_text("abcdefghij", 4) == "abcd"


def test_score_result_from_payload_full_and_junk() -> None:
    result = score._result_from_payload(
        {
            "score": 150,  # clamped to 100
            "recommendation": "strong_fit",
            "reason": "Excellent match.",
            "matched_keywords": ["python", " aws ", "", 7],
            "missing_keywords": "kubernetes",
            "tailoring_tips": ["Lead with metrics"],
            "dealbreakers": [],
            "legitimacy": "high_confidence",
            "legitimacy_notes": "Named team + stack.",
        }
    )
    assert isinstance(result, ScoreResult)
    assert result.score == 100
    assert result.recommendation == "strong_fit"
    assert result.matched_keywords == ["python", "aws", "7"]
    assert result.missing_keywords == ["kubernetes"]
    assert result.legitimacy == "high_confidence"

    junk = score._result_from_payload({"score": "not-a-number"})
    assert junk.score == 0


def test_score_prompt_shape() -> None:
    job = JobPosting(
        source="adzuna",
        source_job_id="1",
        title="Backend Engineer",
        employer="Globex",
        job_url="https://x/1",
        job_description="<p>Build <b>APIs</b> in Python</p>",
    )
    prompt = score._prompt(job, Resume(text="Senior Python engineer"))
    assert "JSON object" in prompt
    assert "legitimacy" in prompt
    assert "Backend Engineer" in prompt
    assert "Build APIs in Python" in prompt  # HTML stripped by prepare_text


def test_review_from_payload_and_prompt() -> None:
    review_result = review._review_from_payload(
        {
            "overall_score": -5,  # clamped to 0
            "summary": "Solid but generic.",
            "strengths": ["Clear structure"],
            "weaknesses": ["Vague metrics"],
            "suggestions": ["Quantify impact"],
            "missing_keywords": ["terraform"],
        }
    )
    assert isinstance(review_result, ResumeReview)
    assert review_result.overall_score == 0
    assert review_result.suggestions == ["Quantify impact"]

    prompt = review._prompt(Resume(text="<p>My resume</p>"), "python engineer")
    assert "JSON object" in prompt
    assert "TARGET ROLE" in prompt
    assert "My resume" in prompt


def test_store_preserves_scoring_enrichment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEVN_CONTENT_ROOT", str(tmp_path))
    store = JobStore(tmp_path)
    job = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    store.upsert_many([job])
    scored = store.load()[0]
    scored.suitability_score = 72
    scored.suitability_recommendation = "good_fit"
    scored.matched_keywords = ["python"]
    scored.legitimacy = "proceed_with_caution"
    store.update(scored)
    bare = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    store.upsert_many([bare])
    final = store.load()[0]
    assert final.suitability_recommendation == "good_fit"
    assert final.matched_keywords == ["python"]
    assert final.legitimacy == "proceed_with_caution"


def test_llm_extract_helpers() -> None:
    chat = {"choices": [{"message": {"content": '{"score": 80, "reason": "ok"}'}}]}
    assert _extract_text(chat).strip().startswith("{")
    anthropic = {"content": [{"text": "prefix "}, {"text": '{"score": 5}'}]}
    assert _extract_json(_extract_text(anthropic)) == {"score": 5}


def test_llm_unavailable_without_proxy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("SEVN_PROXY_URL", raising=False)

    class _FakeSettings:
        proxy_url = ""

    monkeypatch.setattr("sevn.config.settings.ProcessSettings", _FakeSettings)
    with pytest.raises(LlmUnavailable):
        complete_json("score this", content_root=tmp_path)


def test_extractor_result_challenge_shape() -> None:
    result = ExtractorResult(
        source="gradcracker", success=False, challenge_required="https://x/challenge"
    )
    assert result.challenge_required == "https://x/challenge"
    assert result.jobs == []


def test_search_query_defaults() -> None:
    q = SearchQuery(search_terms=["dev"])
    assert q.results_wanted == 50
    assert q.workplace_types == []


def test_track_apply_updates_and_appends() -> None:
    import argparse

    job = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    args = argparse.Namespace(
        seen=False,
        unseen=False,
        status="applied",
        applied=True,
        applied_date="2026-07-05",
        due_date="2026-07-20",
        salary_range="60k-80k",
        note="referred by X",
        tag="priority",
        interview="phone screen 2026-07-10",
    )
    track._apply_updates(job, args)
    assert job.status == "applied"
    assert job.applied is True
    assert job.applied_date == "2026-07-05"
    assert job.due_date == "2026-07-20"
    assert job.salary_range == "60k-80k"
    assert job.notes == ["referred by X"]
    assert job.tags == ["priority"]
    assert job.interviews == ["phone screen 2026-07-10"]
    # appends are de-duplicated
    track._apply_updates(job, args)
    assert job.notes == ["referred by X"]
    assert set(TRACKING_STATUSES) >= {"applied", "interviewing", "offer"}


def test_store_get_and_tracking_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_CONTENT_ROOT", str(tmp_path))
    store = JobStore(tmp_path)
    job = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    store.upsert_many([job])
    key = job.dedupe_key()
    fetched = store.get(key)
    assert fetched is not None
    fetched.status = "interviewing"
    fetched.notes = ["call scheduled"]
    store.update(fetched)
    # re-discovery of a bare copy preserves tracking fields
    bare = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    store.upsert_many([bare])
    final = store.get(key)
    assert final is not None
    assert final.status == "interviewing"
    assert final.notes == ["call scheduled"]


def test_list_jobs_status_filter() -> None:
    applied = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    applied.status = "applied"
    other = JobPosting(
        source="adzuna", source_job_id="2", title="B", employer="E", job_url="https://a/2"
    )
    assert (
        list_jobs._matches(
            applied, source="", status="applied", min_score=None, unscored=False, new_only=False
        )
        is True
    )
    assert (
        list_jobs._matches(
            other, source="", status="applied", min_score=None, unscored=False, new_only=False
        )
        is False
    )


def test_cover_letter_prompt_and_payload() -> None:
    job = JobPosting(
        source="adzuna",
        source_job_id="1",
        title="Backend Engineer",
        employer="Globex",
        job_url="https://x/1",
        job_description="<p>Python APIs</p>",
    )
    prompt = cover_letter._prompt(job, Resume(text="Senior Python engineer"), "professional")
    assert "JSON object" in prompt
    assert "cover_letter" in prompt
    assert "Python APIs" in prompt  # HTML stripped
    assert cover_letter._text_from_payload({"cover_letter": " Dear team "}, "cover_letter") == (
        "Dear team"
    )
    assert cover_letter._text_from_payload({"cover_letter": 5}, "cover_letter") == ""


def test_interview_prep_prompt_and_payload() -> None:
    job = JobPosting(
        source="adzuna",
        source_job_id="1",
        title="Backend Engineer",
        employer="Globex",
        job_url="https://x/1",
        job_description="<p>Python APIs</p>",
    )
    prompt = interview_prep._prompt(job, Resume(text="Senior Python engineer"))
    assert "JSON object" in prompt
    assert "STAR" in prompt
    assert "interview_prep" in prompt
    assert interview_prep._text_from_payload({"interview_prep": "notes"}, "interview_prep") == (
        "notes"
    )


def test_jobnet_build_urls_country_gate() -> None:
    assert jobnet._build_urls(SearchQuery(search_terms=["dev"], country="united kingdom")) == []
    urls = jobnet._build_urls(SearchQuery(search_terms=["python developer"], country="denmark"))
    assert urls == ["https://job.jobnet.dk/CV/FindWork/Search?SearchString=python+developer"]


def test_jobnet_login_wall_detection() -> None:
    assert jobnet._LOGIN_WALL.search("<title>STAR Login</title>") is not None
    assert jobnet._LOGIN_WALL.search("<html>normal results</html>") is None


def test_source_matches_jobspy_fans_out() -> None:
    assert registry.source_matches("linkedin", "jobspy") is True
    assert registry.source_matches("indeed", "jobspy") is True
    assert registry.source_matches("glassdoor", "jobspy") is True
    assert registry.source_matches("linkedin", "linkedin") is True
    assert registry.source_matches("adzuna", "jobspy") is False
    assert registry.source_matches("adzuna", "") is True
    # list_jobs filter: a jobspy-sourced (linkedin) posting matches --source jobspy
    li = JobPosting(
        source="linkedin", source_job_id="1", title="X", employer="E", job_url="https://l/1"
    )
    assert (
        list_jobs._matches(
            li, source="jobspy", status="", min_score=None, unscored=False, new_only=False
        )
        is True
    )


def test_upsert_merges_prior_listing_fields_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEVN_CONTENT_ROOT", str(tmp_path))
    store = JobStore(tmp_path)
    full = JobPosting(
        source="adzuna",
        source_job_id="1",
        title="A",
        employer="E",
        job_url="https://a/1",
        job_description="Detailed JD",
        salary="50k",
    )
    store.upsert_many([full])
    # a leaner re-scrape omits the description; populated incoming fields still win
    bare = JobPosting(
        source="adzuna", source_job_id="1", title="A (updated)", employer="E", job_url="https://a/1"
    )
    added, updated = store.upsert_many([bare])
    assert (added, updated) == (0, 1)
    final = store.load()[0]
    assert final.title == "A (updated)"
    assert final.job_description == "Detailed JD"
    assert final.salary == "50k"


def test_upsert_stamps_first_seen_and_preserves_seen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SEVN_CONTENT_ROOT", str(tmp_path))
    store = JobStore(tmp_path)
    job = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    store.upsert_many([job])
    stored = store.load()[0]
    assert stored.first_seen  # stamped on first discovery
    assert stored.seen is None
    first_seen = stored.first_seen
    # mark seen, then re-discover a bare copy: seen + first_seen survive
    store.mark_seen([stored.dedupe_key()])
    store.upsert_many(
        [
            JobPosting(
                source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
            )
        ]
    )
    refreshed = store.load()[0]
    assert refreshed.seen is True
    assert refreshed.first_seen == first_seen


def test_mark_seen_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEVN_CONTENT_ROOT", str(tmp_path))
    store = JobStore(tmp_path)
    a = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    b = JobPosting(
        source="adzuna", source_job_id="2", title="B", employer="E", job_url="https://a/2"
    )
    store.upsert_many([a, b])
    assert store.mark_seen([]) == 0
    assert store.mark_seen([a.dedupe_key()]) == 1
    seen_map = {j.dedupe_key(): j.seen for j in store.load()}
    assert seen_map[a.dedupe_key()] is True
    assert seen_map[b.dedupe_key()] is None
    # clearing works too
    assert store.mark_seen([a.dedupe_key()], seen=False) == 1
    assert store.get(a.dedupe_key()).seen is False


def test_list_jobs_new_only_filter() -> None:
    unseen = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    seen = JobPosting(
        source="adzuna", source_job_id="2", title="B", employer="E", job_url="https://a/2"
    )
    seen.seen = True
    assert (
        list_jobs._matches(
            unseen, source="", status="", min_score=None, unscored=False, new_only=True
        )
        is True
    )
    assert (
        list_jobs._matches(
            seen, source="", status="", min_score=None, unscored=False, new_only=True
        )
        is False
    )


def test_track_seen_unseen() -> None:
    import argparse

    job = JobPosting(
        source="adzuna", source_job_id="1", title="A", employer="E", job_url="https://a/1"
    )
    base = dict(
        status=None,
        applied=False,
        applied_date="",
        due_date="",
        salary_range="",
        note="",
        tag="",
        interview="",
    )
    track._apply_updates(job, argparse.Namespace(seen=True, unseen=False, **base))
    assert job.seen is True
    track._apply_updates(job, argparse.Namespace(seen=False, unseen=True, **base))
    assert job.seen is False
