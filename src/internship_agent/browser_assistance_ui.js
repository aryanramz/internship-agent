"use strict";

(() => {
  // One fixed local adapter. These constants must match the server's FORM.
  const FORM = { version: 1, method: "POST", fields: [
    { name: "name", type: "text", max_length: 200 },
    { name: "email", type: "email", max_length: 254 },
    { name: "legal", type: "manual" },
    { name: "eeo", type: "manual" },
    { name: "work_authorization", type: "manual" }
  ] };
  const FINGERPRINT = "84ca6517270c6bcb72ec999ac498864773af1505ff3d97d06d879d482eff4152";
  const fixtureMatch = /^\/sandbox\/application\/([a-f0-9]{32})$/.exec(location.pathname);
  const isFixture = Boolean(fixtureMatch);
  const labels = { name: "Name", email: "Email", legal: "Legal questions (manual)", eeo: "Equal opportunity questions (manual)", work_authorization: "Work authorization (manual)" };
  const state = { plan: null, busy: false, displayed: false, drift: false, observed: false, epoch: 0 };
  let content, status, dialog, fixtureForm;

  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function add(parent, ...children) { children.flat().forEach((child) => parent.append(child)); return parent; }
  function button(text, id, handler) {
    const node = el("button", text, "button secondary");
    node.type = "button";
    if (id) node.id = id;
    node.addEventListener("click", handler);
    return node;
  }
  function message(text, error = false) {
    status.textContent = text;
    status.setAttribute("role", error ? "alert" : "status");
  }
  function printable(value) {
    if (value === undefined || value === null || value === "") return "Not recorded";
    return typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  }
  function pair(parent, label, value) { add(parent, el("dt", label), el("dd", printable(value))); }
  function fieldInput(parent, label, name, type = "text") {
    const id = `assistance-${name}`;
    const caption = el("label", label); caption.htmlFor = id;
    const input = el("input"); input.id = id; input.name = name; input.type = type;
    add(parent, caption, input);
    return input;
  }
  function checkbox(parent, text, name = "reviewed", id) {
    const label = el("label", undefined, "check-label");
    const input = el("input"); input.type = "checkbox"; input.name = name;
    if (id) input.id = id;
    add(label, input, el("span", text)); parent.append(label);
    return input;
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : "Local assistance request failed. Review the plan before trying again.");
    return result;
  }
  async function post(payload) {
    // Refresh for each action; neither CSRF nor action tokens enter a URL/storage.
    const session = await api("/api/session");
    if (!session.csrf) throw new Error("Your workspace session expired. Unlock the workspace and review the plan again.");
    return api("/api/assistance", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf }, body: JSON.stringify({ ...payload, confirm: payload.action }) });
  }
  function planOf(value) { return value && value.plan ? value.plan : value; }
  function validatePlan(plan) {
    if (!plan || !/^[a-f0-9]{32}$/.test(plan.plan_id) || !Array.isArray(plan.fields) || plan.fields.length !== FORM.fields.length ||
        plan.form_fingerprint !== FINGERPRINT || JSON.stringify(plan.form_schema) !== JSON.stringify(FORM)) {
      throw new Error("The local form schema changed or is unavailable. Refusing assistance; create a new reviewed plan.");
    }
    const names = new Set();
    for (const field of plan.fields) {
      if (!field || !FORM.fields.some((item) => item.name === field.name) || names.has(field.name)) throw new Error("Malformed local field mapping. Review a new plan.");
      names.add(field.name);
      const spec = FORM.fields.find((item) => item.name === field.name);
      if (spec.type === "manual" && (field.value !== undefined && field.value !== "")) throw new Error("Sensitive or unknown fields must remain empty.");
      if (field.value !== undefined && (typeof field.value !== "string" || field.value.length > (spec.max_length || 0))) throw new Error("Invalid proposed field value.");
    }
    return plan;
  }
  function expectedValue(name) {
    const field = state.plan.fields.find((item) => item.name === name);
    return field && field.manual === false && typeof field.value === "string" && ["name", "email"].includes(name) ? field.value : "";
  }
  function schemaGuard(requireDisplayed = false) {
    validatePlan(state.plan);
    if (state.drift) throw new Error("The fixture was edited. Assistance is paused; create a new plan and review the changed fields.");
    const expectedPath = `/sandbox/application/${state.plan.plan_id}`;
    if (!fixtureForm || fixtureForm.getAttribute("method") !== "post" || fixtureForm.getAttribute("action") !== expectedPath ||
        fixtureForm.querySelectorAll("input,select,textarea,button,iframe,object,embed").length !== FORM.fields.length || fixtureForm.elements.length !== FORM.fields.length) {
      state.drift = true; throw new Error("The fixture form controls changed. Assistance is refused; review a new plan.");
    }
    const inputs = [...fixtureForm.querySelectorAll("input")];
    for (const [index, spec] of FORM.fields.entries()) {
      const input = inputs[index], manual = spec.type === "manual";
      if (!input || input.name !== spec.name || input.type !== (manual ? "text" : spec.type) || !input.readOnly || input.disabled ||
          input.getAttribute("form") !== null || input.dataset.fieldKind !== spec.type || input.maxLength !== (spec.max_length || 0) ||
          input.value !== (state.displayed ? expectedValue(spec.name) : "")) {
        state.drift = true; throw new Error("Fixture fields or approved values changed. Assistance is paused for a new review.");
      }
    }
    if (requireDisplayed && !state.displayed) throw new Error("Explicitly display and review the approved fixture values before continuing.");
    if (isFixture && location.href !== state.plan.target_url) throw new Error("The fixture navigation changed. Review the exact allowed URL before assistance.");
    if (state.plan.origin !== location.origin || state.plan.target_url !== location.origin + expectedPath) throw new Error("The fixture target changed. Only this exact local fixture is allowed.");
  }
  function observeKey() { return `internship-fixture-observe-attempt:${state.plan.plan_id}`; }
  function attempted() {
    try { return sessionStorage.getItem(observeKey()) === "1"; } catch (_) { return false; }
  }
  function markAttempted() { try { sessionStorage.setItem(observeKey(), "1"); } catch (_) { /* In-memory guard remains active. */ } }
  function displayValues() {
    schemaGuard();
    for (const input of fixtureForm.querySelectorAll("input")) input.value = expectedValue(input.name);
    state.displayed = true;
  }
  function disableActions(disabled) {
    for (const node of content.querySelectorAll("button[data-action]")) node.disabled = disabled || node.dataset.permanent === "true";
  }
  async function action(name, payload = {}) {
    if (state.busy) return;
    // Recovery must remain available after schema, page, origin, or session drift.
    if (!["revoke", "reconcile"].includes(name)) schemaGuard(["handoff", "resume", "intent", "observe"].includes(name));
    const token = name === "observe" ? state.plan.observe_token : state.plan.action_token;
    if (!token) throw new Error("This action belongs to another or expired session. Reload the plan; ambiguous activity requires reconciliation.");
    state.busy = true; disableActions(true);
    const epoch = state.epoch;
    const oldPlan = state.plan;
    try {
      const result = await post({ action: name, plan_id: oldPlan.plan_id, token, form_fingerprint: FINGERPRINT, ...payload });
      if (epoch !== state.epoch) return;
      state.plan = validatePlan(planOf(result));
      if (name === "fill") displayValues();
      renderPlan();
      message(name === "observe" ? "Local fixture confirmation observed. This is not employer verification. Reconciliation is still required." : `Local ${name} recorded. Review the next action separately.`);
    } catch (error) {
      if (epoch === state.epoch) message(error.message + (name === "observe" || name === "intent" ? " Do not repeat the final action. Reload and reconcile the ambiguous state." : ""), true);
    } finally {
      if (epoch === state.epoch) { state.busy = false; disableActions(false); }
    }
  }
  function actionReview(actionName, heading, help, phrase, payloadBuilder) {
    const section = el("fieldset", undefined, "detail-section");
    section.dataset.actionReview = actionName;
    add(section, el("legend", heading), el("p", help));
    const reviewed = checkbox(section, "I reviewed this exact plan, approved values, empty manual fields, packet identity, and expiry for this action.");
    const typed = fieldInput(section, `Type ${phrase} to confirm`, `phrase-${actionName}`); typed.name = "phrase"; typed.autocomplete = "off"; typed.spellcheck = false;
    let extra = () => ({});
    if (payloadBuilder) extra = payloadBuilder(section);
    const go = button(heading, `assistance-${actionName}`, async () => {
      if (!reviewed.checked || typed.value !== phrase) { message("Review the plan, check the acknowledgement, and type the exact phrase for this action.", true); return; }
      try { await action(actionName, { phrase: typed.value, ...extra() }); } catch (error) { message(error.message, true); }
    });
    go.dataset.action = actionName;
    section.append(go); content.append(section);
  }
  function renderFixtureFields(parent) {
    fixtureForm = el("form"); fixtureForm.id = "fixture-form"; fixtureForm.method = "post";
    fixtureForm.setAttribute("action", `/sandbox/application/${state.plan.plan_id}`);
    fixtureForm.addEventListener("submit", (event) => event.preventDefault());
    for (const spec of FORM.fields) {
      const label = el("label", labels[spec.name]); label.htmlFor = `fixture-${spec.name}`;
      const input = el("input"); input.id = `fixture-${spec.name}`; input.name = spec.name;
      input.type = spec.type === "manual" ? "text" : spec.type;
      input.dataset.fieldKind = spec.type; input.readOnly = true; input.maxLength = spec.max_length || 0;
      input.autocomplete = "off";
      input.value = state.displayed ? expectedValue(spec.name) : "";
      input.addEventListener("input", () => { state.drift = true; message("Field edits are not authorized. Assistance paused; review a new plan.", true); disableActions(true); });
      input.addEventListener("change", () => { state.drift = true; message("Field edits require a new review.", true); disableActions(true); });
      add(fixtureForm, label, input);
    }
    add(parent, el("h3", "Local fixture fields"), el("p", "Name and email appear only after an explicit reviewed fill or display action. Legal, equal opportunity, and work authorization answers remain empty and are never inferred or collected here."), fixtureForm);
  }
  function renderPlan() {
    const plan = state.plan;
    content.replaceChildren();
    add(content, el("h2", "Review the exact local plan"), el("p", "This adapter acts only on a same-origin sandbox fixture. Each action needs a separate review. Final submission is a human fixture control; no employer is contacted.", "info-box"));
    const info = el("dl", undefined, "key-value");
    for (const [label, value] of [
      ["Plan", plan.plan_id], ["State", plan.state], ["Job", plan.job_id || plan.job], ["Role", plan.title], ["Employer", plan.company],
      ["Allowed URL", plan.target_url], ["Source provider", plan.provider], ["Source ID", plan.source_id], ["Source freshness", plan.freshness],
      ["Job hash", plan.job_sha256], ["Profile hash", plan.profile_sha256], ["Exact packet hash", plan.packet_sha256], ["Plan hash", plan.plan_digest],
      ["Form fingerprint", plan.form_fingerprint], ["Plan expiry", new Date(plan.expires_at * 1000).toISOString()], ["Challenge", plan.challenge]
    ]) pair(info, label, value);
    add(content, info, el("p", "Workspace sessions expire after one hour; plans expire 15 minutes after creation. A changed job, profile, packet, schema, or session requires fresh review.", "field-help"));
    const section = el("section", undefined, "detail-section"); add(section, el("h3", "Proposed fields and provenance"));
    const table = el("table");
    const head = el("tr"); for (const heading of ["Field", "Proposed value", "Provenance / manual review"]) head.append(el("th", heading));
    const thead = el("thead"); thead.append(head); table.append(thead);
    const tbody = el("tbody");
    for (const spec of FORM.fields) {
      const field = plan.fields.find((item) => item.name === spec.name);
      const row = el("tr");
      const manual = !field || field.manual !== false || spec.type === "manual";
      add(row, el("td", labels[spec.name]), el("td", manual ? "Empty — manual review required" : printable(field.value)), el("td", manual ? "No automated answer or sensitive data collection" : printable(field.provenance)));
      tbody.append(row);
    }
    table.append(tbody); const wrap = el("div", undefined, "table-wrap"); wrap.append(table); section.append(wrap); content.append(section);
    add(content, el("h3", "Bound document packet"), el("p", `Exact approved packet: ${printable(plan.packet_sha256)}. This fixture records its identity only. It has no upload control; document contents never leave the workspace.`));
    renderFixtureFields(content);
    const link = el("a", "Open this exact local fixture in a new tab", "button secondary");
    link.href = `/sandbox/application/${plan.plan_id}`; link.target = "_blank"; link.rel = "noopener noreferrer"; content.append(link);
    const refresh = button("Reload plan and receipt", "assistance-refresh", () => loadPlan(plan.plan_id)); content.append(refresh);
    if (!state.displayed && ["filled", "handoff", "needs_manual_reconciliation"].includes(plan.state)) {
      const display = button("Review and display approved local values", "assistance-display-values", () => {
        try { displayValues(); renderPlan(); message("Approved local values displayed. Review the next action separately."); } catch (error) { message(error.message, true); }
      });
      content.append(display);
    }
    if (plan.reconciliation_only) content.append(el("p", "This plan belongs to an expired or different session. Only revocation before intent, or reconciliation after intent, is available. No fill or final action is authorized.", "warning-box"));
    if (!plan.reconciliation_only && plan.state === "plan") actionReview("fill", "Fill reviewed fixture fields", "Only mapped, verified name and email facts may be filled. Unknown and sensitive answers stay empty.", `FILL FIXTURE ${plan.plan_id}`);
    if (!plan.reconciliation_only && plan.state === "filled") actionReview("handoff", "Hand off to human review", "Review the local fixture and its exact binding before handing control to a person.", `HANDOFF FIXTURE ${plan.plan_id}`);
    if (!plan.reconciliation_only && plan.state === "handoff" && plan.challenge && plan.challenge !== "none" && !plan.challenge_resolved) {
      actionReview("resume", "Resume after human challenge acknowledgement", "This is a synthetic MFA or CAPTCHA boundary. A person must acknowledge it. Do not enter passwords, one-time codes, or CAPTCHA answers here.", `RESUME FIXTURE ${plan.plan_id}`, (parent) => {
        const acknowledged = checkbox(parent, "I handled the synthetic challenge boundary manually and choose to resume.", "challenge_ack", "assistance-challenge-ack");
        return () => { if (!acknowledged.checked) throw new Error("Human challenge acknowledgement is required."); return { challenge_ack: true }; };
      });
    }
    if (!plan.reconciliation_only && plan.state === "handoff" && plan.challenge_resolved) {
      if (isFixture) actionReview("intent", "Authorize one human fixture submission", "This records an ambiguous submission intent before a final control is enabled. A crash or uncertain result must be reconciled; never retry automatically.", `AUTHORIZE FIXTURE ${plan.plan_id}`);
      else content.append(el("p", "Open the local fixture tab, explicitly display and review the approved values, then authorize its one human final action there."));
    }
    if (plan.state === "needs_manual_reconciliation") {
      add(content, el("p", "Intent is recorded. External submission is unverified. Complete or reconcile this local fixture before any new attempt.", "warning-box"));
      if (isFixture && !plan.reconciliation_only && plan.can_observe === true && typeof plan.observe_token === "string" && plan.observe_token) {
        const final = button("Manually submit local fixture once", "fixture-submit", async () => {
          if (state.observed || attempted()) return;
          try { schemaGuard(true); } catch (error) { message(error.message, true); return; }
          // Disable synchronously, including on transport failure. Only reconciliation follows uncertainty.
          final.disabled = true; final.dataset.permanent = "true"; state.observed = true; markAttempted();
          try { await action("observe"); } catch (error) { message(`${error.message} Do not repeat the final action; reconcile instead.`, true); }
        });
        final.dataset.action = "observe";
        const observed = state.observed || attempted() || Boolean(plan.fixture_ui_observed || plan.observed_at);
        final.disabled = observed; final.dataset.permanent = String(observed); content.append(final);
      } else content.append(el("p", "The one human final control is unavailable after a reload, session change, or uncertain action. Reconcile the existing intent below; do not repeat it."));
      if (state.observed || attempted() || plan.fixture_ui_observed) add(content, el("p", "A local fixture action was observed or attempted. This does not verify employer receipt. Manual reconciliation remains required.", "info-box"));
      actionReview("reconcile", "Reconcile ambiguous fixture activity", "Record the observed outcome and its provenance. Unknown preserves the ambiguity; a local receipt never verifies employer submission.", `RECONCILE ${plan.plan_id}`, (parent) => {
        const label = el("label", "Observed outcome"); label.htmlFor = "assistance-outcome";
        const outcome = el("select"); outcome.id = "assistance-outcome"; outcome.name = "outcome";
        for (const value of ["unknown", "submitted", "not_submitted"]) { const option = el("option", value.replaceAll("_", " ")); option.value = value; outcome.append(option); }
        const provenanceLabel = el("label", "Provenance (local observation or operator report; no secrets)"); provenanceLabel.htmlFor = "assistance-provenance";
        const provenance = el("input"); provenance.type = "text"; provenance.id = "assistance-provenance"; provenance.name = "provenance"; provenance.maxLength = 500;
        add(parent, label, outcome, provenanceLabel, provenance);
        return () => { if (!provenance.value.trim() || /[\x00-\x1f]/.test(provenance.value)) throw new Error("A single line of provenance is required for reconciliation."); return { outcome: outcome.value, provenance: provenance.value.trim() }; };
      });
    }
    if (["plan", "filled", "handoff"].includes(plan.state)) actionReview("revoke", "Revoke this assistance plan", "Stop further local assistance. Revocation does not resolve an uncertain submission; reconcile ambiguity first.", `REVOKE ${plan.plan_id}`);
    if (plan.history) add(content, el("h3", "Local observations — employer unverified"), el("pre", printable(plan.history), "evidence"));
  }
  async function loadPlan(id) {
    const epoch = ++state.epoch;
    state.busy = false; state.displayed = false; state.drift = false; state.observed = false;
    message("Loading the local plan. No fixture fields are being filled.");
    try {
      const plan = validatePlan(planOf(await api(`/api/assistance?id=${encodeURIComponent(id)}`)));
      if (epoch !== state.epoch) return;
      state.plan = plan; renderPlan(); message("Plan loaded. Review each action explicitly.");
    } catch (error) { if (epoch === state.epoch) { content.replaceChildren(); message(error.message, true); } }
  }
  function ensureDialog() {
    if (dialog) return;
    dialog = el("dialog", undefined, "detail-dialog"); dialog.id = "assistance-dialog"; dialog.setAttribute("aria-labelledby", "assistance-heading");
    const top = el("div", undefined, "dialog-top");
    const heading = el("h2", "Local application assistance"); heading.id = "assistance-heading";
    add(top, heading, button("Close", "assistance-close", () => dialog.close()));
    content = el("div", undefined, "detail-content"); content.id = "assistance-content"; content.tabIndex = -1;
    status = el("p", undefined, "form-message"); status.id = "assistance-status"; status.setAttribute("aria-live", "polite"); status.setAttribute("role", "status");
    add(dialog, top, status, content); document.body.append(dialog);
  }
  window.openAssistance = async (jobId, reviewToken) => {
    if (isFixture) return;
    ensureDialog();
    const epoch = ++state.epoch;
    state.plan = null; state.busy = false; state.displayed = false; state.drift = false; state.observed = false;
    content.replaceChildren(); message("");
    if (!dialog.open) dialog.showModal();
    add(content, el("h3", "Create a reviewed local fixture plan"), el("p", "Assistance is limited to the local sandbox. It binds this job, the reviewed document revision, verified profile facts, and the exact form. No employer page is opened or contacted."));
    const challengeLabel = el("label", "Synthetic human challenge boundary"); challengeLabel.htmlFor = "assistance-challenge";
    const challenge = el("select"); challenge.id = "assistance-challenge";
    for (const value of ["none", "mfa", "captcha"]) { const option = el("option", value === "none" ? "None" : `${value.toUpperCase()} (human acknowledgement only)`); option.value = value; challenge.append(option); }
    add(content, challengeLabel, challenge);
    const reviewed = checkbox(content, "I reviewed and approved this exact document revision and want to create a local fixture plan.", "reviewed", "assistance-create-reviewed");
    const create = button("Create local fixture plan", "assistance-create", async () => {
      if (state.busy) return;
      if (!reviewed.checked) { message("Review and acknowledge the approved revision first.", true); return; }
      state.busy = true; create.disabled = true;
      try {
        const plan = validatePlan(planOf(await post({ action: "create", id: jobId, review_token: reviewToken, challenge: challenge.value })));
        if (epoch !== state.epoch) return;
        state.plan = plan; renderPlan(); message("Local plan created. No fields have been filled.");
      } catch (error) { if (epoch === state.epoch) { message(error.message, true); create.disabled = false; } }
      finally { if (epoch === state.epoch) state.busy = false; }
    });
    if (!reviewToken) { create.disabled = true; reviewed.disabled = true; content.append(el("p", "Creation requires a current approved packet review. Existing plans remain available for recovery below.")); }
    content.append(create);
    const recovery = el("section", undefined, "detail-section"); add(recovery, el("h3", "Recover or reconcile an existing plan")); content.append(recovery);
    try {
      const existing = await api(`/api/assistance?job_id=${encodeURIComponent(jobId)}`);
      if (epoch !== state.epoch) return;
      for (const plan of Array.isArray(existing.plans) ? existing.plans : []) {
        if (plan && /^[a-f0-9]{32}$/.test(plan.plan_id)) recovery.append(button(`Review ${plan.plan_id} · ${plan.state || "unknown"}`, "", () => loadPlan(plan.plan_id)));
      }
      if (recovery.childElementCount === 1) recovery.append(el("p", "No earlier local plans are recorded for this job."));
    } catch (error) { if (epoch === state.epoch) recovery.append(el("p", error.message)); }
  };
  if (isFixture) {
    content = document.getElementById("assistance-content"); status = document.getElementById("assistance-status");
    if (content && status) loadPlan(fixtureMatch[1]);
  }
})();
