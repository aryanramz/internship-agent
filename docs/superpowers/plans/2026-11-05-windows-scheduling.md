# Windows unattended scheduling implementation plan

Goal: implement Issue #15's kickoff contract from develop 09ba1e3 without installing native tasks or enabling integrations.

Architecture/design: Windows current-user InteractiveToken/LeastPrivilege task invokes the configured Python executable directly. A five-minute recurring trigger and logon trigger wake a short-lived runner. Python selects only the latest local daily window within 24 hours, with a stable local date identity across DST. SQLite keeps durable bounded attempt history separately from agent.db; OS file locking, held by the actual worker, fences concurrent/orphaned workers without stealing locks based on time or PID. A supervisor cancels only its child; an independent worker watchdog bounds orphan lifetime. Existing discovery recovery/cooldowns remain authoritative.

Alternatives: a resident service needs more lifecycle machinery and privileges; Task Scheduler alone cannot identify duplicate windows or preserve provider retry restrictions. Use Task Scheduler plus the local journal. Implementation choices follow the detailed kickoff, with inline implementation and independent correctness/security reviewers before delivery.

Defaults: local 09:00, 24-hour catch-up, three attempts/window, 60-second exponential backoff plus up to 30 seconds jitter, five-minute wake, 30-minute attempt timeout, battery allowed, no wake-from-sleep or network requirement. Notification failure never retries work. Reports contain status/counts only; retention 30 windows. No Google or document generation on unattended path. Setup always previews and requires exact approval; no native task changes in this development session.

Global constraints: Python 3.11–3.13; core only supported; no version/schema change to agent.db, MCP change, Issue #16, real applicant data, integrations, merge or native installation here.

Review focus: orphan worker overlap; stale/corrupt journal; DST/clock rollback; task identity/action drift; error payload privacy.

- [x] Task 1: write failing scheduler tests (window, retry, partial/cooldown, OS lock, crash recovery, cancellation, retention/privacy), implement scheduler journal and worker/supervisor, verify targeted tests.
- [x] Task 2: write failing native definition/control tests; implement task XML, strict ownership checks and reviewed current-user COM adapter, CLI and double-click launchers; verify tests without task installation.
- [x] Task 3: make daily integrations explicit opt-in, document operator/recovery/native qualification procedure, preserve CI and extend core CI scheduler coverage.
- [ ] Task 4: run targeted/full Linux tests, hygiene/compile/pip/demo; independent correctness and security reviews with regression fixes; open unmerged PR to develop, collect exact Linux/Windows/security CI results and disclose native qualification limits.

Progress: tasks 1–3 complete with synthetic tests; independent reviews and regression fixes complete. Local full suite 1108 passed / 8 skipped / 22 subtests. Task 4 delivery/CI tracked in the PR; native lifecycle gate stays open. See docs/SCHEDULER_VALIDATION.md.
