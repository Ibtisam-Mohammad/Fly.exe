const canvas = document.querySelector("#arena");
const ctx = canvas.getContext("2d");
const ui = {
  connection: document.querySelector("#connection"),
  execution: document.querySelector("#execution"),
  clock: document.querySelector("#sim-clock"),
  speed: document.querySelector("#speed"),
  modeTitle: document.querySelector("#mode-title"),
  claim: document.querySelector("#claim"),
  warning: document.querySelector("#warning"),
  flies: document.querySelector("#flies"),
  flyCount: document.querySelector("#fly-count"),
  selectedName: document.querySelector("#selected-name"),
  neuralBars: document.querySelector("#neural-bars"),
};

let socket;
let state;
let selectedKind = "food";
let selectedFly = null;
let stimulusCounter = 1;
const trails = new Map();

const palette = {
  food: "#f25f5c",
  "visual-target": "#232c29",
  obstacle: "#66756e",
  dust: "#b49568",
};

function send(command) {
  if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify(command));
}

function connect() {
  const protocol = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${location.host}/ws`);
  socket.onopen = () => {
    ui.connection.textContent = "LIVE LINK";
    ui.connection.className = "pill online";
  };
  socket.onclose = () => {
    ui.connection.textContent = "RECONNECTING";
    ui.connection.className = "pill offline";
    setTimeout(connect, 1000);
  };
  socket.onmessage = ({ data }) => {
    const payload = JSON.parse(data);
    if (payload.error) {
      ui.warning.textContent = `${payload.error}: ${payload.message}`;
      return;
    }
    state = payload;
    render();
  };
}

function mapPoint(x, y, bounds) {
  const px = ((x - bounds.x[0]) / (bounds.x[1] - bounds.x[0])) * canvas.width;
  const py = canvas.height - ((y - bounds.y[0]) / (bounds.y[1] - bounds.y[0])) * canvas.height;
  return [px, py];
}

function mmScale(bounds) {
  return canvas.width / (bounds.x[1] - bounds.x[0]);
}

function drawGrid(bounds) {
  ctx.fillStyle = "#dfe9d4";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "rgba(32,70,57,.09)";
  ctx.lineWidth = 1;
  const scale = mmScale(bounds);
  for (let x = bounds.x[0]; x <= bounds.x[1]; x += 5) {
    const [px] = mapPoint(x, 0, bounds);
    ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, canvas.height); ctx.stroke();
  }
  for (let y = bounds.y[0]; y <= bounds.y[1]; y += 5) {
    const [, py] = mapPoint(0, y, bounds);
    ctx.beginPath(); ctx.moveTo(0, py); ctx.lineTo(canvas.width, py); ctx.stroke();
  }
  ctx.strokeStyle = "rgba(32,70,57,.24)";
  ctx.lineWidth = Math.max(2, scale * .05);
  ctx.strokeRect(1, 1, canvas.width - 2, canvas.height - 2);
}

function drawStimulus(item, bounds) {
  const [x, y] = mapPoint(item.x_mm, item.y_mm, bounds);
  const radius = Math.max(7, item.radius_mm * mmScale(bounds));
  ctx.save();
  if (item.kind === "food") {
    const glow = ctx.createRadialGradient(x, y, radius * .2, x, y, radius * 4);
    glow.addColorStop(0, "rgba(242,95,92,.22)"); glow.addColorStop(1, "rgba(242,95,92,0)");
    ctx.fillStyle = glow; ctx.beginPath(); ctx.arc(x, y, radius * 4, 0, Math.PI * 2); ctx.fill();
  }
  ctx.globalAlpha = item.kind === "dust" ? .45 : .95;
  ctx.fillStyle = palette[item.kind] || "#222";
  ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI * 2); ctx.fill();
  ctx.globalAlpha = 1;
  ctx.fillStyle = "rgba(16,44,36,.72)";
  ctx.font = "700 14px ui-monospace, monospace";
  ctx.textAlign = "center";
  ctx.fillText(`${item.kind} ${Math.round(item.remaining * 100)}%`, x, y + radius + 22);
  ctx.restore();
}

function drawFly(fly, bounds) {
  const [x, y] = mapPoint(fly.x_mm, fly.y_mm, bounds);
  const scale = mmScale(bounds);
  const length = Math.max(17, fly.radius_mm * scale * 2.2);
  const trail = trails.get(fly.id) || [];
  const last = trail.at(-1);
  if (!last || Math.hypot(last[0] - x, last[1] - y) > 1.5) trail.push([x, y]);
  if (trail.length > 160) trail.shift();
  trails.set(fly.id, trail);
  ctx.save();
  ctx.strokeStyle = `${fly.color}66`; ctx.lineWidth = 2; ctx.beginPath();
  trail.forEach(([tx, ty], index) => index ? ctx.lineTo(tx, ty) : ctx.moveTo(tx, ty));
  ctx.stroke();
  ctx.translate(x, y); ctx.rotate(-fly.heading_rad);
  ctx.strokeStyle = "rgba(17,35,30,.65)"; ctx.lineWidth = 2;
  [-.65, 0, .65].forEach((offset) => {
    ctx.beginPath(); ctx.moveTo(-length * .1, offset * length * .28); ctx.lineTo(-length * .6, offset * length * .65); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(length * .12, offset * length * .28); ctx.lineTo(length * .58, offset * length * .68); ctx.stroke();
  });
  ctx.fillStyle = `${fly.color}88`;
  ctx.beginPath(); ctx.ellipse(-length * .05, -length * .28, length * .46, length * .2, -.45, 0, Math.PI * 2); ctx.fill();
  ctx.beginPath(); ctx.ellipse(-length * .05, length * .28, length * .46, length * .2, .45, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = "#16221e";
  ctx.beginPath(); ctx.ellipse(0, 0, length * .42, length * .25, 0, 0, Math.PI * 2); ctx.fill();
  ctx.fillStyle = fly.color;
  ctx.beginPath(); ctx.arc(length * .4, 0, length * .17, 0, Math.PI * 2); ctx.fill();
  ctx.restore();
  ctx.fillStyle = "rgba(10,30,24,.82)"; ctx.font = "700 13px ui-monospace, monospace"; ctx.textAlign = "center";
  ctx.fillText(fly.id, x, y - length * .72);
}

function renderAgentList(flies) {
  ui.flyCount.textContent = `${flies.length} flies`;
  if (!selectedFly && flies.length) selectedFly = flies[0].id;
  ui.flies.replaceChildren(...flies.map((fly) => {
    const row = document.createElement("div");
    row.className = `fly-row ${selectedFly === fly.id ? "selected" : ""}`;
    row.innerHTML = `<span class="swatch" style="background:${fly.color};color:${fly.color}"></span><div><div class="fly-name">${fly.id}</div><div class="fly-mode">${fly.mode}</div></div><span class="fly-mode">${fly.path_length_mm.toFixed(1)} mm</span>`;
    row.onclick = () => { selectedFly = fly.id; render(); };
    return row;
  }));
}

function renderNeural() {
  const fly = state.arena.flies.find((item) => item.id === selectedFly);
  ui.selectedName.textContent = fly ? `${fly.id} / ${fly.mode}` : "Select a fly";
  const neural = state.neural.agents[selectedFly];
  if (!neural) {
    ui.neuralBars.innerHTML = `<p>${fly?.mode === "controller-only" ? "No graph: bilateral local-sensor controller." : "No neural readout for this agent."}</p>`;
    return;
  }
  const max = Math.max(1, ...neural.values_hz);
  ui.neuralBars.replaceChildren(...neural.values_hz.slice(0, 12).map((value, index) => {
    const row = document.createElement("div"); row.className = "bar-row";
    const label = neural.ids[index].length > 12 ? `${neural.ids[index].slice(0, 10)}…` : neural.ids[index];
    row.innerHTML = `<span>${label}</span><span class="bar-track"><span class="bar-fill" style="display:block;width:${(value / max) * 100}%"></span></span><span class="bar-value">${value.toFixed(1)}</span>`;
    return row;
  }));
}

function render() {
  if (!state?.arena) return;
  const bounds = state.arena.bounds_mm;
  drawGrid(bounds);
  state.arena.stimuli.forEach((item) => drawStimulus(item, bounds));
  state.arena.flies.forEach((fly) => drawFly(fly, bounds));
  renderAgentList(state.arena.flies);
  renderNeural();
  ui.clock.textContent = `t = ${(state.arena.t_us / 1e6).toFixed(3)} biological s`;
  ui.speed.textContent = `${state.service.biological_per_wall.toFixed(2)}×`;
  ui.execution.textContent = state.execution_mode;
  ui.modeTitle.textContent = state.neural.enabled ? "Full-graph cohort active" : "Controller preview — no CNS";
  ui.claim.textContent = state.claim_boundary;
  ui.warning.textContent = state.runtime.warning || "Engineering showcase only. No validation tier is awarded.";
}

document.querySelectorAll(".tool").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".tool").forEach((item) => item.classList.remove("active"));
  button.classList.add("active"); selectedKind = button.dataset.kind;
}));
document.querySelector("#start").onclick = () => send({ command: "start" });
document.querySelector("#pause").onclick = () => send({ command: "pause" });
document.querySelector("#step").onclick = () => send({ command: "step" });
document.querySelector("#reset").onclick = () => { trails.clear(); send({ command: "reset" }); };
canvas.addEventListener("click", (event) => {
  if (!state) return;
  const rect = canvas.getBoundingClientRect();
  const fx = (event.clientX - rect.left) / rect.width;
  const fy = (event.clientY - rect.top) / rect.height;
  const bounds = state.arena.bounds_mm;
  const x = bounds.x[0] + fx * (bounds.x[1] - bounds.x[0]);
  const y = bounds.y[1] - fy * (bounds.y[1] - bounds.y[0]);
  const movableCue = selectedKind === "food" || selectedKind === "visual-target";
  const id = movableCue ? `${selectedKind}-1` : `${selectedKind}-${stimulusCounter++}`;
  const radius = selectedKind === "obstacle" ? 2 : movableCue ? 3 : 1.2;
  send({
    command: "place-stimulus",
    stimulus: { id, kind: selectedKind, x_mm: x, y_mm: y, radius_mm: radius, strength: 1 },
  });
});

connect();
