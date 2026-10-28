# Portfolio presentation notes

## The problem

Internship opportunities are scattered across different ATS providers and career portals. Keeping them deduplicated, relevant, and organized while preparing accurate applications requires more than scraping links.

## The engineering contribution

Internship Agent provides a modular Python pipeline with normalized provider adapters, explainable fit scoring, SQLite persistence and application state guards, user-verified DOCX drafting, optional Google Workspace reconciliation, and an MCP tool interface. It is intentionally designed not to automate risky submissions without confirmation.

## Demonstration and interview talking points

1. **Architecture:** why adapter boundaries and a local authoritative ledger are preferable to a single fragile browser scraper.
2. **Data integrity:** canonical URL duplicates, distinct requisition IDs, update idempotency and state transitions.
3. **Security:** external-job prompt injection, risky RSS redirect targets, local OAuth credential protection, untrusted feeds and user approval.
4. **Testability:** realistic fictional fixtures, mocked Google interactions and a fully offline end-to-end demonstration.
5. **Limitations:** heuristic fit score, incomplete eligibility fields, external API drift, and current lack of live OAuth/MCP validation.

## Resume description (use only after validating the claimed functionality)

**Internship Agent — Python, SQLite, MCP, REST APIs, Google Workspace**

- Built a modular internship discovery pipeline with provider-specific readers, normalized job records, canonical-URL deduplication and persistent SQLite state.
- Implemented an explainable role-fit scoring engine and generated draft, single-column DOCX application documents using profile-verified qualifications.
- Developed guarded application-status workflows, optional Google Sheets reconciliation, synthetic integration fixtures and automated regression tests.

Do **not** advertise fully automated submissions, production deployment, guaranteed ATS success, or live integrations until those capabilities are actually demonstrated.

## Stronger next milestone

Demonstrate a real source's read-only API retrieval (with permission), plus a live dry-run and confirmed sync against a separate test Google Sheet. Capture sanitized logs and a short screen recording. Those constitute substantially stronger portfolio evidence than additional mocked adapters alone.
