/* quick_transcribe – page logic. Talks to the local server over JSON. Author: MEL */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));

const S = {
  settings: {}, models: [], languages: {}, dataDir: "",
  recs: [], sel: null, rec: null, segs: [], lastIdx: -1,
  query: "", hits: [], jobs: [], hiddenJobs: new Set(),
  liveTimer: null, jobsTimer: null, lastBusy: false, nowRow: -1,
};

// ---------- helpers ----------
async function api(method, url, body, raw) {
  const opt = { method, headers: {} };
  if (method !== "GET") opt.headers["X-QT"] = "1";
  if (raw) { opt.body = raw; }
  else if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
  let r;
  try { r = await fetch(url, opt); }
  catch (e) { throw new Error("quick_transcribe does not answer. Is it still running?"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
  return data;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function fmtT(t) {
  t = Math.max(0, Math.floor(t || 0));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function fmtDur(t) {
  if (!t) return "–";
  t = Math.round(t);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return h ? `${h} h ${m} min` : m ? `${m} min ${s} s` : `${s} s`;
}

let toastTimer = null;
function toast(msg, isErr) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = isErr ? "error" : "";
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (t.hidden = true), isErr ? 6000 : 2600);
}

function status(msg) { $("#statusText").textContent = msg || ""; }

const ACTIVE = new Set(["queued", "archiving", "loading", "running"]);

// ---------- start ----------
async function init() {
  try {
    const st = await api("GET", "/api/state");
    S.settings = st.settings; S.models = st.models; S.languages = st.languages; S.dataDir = st.data_dir;
    S.jobs = st.jobs;
    $("#ver").textContent = "v" + st.version;
    if (!st.fts) status("Full-text index (FTS5) not available in this SQLite; search uses slower LIKE.");
  } catch (e) { toast(e.message, true); return; }
  fillSelect($("#sModel"), S.models.map(m => [m, m]));
  fillSelect($("#rModel"), S.models.map(m => [m, m]));
  const langs = Object.entries(S.languages);
  fillSelect($("#sLang"), langs);
  fillSelect($("#rLang"), langs);
  await loadList();
  renderJobs();
  pollJobs();
  bind();
  const first = S.recs[0];
  if (first) select(first.id);
}

function fillSelect(sel, pairs) {
  sel.innerHTML = pairs.map(([v, t]) => `<option value="${esc(v)}">${esc(t)}</option>`).join("");
}

// ---------- list / search ----------
async function loadList() {
  const d = await api("GET", "/api/recordings");
  S.recs = d.recordings;
  if (!S.query) renderList();
}

function renderList() {
  const box = $("#list");
  if (S.query) {
    $("#listTitle").textContent = "Search results";
    $("#listCount").textContent = S.hits.length >= 200 ? "200+" : String(S.hits.length);
    if (!S.hits.length) { box.innerHTML = `<div class="nothing">Nothing found for “${esc(S.query)}”.</div>`; return; }
    const re = termsRegex(S.query);
    box.innerHTML = S.hits.map(h => `
      <div class="hit" data-rec="${h.recording_id}" data-idx="${h.idx}">
        <div class="hit-head"><b>${esc(h.name)}</b><span>${fmtT(h.start)}</span></div>
        <div class="hit-text">${markTerms(h.text, re)}</div>
      </div>`).join("");
    return;
  }
  $("#listTitle").textContent = "Recordings";
  $("#listCount").textContent = S.recs.length ? String(S.recs.length) : "";
  if (!S.recs.length) { box.innerHTML = `<div class="nothing">No recordings yet.</div>`; return; }
  box.innerHTML = S.recs.map(r => {
    const when = (r.recorded_at || r.created_at || "").slice(0, 16);
    const badge = r.status === "done" ? "" : `<span class="badge ${esc(r.status)}">${esc(r.status)}</span>`;
    const ed = r.n_edited ? ` · ${r.n_edited} edited` : "";
    return `<div class="rec${r.id === S.sel ? " sel" : ""}" data-rec="${r.id}">
      <div class="rec-top"><span class="rec-name">${esc(r.name)}</span>${badge}</div>
      <div class="rec-meta">${esc(when)} · ${fmtDur(r.duration)} · ${esc(r.model || "")}${ed}</div>
    </div>`;
  }).join("");
}

function termsRegex(q) {
  const terms = q.trim().split(/\s+/).filter(Boolean).map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  return terms.length ? new RegExp("(" + terms.join("|") + ")", "gi") : null;
}
function markTerms(text, re) {
  const e = esc(text);
  return re ? e.replace(re, "<mark>$1</mark>") : e;
}

let searchTimer = null;
function onSearch() {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(async () => {
    S.query = $("#search").value.trim();
    if (S.query) {
      try { S.hits = (await api("GET", "/api/search?q=" + encodeURIComponent(S.query))).hits; }
      catch (e) { toast(e.message, true); S.hits = []; }
    }
    renderList();
    markTranscript();
  }, 220);
}

// ---------- recording ----------
async function select(id, focusIdx) {
  stopLive();
  const changed = id !== S.sel;
  S.sel = id;
  let d;
  try { d = await api("GET", `/api/recordings/${id}`); }
  catch (e) { toast(e.message, true); return; }
  S.rec = d.recording; S.segs = d.segments;
  S.lastIdx = S.segs.length ? S.segs[S.segs.length - 1].idx : -1;
  renderList();
  renderHeader();
  if (changed) setAudio();
  renderTranscript();
  if (focusIdx !== undefined) jumpTo(focusIdx, false);
  if (ACTIVE.has(S.rec.status)) startLive();
}

function renderHeader() {
  const r = S.rec;
  const has = !!r;
  ["#btnExport", "#btnCopy", "#btnReplace", "#btnRedo", "#btnDelete"].forEach(s => ($(s).disabled = !has));
  $("#recName").disabled = !has;
  $("#recName").value = has ? r.name : "";
  if (!has) { $("#meta").innerHTML = ""; return; }
  const parts = [
    `Recorded ${esc((r.recorded_at || "–").slice(0, 16))}`,
    `duration ${fmtDur(r.duration)}`,
    `model ${esc(r.model || "–")}`,
    `language ${esc(r.language || "auto")}`,
    `${S.segs.length} lines`,
    `source ${esc(r.source_name || "–")}${r.source_exists === false && r.source_path ? " (moved)" : ""}`,
  ];
  let html = parts.join(" · ");
  if (r.status === "error") html += ` · <span class="err">${esc(r.error || "error")}</span>`;
  else if (r.status === "cancelled") html += ` · <span class="err">cancelled – partial transcript</span>`;
  if (!r.has_audio) html += " · no archived audio (playback off)";
  $("#meta").innerHTML = html;
}

function setAudio() {
  const a = $("#audio");
  const r = S.rec;
  if (r && r.has_audio) {
    $("#player").hidden = false;
    a.src = `/audio/${r.id}`;
    a.playbackRate = parseFloat($("#rate").value);
  } else {
    a.removeAttribute("src"); a.load();
    $("#player").hidden = true;
  }
  S.nowRow = -1;
}

function rowHtml(s) {
  const tip = s.edited ? ` title="Original: ${esc(s.original_text)}"` : "";
  return `<div class="row" data-idx="${s.idx}" data-id="${s.id}">
    <button class="ts" data-start="${s.start}" ${S.rec && S.rec.has_audio ? "" : "disabled"} title="Play from here">${fmtT(s.start)}</button>
    <div class="t" contenteditable="true" spellcheck="false">${esc(s.text)}</div>
    ${s.edited ? `<span class="ed"${tip}></span>` : "<span></span>"}
  </div>`;
}

function renderTranscript() {
  const box = $("#transcript");
  if (!S.rec) { box.hidden = true; $("#empty").hidden = false; return; }
  $("#empty").hidden = true;
  box.hidden = false;
  let html = S.segs.map(rowHtml).join("");
  if (ACTIVE.has(S.rec.status)) html += `<div class="live" id="live">Transcribing… new lines appear here.</div>`;
  else if (!S.segs.length) html += `<div class="live">No text in this recording.</div>`;
  box.innerHTML = html;
  markTranscript();
}

function markTranscript() {
  if (!S.query || !S.segs.length) {
    $$(".t mark").forEach(m => m.replaceWith(m.textContent));
    return;
  }
  const re = termsRegex(S.query);
  $$("#transcript .row").forEach(row => {
    const t = $(".t", row);
    if (document.activeElement === t) return;
    const seg = S.segs.find(s => String(s.idx) === row.dataset.idx);
    if (seg) t.innerHTML = markTerms(seg.text, re);
  });
}

function jumpTo(idx, play) {
  const row = $(`#transcript .row[data-idx="${idx}"]`);
  if (!row) return;
  row.scrollIntoView({ block: "center" });
  row.classList.remove("flash"); void row.offsetWidth; row.classList.add("flash");
  const seg = S.segs.find(s => s.idx === idx);
  if (seg && play && S.rec.has_audio) seek(seg.start, true);
}

function seek(t, play) {
  const a = $("#audio");
  a.currentTime = Math.max(0, t - 0.3);
  if (play) a.play().catch(() => {});
}

// live updates of a running transcription
function startLive() {
  stopLive();
  S.liveTimer = setInterval(async () => {
    if (!S.sel) return;
    let d;
    try { d = await api("GET", `/api/recordings/${S.sel}?after=${S.lastIdx}`); } catch (e) { return; }
    const box = $("#transcript");
    const live = $("#live");
    for (const s of d.segments) {
      S.segs.push(s); S.lastIdx = s.idx;
      const tmp = document.createElement("div");
      tmp.innerHTML = rowHtml(s);
      box.insertBefore(tmp.firstElementChild, live);
    }
    const wasActive = ACTIVE.has(S.rec.status);
    S.rec = d.recording;
    renderHeader();
    if (wasActive && !ACTIVE.has(S.rec.status)) {
      stopLive();
      const firstTime = !$("#player").hidden ? false : true;
      if (live) live.remove();
      if (firstTime) setAudio();
      $$("#transcript .ts").forEach(b => (b.disabled = !S.rec.has_audio));
      loadList();
    } else if (live && d.segments.length && $("#follow").checked && $("#audio").paused) {
      live.scrollIntoView({ block: "nearest" });
    }
  }, 1500);
}
function stopLive() { if (S.liveTimer) clearInterval(S.liveTimer); S.liveTimer = null; }

// playback follow
function onTime() {
  const t = $("#audio").currentTime;
  let lo = 0, hi = S.segs.length - 1, k = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (S.segs[m].start <= t + 0.05) { k = m; lo = m + 1; } else hi = m - 1; }
  if (k === S.nowRow) return;
  const prev = $("#transcript .row.now");
  if (prev) prev.classList.remove("now");
  S.nowRow = k;
  if (k < 0) return;
  const row = $(`#transcript .row[data-idx="${S.segs[k].idx}"]`);
  if (!row) return;
  row.classList.add("now");
  const editing = document.activeElement && document.activeElement.classList.contains("t");
  if ($("#follow").checked && !editing && !$("#audio").paused) row.scrollIntoView({ block: "center", behavior: "smooth" });
}

// editing
function onEditFocus(e) {
  const t = e.target;
  if (!t.classList.contains("t")) return;
  const seg = segOf(t);
  if (seg) t.textContent = seg.text; // drop search marks while editing
  t.dataset.before = t.textContent;
}
async function onEditBlur(e) {
  const t = e.target;
  if (!t.classList.contains("t")) return;
  const now = t.textContent.replace(/\s+/g, " ").trim();
  const seg = segOf(t);
  if (!seg || now === seg.text) { markTranscript(); return; }
  if (!now) { t.textContent = seg.text; toast("A line cannot be empty – the text was restored.", true); return; }
  try {
    const d = await api("PATCH", `/api/segments/${seg.id}`, { text: now });
    Object.assign(seg, d.segment);
    const row = t.closest(".row");
    const tmp = document.createElement("div");
    tmp.innerHTML = rowHtml(seg);
    row.replaceWith(tmp.firstElementChild);
    status(seg.edited ? "Saved. The original text is kept (hover the orange dot)." : "Saved – back to the original text.");
    loadList();
    markTranscript();
  } catch (err) { toast(err.message, true); t.textContent = seg.text; }
}
function onEditKey(e) {
  const t = e.target;
  if (!t.classList || !t.classList.contains("t")) return;
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); t.blur(); }
  else if (e.key === "Escape") { e.preventDefault(); t.textContent = t.dataset.before || ""; t.blur(); }
}
function segOf(el) {
  const row = el.closest(".row");
  return row ? S.segs.find(s => String(s.id) === row.dataset.id) : null;
}

