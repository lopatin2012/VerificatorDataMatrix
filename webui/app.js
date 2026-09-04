"use strict";

const state = {
  result: null,
  img: null,           // Image object of the base frame
  zoom: 1,
  rotate: 0,
  channel: "color",
  focus: null,
  analyzed: 0,
};

const $ = (id) => document.getElementById(id);

async function fetchVersion() {
  try {
    const r = await fetch("api/version");
    const j = await r.json();
    $("version").textContent = "v" + j.version;
    $("appver").textContent = "DataMatrix Verifier v" + j.version;
  } catch (e) { /* server has no version endpoint yet */ }
}

// ------------------------------------------------------------- canvas draw

function computeArc(cx, cy, r, startDeg, endDeg, steps) {
  const pts = [];
  for (let i = 0; i <= steps; i++) {
    const deg = startDeg + (endDeg - startDeg) * i / steps;
    const rad = deg * Math.PI / 180;
    pts.push((cx + r * Math.cos(rad)) + "," + (cy - r * Math.sin(rad)));
  }
  return pts.join(" ");
}

function drawGauge(score, color, grade) {
  const g = $("gauge");
  const ns = "http://www.w3.org/2000/svg";
  g.innerHTML = "";
  const cx = 100, cy = 112, r = 84;
  const bg = document.createElementNS(ns, "polyline");
  bg.setAttribute("points", computeArc(cx, cy, r, 210, -30, 60));
  bg.setAttribute("fill", "none");
  bg.setAttribute("stroke", "#e3e8ee");
  bg.setAttribute("stroke-width", "14");
  bg.setAttribute("stroke-linecap", "round");
  g.appendChild(bg);

  const frac = Math.max(0, Math.min(1, score / 100));
  const val = document.createElementNS(ns, "polyline");
  val.setAttribute("points", computeArc(cx, cy, r, 210, 210 - 240 * frac, 60));
  val.setAttribute("fill", "none");
  val.setAttribute("stroke", color);
  val.setAttribute("stroke-width", "14");
  val.setAttribute("stroke-linecap", "round");
  g.appendChild(val);

  const ticks = document.createElementNS(ns, "g");
  for (let i = 0; i <= 10; i++) {
    const a = (210 - 240 * i / 10) * Math.PI / 180;
    const x0 = cx + (r - 13) * Math.cos(a), y0 = cy - (r - 13) * Math.sin(a);
    const x1 = cx + (r - 4) * Math.cos(a), y1 = cy - (r - 4) * Math.sin(a);
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", x0); line.setAttribute("y1", y0);
    line.setAttribute("x2", x1); line.setAttribute("y2", y1);
    line.setAttribute("stroke", "#cfd8dc"); line.setAttribute("stroke-width", "2");
    ticks.appendChild(line);
  }
  g.appendChild(ticks);

  const a = (210 - 240 * frac) * Math.PI / 180;
  const needle = document.createElementNS(ns, "line");
  needle.setAttribute("x1", cx); needle.setAttribute("y1", cy);
  needle.setAttribute("x2", cx + (r - 20) * Math.cos(a));
  needle.setAttribute("y2", cy - (r - 20) * Math.sin(a));
  needle.setAttribute("stroke", "#455a64"); needle.setAttribute("stroke-width", "4");
  needle.setAttribute("stroke-linecap", "round");
  g.appendChild(needle);
}

