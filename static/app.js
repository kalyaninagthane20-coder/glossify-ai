// Glossify AI front end. Plain JavaScript, no build step.
// All user text is inserted with textContent (never innerHTML) to avoid XSS.

const state = { documentId: null, document: null };

const $ = (id) => document.getElementById(id);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    node.append(child instanceof Node ? child : document.createTextNode(child ?? ""));
  }
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  if (response.status === 204) return null;
  const body = response.headers.get("content-type")?.includes("json") ? await response.json() : null;
  if (!response.ok) {
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : detail?.message || `Request failed (${response.status})`;
    throw new Error(message);
  }
  return body;
}

function setStatus(message) {
  $("status").textContent = message;
}

// ── documents ──────────────────────────────────────────────

async function loadDocuments() {
  const docs = await api("/api/documents");
  const list = $("doc-list");
  list.replaceChildren();
  if (!docs.length) list.append(el("span", { class: "muted" }, "No documents yet."));
  for (const doc of docs) {
    list.append(el("button", { onclick: () => openDocument(doc.id) },
      `${doc.filename} (${doc.source_lang}→${doc.target_lang}, ${doc.segment_count} blocks)`));
  }
}

async function openDocument(id) {
  state.documentId = id;
  state.document = await api(`/api/documents/${id}`);
  renderDocument();
}

function renderDocument() {
  const doc = state.document;
  $("doc-title").textContent = doc ? `${doc.filename} (${doc.source_lang}→${doc.target_lang})` : "Select a document";
  for (const id of ["btn-translate", "btn-docx", "btn-txt"]) $(id).disabled = !doc;

  const container = $("segments");
  container.replaceChildren();
  if (!doc) return;

  const approved = doc.segments.filter((s) => s.status === "approved").length;
  setStatus(`${approved} of ${doc.segments.length} blocks approved.`);

  for (const seg of doc.segments) container.append(renderSegment(seg));
}

function renderSegment(seg) {
  const textarea = el("textarea", { rows: 3 });
  textarea.value = seg.target_text || "";

  const meta = [
    el("span", { class: "badge" }, seg.block_type.replace("_", " ")),
    el("span", { class: `st-${seg.status}` }, seg.status.replace("_", " ")),
  ];
  if (seg.method) meta.push(el("span", { class: "badge" }, seg.method));
  if (seg.score !== null && seg.score !== undefined) meta.push(el("span", { class: "badge" }, `match ${Math.round(seg.score * 100)}%`));
  if (seg.page) meta.push(el("span", { class: "badge" }, `page ${seg.page}`));

  const issues = (seg.qa_issues || []).map((issue) => el("div", { class: "issue" }, `⚠ ${issue}`));

  return el("div", { class: "seg" },
    el("div", { class: "meta" }, ...meta),
    el("div", { class: "src" }, seg.source_text),
    textarea,
    ...issues,
    el("div", { class: "row", style: "margin-top:6px" },
      el("button", { onclick: () => saveSegment(seg.id, textarea.value) }, "Save edit"),
      el("button", { class: "primary", onclick: () => approveSegment(seg.id) }, "Approve"),
      el("button", { onclick: () => rejectSegment(seg.id) }, "Reject"),
    ),
  );
}

async function refreshDocument(message) {
  state.document = await api(`/api/documents/${state.documentId}`);
  renderDocument();
  if (message) setStatus(message);
}

// ── actions ────────────────────────────────────────────────

$("upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = new FormData(event.target);
  $("upload-status").textContent = "Uploading and parsing…";
  try {
    const doc = await api("/api/documents", { method: "POST", body: form });
    $("upload-status").textContent = `Uploaded ${doc.segment_count} blocks.`;
    await loadDocuments();
    await openDocument(doc.id);
  } catch (err) {
    $("upload-status").textContent = err.message;
  }
});

$("btn-translate").addEventListener("click", async () => {
  setStatus("Translating…");
  try {
    const report = await api(`/api/documents/${state.documentId}/translate`, { method: "POST" });
    const methods = Object.entries(report.by_method).map(([k, v]) => `${v} ${k}`).join(", ");
    await refreshDocument(`Translated ${report.translated} blocks (${methods}). ${report.flagged} need review.`);
  } catch (err) {
    setStatus(err.message);
  }
});

async function saveSegment(id, text) {
  try {
    await api(`/api/segments/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify({ target_text: text }) });
    await refreshDocument("Saved.");
  } catch (err) { setStatus(err.message); }
}

async function approveSegment(id) {
  try {
    await api(`/api/segments/${id}/approve`, { method: "POST" });
    await refreshDocument("Approved. The pair was added to the translation memory.");
  } catch (err) { setStatus(err.message); }
}

async function rejectSegment(id) {
  const comment = prompt("Why is this rejected? (optional)") || null;
  try {
    await api(`/api/segments/${id}/reject`, { method: "POST", headers: { "Content-Type": "application/json" },
                                              body: JSON.stringify({ comment }) });
    await refreshDocument("Rejected.");
  } catch (err) { setStatus(err.message); }
}

function download(format) {
  const unapproved = state.document.segments.filter((s) => s.status !== "approved").length;
  if (unapproved && !confirm(`${unapproved} blocks are not approved yet. Export anyway?`)) return;
  const force = unapproved ? "&force=true" : "";
  window.location.href = `/api/documents/${state.documentId}/export?format=${format}${force}`;
}
$("btn-docx").addEventListener("click", () => download("docx"));
$("btn-txt").addEventListener("click", () => download("txt"));

// ── glossary and translation memory ────────────────────────

async function loadGlossary() {
  const [src, tgt] = $("g-langs").value.split("→").map((s) => s.trim());
  if (!src || !tgt) return;
  const terms = await api(`/api/glossary?source_lang=${encodeURIComponent(src)}&target_lang=${encodeURIComponent(tgt)}`);
  const box = $("glossary-list");
  box.replaceChildren();
  for (const t of terms) {
    const label = t.kind === "term" ? `${t.source_term} → ${t.target_term}` : `avoid "${t.target_term}" for "${t.source_term}"`;
    box.append(el("div", {}, label, " ", el("button", { onclick: () => deleteTerm(t.id) }, "×")));
  }
}

async function deleteTerm(id) {
  await api(`/api/glossary/${id}`, { method: "DELETE" });
  await loadGlossary();
}

$("glossary-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const [src, tgt] = $("g-langs").value.split("→").map((s) => s.trim());
  try {
    await api("/api/glossary", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind: $("g-kind").value, source_lang: src, target_lang: tgt,
                             source_term: $("g-src").value, target_term: $("g-tgt").value || null }),
    });
    $("g-src").value = ""; $("g-tgt").value = "";
    await loadGlossary();
  } catch (err) { alert(err.message); }
});

let tmTimer = null;
$("tm-q").addEventListener("input", () => {
  clearTimeout(tmTimer);
  tmTimer = setTimeout(async () => {
    const q = $("tm-q").value.trim();
    const box = $("tm-results");
    box.replaceChildren();
    if (!q) return;
    const [src, tgt] = $("g-langs").value.split("→").map((s) => s.trim());
    const matches = await api(`/api/tm/search?q=${encodeURIComponent(q)}&source_lang=${src}&target_lang=${tgt}&limit=5`);
    if (!matches.length) box.textContent = "No matches.";
    for (const m of matches) {
      box.append(el("div", { style: "margin-bottom:6px" },
        el("div", {}, `${Math.round(m.score * 100)}% · ${m.source_text}`),
        el("div", { class: "muted" }, `→ ${m.target_text}`)));
    }
  }, 250);
});

loadDocuments();
loadGlossary();
