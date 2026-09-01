function byId(id) {
  return document.getElementById(id);
}

function fmt(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return Number(value).toFixed(digits);
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

function syncRangeAndBox(rangeId, boxId) {
  const range = byId(rangeId);
  const box = byId(boxId);
  range.addEventListener("input", () => {
    box.value = range.value;
  });
  box.addEventListener("input", () => {
    range.value = box.value;
  });
}

async function refreshState() {
  const state = await api("/api/state");

  byId("host").value = state.config.opta_host;
  byId("port").value = state.config.opta_port;
  byId("poll").value = state.config.poll_interval_s;
  byId("levelMin").value = state.config.level_min;
  byId("levelMax").value = state.config.level_max;

  const v1 = state.control.valve1_cmd_mA ?? 4;
  const v2 = state.control.valve2_cmd_mA ?? 20;
  byId("valve1").value = v1;
  byId("valve1Box").value = Number(v1).toFixed(2);
  byId("valve2").value = v2;
  byId("valve2Box").value = Number(v2).toFixed(2);

  byId("i1").textContent = fmt(state.data.i1_mA, 3);
  byId("i2").textContent = fmt(state.data.i2_mA, 3);
  byId("i3").textContent = `${fmt(state.data.i3_mA, 3)} mA`;
  byId("i4").textContent = `${fmt(state.data.i4_mA, 3)} mA`;
  byId("flow").textContent = fmt(state.data.flow_l_s, 2);
  byId("level").textContent = fmt(state.data.level_value, 2);

  byId("pollState").textContent = state.last_error ? "poll error" : "poll ok";
  byId("lastPoll").textContent = `last poll: ${state.last_poll || "-"}`;
  byId("lastError").textContent = state.last_error || "";
  byId("jsonDump").textContent = JSON.stringify(state, null, 2);
}

async function saveConnection() {
  await api("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      opta_host: byId("host").value.trim(),
      opta_port: Number(byId("port").value),
      poll_interval_s: Number(byId("poll").value),
    }),
  });
  await api("/api/poll", { method: "POST" });
  await refreshState();
}

async function saveScale() {
  await api("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      level_min: Number(byId("levelMin").value),
      level_max: Number(byId("levelMax").value),
    }),
  });
  await refreshState();
}

async function applyValves() {
  await api("/api/valves", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      valve1_cmd_mA: Number(byId("valve1Box").value),
      valve2_cmd_mA: Number(byId("valve2Box").value),
    }),
  });
  await refreshState();
}

async function setRunState(running) {
  await api("/api/valves", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ running }),
  });
  await refreshState();
}

function wireUi() {
  syncRangeAndBox("valve1", "valve1Box");
  syncRangeAndBox("valve2", "valve2Box");

  byId("saveConnection").addEventListener("click", () => saveConnection().catch(alert));
  byId("saveScale").addEventListener("click", () => saveScale().catch(alert));
  byId("applyValves").addEventListener("click", () => applyValves().catch(alert));
  byId("startRun").addEventListener("click", () => setRunState(true).catch(alert));
  byId("stopRun").addEventListener("click", () => setRunState(false).catch(alert));
  byId("forceRefresh").addEventListener("click", () => refreshState().catch(alert));
}

wireUi();
refreshState();
setInterval(() => {
  refreshState().catch((err) => {
    byId("lastError").textContent = String(err);
  });
}, 1500);