// ---------- upload / jobs ----------
async function upload(files) {
  const list = Array.from(files).filter(f => f.size > 0);
  if (!list.length) return;
  for (const f of list) {
    status(`Copying ${f.name} (${(f.size / 1048576).toFixed(1)} MB) into quick_transcribe…`);
    try {
      const q = `name=${encodeURIComponent(f.name)}&lastModified=${f.lastModified || ""}`;
      const d = await api("POST", "/api/upload?" + q, undefined, f);
      S.jobs.push(d.job);
    } catch (e) { toast(`${f.name}: ${e.message}`, true); }
  }
  status(`${list.length} file(s) added to the queue.`);
  renderJobs();
  pollJobs(true);
}

async function pollJobs(now) {
  clearTimeout(S.jobsTimer);
  const tick = async () => {
    try {
      const d = await api("GET", "/api/jobs");
      const before = new Map(S.jobs.map(j => [j.id, j.status]));
      S.jobs = d.jobs;
      renderJobs();
      let listDirty = false;
      for (const j of S.jobs) {
        const was = before.get(j.id);
        if (was !== j.status) listDirty = true;
        if (j.rec_id && was !== j.status && (j.status === "running" || j.status === "archiving") && !S.sel) select(j.rec_id);
        if (j.rec_id && was && ACTIVE.has(was) && j.status === "done") toast(`Done: ${j.name}`);
        if (was && ACTIVE.has(was) && j.status === "error") toast(`${j.name}: ${j.message}`, true);
      }
      if (listDirty) await loadList();
      if (S.sel && S.rec && !S.liveTimer && S.jobs.some(j => j.rec_id === S.sel && ACTIVE.has(j.status))) select(S.sel);
      S.lastBusy = d.busy;
    } catch (e) { /* server gone: keep trying slowly */ }
    S.jobsTimer = setTimeout(tick, S.lastBusy ? 1000 : 4000);
  };
  if (now) tick(); else S.jobsTimer = setTimeout(tick, 1000);
}