function drawScene() {
  if (!state.img) return;
  const canvas = $("scene");
  const ctx = canvas.getContext("2d");
  const cw = canvas.clientWidth || 600;
  const ch = canvas.clientHeight || 400;

  // figure display transform
  let w = state.img.naturalWidth, h = state.img.naturalHeight;
  let rot = state.rotate % 4;
  let rw = (rot % 2) ? h : w;
  let rh = (rot % 2) ? w : h;
  const scale = Math.min(cw / rw, ch / rh) * state.zoom;
  const tw = rw * scale, th = rh * scale;

  ctx.clearRect(0, 0, cw, ch);
  ctx.save();
  ctx.translate((cw - tw) / 2, (ch - th) / 2);
  if (rot) ctx.rotate(rot * Math.PI / 2);

  // channel filter
  ctx.filter = "none";
  if (state.channel === "gray") ctx.filter = "grayscale(1)";
  else if (state.channel === "ir") ctx.filter = "grayscale(1) contrast(1.6)";

  const dw = (rot % 2) ? th : tw;
  const dh = (rot % 2) ? tw : th;
  const offx = (rot % 2) ? (tw - dw) / 2 : 0;
  const offy = (rot % 2) ? (th - dh) / 2 : 0;
  ctx.drawImage(state.img, offx, offy, dw, dh);
  ctx.filter = "none";

  // map original image coords -> canvas coords
  const toCanvas = (x, y) => {
    let px = x, py = y;
    for (let k = 0; k < rot; k++) {  // np.rot90 ccw
      const nx = w - 1 - py, ny = px;
      px = nx; py = ny;
    }
    return [px * scale + (cw - tw) / 2, py * scale + (ch - th) / 2];
  };

  // symbol outline
  if (state.result && state.result.corners) {
    const c = state.result.corners;
    ctx.beginPath();
    const p0 = toCanvas(c[0], c[1]);
    ctx.moveTo(p0[0], p0[1]);
    for (let k = 2; k < c.length; k += 2) {
      const p = toCanvas(c[k], c[k + 1]);
      ctx.lineTo(p[0], p[1]);
    }
    ctx.closePath();
    ctx.strokeStyle = "#2e7d32";
    ctx.lineWidth = 3;
    ctx.stroke();
  }

  // heatmap polygons
  const sevColor = { critical: "#e53935", warning: "#fb8c00", minor: "#fdd835" };
  (state.result?.regions || []).forEach((reg, i) => {
    const pts = [];
    for (let k = 0; k < reg.poly.length; k += 2) {
      pts.push(toCanvas(reg.poly[k], reg.poly[k + 1]));
    }
    if (pts.length < 3) return;
    const focus = state.focus === i;
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1]);
    ctx.closePath();
    ctx.fillStyle = sevColor[reg.severity] || "#e53935";
    ctx.globalAlpha = focus ? 0.75 : 0.35;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = sevColor[reg.severity];
    ctx.lineWidth = focus ? 4 : 2;
    ctx.stroke();
  });
  ctx.restore();
}

// ------------------------------------------------------------- rendering

function render(data) {
  state.result = data;
  state.focus = null;

  const good = data.good;
  const vcolor = good ? "#2e7d32" : "#c62828";
  const val = $("validation");
  val.textContent = "Валидация: " + (data.validation === "OK" ? "ОК" : "БРАК");
  val.style.color = vcolor;

  const scoreEl = $("score");
  scoreEl.innerHTML = data.score + '<span class="of"> из 100</span>';
  scoreEl.style.color = data.color;
  $("grade").textContent = "Грейд " + data.min_grade.toFixed(1).replace(".", ",") +
    (data.symbol_size ? " / " + data.symbol_size : "");
  $("grade").style.color = vcolor;
  drawGauge(data.score, data.color);

  $("verdict").textContent = good ? "ГОДЕН" : "БРАК";
  $("verdict").style.color = good ? "#2e7d32" : "#c62828";
  const reason = (data.params || []).find(p => !p.passed);
  $("reason").textContent = reason ? (reason.name + ": " + reason.value)
    : (data.error || "Все параметры в норме");

  renderParams(data);
  renderDefects(data);
  renderData(data);
  renderReport(data);
}

