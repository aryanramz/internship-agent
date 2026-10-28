# Offline demonstration

This demo requires no Google account, API key, job website, ChatGPT connection, or internet access. All companies, roles, links and personal details are fictional.

## Run

```powershell
.\scripts\setup-windows.ps1
.\.venv\Scripts\Activate.ps1
python scripts/demo.py
```

Files appear in ignored `demo-output/`, including `agent.db`, `demo_summary.json`, and a generated DOCX resume and cover-letter draft under `generated/<job_id>/`.

## What to show on a portfolio video

1. Explain the example `examples/demo_jobs.json` and synthetic profile: these represent untrusted leads and verified demo facts respectively.
2. Execute the demo and show the three ranked jobs with breakdowns: the senior position should be flagged as unsuitable.
3. Open the generated DOCX resume; verify only skills present in the demo profile appear.
4. Inspect the database/application status: it stops at `prepared`, not `submitted`.
5. Run `python -m pytest -q`, then explain how mocked tests protect the state-machine and Sheets conflict logic.

## Honest demonstration boundaries

These scores are derived from an example profile and synthetic descriptions. They are not measured recommendation quality, an ATS success rate, or evidence of live platform integration. A production deployment needs actual provider validation and approved OAuth authorization.