function renderJobs() {
  const vis = S.jobs.filter(j => !S.hiddenJobs.has(j.id));
  $("#jobsBlock").hidden = !vis.length;
  $("#jobs").innerHTML = vis.slice().reverse().map(j => {
    const active = ACTIVE.has(j.status);
    const open = j.rec_id ? `<button class="btn quiet small" data-open="${j.rec_id}">Open</button>` : "";
    const cancel = active ? `<button class="btn quiet small" data-cancel="${j.id}">Cancel</button>` : "";
    return `<div class="job ${esc(j.status)}">
      <div class="job-top"><span class="job-name" title="${esc(j.name)}">${esc(j.name)}</span>
        <span class="badge ${esc(j.status)}">${esc(j.status)}</span>${open}${cancel}</div>
      <div class="job-msg">${esc(j.message || "")}${j.model ? ` · ${esc(j.model)}` : ""}</div>
      ${active || j.status === "done" ? `<div class="bar"><i style="width:${j.progress}%"></i></div>` : ""}
    </div>`;
  }).join("");
}

// ---------- actions ----------
async function rename() {
  if (!S.rec) return;
  const name = $("#recName").value.trim();
  if (!name || name === S.rec.name) { $("#recName").value = S.rec.name; return; }
  try {
    const d = await api("PATCH", `/api/recordings/${S.rec.id}`, { name });
    S.rec.name = d.recording.name;
    await loadList();
    status("Renamed.");
  } catch (e) { toast(e.message, true); }
}

