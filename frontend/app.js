/* Zoroi incident console.
   All decisions come from the Python agent (FastAPI). This file only draws what
   the server streams back: the animated agent flow, the service map, the agent's
   reasoning, escalations, lessons and results. */
(function () {
"use strict";

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
const C = { llm: "#6FB6FF", search: "#B39BFF", rl: "#F0B86E", ok: "#6FD7A8", bad: "#FF8A8A", warn: "#F0B86E",
  ink: "#E6ECF5", muted: "#8A98AE", faint: "#4A5A72", line: "#223044", panel: "#111824", panel2: "#162030", bg: "#0B1018" };

/* ===== API ===== */
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

/* ===== state ===== */
let NODES = {}, DEPS = [], SCN = {}, ORDER = [], NEED = 3;
const W = 136, H = 54;
const state = { scn: "db", sel: new Set(["db"]), pol: "rl", speed: 1, running: false,
  health: {}, explored: new Set(), roots: [], clock: 0, incident: null };
let lastRun = null, RESULTS = null, QUEUE = [];

/* ===== agent flow diagram ===== */
const FN = {
  alerts: { x: 80, y: 150, c: C.bad, label: "Alerts", tag: "INPUT" },
  llm: { x: 270, y: 150, c: C.llm, label: "Read", tag: "LLM" },
  search: { x: 460, y: 150, c: C.search, label: "Diagnose", tag: "A* SEARCH" },
  rl: { x: 650, y: 150, c: C.rl, label: "Decide", tag: "RL" },
  act: { x: 840, y: 72, c: C.ok, label: "Act", tag: "FIX" },
  ask: { x: 840, y: 228, c: C.warn, label: "Escalate", tag: "HUMAN" },
  done: { x: 1020, y: 150, c: C.ok, label: "Resolved", tag: "DONE" },
};
const FE = [["alerts", "llm"], ["llm", "search"], ["search", "rl"], ["rl", "act"], ["rl", "ask"], ["act", "done"],
  ["ask", "done"], ["act", "ask"], ["ask", "rl"]];
const ICON = {
  alerts: '<path d="M0 -11 L11 8 H-11 Z" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/><path d="M0 -3 V2" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><circle cx="0" cy="5.5" r="1.3" fill="currentColor"/>',
  llm: '<rect x="-11" y="-9" width="22" height="15" rx="4" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M-5 6 L-6 11 L0 6" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round"/><path d="M-6 -3 H6 M-6 1 H2" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>',
  search: '<circle cx="-2" cy="-2" r="8" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M4 4 L10 10" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/>',
  rl: '<path d="M0 11 V2 M0 2 L-8 -9 M0 2 L8 -9 M-8 -9 H-3 M-8 -9 V-4 M8 -9 H3 M8 -9 V-4" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>',
  act: '<path d="M2 -11 L-6 2 H0 L-2 11 L6 -2 H0 Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>',
  ask: '<circle cx="0" cy="-4" r="4.5" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M-8 10 C-8 4 -4 2 0 2 C4 2 8 4 8 10" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/>',
  done: '<path d="M-8 0 L-2 6 L9 -6" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"/>',
};
const nodeState = {}, nodeSub = {};
let edgeActive = {};

function edgeD(a, b) {
  const A = FN[a], B = FN[b];
  if (a === "ask" && b === "rl") return `M${A.x} ${A.y + 28} V${A.y + 64} H${B.x} V${B.y + 110}`;
  if (a === "act" && b === "ask") return `M${A.x} ${A.y + 34} V${B.y - 34}`;
  const r = a === "rl" || b === "done" ? 36 : 38;
  const x1 = A.x + r, x2 = B.x - (b === "act" || b === "ask" ? 58 : r);
  if (A.y === B.y) return `M${x1} ${A.y} H${x2}`;
  const mx = (x1 + x2) / 2, pill = a === "act" || a === "ask";
  const sx = pill ? A.x + 58 : x1;
  return `M${sx} ${A.y} C${mx + (pill ? 10 : 0)} ${A.y} ${mx} ${B.y} ${x2} ${B.y}`;
}
function drawFlow() {
  let s = "";
  for (const [a, b] of FE) s += `<path id="e-${a}-${b}" class="edge" d="${edgeD(a, b)}"${a === "ask" && b === "rl" ? ' stroke-dasharray="4 6"' : ""}/>`;
  s += `<text class="sub" x="745" y="285" text-anchor="middle">learns from the engineer's fix</text>`;
  s += '<g id="parts"></g>';
  for (const k in FN) {
    const n = FN[k], pill = k === "act" || k === "ask";
    s += `<g class="node" id="n-${k}" transform="translate(${n.x},${n.y})" style="color:${n.c}">`;
    if (pill) {
      s += `<rect class="halo" x="-58" y="-28" width="116" height="56" rx="28" fill="none" stroke="currentColor" stroke-width="2" opacity="0"/><rect class="ring" x="-58" y="-28" width="116" height="56" rx="28" fill="${C.panel2}" stroke="${C.line}" stroke-width="2"/><g transform="translate(-30,0)">${ICON[k]}</g><text class="lbl" x="-12" y="-2" style="font-size:14px">${n.label}</text><text class="tag" x="-12" y="14" fill="currentColor">${n.tag}</text>`;
    } else {
      s += `<circle class="halo" r="36" fill="none" stroke="currentColor" stroke-width="2" opacity="0"/><circle class="ring" r="36" fill="${C.panel2}" stroke="${C.line}" stroke-width="2"/>${ICON[k]}<text class="lbl" y="64" text-anchor="middle">${n.label}</text><text class="tag" y="82" text-anchor="middle" fill="currentColor">${n.tag}</text><text class="sub" id="sub-${k}" y="100" text-anchor="middle"></text>`;
    }
    s += "</g>";
  }
  $("flow").innerHTML = s;
  paintNodes();
}
function paintNodes() {
  for (const k in FN) {
    const g = $("n-" + k); if (!g) continue;
    const st = nodeState[k] || "idle", n = FN[k];
    g.classList.toggle("active", st === "active");
    const ring = g.querySelector(".ring"), col = st === "error" ? C.bad : n.c;
    g.style.color = st === "idle" ? C.faint : col;
    ring.setAttribute("stroke", st === "idle" ? C.line : col);
    ring.setAttribute("fill", st === "idle" ? C.panel2 : st === "active" ? col + "26" : col + "14");
    ring.setAttribute("stroke-width", st === "active" ? 2.5 : 2);
    const sub = $("sub-" + k); if (sub) sub.textContent = nodeSub[k] || "";
  }
  for (const [a, b] of FE) {
    const e = $(`e-${a}-${b}`); if (!e) continue;
    const on = edgeActive[a + "-" + b];
    e.setAttribute("stroke", on ? FN[a].c : C.line);
    e.setAttribute("stroke-opacity", on ? 0.35 : 1);
  }
}
function stage(k, st, sub) { nodeState[k] = st; if (sub !== undefined) nodeSub[k] = sub; paintNodes(); }
function flowOn(a, b, col) { edgeActive[a + "-" + b] = col || true; paintNodes(); }
function flowOff(a, b) { delete edgeActive[a + "-" + b]; paintNodes(); }
function flowOffAll() { edgeActive = {}; paintNodes(); }

/* moving particles along active edges */
const parts = [];
let lastT = 0, spawnAcc = {};
function spawn(a, b, c, o, v) {
  const el = $(`e-${a}-${b}`); if (!el) return;
  parts.push({ el, len: el.getTotalLength(), t: 0, c, o, v: (v || 1) * (0.85 + Math.random() * 0.3), r: 2.6 + Math.random() * 1.2 });
}
function tick(t) {
  const dt = Math.min(50, t - (lastT || t)); lastT = t;
  const g = $("parts");
  if (g) {
    if (!state.running) { spawnAcc.idle = (spawnAcc.idle || 0) + dt; if (spawnAcc.idle > 900) { spawnAcc.idle = 0; spawn("alerts", "llm", C.faint, 0.5, 0.55); } }
    for (const key in edgeActive) {
      spawnAcc[key] = (spawnAcc[key] || 0) + dt * state.speed;
      if (spawnAcc[key] > 140) { spawnAcc[key] = 0; const [a, b] = key.split("-"); spawn(a, b, edgeActive[key] === true ? FN[a].c : edgeActive[key], 1, 1); }
    }
    let html = "";
    for (let i = parts.length - 1; i >= 0; i--) {
      const p = parts[i]; p.t += dt * p.v * state.speed / 900;
      if (p.t >= 1 || !p.el.isConnected) { parts.splice(i, 1); continue; }
      const pt = p.el.getPointAtLength(p.t * p.len), fade = p.t < 0.1 ? p.t / 0.1 : p.t > 0.85 ? (1 - p.t) / 0.15 : 1;
      html += `<circle cx="${pt.x}" cy="${pt.y}" r="${p.r * 2.6}" fill="${p.c}" opacity="${0.18 * fade * p.o}"/><circle cx="${pt.x}" cy="${pt.y}" r="${p.r}" fill="${p.c}" opacity="${fade * p.o}"/>`;
    }
    g.innerHTML = html;
  }
  if (!reduce) requestAnimationFrame(tick);
}

/* ===== service map ===== */
const HC = { ok: C.ok, warn: C.warn, bad: C.bad, info: C.llm };
function mEdge(a, b) {
  const A = NODES[a], B = NODES[b]; let x1, y1, x2, y2;
  if (B.x > A.x) { x1 = A.x + W / 2; y1 = A.y; x2 = B.x - W / 2; y2 = B.y; } else { x1 = A.x - W / 2; y1 = A.y; x2 = B.x + W / 2; y2 = B.y; }
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
}
function drawMap() {
  let s = `<defs><marker id="ma" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="${C.faint}"/></marker><marker id="mh" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto"><path d="M0 0L10 5L0 10z" fill="${C.bad}"/></marker></defs>`;
  const sick = x => ["warn", "bad"].includes(state.health[x]);
  for (const [a, b] of DEPS) {
    const hot = sick(a) && sick(b);
    s += `<path d="${mEdge(a, b)}" fill="none" stroke="${hot ? C.bad : C.line}" stroke-opacity="${hot ? 0.6 : 1}" stroke-width="1.6" marker-end="url(#${hot ? "mh" : "ma"})"/>`;
  }
  for (const k in NODES) {
    const n = NODES[k], h = state.health[k] || "ok", ex = state.explored.has(k), root = state.roots.includes(k), col = HC[h];
    const stroke = ex ? C.search : (h === "ok" ? C.line : col), ext = n.kind === "external";
    const word = h === "ok" ? "healthy" : h === "warn" ? "degraded" : h === "bad" ? (ext ? "no response" : "down") : "recovering";
    s += `<g transform="translate(${n.x - W / 2},${n.y - H / 2})"><rect width="${W}" height="${H}" rx="${n.kind === "db" ? 14 : 9}" fill="${h === "ok" ? C.panel2 : col + "1F"}" stroke="${stroke}" stroke-width="${ex || h !== "ok" ? 2 : 1.4}"${ext ? ' stroke-dasharray="5 4"' : ""}/>` +
      `<circle cx="14" cy="18" r="4.5" fill="${col}"/><text class="nm" x="26" y="23">${esc(n.label)}</text><text class="st" x="14" y="43">${word}</text>`;
    if (root) {
      const lbl = state.roots.length > 1 ? "POSSIBLE CAUSE" : "ROOT CAUSE", w = lbl.length * 6.6 + 16;
      s += `<g transform="translate(${W - w + 6},-12)"><rect width="${w}" height="20" rx="10" fill="${C.search}"/><text x="${w / 2}" y="14" text-anchor="middle" font-size="10.5" font-weight="700" fill="${C.bg}" font-family="IBM Plex Sans,sans-serif">${lbl}</text></g>`;
    }
    s += "</g>";
  }
  $("map").innerHTML = s;
}

/* ===== small UI helpers ===== */
function think(tag, col, html) {
  const ul = $("think"), e = ul.querySelector(".empty"); if (e) e.remove();
  const li = document.createElement("li"); li.className = "th";
  li.innerHTML = `<span class="chip" style="color:${col}">${tag}</span><div class="body">${html}</div>`;
  ul.appendChild(li); ul.scrollTop = ul.scrollHeight;
}
function fmt(sec) {
  const t = 14 * 3600 + 7 * 60 + Math.round(sec), h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60;
  return [h, m, s].map(v => String(v).padStart(2, "0")).join(":");
}
function setClock(sec) { state.clock = sec; $("clock").textContent = fmt(sec); }
function setStatus(cls, txt) { const p = $("status"); p.className = "pill " + cls; p.textContent = txt; }
function cap(t) { $("flow-cap").textContent = t; }
const muted = t => `<span style="color:${C.muted}">${t}</span>`;

function qBars(rows, chosen) {
  const mx = Math.max(1, ...rows.map(r => Math.abs(r.value)));
  return `<div class="qs">${rows.map(r => {
    const w = Math.abs(r.value) / mx * 50;
    return `<div class="q${r.action === chosen ? " best" : ""}"><span class="l">${esc(r.label)}</span><span class="tr"><span class="b" style="${r.value >= 0 ? `left:50%;width:${w}%` : `left:${50 - w}%;width:${w}%`}"></span></span><span class="v">${r.value > 0 ? "+" : ""}${r.value.toFixed(1)}</span></div>`;
  }).join("")}</div>`;
}

/* ===== escalation dialog ===== */
let escCtx = null;
function openEscalation(ev, incidentId) {
  escCtx = { id: incidentId, choice: null };
  $("esc-who").textContent = `${$("inc-id").textContent} · paged at ${fmt(state.clock)}`;
  $("esc-h").textContent = ev.kind === "cleanup" ? "Outage made worse. Engineer paged" : "Escalated to the on-call engineer";
  $("esc-why").textContent = ev.reason;
  const sug = ev.learned_from ? `${esc(ev.suggested)} <span style="color:var(--rl)">(learned from ${ev.learned_from} earlier fix${ev.learned_from > 1 ? "es" : ""})</span>` : esc(ev.suggested);
  $("esc-ev").innerHTML = `<b>Evidence:</b> ${esc(ev.evidence)}<br><b>Likely cause:</b> ${esc(ev.cause)}<br><b>Suggested fix:</b> ${sug}`;
  $("esc-a").hidden = false; $("esc-b").hidden = true; $("esc-note").value = "";
  $("opts").innerHTML = ev.options.map(o => `<button class="opt" role="radio" aria-checked="false" data-v="${esc(o.value)}">${esc(o.label)}</button>`).join("");
  $("opts").querySelectorAll(".opt").forEach(b => b.addEventListener("click", () => {
    escCtx.choice = b.dataset.v;
    $("opts").querySelectorAll(".opt").forEach(o => o.setAttribute("aria-checked", String(o === b)));
    syncLog();
  }));
  syncLog();
  $("esc").hidden = false; $("esc-approve").focus();
}
function syncLog() { $("esc-log").disabled = !(escCtx && escCtx.choice) && !$("esc-note").value.trim(); }
async function sendHuman(body) {
  if (!escCtx) return;
  const id = escCtx.id; escCtx = null; $("esc").hidden = true;
  try { await api(`/api/incidents/${id}/human`, { method: "POST", body: JSON.stringify(body) }); }
  catch (e) { think("ERROR", C.bad, esc("Could not send the engineer's answer: " + e.message)); }
}
$("esc-approve").addEventListener("click", () => sendHuman({ how: "approve" }));
$("esc-take").addEventListener("click", () => { $("esc-a").hidden = true; $("esc-b").hidden = false; const f = $("opts").querySelector(".opt"); if (f) f.focus(); });
$("esc-note").addEventListener("input", syncLog);
$("esc-log").addEventListener("click", () => sendHuman({ how: "take", choice: escCtx && escCtx.choice, note: $("esc-note").value.trim() || null }));
document.addEventListener("keydown", e => { if (e.key === "Escape" && !$("esc").hidden && !$("esc-a").hidden) $("esc-take").click(); });

/* ===== one incident, driven by server events ===== */
function resetView() {
  for (const k in FN) { nodeState[k] = "idle"; nodeSub[k] = ""; }
  edgeActive = {}; parts.length = 0;
  state.health = {}; state.explored = new Set(); state.roots = []; setClock(0);
  $("think").innerHTML = '<li class="empty">Each step appears here as the agent works.</li>';
  $("inc-id").textContent = "No incident"; setStatus("ok", "Monitoring");
  cap("Watching 15 services. Pick one or more outages and press Run.");
  drawFlow(); drawMap();
}

function runOne(key) {
  return new Promise(async resolve => {
    resetView();
    let id;
    try { ({ id } = await api("/api/incidents", { method: "POST", body: JSON.stringify({ scenario: key, policy: state.pol, speed: state.speed }) })); }
    catch (e) { think("ERROR", C.bad, esc("Could not start the incident: " + e.message)); return resolve(null); }
    state.incident = id;
    const run = { key, alerts: 0, escFrom: "rl", recoverFrom: "act", result: null, pattern: "" };
    const es = new EventSource(`/api/incidents/${id}/events`);
    es.onmessage = m => {
      const ev = JSON.parse(m.data);
      if (ev.clock !== undefined) setClock(ev.clock);
      handle(ev, run, id);
      if (ev.type === "end") { es.close(); state.incident = null; resolve(run.result); }
    };
    es.onerror = () => { es.close(); state.incident = null; if (!run.result) think("ERROR", C.bad, "Lost connection to the agent."); resolve(run.result); };
  });
}

function handle(ev, run, id) {
  const s = SCN[run.key];
  switch (ev.type) {
    case "start":
      $("inc-id").textContent = `${ev.incident} · ${ev.sev}`; setStatus("bad", "Incident · " + ev.sev);
      stage("alerts", "active", ""); cap(ev.name + ": failure spreading through the system");
      { const cur = QUEUE.find(i => i.st === "now"); if (cur) { cur.name = ev.name; renderQueue(); } }
      break;
    case "health":
      state.health[ev.service] = ev.status; drawMap();
      if (ev.alert) { run.alerts++; nodeSub.alerts = run.alerts * 3 + " alerts"; paintNodes(); }
      break;
    case "alerts_done": stage("alerts", "done", ev.count + " alerts"); break;
    case "llm_start":
      flowOn("alerts", "llm"); stage("llm", "active", "reading…"); cap(`LLM is reading ${ev.count} alerts`);
      break;
    case "llm_result": {
      const sm = ev.summary; run.pattern = sm.pattern;
      const shown = { affected: sm.affected_services.length + " services", pattern: sm.pattern, recent_change: sm.recent_change, external_dependency: sm.external_dependency };
      think("LLM", C.llm, `${esc(sm.summary)}<pre>${esc(JSON.stringify(shown, null, 2))}</pre>${ev.provider === "mock" ? muted("Mock LLM (set LLM_PROVIDER in .env for a real model)") : ""}`);
      flowOff("alerts", "llm"); stage("llm", "done", sm.pattern);
      break;
    }
    case "search_start":
      flowOn("llm", "search"); stage("search", "active", "searching…"); cap("A* search is tracing the alerts back to a cause");
      break;
    case "search_visit": state.explored.add(ev.service); drawMap(); break;
    case "search_result": {
      state.roots = ev.marked; drawMap();
      const st = ev.stats, two = ev.best.length > 1, top = ev.candidates[0];
      think("A* SEARCH", C.search,
        `${two ? `No single failure explains every alert. Best explanation: <b>two failures</b>, ${esc(top.label)}.` : `Best explanation: <b>${esc(top.label)}</b> explains every alert.`} Confidence: <b style="color:${ev.confident ? C.ok : C.warn}">${ev.confident ? "high" : "low"}</b>` +
        `<div class="cands">${ev.candidates.map((c, i) => `<div class="cand${i === 0 ? " top" : ""}"><span>${esc(c.label)}</span><span class="tr"><i style="width:${Math.round(c.score * 100)}%"></i></span><span class="v">${c.cost.toFixed(1)}</span></div>`).join("")}</div>` +
        `<div style="margin-top:6px;color:${C.muted};font-size:12px">Cost (lower is more likely). Hypotheses checked: <b style="color:${C.search}">A* ${st.astar}</b> · BFS ${st.bfs}${st.bfs_correct ? "" : ` (picked ${esc(st.bfs_pick)}, wrong)`} · Greedy ${st.greedy}${st.greedy_correct ? "" : ` (picked ${esc(st.greedy_pick)}, wrong)`}</div>`);
      flowOff("llm", "search"); stage("search", "done", (ev.confident ? "high" : "low") + " confidence");
      break;
    }
    case "decide_start":
      if (ev.attempt === 0) flowOn("search", "rl");
      stage("rl", "active", "weighing options…");
      cap(`${state.pol === "rl" ? "Zoroi" : POLICY_NAMES[state.pol]} is deciding: act or escalate?`);
      break;
    case "decision": {
      if (ev.policy === "rl") {
        const L = ev.lesson;
        const lnote = L ? (L.state === "mastered"
          ? `<br><span style="color:${C.ok}">${L.ok} confirmed human fixes for this pattern, so Zoroi now acts alone.</span>`
          : `<br>${muted(`The learned fix scores well, but has only ${L.ok} of ${L.need} confirmations, so Zoroi still escalates and suggests it.`)}`) : "";
        think("RL", C.rl, `${ev.attempt ? "First fix did not work. " : ""}Learned values for this situation:${qBars(ev.q_values, ev.action)}${lnote}`);
      } else {
        think("RULE", C.muted, `${esc(POLICY_NAMES[state.pol])} picks <b>${esc(ev.label)}</b> without weighing the situation.`);
      }
      stage("rl", "done", ev.action === "escalate" ? "escalate" : ev.action === "learned" ? "act: learned fix" : "act: " + ev.label.toLowerCase());
      flowOff("search", "rl");
      break;
    }
    case "act_start":
      flowOn("rl", "act", C.ok); stage("act", "active", ev.label.toLowerCase() + "…");
      cap(ev.action === "learned" ? "Running the fix learned from engineers: " + ev.label.toLowerCase() : `Running: ${ev.label.toLowerCase()} on ${ev.target}`);
      break;
    case "act_result":
      flowOff("rl", "act");
      if (ev.harm) {
        stage("act", "error", "made it worse");
        for (const k in state.health) if (state.health[k] === "warn") state.health[k] = "bad";
        drawMap();
        think("RESULT", C.bad, `<b style="color:${C.bad}">${esc(ev.label)} made it worse.</b> ${esc(ev.note)}. ${muted(ev.minutes + " min")}`);
      } else if (ev.fixed) {
        stage("act", "done", "fixed");
        think("RESULT", C.ok, `<b style="color:${C.ok}">${esc(ev.label)} worked.</b> ${esc(ev.note)}. ${muted(ev.minutes + " min")}`);
      } else {
        stage("act", "done", "no effect");
        think("RESULT", C.muted, `${esc(ev.label)} had no effect: ${esc(ev.note)}. ${muted(ev.minutes + " min")}`);
      }
      break;
    case "escalate":
      run.escFrom = ev.kind === "cleanup" || ev.kind === "forced" ? "act" : "rl";
      flowOn(run.escFrom, "ask", C.warn); stage("ask", "active", "waiting for engineer");
      setStatus("wait", "Waiting for engineer"); cap("Escalated: waiting for the on-call engineer");
      openEscalation(ev, id);
      break;
    case "human_result":
      flowOff(run.escFrom, "ask");
      if (ev.note_reading) think("LLM", C.llm, `Read the engineer's note: <i>"${esc(ev.note_reading.note)}"</i><br>${ev.note_reading.understood_as ? `Understood as: <b>${esc(ev.note_reading.understood_as)}</b>` : "Could not tell which fix was used, so nothing will be learned."}`);
      think("HUMAN", C.warn,
        ev.how === "approve" ? `Engineer approved the suggested fix: <b>${esc(ev.learn_label)}</b>. It worked. ${muted(ev.minutes + " min")}`
          : ev.worked ? `Engineer took over and used <b>${esc(ev.label)}</b>. It worked. ${muted(ev.minutes + " min")}`
            : ev.choice ? `Engineer tried <b>${esc(ev.label)}</b>, which did not resolve it, then ${esc(ev.human_fix)}. ${muted(ev.minutes + " min")}`
              : `Engineer fixed it without saying how. ${muted(ev.minutes + " min")}`);
      stage("ask", "done", ev.how === "approve" ? "fix approved" : "engineer fixed it");
      run.recoverFrom = "ask";
      break;
    case "learning_start":
      flowOn("ask", "rl", C.rl); stage("rl", "active", "learning…"); cap("Zoroi is learning from the engineer's fix");
      break;
    case "learning_result": {
      const L = ev.lesson;
      think("LEARN", C.rl, ev.worked
        ? (L.ok >= ev.need
          ? `Lesson stored: <b>${esc(L.label)}</b> fixes <i>${esc(ev.pattern.toLowerCase())}</i>. <b style="color:${C.ok}">${L.ok} of ${ev.need} confirmations: next time Zoroi will fix this alone.</b>`
          : `Lesson stored: <b>${esc(L.label)}</b> fixes <i>${esc(ev.pattern.toLowerCase())}</i>. Confirmations: <b>${L.ok} of ${ev.need}</b>. Learned value now ${L.value > 0 ? "+" : ""}${L.value.toFixed(1)}.`)
        : `<b>${esc(ev.label)}</b> did not work here, so Zoroi will not suggest it for this pattern.`);
      flowOff("ask", "rl"); stage("rl", "done", L.ok >= ev.need ? "learned: acts alone" : `learned ${L.ok}/${ev.need}`);
      loadLessons();
      break;
    }
    case "recovering":
      run.recoverFrom = ev.source === "escalate" ? "ask" : "act";
      flowOn(run.recoverFrom, "done", C.ok); stage("done", "active", "recovering…"); cap("Services recovering");
      break;
    case "resolved":
      state.explored = new Set(); state.roots = []; drawMap();
      flowOffAll(); stage("done", "done", ev.total + " min");
      setStatus("ok", `Resolved in ${ev.total} min`);
      run.result = { total: ev.total, harm: ev.harm, human: ev.human, key: run.key };
      lastRun = run.result; renderKpis();
      cap(`Resolved in ${ev.total} minutes. ` + (state.pol === "rl" && ev.human ? "Run it again to see what Zoroi learned." : "Try the same outage with another responder."));
      break;
    case "report": think("LLM", C.llm, `<b>Incident report:</b> ${esc(ev.text)}`); break;
    case "error": think("ERROR", C.bad, esc(ev.message)); setStatus("bad", "Agent error"); break;
  }
}

/* ===== queue of incidents ===== */
function renderQueue() {
  const q = $("queue"); q.hidden = QUEUE.length < 2; if (q.hidden) return;
  const lbl = { wait: "Waiting", now: "In progress", done: "Fixed alone", esc: "Escalated", bad: "Made worse" };
  $("qrow").innerHTML = QUEUE.map(it => `<div class="qi q-${it.st}"><span>${esc(it.name || SCN[it.k].name)}</span><span class="s">${lbl[it.st]}${it.min ? " · " + it.min + " min" : ""}</span></div>`).join("");
  const done = QUEUE.filter(i => ["done", "esc", "bad"].includes(i.st));
  $("q-sum").textContent = done.length === QUEUE.length
    ? `${QUEUE.length} incidents · ${done.reduce((a, b) => a + b.min, 0)} min total · ${QUEUE.filter(i => i.st === "done").length} fixed alone · ${QUEUE.filter(i => i.st !== "done").length} escalated`
    : `${done.length} of ${QUEUE.length} handled`;
}
function lockControls(on) { document.querySelectorAll(".scn,#pol button,#reset-l,.link").forEach(b => (b.disabled = on)); $("run").disabled = on; }
async function run() {
  if (state.running) return;
  state.running = true; lockControls(true);
  QUEUE = ORDER.filter(k => state.sel.has(k)).map(k => ({ k, st: "wait", min: 0 })); renderQueue();
  for (const it of QUEUE) {
    it.st = "now"; state.scn = it.k; renderQueue();
    const r = await runOne(it.k);
    if (r) { it.min = r.total; it.st = r.harm ? "bad" : r.human ? "esc" : "done"; } else it.st = "bad";
    renderQueue();
    if (QUEUE.length > 1 && it !== QUEUE.at(-1)) await new Promise(res => setTimeout(res, 1400 / state.speed));
  }
  state.running = false; lockControls(false);
}

/* ===== lessons and results ===== */
async function loadLessons() {
  try { const d = await api("/api/lessons"); renderLessons(d.lessons); } catch (e) { /* keep last view */ }
}
function renderLessons(list) {
  if (!list.length) {
    $("lessons").innerHTML = `<p class="l-empty">No lessons yet. Run <b>Two failures at once</b>, <b>Unfamiliar error</b> or <b>Traffic spike</b>: Zoroi escalates, you tell it how you fixed it, and it learns. After ${NEED} confirmed fixes for the same pattern, it handles it alone.</p>`;
    return;
  }
  $("lessons").innerHTML = `<table><thead><tr><th>Outage pattern</th><th>Learned fix</th><th>Confirmations</th><th class="n">Learned value</th><th>Status</th></tr></thead><tbody>` +
    list.map(L => `<tr><td>${esc(SCN[L.scenario] ? SCN[L.scenario].name : L.scenario || L.key)}</td><td>${L.ok ? esc(L.label) : "none yet"}</td><td><span class="dots" aria-label="${L.ok} of ${NEED}">${Array.from({ length: NEED }, (_, i) => `<i class="${i < L.ok ? "on" : ""}"></i>`).join("")}</span>${L.wrong ? ` <span style="color:${C.muted};font-size:12px">${L.wrong} wrong</span>` : ""}</td><td class="n">${L.value > 0 ? "+" : ""}${L.value.toFixed(1)}</td><td>${L.mastered ? '<span class="sp-pill go">Acts alone</span>' : '<span class="sp-pill wait">Escalates and suggests</span>'}</td></tr>`).join("") +
    "</tbody></table>";
}
function renderKpis() {
  const r = lastRun, rl = RESULTS && RESULTS.rl;
  $("kpis").innerHTML = [
    ["This incident", r ? r.total + " min" : "—", r ? "time to recovery" : "run an incident"],
    ["Made it worse", r ? (r.harm ? "Yes" : "No") : "—", r ? (r.harm ? "an action caused damage" : "no harmful actions") : ""],
    ["Escalated", r ? (r.human ? "Yes" : "No") : "—", r ? (r.human ? "engineer involved" : "fixed automatically") : ""],
    ["Zoroi on average", rl ? rl.avg_recovery_min + " min" : "—", rl ? rl.made_worse_pct + "% made worse" : ""],
  ].map(([k, v, s]) => `<div class="kpi"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${s}</div></div>`).join("");
}
function renderResults() {
  if (!RESULTS) return;
  $("agg").innerHTML = `<thead><tr><th>Responder</th><th class="n">Avg recovery</th><th class="n">Made it worse</th><th class="n">Escalated</th></tr></thead><tbody>` +
    ["rl", "act", "rule", "escalate", "random"].filter(p => RESULTS[p]).map(p => {
      const r = RESULTS[p];
      return `<tr class="${p === state.pol ? "me" : ""}"><td>${esc(r.name)}</td><td class="n">${r.avg_recovery_min} min</td><td class="n">${r.made_worse_pct}%</td><td class="n">${r.escalated_pct}%</td></tr>`;
    }).join("") + "</tbody>";
  renderKpis();
}

/* ===== controls ===== */
let POLICY_NAMES = {};
function press(sel, v) { document.querySelectorAll(sel).forEach(b => b.setAttribute("aria-pressed", String(b.dataset.v === v))); }
function sync() {
  document.querySelectorAll(".scn").forEach(b => b.setAttribute("aria-pressed", String(state.sel.has(b.dataset.v))));
  const n = state.sel.size;
  $("run").lastChild.textContent = n > 1 ? `Run ${n} incidents` : "Run incident";
  press("#pol button", state.pol); press("#spd button", String(state.speed));
}
function bindControls() {
  document.querySelectorAll(".scn").forEach(b => b.addEventListener("click", () => {
    if (state.running) return;
    const v = b.dataset.v;
    if (state.sel.has(v)) { if (state.sel.size > 1) state.sel.delete(v); } else state.sel.add(v);
    state.scn = [...state.sel].at(-1); QUEUE = []; renderQueue(); sync(); resetView();
  }));
  $("sel-all").addEventListener("click", () => { if (!state.running) { state.sel = new Set(ORDER); sync(); } });
  $("sel-one").addEventListener("click", () => { if (!state.running) { state.sel = new Set([state.scn]); QUEUE = []; renderQueue(); sync(); } });
  document.querySelectorAll("#pol button").forEach(b => b.addEventListener("click", () => { if (state.running) return; state.pol = b.dataset.v; sync(); renderResults(); }));
  document.querySelectorAll("#spd button").forEach(b => b.addEventListener("click", () => {
    state.speed = +b.dataset.v; sync();
    if (state.incident) api(`/api/incidents/${state.incident}/speed`, { method: "POST", body: JSON.stringify({ speed: state.speed }) }).catch(() => {});
  }));
  $("run").addEventListener("click", run);
  $("reset-l").addEventListener("click", async () => { if (state.running) return; await api("/api/lessons", { method: "DELETE" }); loadLessons(); });
}

/* ===== boot ===== */
async function boot() {
  drawFlow();
  if (!reduce) requestAnimationFrame(tick);
  try {
    const meta = await api("/api/meta");
    NEED = meta.need; POLICY_NAMES = meta.policies;
    for (const n of meta.graph.nodes) NODES[n.id] = n;
    DEPS = meta.graph.deps;
    for (const s of meta.scenarios) SCN[s.key] = s;
    ORDER = meta.scenarios.map(s => s.key);
    $("scns").innerHTML = meta.scenarios.map(s => `<button class="scn" id="scn-${s.key}" data-v="${s.key}"><span class="ck" aria-hidden="true"></span><span class="t"><b>${esc(s.name)}</b><span>${esc(s.hint)}</span></span><span class="d" title="${s.clear ? "Clear cause" : "Uncertain"}" style="background:${s.clear ? C.ok : C.warn}"></span></button>`).join("");
    $("llm-env").textContent = "LLM: " + meta.llm_provider;
    $("rail-note").textContent = `The agent was trained on ${meta.train_episodes.toLocaleString()} simulated outages.`;
    bindControls(); sync(); resetView();
    RESULTS = await api("/api/results"); renderResults();
    loadLessons();
  } catch (e) {
    $("rail-note").textContent = "Could not reach the agent. Is the server running? (uvicorn app.main:app)";
    $("run").disabled = true;
  }
}
boot();
})();