function renderParams(data) {
  const wrap = $("params");
  wrap.innerHTML = "";
  const keys = ["Контраст символа", "Неоднородность сетки",
                "Размерность печати X", "Последовательность тактовых модулей"];
  const map = {
    "Контраст символа": "Контраст символа",
    "Неоднородность сетки": "Неоднородность сетки",
    "Размерность печати X": "Размерность печати X",
    "Последовательность тактовых модулей": "Последовательность тактовых модулей",
  };
  keys.forEach(k => {
    const p = (data.params || []).find(x => x.name === map[k]);
    const grade = p ? p.grade : 0;
    const color = grade >= 4 ? "#2e7d32" : (grade >= 2 ? "#f9a825" : "#c62828");
    const row = document.createElement("div");
    row.className = "param";
    row.innerHTML =
      '<span class="pname">' + k + '</span>' +
      '<span class="ptrack"><span class="pfill" style="width:' + (grade / 4 * 100) + '%;background:' + color + '"></span></span>' +
      '<span class="pval">' + grade + '</span>';
    wrap.appendChild(row);
  });
}

function renderDefects(data) {
  const wrap = $("defects");
  wrap.innerHTML = "";
  const bad = (data.params || []).filter(p => !p.passed);
  if (!bad.length) {
    wrap.innerHTML = '<div class="defect" style="border-color:#2e7d32"><div class="dtitle">Все параметры в норме ✅</div></div>';
    return;
  }
  bad.forEach((p, i) => {
    const sev = p.grade <= 1 ? "critical" : (p.grade <= 3 ? "warning" : "minor");
    const icon = p.grade <= 1 ? "🚫" : (p.grade <= 3 ? "⚠️" : "🟡");
    const cls = sev === "critical" ? "" : (sev === "warning" ? "warn" : "minor");
    const d = document.createElement("div");
    d.className = "defect " + cls;
    d.innerHTML = '<div class="dtitle">' + icon + " " + p.name + ": " + p.value + '</div>' +
      '<div class="drec">' + recommend(p.name) + '</div>' +
      '<button class="ccopy" data-i="' + i + '">Показать на коде</button>';
    wrap.appendChild(d);
  });
  wrap.querySelectorAll("[data-i]").forEach(btn => {
    btn.addEventListener("click", () => {
      state.focus = parseInt(btn.dataset.i, 10);
      state.zoom = 1.5;
      drawScene();
    });
  });
}

function recommend(name) {
  if (name.includes("Размерность печати")) return "Рекомендация: отрегулировать чернила / давление печати.";
  if (name.includes("шаблона") || name.includes("тактовых")) return "Рекомендация: проверить чистоту формы и материала.";
  if (name.includes("Контраст")) return "Рекомендация: улучшить контраст краски и подложки.";
  if (name.includes("Неоднородность")) return "Рекомендация: проверить равномерность освещения и сетки.";
  if (name.includes("Декодирование")) return "Код не читается — требуется перепечатка.";
  if (name.includes("Запас коррекции")) return "Рекомендация: снизить повреждения модулей.";
  return "Рекомендация: проверить технологический процесс нанесения.";
}

function renderData(data) {
  const wrap = $("chips");
  wrap.innerHTML = "";
  (data.elements || []).forEach(el => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.innerHTML = '<div class="cname">' + el.name + '</div>' +
      '<div class="cval">' + el.value + '</div>' +
      '<button class="ccopy">Копировать</button>';
    chip.querySelector(".ccopy").addEventListener("click", () => {
      navigator.clipboard.writeText(el.value);
    });
    wrap.appendChild(chip);
  });
  $("copyall").disabled = !(data.content);
}

function renderReport(data) {
  const lines = [];
  lines.push("Класс: " + data.overall_class);
  lines.push("Валидация: " + data.validation);
  lines.push("Содержимое: " + (data.content || "(не декодировано)"));
  lines.push("Размер символа: " + data.symbol_size);
  lines.push("X-размерность: " + data.x_dim_um.toFixed(0) + " мкм | Y: " + data.y_dim_um.toFixed(0) + " мкм | Апертура: " + data.aperture_um + " мкм");
  lines.push("");
  lines.push("Параметры ISO 15415:");
  (data.params || []).forEach(p => {
    lines.push("  [" + (p.passed ? "OK" : "FAIL") + "] " + p.name + ": " + p.value);
  });
  lines.push("");
  lines.push("Данные GS1:");
  (data.elements || []).forEach(el => {
    lines.push("  " + el.name + " = " + el.value);
  });
  $("reporttext").textContent = lines.join("\n");
}