async function copyText() {
  const r = await fetch(`/api/recordings/${S.rec.id}/export?fmt=txt`);
  const text = await r.text();
  try { await navigator.clipboard.writeText(text); toast("Transcript copied to the clipboard."); }
  catch (e) {
    const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove(); toast("Transcript copied to the clipboard.");
  }
}

function doExport(fmt) {
  const a = document.createElement("a");
  a.href = `/api/recordings/${S.rec.id}/export?fmt=${fmt}`;
  document.body.appendChild(a); a.click(); a.remove();
}

async function del() {
  if (!S.rec) return;
  if (!confirm(`Delete “${S.rec.name}” with its transcript and archived audio?\nThe original source file is not touched.`)) return;
  try {
    await api("DELETE", `/api/recordings/${S.rec.id}`);
    S.sel = null; S.rec = null; S.segs = [];
    setAudio(); renderHeader(); renderTranscript();
    await loadList();
    if (S.recs[0]) select(S.recs[0].id);
    toast("Deleted.");
  } catch (e) { toast(e.message, true); }
}

function openSettings() {
  const v = S.settings;
  $("#sModel").value = v.model; $("#sLang").value = v.language ?? "";
  $("#sDevice").value = v.device || "cpu";
  $("#sOffline").checked = !!v.offline; $("#sArchive").checked = !!v.archive_audio;
  $("#sTxt").checked = !!v.write_txt_next_to_source;
  $("#sGlossary").value = v.glossary || ""; $("#sBackup").value = v.backup_dir || "";
  $("#sData").textContent = S.dataDir;
  $("#dlgSettings").showModal();
}
async function saveSettings() {
  const body = {
    model: $("#sModel").value, language: $("#sLang").value, device: $("#sDevice").value,
    compute_type: $("#sDevice").value === "cuda" ? "float16" : "int8",
    offline: $("#sOffline").checked, archive_audio: $("#sArchive").checked,
    write_txt_next_to_source: $("#sTxt").checked,
    glossary: $("#sGlossary").value, backup_dir: $("#sBackup").value.trim(),
  };
  try { S.settings = (await api("PUT", "/api/settings", body)).settings; toast("Settings saved."); }
  catch (e) { toast(e.message, true); }
}

