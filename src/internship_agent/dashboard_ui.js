"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = { csrf: "", view: "overview", page: 1, filters: {}, detail: null, review: null, busy: false, request: 0, overview: null };
  const names = { overview: "Overview", opportunities: "Opportunities", review: "Review & tracking", operations: "Operations" };
  const statuses = ["discovered", "shortlisted", "prepared", "approved", "submitted", "assessment", "interview", "offer", "rejected", "withdrawn"];
  const completed = new Set(["submitted", "assessment", "interview", "offer", "rejected", "withdrawn"]);
  const tracks = ["cloud", "infrastructure", "devops", "security", "software", "systems", "it"];
  let confirmation = null;
  let notificationTimer;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function append(parent, ...children) { children.flat().forEach((child) => { if (child) parent.append(child); }); return parent; }
  function button(text, className, action) {
    const node = el("button", className || "button secondary", text);
    node.type = "button";
    if (action) node.addEventListener("click", action);
    return node;
  }
  function titleCase(value) { return String(value || "Unknown").replace(/[_-]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()); }
  function date(value) {
    if (!value) return "Not recorded";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "Date unavailable" : parsed.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }
  function list(value) { return Array.isArray(value) ? value : []; }
  function asText(value) {
    if (typeof value === "string" || typeof value === "number") return String(value);
    if (value && typeof value === "object") return value.message || value.note || value.reason || value.evidence || value.description || value.rule || value.label || value.status || "Details require manual review";
    return "Not available";
  }
  function notify(message, error = false) {
    const node = $("notification");
    node.textContent = message;
    node.className = `notification${error ? " error" : ""}`;
    node.hidden = false;
    clearTimeout(notificationTimer);
    notificationTimer = setTimeout(() => { node.hidden = true; }, error ? 10000 : 6500);
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
    const json = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401 && path !== "/login") showLogin();
      throw new Error(typeof json.error === "string" ? json.error : "The request could not be completed. Please try again.");
    }
    return json;
  }
  async function csrf() {
    const session = await api("/api/session");
    state.csrf = session.csrf;
    if (!state.csrf) throw new Error("The local session has expired. Unlock the workspace again.");
    return state.csrf;
  }
  function showLogin() {
    $("workspace").hidden = true;
    $("login").hidden = false;
    if ($("detail-dialog").open) $("detail-dialog").close();
    if ($("confirm-dialog").open) $("confirm-dialog").close();
    $("secret").focus();
  }
  function showWorkspace() {
    $("login").hidden = true;
    $("workspace").hidden = false;
    renderView();
  }
  function loading(parent) {
    const status = el("div", "loading");
    status.setAttribute("role", "status");
    append(status, el("span", "spinner"), el("span", "", "Loading your workspace…"));
    parent.replaceChildren(status);
  }
  function empty(title, text, action) {
    const node = el("div", "empty-state");
    append(node, el("div", "empty-icon", "◇"), el("h3", "", title), el("p", "", text));
    if (action) node.append(action);
    return node;
  }
  function heading(title, subtitle, action) {
    const node = el("div", "page-heading");
    append(node, append(el("div"), el("h1", "", title), el("p", "muted", subtitle)));
    if (action) node.append(action);
    return node;
  }
  function badge(value, type) {
    const normalized = String(value || "unknown").toLowerCase();
    const kind = type || (["uncertain", "unknown", "partial", "prepared", "review_required"].includes(normalized) ? "warning" : ["ineligible", "not_qualified", "not qualified", "failed", "rejected"].includes(normalized) ? "danger" : ["eligible", "approved", "offer", "healthy", "complete", "committed"].includes(normalized) ? "good" : "neutral");
    return el("span", `badge ${kind}`, titleCase(value));
  }
  function eligibility(job) { return job.eligibility?.outcome || "unknown"; }
  function jobRow(job) {
    const row = el("div", "job-row");
    const icon = el("div", "company-icon", String(job.company || "?").slice(0, 2).toUpperCase());
    icon.setAttribute("aria-hidden", "true");
    const info = el("div");
    const title = button(job.title || "Untitled opportunity", "job-title", () => openJob(job.id || job.job_id));
    title.setAttribute("aria-label", `Review ${job.title || "opportunity"} at ${job.company || "unknown employer"}`);
    const meta = append(el("div", "job-meta"), el("span", "company", job.company || "Unknown employer"), el("span", "", job.location || "Location not specified"));
    if (job.work_mode && job.work_mode !== "Unknown") meta.append(el("span", "", job.work_mode));
    append(info, title, meta);
    const side = el("div", "job-side");
    const score = job.ranking?.score ?? job.score;
    if (typeof score === "number") {
      const scoreLabel = append(el("span", "score"), el("span", "", Math.round(score)), el("small", "", "FIT"));
      scoreLabel.setAttribute("aria-label", `Heuristic fit score ${Math.round(score)}. Not eligibility or hiring probability.`);
      side.append(scoreLabel);
    }
    side.append(badge(job.status || "discovered"));
    if (["ineligible", "uncertain", "unknown", "not_qualified"].includes(eligibility(job))) side.append(badge(eligibility(job)));
    append(row, icon, info, side);
    return row;
  }
  function panel(title, subtitle, action) {
    const node = el("section", "panel");
    const header = el("div", "panel-header");
    append(header, append(el("div"), el("h2", "", title), el("p", "", subtitle)));
    if (action) header.append(action);
    node.append(header);
    return node;
  }
  function navigate(view) {
    if (location.hash === `#${view}`) renderView();
    else location.hash = view;
  }
  async function renderView() {
    if ($("workspace").hidden) return;
    const view = location.hash.slice(1);
    state.view = Object.hasOwn(names, view) ? view : "overview";
    const current = ++state.request;
    $("breadcrumb-current").textContent = names[state.view];
    document.title = `${names[state.view]} · Internship Agent`;
    document.querySelectorAll("[data-view]").forEach((node) => {
      if (node.dataset.view === state.view) node.setAttribute("aria-current", "page");
      else node.removeAttribute("aria-current");
    });
    const container = $("page-content");
    loading(container);
    try {
      if (state.view === "overview") await renderOverview(container, current);
      else if (state.view === "operations") await renderOperations(container, current);
      else await renderJobs(container, current);
    } catch (error) {
      if (current !== state.request || $("workspace").hidden) return;
      container.replaceChildren(heading(names[state.view], "Your local workspace"), empty("We couldn’t load this view", error.message, button("Try again", "button primary", renderView)));
    }
  }
  async function renderOverview(container, current) {
    const [overview, results, operations] = await Promise.all([api("/api/overview"), api("/api/jobs?page=1"), api("/api/operations")]);
    if (current !== state.request) return;
    state.overview = overview;
    const dateLabel = el("span", "date-label", new Date().toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" }));
    const head = heading("Make room for what’s next.", "A clear view of your search, and a thoughtful next step.", dateLabel);
    const hero = el("section", "hero");
    const heroText = el("div");
    append(heroText, el("p", "eyebrow", "YOUR NEXT CHAPTER"), el("h2", "", "Good opportunities deserve a little focus."), el("p", "", "Explore your matches, review the details, and prepare an application that sounds like you. Every step stays in your hands."), button("Explore opportunities  →", "button primary", () => navigate("opportunities")));
    const art = append(el("div", "hero-art"), append(el("div", "orbit"), el("div", "orbit-leaf")), el("span", "orbit-spark", "✧"));
    art.setAttribute("aria-hidden", "true");
    append(hero, heroText, art);
    const counts = overview.counts || {};
    const stats = el("div", "stats-grid");
    [["Opportunities", overview.total_jobs ?? results.total ?? 0, "In your local workspace", "⌕"], ["Ready for review", overview.awaiting_approval ?? counts.prepared ?? 0, "Prepared, awaiting your approval", "▤"], ["Submitted", overview.submitted ?? counts.submitted ?? 0, "Current status · operator reported", "↗"], ["Interviews", counts.interview ?? overview.outcomes?.interview ?? 0, "Every conversation is progress", "◷"]].forEach(([label, value, note, symbol]) => {
      const card = el("div", "stat-card");
      append(card, append(el("div", "stat-label"), el("span", "", label), el("span", "stat-symbol", symbol)), el("div", "stat-value", value), el("p", "stat-note", note));
      stats.append(card);
    });
    const grid = el("div", "dashboard-grid");
    const opportunities = panel("Opportunities to explore", "Recent local postings. Review fit and eligibility separately.", button("View all  ↗", "text-button", () => navigate("opportunities")));
    const jobs = list(results.jobs).slice(0, 5);
    if (jobs.length) opportunities.append(append(el("div", "job-list"), jobs.map(jobRow)));
    else opportunities.append(empty("Your search starts here", "Run discovery to bring opportunities from your configured sources into this workspace.", button("Discover opportunities", "button primary", confirmDiscovery)));
    if (jobs.length) opportunities.append(append(el("div", "panel-footer"), button("Explore all opportunities  →", "text-button", () => navigate("opportunities"))));
    const side = el("div", "stack");
    const next = append(el("section", "panel insight-card"), el("h3", "", "A good next step"));
    const steps = el("ol", "step-list");
    [["Find your fit", "Explore roles that align with your interests."], ["Make it yours", "Prepare documents from your verified facts."], ["Review, then move", "Approve a revision. Apply outside this workspace."]].forEach(([name, text], i) => steps.append(append(el("li"), el("span", "step-number", i + 1), append(el("div"), el("h3", "", name), el("p", "", text)))));
    next.append(steps);
    const health = append(el("section", "panel insight-card quiet-card"), el("p", "eyebrow", "A NOTE ON YOUR WORKSPACE"), el("h3", "", "Your pace. Your decisions."), el("p", "", "Discovery and document preparation run only when you confirm them. This workspace never submits an application or verifies employer receipt."), button("View operations  →", "text-button", () => navigate("operations")));
    append(side, next, health);
    append(grid, opportunities, side);
    const note = el("p", "disclaimer", "Fit scores are local heuristics, not hiring probabilities. Unknown eligibility, partial discovery, and unqualified sources need your review.");
    const evidence = panel("Evidence & freshness", "Counts reflect local records, not employer decisions.");
    keyValues(evidence, Object.entries(overview.eligibility_counts || {}).map(([key, value]) => [titleCase(key) + " eligibility", value]));
    const latest = list(operations.runs)[0];
    keyValues(evidence, [["Latest discovery", latest ? `${titleCase(latest.status)} · ${date(latest.completed_at || latest.started_at)}` : "Not recorded"], ["Scheduler", titleCase(operations.scheduler?.status || "not configured")], ["Native task qualification", "Not checked; installed-task lifecycle remains unqualified"]]);
    if (latest && !["complete", "success"].includes(latest.status)) evidence.append(el("p", "warning-box", "Discovery may be partial or failed. Inspect Operations before relying on freshness."));
    container.replaceChildren(head, hero, stats, grid, evidence, note);
  }

  function field(parent, label, name, type = "text", value = "") {
    const box = el("div");
    const caption = el("label", "", label);
    const input = el("input");
    input.type = type;
    input.name = name;
    input.id = `field-${name}`;
    input.value = value;
    caption.htmlFor = input.id;
    append(box, caption, input);
    parent.append(box);
    return input;
  }
  function selectField(parent, label, name, choices, value = "") {
    const box = el("div");
    const caption = el("label", "", label);
    const select = el("select");
    select.name = name;
    select.id = `field-${name}`;
    caption.htmlFor = select.id;
    choices.forEach(([key, text]) => { const option = el("option", "", text); option.value = key; select.append(option); });
    select.value = value;
    append(box, caption, select);
    parent.append(box);
    return select;
  }
  async function renderJobs(container, current) {
    const isReview = state.view === "review";
    const query = new URLSearchParams({ ...state.filters, page: String(state.page) });
    const results = await api(`/api/jobs?${query}`);
    if (current !== state.request) return;
    const head = heading(isReview ? "Every application, a clear next step." : "Find something worth exploring.", isReview ? "Review your materials, record your progress, and keep the story together." : "Your local opportunities. A starting point for a thoughtful search.", button("Discover  +", "button primary", confirmDiscovery));
    const filters = el("form", "filters");
    filters.setAttribute("aria-label", "Filter opportunities");
    const search = field(filters, "Search roles or companies", "search", "search", state.filters.search || "");
    search.placeholder = "Title, company, or keyword…";
    selectField(filters, "Application status", "status", [["", "All statuses"], ...statuses.map((status) => [status, titleCase(status)])], state.filters.status || "");
    selectField(filters, "Eligibility", "eligibility", [["", "All assessments"], ["eligible", "Eligible"], ["uncertain", "Uncertain"], ["ineligible", "Ineligible"], ["unknown", "Unknown"]], state.filters.eligibility || "");
    selectField(filters, "Role track", "track", [["", "All tracks"], ...tracks.map((track) => [track, titleCase(track)])], state.filters.track || "");
    field(filters, "Location", "location", "text", state.filters.location || "").placeholder = "Any location";
    const apply = el("button", "button secondary", "Apply filters");
    apply.type = "submit";
    filters.append(apply);
    filters.addEventListener("submit", (event) => {
      event.preventDefault();
      state.filters = Object.fromEntries(new FormData(filters));
      state.page = 1;
      renderView();
    });
    const information = el("div", "info-box", isReview ? "Approval is bound to the exact documents you review. Recording a submission is your report of an action completed elsewhere; it does not verify employer receipt." : "A fit score describes relevance, not eligibility. Read uncertain or ineligible assessments and confirm the original posting before proceeding.");
    const summary = append(el("div", "results-header"), el("span", "", `${results.total || 0} opportunit${results.total === 1 ? "y" : "ies"}`), button("Clear filters", "text-button", () => { state.filters = {}; state.page = 1; renderView(); }));
    const jobs = list(results.jobs);
    const body = el("section", "panel full-list");
    body.setAttribute("aria-label", "Opportunity results");
    if (jobs.length) body.append(append(el("div", "job-list"), jobs.map(jobRow)));
    else body.append(empty("No opportunities here yet", Object.values(state.filters).some(Boolean) ? "Try a broader search or clear the filters to see more opportunities." : "Confirm discovery to read your configured sources. You can also use the independent CLI to import local records.", button("Clear filters", "button secondary", () => { state.filters = {}; state.page = 1; renderView(); })));
    const pages = results.pages || 1;
    const pagination = el("nav", "pagination");
    pagination.setAttribute("aria-label", "Results pages");
    const previous = button("← Previous", "button secondary", () => { state.page--; renderView(); });
    previous.disabled = state.page <= 1;
    const next = button("Next →", "button secondary", () => { state.page++; renderView(); });
    next.disabled = state.page >= pages;
    append(pagination, previous, el("span", "", `Page ${state.page} of ${pages}`), next);
    body.append(pagination);
    container.replaceChildren(head, information, filters, summary, body);
  }

  function readableRows(items, columns, label) {
    const wrapper = el("div", "table-wrap");
    const table = el("table");
    table.setAttribute("aria-label", label);
    const header = el("tr");
    columns.forEach(([caption]) => { const th = el("th", "", caption); th.scope = "col"; header.append(th); });
    table.append(append(el("thead"), header));
    const body = el("tbody");
    items.forEach((item) => {
      const row = el("tr");
      columns.forEach(([, key, formatter]) => row.append(el("td", "", formatter ? formatter(item[key], item) : asText(item[key]))));
      body.append(row);
    });
    table.append(body);
    wrapper.append(table);
    return wrapper;
  }
  async function renderOperations(container, current) {
    const data = await api("/api/operations");
    if (current !== state.request) return;
    const head = heading("A healthy workspace, a steadier search.", "Inspect discovery and preparation activity. Nothing runs until you confirm it.", button("Refresh", "button secondary", renderView));
    const actions = el("section", "panel");
    const discover = append(el("div", "operation-section"), el("h3", "", "Discover opportunities"), el("p", "", "Read your configured, permitted sources. Discovery may contact external job boards and updates the local job ledger; it does not submit applications."), button("Review discovery action", "button primary", confirmDiscovery));
    const recover = append(el("div", "operation-section"), el("h3", "", "Recover interrupted preparations"), el("p", "", "Reconcile completed document packets with the local ledger. Incomplete or stale work is marked failed and retained. Recovery never approves or submits."), button("Review recovery action", "button secondary", confirmRecovery));
    append(actions, discover, recover);
    const warning = el("p", "warning-box", "Source health is discovery evidence, not proof that a posting is open. Partial, unknown, or unqualified sources require manual verification. Missing listings never establish an application outcome.");
    const sources = panel("Source health", "Local evidence from configured discovery sources.");
    const sourceItems = list(data.sources);
    if (sourceItems.length) sources.append(readableRows(sourceItems, [["Source", "company", (_, item) => item.company || item.source_key || item.source_id || item.provider || "Configured source"], ["Health", "status", (_, item) => titleCase(item.status || item.health || item.last_state || "unknown")], ["Last checked", "last_success_at", (value, item) => date(value || item.updated_at || item.last_attempt_at)], ["Coverage", "coverage", (value, item) => asText(value || item.qualification || "Not qualified")], ["Retry after", "next_retry_at", date]], "Discovery source health"));
    else sources.append(empty("No discovery health recorded", "Source health will appear after a configured discovery run."));
    const preparations = panel("Document preparation activity", "Durable preparation history, including interrupted work.");
    const prepItems = list(data.preparations);
    if (prepItems.length) preparations.append(readableRows(prepItems, [["Opportunity", "title", (value, item) => value || item.job_id || "Local opportunity"], ["State", "state", titleCase], ["Started", "started_at", (value, item) => date(value || item.created_at)], ["Completed", "completed_at", date]], "Document preparation operations"));
    else preparations.append(empty("A clean slate", "Preparation activity appears here after you prepare an application packet."));
    const runs = panel("Discovery runs", "Recent discovery activity and recorded coverage.");
    const runItems = list(data.runs);
    if (runItems.length) runs.append(readableRows(runItems, [["Started", "started_at", date], ["State", "status", (value, item) => titleCase(value || item.state || "unknown")], ["Coverage", "coverage", (value) => asText(value || "Unknown")]], "Recent discovery runs"));
    else runs.append(empty("No discovery runs recorded", "Confirmed discovery runs will appear here."));
    const localStatus = panel("Scheduler & integrations", "Read-only local configuration and qualification status.");
    const localBody = el("div", "panel-body");
    const scheduler = data.scheduler || {};
    keyValues(localBody, [["Scheduler", titleCase(scheduler.status || "unknown")], ["Native task", "Not checked by this dashboard"], ["Latest window", titleCase(scheduler.latest?.status || "not recorded")], ["Google", titleCase(data.integrations?.google?.status || "unknown")], ["MCP", titleCase(data.integrations?.mcp?.status || "unqualified")]]);
    localBody.append(el("p", "disclaimer", "Local configuration does not establish native scheduler operation or external integration qualification. This dashboard does not connect Google or verify an authenticated MCP invocation."));
    localStatus.append(localBody);
    container.replaceChildren(head, warning, append(el("div", "stack"), actions, sources, preparations, runs, localStatus));
  }

  function detailSection(parent, title) {
    const section = append(el("section", "detail-section"), el("h3", "", title));
    parent.append(section);
    return section;
  }
  function keyValues(parent, entries) {
    const dl = el("dl", "key-value");
    entries.forEach(([key, value]) => append(dl, el("dt", "", key), el("dd", "", value)));
    parent.append(dl);
  }
  function safeLink(value, text) {
    try {
      const url = new URL(value);
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) return null;
      // URL canonicalization also turns numeric/hex/octal IPv4 forms into dotted IPs.
      // Only explicit public-DNS-shaped destinations become clickable; no DNS lookup.
      const hostname = url.hostname.toLowerCase().replace(/\.+$/, "");
      if (!hostname.includes(".") || /^[0-9.]+$/.test(hostname) || hostname.includes(":") || hostname.includes("[") ||
          ["localhost", "local", "internal"].some((suffix) => hostname === suffix || hostname.endsWith(`.${suffix}`)) ||
          !/^[a-z0-9.-]+$/.test(hostname)) return null;
      const link = el("a", "button secondary", text);
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      return link;
    } catch { return null; }
  }
  async function openJob(id) {
    state.review = null;
    state.detail = null;
    const content = $("detail-content");
    loading(content);
    // A stable heading exists while the dialog is loading.
    const loadHeading = el("h2", "", "Loading opportunity");
    loadHeading.id = "detail-heading";
    content.prepend(loadHeading);
    if (!$("detail-dialog").open) $("detail-dialog").showModal();
    try {
      const data = await api(`/api/job?id=${encodeURIComponent(id)}`);
      state.detail = data;
      renderDetail(data);
    } catch (error) {
      content.replaceChildren(empty("Couldn’t open this opportunity", error.message, button("Try again", "button secondary", () => openJob(id))));
      const errorHeading = content.querySelector("h3");
      errorHeading.id = "detail-heading";
    }
  }
  function renderDetail(data) {
    const job = data.job || data;
    const id = job.id || job.job_id;
    const status = data.application?.status || job.status || "discovered";
    const header = el("header", "detail-header");
    const h2 = el("h2", "", job.title || "Untitled opportunity");
    h2.id = "detail-heading";
    append(header, h2, append(el("div", "detail-meta"), el("span", "", job.company || "Unknown employer"), el("span", "", job.location || "Location unknown"), el("span", "", titleCase(job.provider))));
    const badges = append(el("div", "detail-badges"), badge(status), badge((data.eligibility || job.eligibility)?.outcome || "unknown"));
    const availability = data.availability || job.availability || {};
    badges.append(badge(availability.status || "unknown"));
    header.append(badges);
    const body = el("div", "detail-content");
    const note = el("p", "warning-box", "Posting content is untrusted source material. Confirm the original role and requirements. Fit and local eligibility checks do not establish legal eligibility or employer verification.");
    body.append(note);
    const actions = el("div", "detail-actions");
    const source = safeLink(job.job_url || job.apply_url, "Original posting  ↗");
    if (source) actions.append(source);
    if (window.openAssistance) actions.append(button("Inspect sandbox plans", "button secondary", () => window.openAssistance(id, null)));
    if (!completed.has(status)) actions.append(button(status === "prepared" || status === "approved" ? "Prepare a revision" : "Prepare documents", "button primary", () => confirmPrepare(job)));
    if (status !== "discovered" && status !== "shortlisted") actions.append(button("Review current packet", "button secondary", () => loadReview(id)));
    body.append(actions);
    const ranking = data.ranking || job.ranking || {};
    const fit = detailSection(body, "Fit & eligibility");
    keyValues(fit, [["Fit score", typeof ranking.score === "number" ? `${Math.round(ranking.score)} / 100 · heuristic relevance` : "Not available"], ["Eligibility", titleCase((data.eligibility || job.eligibility)?.outcome || "unknown")], ["Posting availability", titleCase(availability.status || "unknown")], ["Role tracks", list(job.tracks).map(titleCase).join(", ") || "Not classified"], ["Compensation", job.compensation || "Not specified"]]);
    const assessment = data.eligibility || job.eligibility || {};
    [["Missing information", assessment.missing_information], ["Manual verification", assessment.manual_verification], ["Assessment limitations", assessment.limitations]].forEach(([label, values]) => {
      const items = list(values);
      if (items.length) {
        fit.append(el("h3", "", label));
        const ul = el("ul", "evidence");
        items.forEach((item) => ul.append(el("li", "", asText(item))));
        fit.append(ul);
      }
    });
    if (list(assessment.rules).length) {
      const requirements = append(el("details"), el("summary", "text-button", "Read requirement evidence & reasoning"));
      list(assessment.rules).forEach((rule) => {
        const item = append(el("div", "history-item"), badge(rule.outcome || "unknown"), el("p", "evidence", `${titleCase(rule.kind || "Requirement")}: ${rule.reason || "Manual review required"}`));
        list(rule.evidence).forEach((evidence) => item.append(el("blockquote", "evidence", evidence.text || "No posting excerpt recorded")));
        requirements.append(item);
      });
      fit.append(requirements);
    }
    const components = ranking.components;
    if (components && typeof components === "object") {
      const breakdown = el("details");
      breakdown.append(el("summary", "text-button", "View fit score explanation"));
      const entries = Array.isArray(components) ? components.map((item) => [item.name || item.component || "Component", item]) : Object.entries(components);
      entries.forEach(([name, item]) => {
        const value = typeof item === "number" ? item : item?.score ?? item?.points ?? item?.weighted_score ?? item?.contribution;
        const text = typeof value === "number" ? `${Math.round(value * 100) / 100}` : "Evidence available";
        breakdown.append(append(el("div", "mini-row"), el("span", "", titleCase(name)), el("strong", "", text)));
        if (item && typeof item === "object" && (item.reason || item.explanation)) breakdown.append(el("p", "evidence", item.reason || item.explanation));
      });
      const explanation = ranking.ranking_explanation || {};
      keyValues(breakdown, [["Role relationship", titleCase(explanation.role?.relation)], ["Evidence confidence", titleCase(explanation.confidence?.level || explanation.confidence)], ["Assessed", date(explanation.as_of)]]);
      ["missing_information", "limitations"].forEach(key => list(explanation[key]).forEach(value => breakdown.append(el("p", "evidence", asText(value)))));
      fit.append(breakdown);
    }
    const description = detailSection(body, "About this opportunity");
    description.append(el("div", "description", job.description || "No description was recorded. Review the original posting for details."));
    const review = detailSection(body, "Document review & next steps");
    review.id = "packet-review";
    review.append(el("p", "evidence", "Review the current packet before approving it. Approval applies only to that exact job, profile, and document revision."));
    if (["discovered", "shortlisted"].includes(status)) review.append(el("p", "info-box", "Prepare documents to create a local packet for review. Facts must come from your configured, attested profile."));
    else review.append(button("Load packet for review", "button secondary", () => loadReview(id)));
    const tracking = detailSection(body, "Application record");
    const application = data.application || {};
    keyValues(tracking, [["Local status", titleCase(status)], ["Approved", date(application.approved_at)], ["Submission recorded", date(application.submitted_at)], ["Employer receipt", "Not independently verified"]]);
    if (application.submission_evidence) tracking.append(el("p", "evidence", `Operator evidence: ${application.submission_evidence}`));
    if (completed.has(status) && status !== "withdrawn") tracking.append(append(el("div", "detail-actions"), button("Record an outcome", "button secondary", () => loadReview(id, "status"))));
    const history = detailSection(body, "Local history");
    if (list(data.history).length) list(data.history).forEach((event) => history.append(append(el("div", "history-item"), el("strong", "", titleCase(event.event_type || event.type || event.status)), el("span", "history-date", date(event.created_at)), event.evidence ? el("p", "evidence", `Operator-supplied evidence: ${event.evidence}`) : null)));
    else history.append(el("p", "evidence", "No history recorded yet."));
    $("detail-content").replaceChildren(header, body);
  }

  async function loadReview(id, nextAction) {
    const target = $("packet-review");
    if (!target) return;
    loading(target);
    try {
      const review = await api(`/api/review?id=${encodeURIComponent(id)}`);
      state.review = review;
      target.replaceChildren(el("h3", "", "Current document packet"));
      target.append(el("p", "info-box", review.note || "Review the text and download each document to inspect its rendering. This review binds the current packet only; changed inputs require a new review."));
      const qa = review.qa || {};
      keyValues(target, [["Revision", review.revision || "Current managed packet"], ["Document emphasis", titleCase(review.variant || "unknown")], ["Structural checks", qa.structural_pass ? "Passed local structural checks" : "Require review"], ["Unresolved checks", qa.unresolved_count ?? "Unknown"], ["Rendering", titleCase(asText(qa.rendering || "Human review required"))], ["ATS compatibility", "Not guaranteed"]]);
      const gaps = list(qa.unresolved);
      if (gaps.length) {
        const unresolved = append(el("details", "detail-section"), el("summary", "text-button", `Review ${gaps.length} unresolved profile item${gaps.length === 1 ? "" : "s"}`));
        gaps.forEach((gap) => unresolved.append(el("p", "evidence", `${titleCase(gap.field || "Profile field")}${gap.item ? `, item ${gap.item}` : ""}: ${gap.reason || "Manual review required"}`)));
        target.append(unresolved);
      }
      const integrity = append(el("details", "detail-section"), el("summary", "text-button", "Inspect revision identity & document checks"));
      keyValues(integrity, [["Job fingerprint", review.job_sha256 || "Not available"], ["Packet fingerprint", review.packet_sha256 || "Not available"]]);
      list(qa.files).forEach((file) => {
        integrity.append(el("h3", "", `${titleCase(file.kind)} checks`));
        keyValues(integrity, [["Document fingerprint", file.sha256 || "Not available"], ...Object.entries(file.checks || {}).map(([name, value]) => [titleCase(name), value === true ? "Passed" : "Requires review"])]);
        list(file.warnings).forEach((warning) => integrity.append(el("p", "warning-box", warning)));
      });
      target.append(integrity);
      const docs = list(review.documents);
      if (docs.length) {
        const downloads = el("div", "review-downloads");
        docs.forEach((doc) => {
          downloads.append(button(`Download ${titleCase(doc.kind)}`, "button secondary", () => downloadDocument(id, review.review_token, doc.kind)));
          const preview = el("details", "detail-section");
          preview.append(el("summary", "text-button", `Read ${titleCase(doc.kind)} text`));
          if (doc.truncated || doc.text_truncated || doc.preview_truncated) preview.append(el("p", "warning-box", "This text preview is truncated. Download and inspect the entire document before approval."));
          preview.append(el("div", "description", doc.text || "Text preview unavailable. Download the document for review."));
          target.append(preview);
        });
        target.append(downloads);
      }
      const status = review.status || state.detail?.application?.status || state.detail?.job?.status;
      const actions = el("div", "detail-actions");
      if (status === "prepared") actions.append(button("Approve reviewed revision", "button primary", () => confirmApprove(id, review)));
      if (status === "approved" && window.openAssistance) actions.append(button("Review sandbox assistance", "button secondary", () => window.openAssistance(id,review.review_token)));
      if (status === "approved") actions.append(button("Record external submission", "button primary", () => confirmSubmitted(id, review)));
      if (completed.has(status) && status !== "withdrawn") actions.append(button("Record an outcome", "button primary", () => confirmStatus(id, review)));
      target.append(actions);
      target.scrollIntoView({ behavior: "instant", block: "start" });
      if (nextAction === "status") confirmStatus(id, review);
    } catch (error) {
      target.replaceChildren(el("h3", "", "Packet review unavailable"), el("p", "warning-box", error.message), button("Try review again", "button secondary", () => loadReview(id)));
    }
  }
  async function downloadDocument(id, token, kind) {
    if (state.busy) return;
    state.busy = true;
    setPending(true);
    try {
      const fresh = await csrf();
      const response = await fetch("/api/document", { method: "POST", credentials: "same-origin", cache: "no-store", headers: { "Content-Type": "application/json", "X-CSRF-Token": fresh }, body: JSON.stringify({ id, review_token: token, kind }) });
      if (!response.ok) {
        const failure = await response.json().catch(() => ({}));
        throw new Error(failure.error || "Couldn’t download the current document. Reload the packet and try again.");
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = el("a");
      link.href = url;
      link.download = `${kind}-${String(id).replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 40)}.docx`;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify("Document downloaded. Inspect its content and rendering before approval.");
    } catch (error) { notify(error.message, true); }
    finally { state.busy = false; setPending(false); }
  }

  function setPending(pending) {
    document.querySelectorAll("button").forEach((node) => {
      if (pending) { node.dataset.wasDisabled = node.disabled ? "yes" : "no"; node.disabled = true; }
      else if (node.dataset.wasDisabled !== undefined) { node.disabled = node.dataset.wasDisabled === "yes"; delete node.dataset.wasDisabled; }
    });
    $("confirm-form").setAttribute("aria-busy", String(pending));
  }
  function openConfirmation(title, text, action, fields, submitLabel) {
    if (state.busy) return;
    const content = $("confirm-content");
    const h2 = el("h2", "", title);
    h2.id = "confirm-heading";
    content.replaceChildren(h2, el("p", "", text));
    if (fields) fields(content);
    const checkLabel = el("label", "check-label");
    const check = el("input");
    check.type = "checkbox";
    check.name = "confirmed";
    check.required = true;
    append(checkLabel, check, el("span", "", "I have reviewed this action and confirm that I want to continue."));
    content.append(checkLabel);
    $("confirm-error").textContent = "";
    $("confirm-submit").textContent = submitLabel || "Confirm action";
    confirmation = action;
    $("confirm-dialog").showModal();
    $("confirm-cancel").focus();
  }
  function confirmDiscovery() {
    openConfirmation("Discover new possibilities?", "This contacts the permitted sources in your local configuration and updates the job ledger. Source rate limits and backoff remain in effect. It does not submit applications or contact recruiters.", () => ({ action: "discover", confirm: "discover" }), null, "Confirm discovery");
  }
  function confirmRecovery() {
    openConfirmation("Reconcile interrupted work?", "This checks pending preparation operations. Complete packets may be recorded; incomplete or stale packets are marked failed and retained. It never approves a packet or submits an application.", () => ({ action: "recover", confirm: "recover" }), null, "Confirm recovery");
  }
  function confirmPrepare(job) {
    const id = job.id || job.job_id;
    openConfirmation("Prepare your documents?", `Create a local document packet for ${job.title || "this role"} at ${job.company || "this employer"} using your configured, attested profile. A new revision requires another review and approval.`, (form) => ({ action: "prepare", id, confirm: "prepare", variant: form.get("variant"), track: form.get("variant") === "track" ? form.get("prepare-track") : null, new_revision: form.get("new_revision") === "on" }), (content) => {
      const variant = selectField(content, "Document emphasis", "variant", [["job", "Tailored to this role"], ["master", "Master resume"], ["track", "Specific role track"]], "job");
      const track = selectField(content, "Track (for a track-specific resume)", "prepare-track", tracks.map((value) => [value, titleCase(value)]), tracks.includes(list(job.tracks)[0]) ? job.tracks[0] : "software");
      track.disabled = true;
      variant.addEventListener("change", () => { track.disabled = variant.value !== "track"; });
      const label = el("label", "check-label");
      const revision = el("input");
      revision.type = "checkbox";
      revision.name = "new_revision";
      append(label, revision, el("span", "", "Create a new revision even if the current inputs match."));
      content.append(label);
    }, "Confirm preparation");
  }
  function confirmApprove(id, review) {
    openConfirmation("Approve this exact revision?", "Approval records your decision about the current job, profile, and document packet. Review each document’s content and rendering first. Approval does not submit anything.", (form) => ({ action: "approve", id, confirm: "approve", phrase: form.get("phrase"), review_token: review.review_token }), (content) => {
      const input = field(content, `Type APPROVE ${id} to confirm`, "phrase");
      input.required = true;
      input.autocomplete = "off";
      input.spellcheck = false;
      input.addEventListener("input", () => input.setCustomValidity(input.value === `APPROVE ${id}` ? "" : "Enter the exact approval phrase shown above."));
      input.setCustomValidity("Enter the exact approval phrase shown above.");
    }, "Approve revision");
  }
  function evidenceField(content) {
    const evidence = field(content, "Evidence reference (6–4,000 characters)", "evidence");
    evidence.required = true;
    evidence.minLength = 6;
    evidence.maxLength = 4000;
    evidence.placeholder = "For example: confirmation email received, date, reference";
    const help = el("p", "field-help", "A short operator-supplied reference. This workspace does not independently verify it. Avoid unnecessary sensitive information.");
    content.append(help);
  }
  function confirmSubmitted(id, review) {
    openConfirmation("Record an external submission?", "Use this only after you have completed the application outside this workspace. This saves your operator report and evidence reference; it does not submit a form or establish employer receipt.", (form) => ({ action: "submitted", id, confirm: "submitted", evidence: form.get("evidence"), review_token: review.review_token }), evidenceField, "Record submission");
  }
  function confirmStatus(id, review) {
    openConfirmation("Record a recruiting outcome?", "Update the local application record with an outcome you observed and an evidence reference. State transitions are checked by the workflow. Your evidence remains operator supplied and unverified.", (form) => ({ action: "status", id, confirm: "status", status: form.get("outcome"), evidence: form.get("evidence"), review_token: review.review_token }), (content) => {
      selectField(content, "Observed outcome", "outcome", ["assessment", "interview", "offer", "rejected", "withdrawn"].map((status) => [status, titleCase(status)]), "interview");
      evidenceField(content);
    }, "Record outcome");
  }
  $("confirm-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.busy || !confirmation) return;
    const form = new FormData(event.currentTarget);
    if (!form.has("confirmed")) return;
    const payload = confirmation(form);
    state.busy = true;
    setPending(true);
    $("confirm-error").textContent = "";
    try {
      const fresh = await csrf();
      const result = await api("/api/action", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": fresh }, body: JSON.stringify(payload) });
      $("confirm-dialog").close();
      const messages = { discover: "Discovery completed. Review source health and coverage in Operations.", recover: "Recovery completed. Review preparation activity in Operations.", prepare: "Documents prepared. Review the current packet before approving.", approve: "This exact revision is approved. Apply externally before recording submission.", submitted: "Your external submission report was recorded. Employer receipt remains unverified.", status: "Your recruiting outcome was recorded with operator-supplied evidence." };
      notify(result.message || (payload.action === "discover" && (result.error_count || result.skipped_count) ? "Discovery returned errors or skipped work. Inspect Operations; coverage may be partial." : messages[payload.action]) || "Action completed.");
      await renderView();
      if (payload.id && $("detail-dialog").open) {
        await openJob(payload.id);
        if (["prepare", "approve"].includes(payload.action)) await loadReview(payload.id);
      }
    } catch (error) { $("confirm-error").textContent = error.message; }
    finally { state.busy = false; setPending(false); }
  });
  $("confirm-close").addEventListener("click", () => { if (!state.busy) $("confirm-dialog").close(); });
  $("confirm-cancel").addEventListener("click", () => { if (!state.busy) $("confirm-dialog").close(); });
  $("confirm-dialog").addEventListener("cancel", (event) => { if (state.busy) event.preventDefault(); });
  $("detail-close").addEventListener("click", () => { if (!state.busy) $("detail-dialog").close(); });
  $("detail-dialog").addEventListener("cancel", (event) => { if (state.busy) event.preventDefault(); });
  $("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.busy) return;
    state.busy = true;
    setPending(true);
    $("login-message").textContent = "Unlocking…";
    try {
      const result = await api("/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ secret: $("secret").value }) });
      state.csrf = result.csrf;
      $("secret").value = "";
      $("login-message").textContent = "";
      showWorkspace();
    } catch (error) { $("login-message").textContent = error.message; }
    finally { state.busy = false; setPending(false); }
  });
  window.addEventListener("hashchange", () => { state.page = 1; renderView(); });
  api("/api/session").then((session) => { state.csrf = session.csrf; showWorkspace(); }).catch(showLogin);
})();
