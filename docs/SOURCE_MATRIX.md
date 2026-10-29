# Job source coverage and qualification

"Reader" means normalizing postings into the local job database. It does **not** imply authorization to apply, authenticated access, or an assurance that all postings are returned.

Baseline: merged develop at `3a79f555617453fc68dd51d36a9d1e51eabd2dcc`.
Only Greenhouse has the recorded live board qualification. Other listed readers
are implemented with local/synthetic coverage, not individually live-qualified.
Existing `add-source`/`suggest-sources` are board registration/detection, not a
complete employer registry or general web crawler. [Issue #9](https://github.com/aryanramz/internship-agent/issues/9)
extends qualification to Greenhouse/Lever/Ashby and a compatible registry;
[Issue #10](https://github.com/aryanramz/internship-agent/issues/10) adds health,
incremental scans and posting lifecycle. See [capability evidence](CAPABILITIES.md).

## Implemented readers — 18 source types

| Type | Reader | Inputs | Current limitations |
|---|---|---|---|
| Company ATS | Greenhouse | Company board slug | [Live validated](LIVE_ATS_VALIDATION.md) on one public board; other/legacy boards may differ |
| Company ATS | Lever | Company slug | Public JSON postings |
| Company ATS | Ashby | Company slug | Public job-board endpoint |
| Company ATS | SmartRecruiters | Company identifier | Public Posting API; first 500 posts; list details may be sparse |
| Company ATS | Workable | Account slug | Public widget endpoint; one record per shortcode; rate limits |
| Company ATS | Breezy HR | Subdomain | Public board JSON; descriptions not included in index |
| Company ATS | Personio | Subdomain, de/com domain | Public XML must be enabled by employer |
| Company ATS | Pinpoint | Subdomain | Documented public postings.json |
| Company ATS | BambooHR | Subdomain | Public careers/list; titles/locations, no full description by default |
| Company ATS | Teamtailor | Subdomain | Public jobs.rss feed; custom branded sites use RSS reader |
| Company ATS | Workday | myworkdayjobs hostname, tenant, site | Uses public career-site search, limited pages and text; some tenants disallow access |
| Federal | USAJOBS | `USAJOBS_API_KEY`, `USAJOBS_EMAIL` env vars | Official Search API; requires registration |
| Internship community list | SimplifyJobs/Pitt CSC Summer 2027 | None | Public community listings, not a general cybersecurity index; freshness and completeness vary |
| Remote jobs | Remotive | None | Public API; jobs delayed; **must credit/link to Remotive** |
| Remote jobs | Jobicy | None | Public API; recent remote roles only |
| RSS / Atom | Any user-trusted public HTTPS feed | Feed URL | May have only title/link; do not configure unknown/untrusted hosts |
| Local import | CSV | Structured local file | User-provided leads, not live or verified |
| Local import | JSON | Structured local file | User-provided leads, not live or verified |

**Public, no-key readers** are not automatically useful without the company's real board slug. The default starter configuration enables only the three global feeds (Simplify, Remotive and Jobicy); employer examples are disabled intentionally. Run `internship-agent add-source <company-career-url> --company <name>` to register a board.

## Broad platforms through approved data/import workflows

The following sites do **not** have direct account scrapers in this project.
Reviewed records can enter through local CLI `import-jobs`, CSV/JSON readers or
reviewed Gmail leads. The backend `Agent.import_external_jobs` method is internal
to those local workflows; it is **not registered as an MCP tool**:

- Handshake (including school-eligible internship postings, when authorized)
- LinkedIn Jobs
- Indeed
- ZipRecruiter
- Wellfound
- RippleMatch
- WayUp
- College Recruiter
- Parker Dewey
- Built In
- Dice
- Y Combinator Work at a Startup
- Simplify's own platform (separate from its public GitHub community list)
- Welcome to the Jungle / Otta
- Levels.fyi jobs
- Internships.com and other internship aggregators, subject to their current availability and terms

For services where authorized alerts/exports are available, review their metadata
and save structured records privately, then use `internship-agent import-jobs FILE`
or the `csv_import`/`json_import` readers. A connected Gmail/job-search tool may
assist review under its own permissions, but cannot call a nonexistent MCP import
tool. This path does not read a protected account directly or grant access to
school-exclusive Handshake postings. Local Gmail staging is implemented but live-unqualified.

Handshake documents job alert emails; LinkedIn documents saved-search emails. LinkedIn prohibits third-party site scraping and unauthorized automation. Indeed restricts bot and scraper access absent express permission. Do **not** try to bypass authentication, challenges, request-rate controls, or school authorization.

## Import file format

For a CSV import, include at least `platform,company,title,job_url` columns. Also supported: `location,description,apply_url,compensation,published_at,work_mode,id`.

```csv
platform,company,title,location,job_url,description
handshake,Example Employer,Cybersecurity Intern,"New York, NY",https://app.joinhandshake.com/stu/jobs/12345,Security operations
linkedin,Example Employer,Cloud Intern,"New York, NY",https://www.linkedin.com/jobs/view/12345,Cloud operations
indeed,Example Employer,IT Intern,"Melville, NY",https://www.indeed.com/viewjob?jk=example,IT support
```

The URLs above are illustrative placeholders. **Never interpret an imported record as a verified current opening** until the employer's job listing is checked. A detailed ATS description may be missing from these alerts; the resume generator should not infer missing requirements.

For a JSON import:

```json
[
  {"platform":"ripplematch","company":"Example","title":"Security Intern","location":"New York","job_url":"https://example.com/jobs/100"}
]
```

The JSON array can be passed to the local `import-jobs` command after review.
Current MCP exposes only `application_summary`, `rank_jobs` and
`preview_application`; discovery/import/write tools remain deliberately absent.
Connector availability is account-specific and does not authenticate the local
backend. Imported leads retain uncertainty until the employer posting is checked.

## Sources and API documentation

- Greenhouse: https://developers.greenhouse.io/job-board.html
- Lever: https://github.com/lever/postings-api
- Ashby: https://developers.ashbyhq.com/docs/public-job-posting-api
- SmartRecruiters: https://developers.smartrecruiters.com/docs/posting-api
- Workable: https://help.workable.com/hc/en-us/articles/115012070587-Using-the-Workable-API-to-create-a-careers-page
- Personio: https://support.personio.de/hc/en-us/articles/207576365-Integrate-jobs-from-Personio-into-your-website-via-XML
- Pinpoint: https://developers.pinpointhq.com/docs/jobs-json-endpoint
- Teamtailor RSS: https://support.teamtailor.com/en/articles/11171756-rss-feed-how-to-guide
- USAJOBS: https://developer.usajobs.gov/api-reference/get-api-search
- Jobicy: https://github.com/Jobicy/remote-jobs-api
- Remotive: https://remotive.com/remote-jobs/api
- Simplify GitHub community list: https://github.com/SimplifyJobs/Summer2027-Internships
- Handshake job alerts: https://support.joinhandshake.com/hc/en-us/articles/218693388-Saving-Job-Searches-and-Receiving-Job-Alerts
- LinkedIn prohibited software: https://www.linkedin.com/help/linkedin/answer/a1341387/
- Indeed ToS: https://www.indeed.com/legal