function openRedo() {
  $("#rModel").value = S.rec.model || S.settings.model;
  $("#rLang").value = S.rec.language ?? S.settings.language ?? "";
  $("#dlgRedo").showModal();
}
async function doRedo() {
  try {
    const d = await api("POST", `/api/recordings/${S.rec.id}/redo`, { model: $("#rModel").value, language: $("#rLang").value });
    S.jobs.push(d.job); renderJobs(); pollJobs(true);
    status("Queued for transcription again.");
  } catch (e) { toast(e.message, true); }
}

async function doReplace() {
  const find = $("#fFind").value.trim();
  if (!find) return;
  try {
    const d = await api("POST", `/api/recordings/${S.rec.id}/replace`, { find, replace: $("#fRepl").value, whole_word: $("#fWhole").checked });
    toast(d.replaced ? `Replaced ${d.replaced}×.` : "Nothing found.");
    if (d.replaced) { await select(S.rec.id); loadList(); }
  } catch (e) { toast(e.message, true); }
}

async function backup() {
  if (!S.settings.backup_dir) { toast("Set the backup folder in Settings first.", true); openSettings(); $("#sBackup").focus(); return; }
  status("Backing up…");
  try {
    const d = await api("POST", "/api/backup", {});
    status(`Backup done: ${d.database} · ${d.audio_copied} new audio file(s).`);
    toast("Backup done.");
  } catch (e) { toast(e.message, true); status(""); }
}

async function quit() {
  if (S.lastBusy && !confirm("A transcription is still running. Quit anyway?")) return;
  try { await api("POST", "/api/quit", {}); } catch (e) { /* ignore */ }
  document.body.innerHTML = `<div style="padding:40px;font:15px var(--font)">quick_transcribe has stopped. You can close this tab.</div>`;
}

