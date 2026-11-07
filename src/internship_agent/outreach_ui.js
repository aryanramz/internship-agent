"use strict";

(() => {
  const tabs = { contacts: "Contacts", drafts: "Drafts", messages: "Messages", followups: "Follow-up suggestions" };
  const show = (value) => value === null || value === undefined || value === "" ? "Not recorded" : typeof value === "object" ? JSON.stringify(value, null, 2) : String(value);
  const list = (value) => Array.isArray(value) ? value : [];
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function add(parent, ...children) { children.flat().filter(Boolean).forEach((child) => parent.append(child)); return parent; }
  function button(label, id, action, primary = false) {
    const node = el("button", label, `button ${primary ? "primary" : "secondary"}`);
    node.type = "button";
    if (id) node.id = id;
    node.addEventListener("click", action);
    return node;
  }
  function pair(parent, name, value) { add(parent, el("dt", name), el("dd", show(value))); }
  function section(title) { return add(el("section", undefined, "detail-section"), el("h3", title)); }
  function field(parent, spec) {
    const wrap = el("div"); wrap.style.marginBottom = "16px";
    const id = `outreach-field-${spec.name}`;
    const label = el("label", spec.label); label.htmlFor = id;
    const input = el(spec.options ? "select" : spec.multiline ? "textarea" : "input");
    input.id = id; input.name = spec.name;
    if (spec.options) {
      for (const option of spec.options) {
        const [value, caption] = Array.isArray(option) ? option : [option, option];
        const node = el("option", caption); node.value = value; input.append(node);
      }
    } else {
      if (!spec.multiline) input.type = spec.type || "text";
      input.maxLength = spec.max || 1000;
      if (spec.multiline) input.rows = spec.rows || 5;
    }
    input.style.width = "100%";
    input.required = Boolean(spec.required);
    input.autocomplete = "off";
    if (spec.placeholder) input.placeholder = spec.placeholder;
    if (spec.value !== undefined && spec.value !== null) input.value = String(spec.value);
    add(wrap, label, input);
    if (spec.help) { const help = el("p", spec.help, "field-help"); help.id = `${id}-help`; input.setAttribute("aria-describedby", help.id); wrap.append(help); }
    parent.append(wrap);
    return input;
  }
  async function api(path, options = {}) {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof result.error === "string" ? result.error : "The local outreach request failed. Refresh and review the record before trying again.");
    return result;
  }
  async function post(payload) {
    const session = await api("/api/session");
    if (!session.csrf) throw new Error("Your local session expired. Unlock the workspace and review this action again.");
    return api("/api/outreach", { method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf }, body: JSON.stringify({ ...payload, confirm: payload.action }) });
  }

  window.renderOutreach = async (container) => {
    const state = { tab: "contacts", page: 1, job: "", request: 0, busy: false };
    const root = el("div"); root.id = "outreach-root";
    const heading = el("div", undefined, "page-heading");
    add(heading, add(el("div"), el("h1", "Recruiter outreach"), el("p", "Keep contact evidence, reviewed drafts and correspondence together.", "muted")));
    const intro = el("div", undefined, "info-box");
    add(intro, el("strong", "Local drafts, with you in control."), el("p", "Register documented contacts, verify their evidence, then review an exact draft before exporting it. Sending happens outside this workspace; a manual send record is operator evidence and does not establish employer receipt."));
    const nav = el("nav", undefined, "detail-actions"); nav.setAttribute("aria-label", "Outreach sections");
    const status = el("p", "", "form-message"); status.id = "outreach-status"; status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
    const content = el("div"); content.id = "outreach-content";
    add(root, heading, intro, nav, status, content); container.replaceChildren(root);
    const active = () => container.contains(root);
    function message(text, error = false) {
      status.textContent = text; status.setAttribute("role", error ? "alert" : "status");
      status.style.color = error ? "var(--danger)" : "var(--muted)";
    }
    for (const [key, label] of Object.entries(tabs)) {
      const tab = button(label, `outreach-tab-${key}`, () => { state.tab = key; state.page = 1; load(key); });
      nav.append(tab);
    }
    function markTab() {
      for (const node of nav.children) {
        const selected = node.id === `outreach-tab-${state.tab}`;
        node.className = `button ${selected ? "primary" : "secondary"}`;
        if (selected) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current");
      }
    }
    function details(title, data, keys) {
      const block = section(title), dl = el("dl", undefined, "key-value");
      for (const [key, label] of keys) pair(dl, label, data[key]);
      block.append(dl); return block;
    }
    function rawDetails(parent, title, value) {
      function safe(record) {
        if (Array.isArray(record)) return record.map(safe);
        if (record && typeof record === "object") return Object.fromEntries(Object.entries(record).filter(([key]) => !/token|password|secret|credential/i.test(key)).map(([key, item]) => [key, safe(item)]));
        return record;
      }
      const block = el("details", undefined, "detail-section"), pre = el("pre", show(safe(value)), "evidence");
      block.append(el("summary", title, "text-button"));
      pre.style.whiteSpace = "pre-wrap"; pre.style.overflowWrap = "anywhere"; block.append(pre); parent.append(block);
    }
    function warnings(parent, values) {
      if (!list(values).length) return;
      const box = el("div", undefined, "info-box"); box.setAttribute("role", "note");
      add(box, el("strong", "Review warnings"));
      const ul = el("ul"); list(values).forEach((item) => ul.append(el("li", show(item)))); box.append(ul); parent.append(box);
    }
    function back(parent) { parent.append(button(`Back to ${tabs[state.tab].toLowerCase()}`, "outreach-back", () => load(state.tab))); }
    function actionDialog({ title, action, help, phrase, specs = [], payload = {}, preview, build, after, setup }) {
      if (state.busy || !active() || root.querySelector("dialog")) return;
      const previousFocus = document.activeElement;
      const dialog = el("dialog", undefined, "detail-dialog"); dialog.id = "outreach-dialog";
      dialog.setAttribute("aria-labelledby", "outreach-dialog-title");
      const form = el("form");
      const top = el("div", undefined, "dialog-top"), titleNode = el("h2", title); titleNode.id = "outreach-dialog-title";
      add(top, titleNode, button("Cancel", "outreach-dialog-close", () => dialog.close()));
      const body = el("div", undefined, "detail-content"); body.style.paddingTop = "20px";
      body.append(el("p", help, "muted"));
      if (preview) rawDetails(body, "Exact record for this action", preview);
      const inputs = {};
      for (const spec of specs) inputs[spec.name] = field(body, spec);
      let typed;
      if (phrase) {
        typed = field(body, { name: "phrase", label: `Type ${phrase} to confirm`, required: true, max: 200 });
        typed.id = "outreach-confirm-phrase"; body.querySelector('label[for="outreach-field-phrase"]').htmlFor = typed.id;
        typed.spellcheck = false;
      }
      const checked = el("input"); checked.type = "checkbox"; checked.required = true; checked.id = "outreach-confirm-checkbox";
      const checkLabel = el("label", undefined, "check-label");
      add(checkLabel, checked, el("span", "I reviewed these exact details and explicitly confirm this local action.")); body.append(checkLabel);
      const error = el("p", "", "form-message"); error.id = "outreach-confirm-error"; error.setAttribute("role", "alert"); body.append(error);
      const actions = el("div", undefined, "dialog-actions");
      const submit = el("button", title, "button primary"); submit.type = "submit"; submit.id = "outreach-confirm-submit"; submit.disabled = true;
      add(actions, button("Cancel", "outreach-confirm-cancel", () => dialog.close()), submit);
      form.addEventListener("input", (event) => {
        if (event.target !== checked) checked.checked = false;
        submit.disabled = !checked.checked || Boolean(phrase && typed.value !== phrase);
      });
      form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (state.busy || !checked.checked || (phrase && typed.value !== phrase) || !form.reportValidity()) return;
        const values = Object.fromEntries(Object.entries(inputs).map(([key, node]) => [key, node.value]));
        if (phrase) values.phrase = typed.value;
        try {
          const extra = build ? build(values) : values;
          state.busy = true; form.setAttribute("aria-busy", "true");
          for (const node of form.elements) node.disabled = true;
          const result = await post({ action, ...payload, ...extra });
          dialog.close();
          if (!active()) return;
          message(`${title} completed locally.`);
          if (after) await after(result); else await load(state.tab);
        } catch (err) {
          if (["review-draft", "verify-contact"].includes(action)) {
            dialog.close();
            if (active()) {
              await load(action === "review-draft" ? "draft" : "contact", { id: payload.id });
              message(`${err.message} The record was refreshed; inspect the displayed evidence and start a new review.`, true);
            }
            return;
          }
          if (dialog.isConnected) error.textContent = err.message; else message(err.message, true);
          for (const node of form.elements) node.disabled = false;
          checked.checked = false; submit.disabled = true;
        } finally { state.busy = false; form.removeAttribute("aria-busy"); }
      });
      dialog.addEventListener("cancel", (event) => { if (state.busy) event.preventDefault(); });
      dialog.addEventListener("close", () => { dialog.remove(); if (previousFocus && previousFocus.isConnected) previousFocus.focus(); }, { once: true });
      add(form, top, body, actions); dialog.append(form); root.append(dialog); dialog.showModal();
      if (setup) setup(body, inputs, () => { checked.checked = false; submit.disabled = true; });
      const first = dialog.querySelector("input,select,textarea"); if (first) first.focus();
    }
    function contactSpecs(contact = {}) {
      return [
        { name: "job_id", label: "Exact job ID", required: true, value: contact.job_id, max: 200 },
        { name: "employer", label: "Employer (exact job company)", required: true, value: contact.employer, max: 200 },
        { name: "employer_domain", label: "Employer domain", required: true, value: contact.employer_domain, max: 253, placeholder: "employer.example" },
        { name: "name", label: "Contact name", required: true, value: contact.name, max: 200 },
        { name: "email", label: "Documented email address", required: true, type: "email", value: contact.email, max: 254, help: "Copy an evidenced address. Do not infer an email pattern." },
        { name: "role", label: "Documented role (optional)", value: contact.role, max: 200 },
        { name: "source_url", label: "Source URL (or provide documentation below)", value: contact.source_url, max: 1000, placeholder: "https://employer.example/team" },
        { name: "documentation", label: "Evidence / documentation", multiline: true, value: contact.documentation, max: 3000, help: "Manual documentation must identify the exact employer and email address. Official sources must use the exact employer HTTPS domain." },
        { name: "observed_at", label: "Evidence observed at (UTC ISO timestamp)", required: true, value: contact.observed_at, max: 40, placeholder: "2026-11-06T12:00:00Z" },
        { name: "method", label: "Evidence method", options: [["manual", "Manual documentation"], ["official", "Official employer source"]], value: contact.method || "manual" },
        { name: "permission", label: "Contact permission", options: [["unknown", "Unknown — requires review"], ["allowed", "Allowed — documented"], ["denied", "Denied"]], value: contact.permission || "unknown" }
      ];
    }
    async function contactForm(contact) {
      let jobs = [];
      if (!contact) {
        try { jobs = list((await api("/api/jobs?page=1")).jobs).slice(0, 25); }
        catch (error) { message(`Job choices unavailable; enter the exact job ID manually. ${error.message}`, true); }
      }
      actionDialog({ title: contact ? "Save contact revision" : "Register documented contact", action: contact ? "edit-contact" : "register-contact", payload: contact ? { id: contact.id } : {}, specs: contactSpecs(contact), help: "Record the exact employer/job binding and contact evidence. Registration does not verify the contact. Editing requires a fresh verification before drafting.", setup: (body, inputs, invalidate) => {
        if (contact) { inputs.job_id.readOnly = true; return; }
        const block = el("div"), choose = field(block, { name: "job-choice", label: "Choose a saved job (first 25)", options: [["", "Enter a job ID manually, or choose a saved job"], ...jobs.map((job) => [job.id, `${job.company} — ${job.title} (${job.id})`])] });
        body.prepend(block);
        choose.addEventListener("change", () => { const job = jobs.find((item) => item.id === choose.value); if (job) { inputs.job_id.value = job.id; inputs.employer.value = job.company; } invalidate(); });
      }, after: (result) => load("contact", { id: result.contact_id }) });
    }
    async function createDraft(contact) {
      let contacts = contact ? [contact] : [];
      if (!contact) {
        try { contacts = list((await api("/api/outreach?view=contacts&page=1")).contacts); }
        catch (error) { message(error.message, true); return; }
      }
      let bound = null, lookup = 0;
      actionDialog({ title: "Create local draft", action: "create-draft", help: "Use a verified contact and the exact current reviewed document packet. Draft text is limited to current verified facts; unknown details stay unknown. This action creates a local draft.", specs: [
        { name: "contact_id", label: "Verified contact ID", required: true, value: contact && contact.id, max: 100, help: "Choose a contact below or enter its exact local ID." },
        { name: "purpose", label: "Purpose", options: [["intro", "Introduction"], ["application_followup", "Application follow-up"], ["reply", "Reply to a matched message"]] },
        { name: "source_message_id", label: "Local source message ID (required for replies)", max: 100 }
      ], setup: (body, inputs, invalidate) => {
        const choices = el("div"), choose = field(choices, { name: "contact-choice", label: "Choose a documented contact (first page)", options: [["", "Choose a contact"], ...contacts.map((item) => [item.contact_id || item.id, `${item.name} — ${item.employer} (${item.state})`])], value: contact && contact.id }); body.prepend(choices);
        const binding = section("Current document packet"); binding.id = "outreach-packet-binding"; body.append(binding);
        async function inspect() {
          const current = ++lookup, id = inputs.contact_id.value.trim(); bound = null; invalidate();
          binding.replaceChildren(el("h3", "Current document packet"), el("p", "Loading the exact contact and current document review…"));
          if (!id) { binding.append(el("p", "Choose or enter a verified contact to inspect its exact job packet.")); return; }
          try {
            const selected = await api(`/api/outreach?${new URLSearchParams({ view: "contact", id })}`);
            const review = await api(`/api/review?${new URLSearchParams({ id: selected.job_id })}`);
            if (current !== lookup || !binding.isConnected) return;
            bound = { contact_id: id, token: review.review_token };
            binding.replaceChildren(el("h3", "Current document packet"));
            binding.append(details("Exact job / document binding", review, [["job_id", "Job ID"], ["status", "Application state"], ["revision", "Document revision"], ["packet_sha256", "Packet fingerprint"], ["job_sha256", "Job fingerprint"]]));
            binding.append(el("p", `Contact: ${show(selected.name)} · ${show(selected.email)} · ${show(selected.state)}. The backend requires this exact packet to be already approved; approve it in Review & tracking first if needed.`, "field-help"));
          } catch (error) { if (current === lookup && binding.isConnected) binding.replaceChildren(el("h3", "Document packet unavailable"), el("p", error.message, "form-message")); }
        }
        choose.addEventListener("change", () => { inputs.contact_id.value = choose.value; inspect(); });
        inputs.contact_id.addEventListener("input", () => { bound = null; lookup++; invalidate(); binding.replaceChildren(el("p", "Leave the contact ID field to inspect its exact packet.")); });
        inputs.contact_id.addEventListener("change", inspect); inspect();
      }, build: (values) => {
        if (!bound || bound.contact_id !== values.contact_id.trim() || !bound.token) throw new Error("Inspect the selected contact's current reviewed document packet before confirming.");
        return { ...values, contact_id: bound.contact_id, packet_review_token: bound.token };
      }, after: (result) => { state.tab = "drafts"; return load("draft", { id: result.draft_id }); } });
    }
    function renderContact(contact) {
      contact = { ...contact, id: contact.contact_id };
      back(content); content.append(el("h2", show(contact.name)));
      warnings(content, contact.warnings);
      content.append(details("Contact evidence", contact, [["id", "Contact ID"], ["state", "Verification state"], ["job_id", "Job ID"], ["employer", "Employer"], ["employer_domain", "Domain"], ["email", "Email"], ["role", "Role"], ["permission", "Permission"], ["suppressed", "Suppressed"], ["suppression_reason", "Suppression reason"], ["source_url", "Source URL (text only)"], ["documentation", "Documentation"], ["observed_at", "Observed at"], ["method", "Evidence method"], ["verifier", "Verifier"]]));
      const actions = el("div", undefined, "detail-actions");
      add(actions,
        button("Verify contact evidence", "outreach-verify-contact", () => actionDialog({ title: "Verify contact evidence", action: "verify-contact", payload: { id: contact.id, expected_contact_hash: contact.contact_hash }, phrase: `VERIFY ${contact.id}`, preview: contact, help: "Confirm the exact contact, employer/job binding, source evidence, observation time and permission. This records your local verification of the displayed evidence.", specs: [{ name: "verifier", label: "Verifier / evidence reviewer", required: true, max: 200 }, { name: "method", label: "Verification method", options: ["manual", "official"], value: contact.method }, ...(contact.state === "conflict" ? [{ name: "resolution", label: "Conflict resolution evidence", required: true, max: 1000, help: "Redact the incorrect competing contact first, then document the evidence resolving this conflict." }] : [])], after: (result) => load("contact", { id: result.contact_id }) })),
        button("Edit evidence", "outreach-edit-contact", () => contactForm(contact)),
        button("Configure follow-up suggestions", "outreach-followup-policy", () => actionDialog({ title: "Configure suggestion policy", action: "followup-policy", payload: { contact_id: contact.id }, help: "Suggestions only: require documented permission and confirmed operator send evidence. Replies, bounces, opt-outs, uncertain evidence and closed outcomes suppress them. No email is sent.", specs: [
          { name: "interval_days", label: "Days after recorded send (7–90)", type: "number", required: true, value: "14" },
          { name: "min_days", label: "Minimum contact interval (7–90)", type: "number", required: true, value: "7" },
          { name: "enabled", label: "Suggestion policy", options: [["false", "Disabled"], ["true", "Enabled — suggestions only"]] }
        ], build: values => ({ interval_days: Number(values.interval_days), min_days: Number(values.min_days), enabled: values.enabled === "true" }), after: () => load("contact", { id: contact.id }) })),
        button("Create draft for contact", "outreach-contact-create-draft", () => createDraft(contact), true),
        button("Record opt-out", "outreach-optout-contact", () => actionDialog({ title: "Record contact opt-out", action: "optout", payload: { id: contact.id }, phrase: `OPTOUT ${contact.id}`, preview: contact, help: "Record this contact's opt-out and suppress further outreach suggestions. Review the exact contact before confirming.", after: () => load("contact", { id: contact.id }) })),
        button("Redact contact", "outreach-redact-contact", () => actionDialog({ title: "Redact contact details", action: "redact-contact", payload: { id: contact.id }, phrase: `REDACT ${contact.id}`, preview: contact, help: "Remove stored personal contact content. The local audit identity may remain. Review the exact contact before confirming redaction.", after: () => load("contact", { id: contact.id }) }))
      ); content.append(actions);
    }
    function draftPreview(draft) {
      return { id: draft.id, revision: draft.revision, content_hash: draft.content_hash, current: draft.current, contact: draft.contact, purpose: draft.purpose, subject: draft.subject, body: draft.body, job_id: draft.job_id, facts: draft.facts, binding: draft.binding, provenance: draft.provenance, source_provenance: draft.source_provenance, warnings: draft.warnings };
    }
    function renderDraft(draft) {
      draft = { ...draft, id: draft.draft_id, state: !draft.current ? "Evidence changed — review unavailable" : draft.review_token ? "Reviewed exact revision" : "Unreviewed revision" };
      back(content); content.append(el("h2", "Review the full draft"));
      warnings(content, draft.warnings);
      content.append(details("Exact draft binding", draft, [["id", "Draft ID"], ["revision", "Revision"], ["purpose", "Purpose"], ["state", "State"], ["job_id", "Job ID"], ["contact", "Recipient"], ["content_hash", "Content fingerprint"]]));
      const preview = section("Full message preview");
      const body = el("pre", show(draft.body), "evidence"); body.style.whiteSpace = "pre-wrap";
      add(preview, el("h3", show(draft.subject)), body); content.append(preview);
      rawDetails(content, "Source provenance and revision details", draft);
      const actions = el("div", undefined, "detail-actions");
      add(actions,
        button("Edit draft revision", "outreach-edit-draft", () => actionDialog({ title: "Save draft revision", action: "edit-draft", payload: { id: draft.id }, help: "Edits clear the previous review. Use only current verified facts and review the complete revised draft before export or recording a manual send.", specs: [{ name: "subject", label: "Subject", required: true, value: draft.subject, max: 200 }, { name: "body", label: "Full message body", required: true, multiline: true, rows: 14, value: draft.body, max: 10000 }], after: (result) => load("draft", { id: result.draft_id }) })),
        button("Review exact draft", "outreach-review-draft", () => actionDialog({ title: "Review exact draft", action: "review-draft", payload: { id: draft.id, expected_revision: draft.revision, expected_content_hash: draft.content_hash }, phrase: `REVIEW ${draft.id}`, preview: draftPreview(draft), help: "Review the complete recipient, subject, body, current verified sources, job/document binding and warnings. This review applies only to the displayed revision; refresh the draft if its content has changed.", after: (result) => load("draft", { id: result.draft_id }) }), true)
      );
      const exportButton = button("Export reviewed RFC822 draft", "outreach-export-draft", () => actionDialog({ title: "Export reviewed draft", action: "export-draft", payload: { id: draft.id, review_token: draft.review_token }, preview: draftPreview(draft), help: "Download the exact reviewed local draft as an .eml file. Export does not send a message or authorize sending.", after: async (result) => {
        if (typeof result.rfc822 !== "string") throw new Error("The export returned no RFC822 text. Review the draft before trying again.");
        const url = URL.createObjectURL(new Blob([result.rfc822], { type: "message/rfc822" }));
        const link = el("a"); link.href = url; link.download = "outreach-draft.eml"; root.append(link); link.click(); link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000); message("Reviewed draft exported locally. No message was sent.");
      } }));
      const recordButton = button("Record manually sent message", "outreach-record-send", () => actionDialog({ title: "Record manual send evidence", action: "record-send", payload: { id: draft.id, review_token: draft.review_token }, preview: draftPreview(draft), help: "Record evidence of an action you already performed outside this workspace. This does not send, authorize sending, verify delivery or establish an application outcome.", specs: [
        { name: "sent_at", label: "Actual sent time (UTC ISO timestamp)", required: true, max: 40, placeholder: "2026-11-06T12:00:00Z" },
        { name: "message_id", label: "Exact external message ID", required: true, max: 254, placeholder: "<message-id@employer.example>" },
        { name: "thread_id", label: "Exact external thread ID", required: true, max: 254 },
        { name: "evidence", label: "Manual send evidence", required: true, multiline: true, max: 2000 },
        { name: "certainty", label: "Evidence certainty", options: [["uncertain", "Uncertain — reconcile before any retry"], ["confirmed", "Confirmed by supplied evidence"]] }
      ], after: () => load("draft", { id: draft.id }) }));
      exportButton.disabled = !draft.review_token || !draft.current; recordButton.disabled = !draft.review_token || !draft.current;
      add(actions, exportButton, recordButton); content.append(actions);
      if (!draft.review_token) content.append(el("p", "Review this exact revision to enable export and manual send recording.", "field-help"));
    }
    function importMessage() {
      actionDialog({ title: "Import local message fixture", action: "import-message", help: "Paste one JSON message object. The message stays untrusted local evidence, and its body is displayed as text. Import performs no mailbox connection or external fetch.", specs: [{ name: "fixture", label: "Message JSON object", required: true, multiline: true, rows: 13, max: 20000, help: 'Fields: message_id, thread_id, from_email, to_email, sent_at (UTC ISO), subject, body. Optional: cc, in_reply_to, references, text_format (plain/html), forwarded, bounce, optout.' }], build: (values) => {
        let value; try { value = JSON.parse(values.fixture); } catch (_) { throw new Error("Enter a valid JSON message object."); }
        if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("The fixture must be one JSON object.");
        if (typeof value.body !== "string" || value.body.length > 8000) throw new Error("The message body must be text with at most 8,000 characters.");
        return { message: value };
      }, after: (result) => load("message", { id: result.message.id }) });
    }
    function renderMessage(item) {
      back(content); content.append(el("h2", show(item.subject)));
      content.append(el("p", "Imported correspondence is untrusted operator-supplied evidence. Matching records a local association; it does not establish employer receipt or a hiring outcome.", "info-box"));
      warnings(content, [...list(item.warnings), ...(item.optout ? ["Opt-out detected: do not contact this recipient."] : []), ...(item.bounce ? ["Bounce detected: delivery is not established."] : []), ...(item.collided ? ["Message identity collision: manual reconciliation required."] : []), ...(item.body_truncated ? ["Only a bounded excerpt of the body is displayed."] : [])]);
      content.append(details("Message identity and matching", item, [["id", "Local ID"], ["message_id", "External message ID"], ["thread_id", "Thread ID"], ["from_email", "From"], ["to_email", "To"], ["sent_at", "Message date"], ["match_state", "Match state"], ["reason", "Matching reason"], ["contact_id", "Associated contact"], ["send_id", "Associated manual send"], ["source", "Evidence source"], ["redacted", "Redacted"], ["text_format", "Original format"]]));
      const body = section("Message body — text only"); const pre = el("pre", show(item.body), "evidence"); pre.style.whiteSpace = "pre-wrap"; body.append(pre); content.append(body);
      rawDetails(content, "Stored message metadata", Object.fromEntries(Object.entries(item).filter(([key]) => key !== "body")));
      const actions = el("div", undefined, "detail-actions");
      add(actions,
        button("Evaluate local message match", "outreach-match-message", () => actionDialog({ title: "Evaluate local message match", action: "match-message", payload: { id: item.id }, preview: { id: item.id, from_email: item.from_email, to_email: item.to_email, message_id: item.message_id, thread_id: item.thread_id, match_state: item.match_state }, help: "Evaluate bounded message identity against recorded manual-send evidence. Ambiguous or unrelated correspondence remains unmatched; no hiring outcome is inferred.", after: () => load("message", { id: item.id }) })),
        button("Redact message content", "outreach-redact-message", () => actionDialog({ title: "Redact message content", action: "redact-message", payload: { id: item.id }, preview: { id: item.id, subject: item.subject, from_email: item.from_email }, help: "Remove stored message content and personal metadata according to local retention rules. Review the exact local message before confirming.", after: () => load("message", { id: item.id }) }))
      ); content.append(actions);
    }
    function renderList(view, data) {
      const tools = el("div", undefined, "detail-actions");
      if (view === "contacts") tools.append(button("Register contact", "outreach-register-contact", () => contactForm(), true));
      if (view === "drafts") tools.append(button("Create local draft", "outreach-create-draft", () => createDraft(), true));
      if (view === "messages") {
        tools.append(button("Import message JSON", "outreach-import-message", importMessage, true));
        tools.append(button("Redact older message content", "outreach-prune-messages", () => actionDialog({ title: "Redact older message content", action: "prune-messages", help: "Redact content imported before the selected retention cutoff, in one bounded batch of up to 100 messages. Suppression and audit hashes remain. This action runs only when you explicitly confirm it.", specs: [{ name: "retention_days", label: "Retention period in days (30–3650)", required: true, type: "number", value: 365, max: 4 }], build: (values) => {
          const days = Number(values.retention_days);
          if (!Number.isInteger(days) || days < 30 || days > 3650) throw new Error("Enter a whole retention period from 30 to 3650 days.");
          return { retention_days: days };
        }, after: async (result) => { await load("messages"); message(`${result.redacted_count} older message(s) redacted locally.${result.more_eligible ? " More records qualify; another batch requires separate confirmation." : ""}`); } })));
      }
      tools.append(button("Refresh", "outreach-refresh", () => load(view))); content.append(tools);
      if (["contacts", "drafts"].includes(view)) {
        const filter = el("form", undefined, "filters");
        const input = field(filter, { name: "filter-job", label: "Filter by exact job ID", value: state.job, max: 200 });
        const go = el("button", "Apply filter", "button secondary"); go.type = "submit"; filter.append(go);
        filter.addEventListener("submit", (event) => { event.preventDefault(); state.job = input.value.trim(); state.page = 1; load(view); }); content.append(filter);
      }
      if (view === "followups") content.append(el("p", "Suggestions are read-only reminders for human review. Opt-outs, bounces, replies and uncertain send evidence can suppress them. Dismissing a suggestion sends nothing.", "info-box"));
      const items = list(data[view] || data.items), panel = el("section", undefined, "panel");
      panel.setAttribute("aria-label", tabs[view]);
      add(panel, add(el("div", undefined, "panel-header"), el("h2", tabs[view]), el("span", `${data.total === undefined ? items.length : data.total} recorded`, "muted")));
      if (!items.length) add(panel, add(el("div", undefined, "empty-state"), el("h3", view === "followups" ? "No follow-up suggestions" : `No ${tabs[view].toLowerCase()} recorded`), el("p", view === "contacts" ? "Start with a documented contact for an exact saved job." : view === "drafts" ? "Verify a documented contact and review the current document packet first." : view === "messages" ? "Import a bounded message fixture to inspect its evidence and matching state." : "Suggestions appear only when the local evidence and timing allow them.")));
      for (const item of items) {
        const row = el("article", undefined, "panel-body"); row.style.borderTop = "1px solid var(--line)";
        let title, detail;
        if (view === "contacts") { title = show(item.name); detail = `${show(item.employer)} · ${show(item.email)} · ${show(item.state)} · permission: ${show(item.permission)}`; }
        else if (view === "drafts") { title = show(item.subject); detail = `${show(item.purpose)} · revision ${show(item.revision)} · ${show(item.state)}`; }
        else if (view === "messages") { title = show(item.subject); detail = `${show(item.from_email)} · ${show(item.sent_at)} · match: ${show(item.match_state)}`; }
        else { title = "Follow-up for human review"; detail = `Contact ${show(item.contact_id)} · job ${show(item.job_id)} · due ${show(item.due_at)}`; }
        add(row, el("h3", title), el("p", detail, "muted"));
        if (view !== "followups") {
          const singular = { contacts: "contact", drafts: "draft", messages: "message" }[view];
          const id = item[`${singular}_id`] || item.id;
          const open = button(`View ${singular}`, null, () => load(singular, { id })); open.dataset[`${singular}Id`] = id; row.append(open);
        } else {
          row.append(el("p", `Suggestion ID: ${show(item.id)} · ${show(item.kind)}`, "field-help"));
          const dismiss = button("Dismiss suggestion", null, () => actionDialog({ title: "Dismiss follow-up suggestion", action: "dismiss-followup", payload: { id: item.id }, preview: item, help: "Dismiss this local reminder. This does not create or send any message.", after: () => load("followups") })); dismiss.dataset.followupId = item.id; row.append(dismiss);
        }
        panel.append(row);
      }
      content.append(panel);
      if (Number(data.pages) > 1) {
        const pages = el("nav", undefined, "pagination"); pages.setAttribute("aria-label", "Outreach pagination");
        const prev = button("Previous", "outreach-page-previous", () => { state.page--; load(view); }); prev.disabled = state.page <= 1;
        const next = button("Next", "outreach-page-next", () => { state.page++; load(view); }); next.disabled = state.page >= Number(data.pages);
        add(pages, prev, el("span", `Page ${state.page} of ${data.pages}`), next); content.append(pages);
      }
    }
    async function load(view, params = {}) {
      if (!active()) return;
      const current = ++state.request; markTab(); content.setAttribute("aria-busy", "true");
      content.replaceChildren(el("p", "Loading local outreach records…", "loading"));
      const query = new URLSearchParams({ view, ...params });
      if (["contacts", "drafts"].includes(view)) { query.set("page", String(state.page)); if (state.job) query.set("job_id", state.job); }
      try {
        const data = await api(`/api/outreach?${query}`);
        if (current !== state.request || !active()) return;
        content.replaceChildren();
        if (view === "contact") renderContact(data);
        else if (view === "draft") renderDraft(data);
        else if (view === "message") renderMessage(data);
        else renderList(view, data);
      } catch (error) {
        if (current !== state.request || !active()) return;
        content.replaceChildren(el("p", "Outreach records could not be loaded.", "empty-state"), button("Try again", "outreach-retry", () => load(view, params)));
        message(error.message, true);
      } finally { if (current === state.request) content.removeAttribute("aria-busy"); }
    }
    await load("contacts");
  };
})();