// ------------------------------------------------------------- analysis

function setImage(dataUrl) {
  const img = new Image();
  img.onload = () => { state.img = img; drawScene(); };
  img.src = dataUrl;
}

async function analyze(file) {
  const fd = new FormData();
  fd.append("image", file);
  $("validation").textContent = "Анализ...";
  $("validation").style.color = "#f9a825";
  try {
    const resp = await fetch("api/analyze", { method: "POST", body: fd });
    const data = await resp.json();
    if (data.error) {
      $("validation").textContent = data.error;
      $("validation").style.color = "#c62828";
      return;
    }
    setImage(data.image);
    render(data);
    state.analyzed++;
    $("history").textContent = "Проанализировано: " + state.analyzed + " кодов";
  } catch (e) {
    $("validation").textContent = "Ошибка сети: " + e;
    $("validation").style.color = "#c62828";
  }
}

// ------------------------------------------------------------- input

function wireDropzone() {
  const dz = $("dropzone");
  const file = $("file");
  dz.addEventListener("click", (e) => {
    if (e.target.tagName === "BUTTON" || e.target.tagName === "VIDEO") return;
    file.click();
  });
  file.addEventListener("change", () => {
    if (file.files[0]) analyze(file.files[0]);
  });
  ["dragover", "dragenter"].forEach(ev => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.add("over");
  }));
  ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => {
    e.preventDefault(); dz.classList.remove("over");
  }));
  dz.addEventListener("drop", (e) => {
    const f = e.dataTransfer.files && e.dataTransfer.files[0];
    if (f) analyze(f);
  });
}

function wireCamera() {
  let stream = null;
  $("cambtn").addEventListener("click", async () => {
    if (!stream) {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        $("video").hidden = false;
        $("video").srcObject = stream;
        $("cambtn").textContent = "📸 Снять кадр";
        await $("video").play();
      } catch (e) {
        $("validation").textContent = "Камера недоступна: " + e.message;
        $("validation").style.color = "#c62828";
        return;
      }
    }
    const v = $("video");
    const canvas = document.createElement("canvas");
    canvas.width = v.videoWidth;
    canvas.height = v.videoHeight;
    canvas.getContext("2d").drawImage(v, 0, 0);
    const blob = await new Promise(res => canvas.toBlob(res, "image/jpeg", 0.9));
    if (blob) {
      const f = new File([blob], "camera.jpg", { type: "image/jpeg" });
      analyze(f);
    }
  });
}

function wireControls() {
  $("zoomin").addEventListener("click", () => { state.zoom = Math.min(4, state.zoom + 0.25); drawScene(); });
  $("zoomout").addEventListener("click", () => { state.zoom = Math.max(0.5, state.zoom - 0.25); drawScene(); });
  $("rotate").addEventListener("click", () => { state.rotate++; drawScene(); });
  $("channel").addEventListener("change", (e) => { state.channel = e.target.value; drawScene(); });
  $("copyall").addEventListener("click", () => {
    if (state.result && state.result.content) navigator.clipboard.writeText(state.result.content);
  });
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    t.classList.add("active");
    ["defects", "data", "report"].forEach(id => $(id).classList.toggle("hidden", id !== t.dataset.tab));
  }));
  $("pdfbtn").addEventListener("click", async () => {
    if (!state.result || !state.result.result_id) return;
    const resp = await fetch("api/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ result_id: state.result.result_id }),
    });
    if (!resp.ok) { $("validation").textContent = "Ошибка PDF"; return; }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "verification_" + state.result.result_id + ".pdf";
    a.click();
    URL.revokeObjectURL(url);
  });
}

fetchVersion();
wireDropzone();
wireCamera();
wireControls();