// ---------- events ----------
function bind() {
  $("#btnAdd").onclick = () => $("#fileInput").click();
  $("#fileInput").onchange = e => { upload(e.target.files); e.target.value = ""; };
  $("#search").addEventListener("input", onSearch);

  $("#list").addEventListener("click", e => {
    const hit = e.target.closest(".hit");
    if (hit) { select(+hit.dataset.rec, +hit.dataset.idx); return; }
    const rec = e.target.closest(".rec");
    if (rec) select(+rec.dataset.rec);
  });
  $("#jobs").addEventListener("click", async e => {
    const o = e.target.closest("[data-open]");
    if (o) { select(+o.dataset.open); return; }
    const c = e.target.closest("[data-cancel]");
    if (c) { try { await api("POST", `/api/jobs/${c.dataset.cancel}/cancel`, {}); pollJobs(true); } catch (err) { toast(err.message, true); } }
  });
  $("#btnClearJobs").onclick = () => { S.jobs.filter(j => !ACTIVE.has(j.status)).forEach(j => S.hiddenJobs.add(j.id)); renderJobs(); };

  const tr = $("#transcript");
  tr.addEventListener("click", e => { const b = e.target.closest(".ts"); if (b && !b.disabled) seek(parseFloat(b.dataset.start), true); });
  tr.addEventListener("focusin", onEditFocus);
  tr.addEventListener("focusout", onEditBlur);
  tr.addEventListener("keydown", onEditKey);

  $("#audio").addEventListener("timeupdate", onTime);
  $("#rate").onchange = () => ($("#audio").playbackRate = parseFloat($("#rate").value));

  $("#recName").addEventListener("change", rename);
  $("#recName").addEventListener("keydown", e => { if (e.key === "Enter") e.target.blur(); if (e.key === "Escape") { e.target.value = S.rec ? S.rec.name : ""; e.target.blur(); } });

  const menu = $("#exportMenu .menu-items");
  $("#btnExport").onclick = e => { e.stopPropagation(); menu.hidden = !menu.hidden; };
  menu.addEventListener("click", e => { const b = e.target.closest("[data-fmt]"); if (b) { doExport(b.dataset.fmt); menu.hidden = true; } });
  document.addEventListener("click", () => (menu.hidden = true));

  $("#btnCopy").onclick = copyText;
  $("#btnDelete").onclick = del;
  $("#btnSettings").onclick = openSettings;
  $("#btnBackup").onclick = backup;
  $("#btnQuit").onclick = quit;
  $("#btnRedo").onclick = openRedo;
  $("#btnReplace").onclick = () => { $("#fFind").value = (window.getSelection().toString() || "").trim(); $("#fRepl").value = ""; $("#dlgReplace").showModal(); };
  $("#dlgSettings").addEventListener("close", () => { if ($("#dlgSettings").returnValue === "save") saveSettings(); });
  $("#dlgRedo").addEventListener("close", () => { if ($("#dlgRedo").returnValue === "ok") doRedo(); });
  $("#dlgReplace").addEventListener("close", () => { if ($("#dlgReplace").returnValue === "ok") doReplace(); });

  // drag & drop anywhere
  let depth = 0;
  const hasFiles = e => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  window.addEventListener("dragenter", e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; $("#drop").hidden = false; });
  window.addEventListener("dragover", e => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("dragleave", e => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) $("#drop").hidden = true; });
  window.addEventListener("drop", e => { if (!hasFiles(e)) return; e.preventDefault(); depth = 0; $("#drop").hidden = true; upload(e.dataTransfer.files); });

  // keyboard
  document.addEventListener("keydown", e => {
    const inField = e.target.closest && e.target.closest("input, textarea, select, [contenteditable=true], dialog");
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") { e.preventDefault(); $("#search").focus(); $("#search").select(); return; }
    if (inField) return;
    const a = $("#audio");
    if (e.code === "Space" && !$("#player").hidden) { e.preventDefault(); a.paused ? a.play().catch(() => {}) : a.pause(); }
    else if (e.key === "ArrowLeft" && !$("#player").hidden) { a.currentTime = Math.max(0, a.currentTime - 5); }
    else if (e.key === "ArrowRight" && !$("#player").hidden) { a.currentTime += 5; }
  });
}

init();
