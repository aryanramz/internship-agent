# ATS replay fixtures

`greenhouse_jobs.json` is a synthetic, sanitized reconstruction of the public
Greenhouse list response shape observed on 2026-10-28. IDs, titles, company,
locations, URLs, descriptions and dates are fictional. There are no copied
employer descriptions, application questions, private metadata or applicant data.
The example.com URLs are never fetched.

The fixture retains the observed `jobs` / `meta` envelope, numeric posting IDs,
location objects, entity-encoded HTML, `first_published`, `updated_at`, and optional
`application_deadline`. Optional departments/offices demonstrate the public schema;
irrelevant provider fields are omitted. The second record exercises missing
optional fields and already-decoded HTML. Tests derive malformed and expired cases
in memory; those are constructed cases, not claims about the live board.

HTTP 404 was observed live for a nonexistent board and posting. Redirects, 410,
429, 503, malformed data and transport failures are synthetic HTTP replays using
the real urllib status/redirect handlers. Normal CI never contacts ATS services.
