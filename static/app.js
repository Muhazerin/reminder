/* Remindly — phone-first PWA client */
"use strict";

const $ = (s) => document.querySelector(s);
const TZ = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const state = {
  token: localStorage.getItem("remindly_token") || "",
  filter: "pending",
  reminders: [],
  subscribed: false,
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const pad = (n) => String(n).padStart(2, "0");
function toLocalInput(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}
function defaultDue() {
  const d = new Date(Date.now() + 60 * 60 * 1000);
  d.setSeconds(0, 0);
  return toLocalInput(d);
}

function fmtDue(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const now = new Date();
  const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dayDiff = Math.round((startOf(d) - startOf(now)) / 86400000);
  const hm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  let day;
  if (dayDiff === 0) day = "Today";
  else if (dayDiff === 1) day = "Tomorrow";
  else if (dayDiff === -1) day = "Yesterday";
  else day = d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
  return { label: `${day} · ${hm}`, overdue: d.getTime() < now.getTime() };
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (state.token) headers["Authorization"] = "Bearer " + state.token;
  let body = opts.body;
  if (body && typeof body === "object") {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(body);
  }
  const res = await fetch(path, { ...opts, headers, body });
  if (res.status === 401 && path !== "/api/login") return logout();
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `HTTP ${res.status}`);
  return data;
}

/* ------------------------------------------------------------ auth */
$("#loginBtn").onclick = async () => {
  const pw = $("#password").value;
  if (!pw) return;
  try {
    const r = await api("/api/login", { method: "POST", body: { password: pw, tz: TZ } });
    state.token = r.token;
    localStorage.setItem("remindly_token", r.token);
    $("#loginErr").hidden = true;
    boot();
  } catch (e) {
    $("#loginErr").textContent = e.message;
    $("#loginErr").hidden = false;
  }
};
$("#password").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#loginBtn").click(); });
$("#logoutBtn").onclick = () => {
  state.token = "";
  localStorage.removeItem("remindly_token");
  location.reload();
};

/* ------------------------------------------------------------- app */
function boot() {
  $("#login").hidden = true;
  $("#app").hidden = false;
  $("#fDue").value = defaultDue();
  showIosHint();
  refreshPushState();
  registerSw();
  load();
  setInterval(load, 15000); // server fires reminders on its own clock; keep list fresh
}

function showIosHint() {
  const iOS = /iP(hone|ad|od)/.test(navigator.userAgent) && !navigator.standalone;
  const standalone = window.matchMedia("(display-mode: standalone)").matches;
  $("#iosBanner").hidden = !(iOS && !standalone);
}

async function load() {
  try {
    const r = await api(`/api/reminders?status=${state.filter}`);
    state.reminders = r.reminders || [];
    render();
  } catch (e) { /* transient */ }
}

function render() {
  const list = $("#list");
  list.innerHTML = "";
  const items = state.reminders;
  $("#empty").hidden = items.length > 0;

  for (const r of items) {
    const due = fmtDue(r.due_utc);
    const isPending = r.status === "pending";
    const li = document.createElement("li");
    li.className = "card" + (isPending ? "" : " done-card");
    const repeatChip = r.repeat ? `<span class="chip">${r.repeat}</span>` : "";

    let actions = "";
    if (isPending) {
      actions = `
        <button class="mini" data-act="done" data-id="${r.id}">✓ Done</button>
        <button class="mini" data-act="snooze10" data-id="${r.id}">+10m</button>
        <button class="mini" data-act="snooze60" data-id="${r.id}">+1h</button>
        <button class="mini" data-act="del" data-id="${r.id}">✕</button>`;
    } else {
      actions = `<button class="mini" data-act="del" data-id="${r.id}">✕</button>
                 <button class="mini" data-act="reopen" data-id="${r.id}">↺ Reopen</button>`;
    }

    li.innerHTML = `
      <div class="top">
        <div>
          <h3>${esc(r.title)}</h3>
          ${r.note ? `<div class="note">${esc(r.note)}</div>` : ""}
        </div>
        <span class="due ${!isPending ? "" : due.overdue ? "overdue" : ""}">
          ${isPending ? (due.overdue ? "Due now · " : "") + due.label : "Done"}
        </span>
      </div>
      <div class="meta">${repeatChip}</div>
      <div class="actions">${actions}</div>`;
    list.appendChild(li);
  }
}

list.addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.dataset.id;
  try {
    switch (btn.dataset.act) {
      case "done": await api(`/api/reminders/${id}`, { method: "PATCH", body: { status: "done" } }); break;
      case "reopen": await api(`/api/reminders/${id}`, { method: "PATCH", body: { status: "pending" } }); break;
      case "snooze10": await api(`/api/reminders/${id}/snooze`, { method: "POST", body: { minutes: 10 } }); break;
      case "snooze60": await api(`/api/reminders/${id}/snooze`, { method: "POST", body: { minutes: 60 } }); break;
      case "del":
        if (confirm("Delete this reminder?")) await api(`/api/reminders/${id}`, { method: "DELETE" });
        break;
    }
    load();
  } catch (err) { alert(err.message); }
});

/* form */
$("#addForm").onsubmit = async (ev) => {
  ev.preventDefault();
  const title = $("#fTitle").value.trim();
  const due = $("#fDue").value;
  if (!title || !due) return;
  try {
    await api("/api/reminders", {
      method: "POST",
      body: { title, note: $("#fNote").value.trim(), due_local: due, repeat: $("#fRepeat").value, tz: TZ },
    });
    $("#fTitle").value = "";
    $("#fNote").value = "";
    $("#fDue").value = defaultDue();
    load();
  } catch (err) { alert(err.message); }
};

/* tabs */
$("#tabPending").onclick = () => setFilter("pending");
$("#tabDone").onclick = () => setFilter("done");
function setFilter(f) {
  state.filter = f;
  $("#tabPending").classList.toggle("active", f === "pending");
  $("#tabDone").classList.toggle("active", f === "done");
  load();
}

/* ------------------------------------------------ push / service worker */
async function registerSw() {
  if (!("serviceWorker" in navigator)) return;
  try {
    await navigator.serviceWorker.register("/sw.js");
    if (Notification.permission === "granted") await subscribePush();
    else if (Notification.permission === "default") $("#notifBanner").hidden = false;
  } catch (e) { console.warn("SW registration failed", e); }
}

$("#enableNotif").onclick = async () => {
  const perm = await Notification.requestPermission();
  if (perm === "granted") {
    $("#notifBanner").hidden = true;
    await subscribePush();
  }
};

function urlBase64ToUint8Array(b64) {
  const pad = "=".repeat((4 - (b64.length % 4)) % 4);
  const raw = atob((b64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return new Uint8Array([...raw].map((c) => c.charCodeAt(0)));
}

async function subscribePush() {
  try {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    const reg = await navigator.serviceWorker.ready;
    const { key } = await api("/api/push/vapid-public-key");
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
    }
    const json = sub.toJSON();
    await api("/api/push/subscribe", {
      method: "POST",
      body: { endpoint: json.endpoint, keys: json.keys },
    });
    state.subscribed = true;
    refreshPushState();
  } catch (e) { console.warn("subscribe failed", e); }
}

function refreshPushState() {
  const el = $("#pushState");
  el.classList.toggle("on", state.subscribed);
  el.title = state.subscribed ? "Push registered" : "Push not registered";
  $("#testBtn").hidden = !state.subscribed;
}

$("#testBtn").onclick = async () => {
  try { await api("/api/push/test", { method: "POST" }); } catch (e) { alert(e.message); }
};

/* ------------------------------------------------------------ start */
if (state.token) boot();
