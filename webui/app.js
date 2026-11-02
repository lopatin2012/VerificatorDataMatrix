"use strict";

const state = {
  result: null,
  results: [],
  current: 0,
  img: null,           // Image object of the base frame
  zoom: 1,
  panX: 0,
  panY: 0,
  rotate: 0,
  channel: "color",
  focus: null,
  history: [],
  showOverlay: true,
  crptCode: null,
  calibration: "",
  suppressClick: false,
  lastFile: null,
  lastFileName: "",
  lastUm: "",
  crptInfo: null,
};

const $ = (id) => document.getElementById(id);

// Rotating hints shown while a photo is analyzed: what the site can do, how
// Chestny Znak works, and DataMatrix facts. `kind` selects the badge style.
const PROCESS_TIPS = [
  { kind: "site", label: "Сайт", text: "Находит все DataMatrix на фото и показывает каждый отдельным результатом — можно переключаться в списке кодов." },
  { kind: "site", label: "Сайт", text: "Грейд печати считается по параметрам ISO/IEC 15415: контраст, неоднородность, сетка, тихая зона, запас коррекции ошибок." },
  { kind: "site", label: "Сайт", text: "Красные зоны на сцене показывают проблемные места символа, а карточка качества — параметр, который тянет грейд вниз." },
  { kind: "site", label: "Сайт", text: "Калибровку можно задать в мкм/px или пересчитать по паспортному X-dim — тогда размеры будут в микронах." },
  { kind: "site", label: "Сайт", text: "PDF-отчёт содержит класс, шкалу 4/3/2/1, параметры, данные GS1 и сведения Честного знака." },
  { kind: "site", label: "Сайт", text: "История проверок хранится в вашем браузере (до 50 записей); экспорт в CSV, TXT и PDF — сервер её не видит." },
  { kind: "site", label: "Сайт", text: "Камера: первый клик — предпросмотр, второй — снимок. Колесо мыши — зум, перетаскивание — панорама." },
  { kind: "site", label: "Сайт", text: "Без интернета работают анализ, грейды и отчёты: сеть нужна только для проверки в Честном знаке." },
  { kind: "cz", label: "Честный знак", text: "Система маркировки: уникальный код получает каждая упаковка, а не только вид товара." },
  { kind: "cz", label: "Честный знак", text: "Код маркировки = GTIN (AI 01) + серийный номер (AI 21) + криптоподпись (AI 91–93)." },
  { kind: "cz", label: "Честный знак", text: "Криптохвост привязан к конкретной упаковке: скопировать код на другую пачку не получится." },
  { kind: "cz", label: "Честный знак", text: "Статусы кода: эмитирован → нанесён → введён в оборот → выведен из оборота. «В обороте» — товар легально в продаже." },
  { kind: "cz", label: "Честный знак", text: "Запрос в ЧЗ уходит только по кнопке «Проверить в ЧЗ»; приложение не отправляет коды само и не пишет их в логи." },
  { kind: "cz", label: "Честный знак", text: "Порог качества печати в ЧЗ — грейд выше 1,5; в приложении такой код получает вердикт «ГОДЕН»." },
  { kind: "fact", label: "Факт", text: "DataMatrix изобрели в 1987 году для электроники: им маркируют микросхемы, детали, лекарства и почту." },
  { kind: "fact", label: "Факт", text: "В DataMatrix помещается до 3116 цифр — в сотни раз больше, чем в обычном штрихкоде EAN-13." },
  { kind: "fact", label: "Факт", text: "Коррекция ошибок Рида–Соломона позволяет прочитать символ, даже если часть модулей стёрта или залита." },
  { kind: "fact", label: "Факт", text: "Сплошные линии «L» слева и снизу задают ориентацию, поэтому код читается в любом повороте." },
  { kind: "fact", label: "Факт", text: "Чем меньше модуль (X-dim), тем выше требования к печати: при 0,3 мм ошибка в один модуль заметнее, чем при 1 мм." },
];
let _progressTipTimer = null;
let _progressTipIndex = 0;

function showProcessTip(index) {
  const el = $("progresstip");
  if (!el) return;
  const tip = PROCESS_TIPS[index % PROCESS_TIPS.length];
  el.innerHTML = "";
  const badge = document.createElement("span");
  badge.className = "tipbadge tip-" + tip.kind;
  badge.textContent = tip.label;
  el.appendChild(badge);
  el.appendChild(document.createTextNode(" " + tip.text));
}

function startProgress(title) {
  const box = $("progress");
  if (!box) return;
  box.hidden = false;
  $("progresstitle").textContent = title || "Обработка...";
  $("progresspct").textContent = "0%";
  const fill = $("progressfill");
  fill.classList.remove("indeterminate");
  fill.style.width = "0%";
  _progressTipIndex = 0;
  showProcessTip(0);
  if (_progressTipTimer) clearInterval(_progressTipTimer);
  _progressTipTimer = setInterval(() => {
    _progressTipIndex = (_progressTipIndex + 1) % PROCESS_TIPS.length;
    showProcessTip(_progressTipIndex);
  }, 5000);
}

function setProgress(pct, title) {
  const fill = $("progressfill");
  if (!fill) return;
  fill.classList.remove("indeterminate");
  fill.style.width = Math.max(0, Math.min(100, pct)) + "%";
  $("progresspct").textContent = Math.round(pct) + "%";
  if (title) $("progresstitle").textContent = title;
}

function indeterminateProgress(title) {
  const fill = $("progressfill");
  if (!fill) return;
  fill.classList.add("indeterminate");
  fill.style.width = "";
  $("progresspct").textContent = "…";
  if (title) $("progresstitle").textContent = title;
}

function stopProgress() {
  const box = $("progress");
  if (box) box.hidden = true;
  if (_progressTipTimer) {
    clearInterval(_progressTipTimer);
    _progressTipTimer = null;
  }
}

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).then(() => true, () => fallbackCopy(text));
  }
  return Promise.resolve(fallbackCopy(text));
}

function fallbackCopy(text) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.focus();
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

function flashCopy(btn, ok) {
  const old = btn.textContent;
  btn.textContent = ok ? "✓ Скопировано" : "Ошибка копирования";
  btn.disabled = true;
  setTimeout(() => { btn.textContent = old; btn.disabled = false; }, 1200);
}

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

function displayWithGS(text) {
  if (!text) return "";
  return text.replace(/\u001d/g, "[GS]");
}

function drawScene() {
  if (!state.img) return;
  const canvas = $("scene");
  const ctx = canvas.getContext("2d");
  const cw = canvas.clientWidth || 600;
  const ch = canvas.clientHeight || 400;
  if (canvas.width !== cw) canvas.width = cw;
  if (canvas.height !== ch) canvas.height = ch;

  // figure display transform: same mapping drives both drawImage and toCanvas
  const w = state.img.naturalWidth, h = state.img.naturalHeight;
  const rot = state.rotate % 4;
  const rw = (rot % 2) ? h : w;   // on-screen width after rotation
  const rh = (rot % 2) ? w : h;   // on-screen height after rotation
  const scale = Math.min(cw / rw, ch / rh) * state.zoom;
  const fitW = rw * scale, fitH = rh * scale;

  // drawing box in the rotated local frame
  let localW = fitW, localH = fitH;
  if (rot % 2) { localW = fitH; localH = fitW; }

  const maxPanX = Math.max(0, (localW - cw) / 2);
  const maxPanY = Math.max(0, (localH - ch) / 2);
  state.panX = Math.max(-maxPanX, Math.min(maxPanX, state.panX));
  state.panY = Math.max(-maxPanY, Math.min(maxPanY, state.panY));
  const originX = cw / 2 + state.panX;
  const originY = ch / 2 + state.panY;

  ctx.clearRect(0, 0, cw, ch);
  ctx.save();
  ctx.translate(originX, originY);
  if (rot) ctx.rotate(rot * Math.PI / 2);

  // a soft matte shadow makes the photo read as a placed sheet on the scene
  ctx.shadowColor = "rgba(0, 0, 0, .45)";
  ctx.shadowBlur = 26;
  ctx.shadowOffsetY = 10;

  // channel filter
  ctx.filter = "none";
  if (state.channel === "gray") ctx.filter = "grayscale(1)";
  else if (state.channel === "ir") ctx.filter = "grayscale(1) contrast(1.6)";
  ctx.drawImage(state.img, -localW / 2, -localH / 2, localW, localH);
  ctx.filter = "none";
  ctx.restore();

  // map original image coords -> canvas coords. toCanvas returns ABSOLUTE
  // canvas coordinates, so the overlay must be drawn in the identity
  // transform (not inside the translate/rotate used for drawImage).
  const sx = localW / w, sy = localH / h;
  const toCanvas = (x, y) => {
    const lx = x * sx - localW / 2, ly = y * sy - localH / 2;
    let rx, ry;
    switch (rot) {
      case 0: rx = lx; ry = ly; break;
      case 1: rx = -ly; ry = lx; break;
      case 2: rx = -lx; ry = -ly; break;
      default: rx = ly; ry = -lx; break;
    }
    return [originX + rx, originY + ry];
  };

  // symbol outlines + heatmap for every detected code
  if (state.showOverlay) {
    const sevColor = { critical: "#e53935", warning: "#fdd835", minor: "#fb8c00" };
    (state.results || []).forEach((r, ri) => {
      const isCur = ri === state.current;
      if (r.corners) {
        const c = r.corners;
        ctx.beginPath();
        const p0 = toCanvas(c[0], c[1]);
        ctx.moveTo(p0[0], p0[1]);
        for (let k = 2; k < c.length; k += 2) {
          const p = toCanvas(c[k], c[k + 1]);
          ctx.lineTo(p[0], p[1]);
        }
        ctx.closePath();
        ctx.strokeStyle = isCur ? "#2e7d32" : "#90a4ae";
        ctx.lineWidth = isCur ? 3 : 1.5;
        ctx.stroke();
      }
      if (!isCur) return;
      (r.regions || []).forEach((reg, i) => {
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
    });
  }

  // Nothing decoded -> say it right on the image so it is not missed.
  // (kept centered on the canvas; the image may be panned away)
  const hasCode = (state.results || []).some((r) => r.corners);
  if (!hasCode) {
    const text = "Код не найден";
    const fs = Math.max(18, Math.round(ch * 0.06));
    ctx.font = "bold " + fs + "px 'Segoe UI', Arial, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    const tw = ctx.measureText(text).width;
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(cw / 2 - tw / 2 - 18, ch / 2 - fs / 2 - 12, tw + 36, fs + 24);
    ctx.fillStyle = "#ff5252";
    ctx.fillText(text, cw / 2, ch / 2);
  }
}

function zoomAt(anchorX, anchorY, factor) {
  const next = Math.max(0.5, Math.min(4, state.zoom * factor));
  if (Math.abs(next - state.zoom) < 1e-4) return;
  const k = next / state.zoom;
  state.panX = anchorX - (anchorX - state.panX) * k;
  state.panY = anchorY - (anchorY - state.panY) * k;
  state.zoom = next;
  drawScene();
}

function resetView() {
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
  state.rotate = 0;
  drawScene();
}

// ------------------------------------------------------------- rendering

function render(data) {
  state.results = Array.isArray(data.results) && data.results.length
    ? data.results
    : (data.result_id ? [data] : []);
  state.current = 0;
  state.focus = null;
  renderCodeSelect();
  if (state.results.length) {
    renderResult(state.results[0]);
    if (data.crpt) renderCrpt(data.crpt);
  } else {
    renderEmpty(data);
  }
  renderHistory();
  drawScene();
}

function initEmptyState() {
  drawGauge(0, "#cfd8dc");
  $("calibbtn").disabled = true;
  renderParamsEmpty();
  renderData({});
  $("defects").innerHTML =
    '<div class="defect" style="border-color:var(--line)">' +
    '<div class="dtitle">Нет данных</div>' +
    '<div class="drec">Загрузите изображение для проверки.</div></div>';
  $("reporttext").textContent =
    "Загрузите изображение, чтобы сформировать отчёт.";
  $("pdfbtn").disabled = true;
  resetCrpt();
  $("crptbtn").disabled = true;
}

function renderEmpty(data) {
  const msg = data.error || "Код не найден";
  $("validation").textContent = msg;
  $("validation").style.color = "#c62828";
  $("score").textContent = "—";
  $("score").style.color = "#607d8b";
  $("grade").textContent = "—";
  $("grade").style.color = "#607d8b";
  drawGauge(0, "#cfd8dc");
  $("verdict").textContent = "БРАК";
  $("verdict").style.color = "#c62828";
  $("reason").textContent = msg;
  $("reason").style.color = "";
  ["msymb", "mdim", "maper", "mcal"].forEach((id) => {
    const el = $(id);
    if (el) el.textContent = "—";
  });
  $("calibbtn").disabled = true;
  renderParamsEmpty();
  const defectCount = $("defectcount");
  if (defectCount) defectCount.textContent = "";
  $("defects").innerHTML =
    '<div class="defect" style="border-color:#90a4ae">' +
    '<div class="dtitle">Код не найден</div>' +
    '<div class="drec">Дефекты не определены.</div></div>';
  renderData({});
  $("reporttext").textContent = "Нет данных для отчёта.";
  $("pdfbtn").disabled = true;
  state.crptCode = null;
  resetCrpt();
  $("crptbtn").disabled = true;
}

function renderParamsEmpty() {
  const wrap = $("params");
  wrap.innerHTML = "";
  const keys = ["Контраст символа", "Неоднородность сетки",
                "Размерность печати X", "Последовательность тактовых модулей"];
  keys.forEach(k => {
    const row = document.createElement("div");
    row.className = "param";
    row.innerHTML = '<span class="pname">' + k + '</span>' +
      '<span class="ptrack"></span><span class="pval">—</span>';
    wrap.appendChild(row);
  });
}

function renderCodeSelect() {
  const wrap = $("codeselect");
  wrap.innerHTML = "";
  if (!state.results.length) return;
  state.results.forEach((r, i) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn small codesel-btn" + (i === state.current ? " active" : "");
    const grade = r.min_grade != null ? r.min_grade.toFixed(1).replace(".", ",") : "—";
    btn.textContent = "Код " + (i + 1) + " — " + grade;
    btn.addEventListener("click", () => {
      state.current = i;
      state.focus = null;
      renderCodeSelect();
      renderResult(r);
      drawScene();
    });
    wrap.appendChild(btn);
  });
}

function renderResult(r) {
  state.result = r;
  state.focus = null;

  const good = r.good;
  const vcolor = good ? "#2e7d32" : "#c62828";
  const val = $("validation");
  const readOk = r.validation === "OK";
  const gs1 = r.gs1_status === "ok" ? "OK"
    : (r.gs1_status === "warn"
      ? ((r.gs1_warnings || []).length + " предупр.") : "—");
  val.textContent = "Чтение: " + (readOk ? "OK" : "ошибка") + " · GS1: " + gs1;
  val.style.color = !readOk ? "#c62828"
    : (r.gs1_status === "warn" ? "#f9a825" : "#2e7d32");

  const scoreEl = $("score");
  scoreEl.innerHTML = r.score + '<span class="of"> из 100</span>';
  scoreEl.style.color = r.color;
  $("grade").textContent = "Грейд " + r.min_grade.toFixed(1).replace(".", ",") +
    (r.symbol_size ? " / " + r.symbol_size : "") +
    (r.calibration_default ? " · без калибровки" : "");
  $("grade").title = "Порог качества печати в ЧЗ: грейд выше 1,5";
  $("grade").style.color = vcolor;
  drawGauge(r.score, r.color);

  $("verdict").textContent = good ? "ГОДЕН" : "БРАК";
  $("verdict").style.color = good ? "#2e7d32" : "#c62828";
  const graded = (r.params || []).filter((p) => p.level);
  const worst = graded.length
    ? graded.reduce((a, b) => (b.grade < a.grade ? b : a))
    : null;
  if (worst && worst.grade < 4) {
    $("reason").textContent = "Ограничивает: " + worst.name + " — " +
      worst.value + " (" + worst.grade + ")";
    $("reason").style.color = worst.grade < 3 ? "#b91c1c" : "#b45309";
  } else {
    $("reason").textContent = r.error || "Все параметры в норме";
    $("reason").style.color = "";
  }
  const num = (v) => v == null ? "—" : Number(v).toLocaleString("ru-RU",
    { maximumFractionDigits: 1 });
  $("msymb").textContent = r.symbology || "—";
  $("mdim").textContent = (r.x_dim_um != null && r.y_dim_um != null)
    ? Math.round(r.x_dim_um) + " × " + Math.round(r.y_dim_um) + " мкм"
    : "—";
  $("maper").textContent = r.aperture_um ? r.aperture_um + " мкм" : "—";
  $("mcal").textContent = r.um_per_px
    ? num(r.um_per_px) + " мкм/px" +
      (r.calibration_default ? " · по умолч." : "")
    : "—";
  $("calibbtn").disabled = !r.module_px_x;
  renderParams(r);
  renderDefects(r);
  renderData(r);
  renderReport(r);
  $("pdfbtn").disabled = false;
  const code = r.content_raw || "";
  if (code !== state.crptCode) {
    state.crptCode = code;
    resetCrpt();
  }
  $("crptbtn").disabled = !code;
  const crptBox = $("crptinfo");
  if (crptBox && !crptBox.children.length) {
    setCrptHelp(crptAvailabilityHint(r));
  }
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
    const color = grade >= 3 ? "#2e7d32" : (grade >= 2 ? "#fdd835" : "#c62828");
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
  const bad = (data.params || []).filter(p => p.level && p.level !== "ok");
  const countEl = $("defectcount");
  if (countEl) countEl.textContent = bad.length ? String(bad.length) : "";
  if (!bad.length) {
    wrap.innerHTML = '<div class="defect" style="border-color:#2e7d32"><div class="dtitle">Все параметры в норме ✅</div></div>';
    return;
  }
  bad.forEach((p, i) => {
    const isErr = p.level === "error";
    const icon = isErr ? "🚫" : "⚠️";
    const status = isErr ? "Ошибка" : "Предупреждение";
    const cls = isErr ? "" : "warn";
    const d = document.createElement("div");
    d.className = "defect " + cls;
    d.innerHTML = '<div class="dtitle">' + icon + " " + p.name + ": " + p.value + '</div>' +
      '<div class="dstatus">' + status + '</div>' +
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

  var contentDisplay = $("contentdisplay");
  if (contentDisplay) {
    var plain = data.content_plain || (data.content || "").replace(/[()]/g, "");
    contentDisplay.textContent = displayWithGS(plain) || "—";
  }
  const dataHint = $("datahint");
  if (dataHint) dataHint.hidden = !!(data && data.content);

  const warn = $("gswarn");
  if (warn) {
    warn.innerHTML = "";
    (data.gs1_warnings || []).forEach(w => {
      const d = document.createElement("div");
      d.className = "gswarnitem";
      d.textContent = "⚠ " + w;
      warn.appendChild(d);
    });
  }

  (data.elements || []).forEach(el => {
    const chip = document.createElement("div");
    chip.className = "chip";
    const name = document.createElement("div");
    name.className = "cname";
    name.textContent = el.label || el.name;
    const val = document.createElement("div");
    val.className = "cval";
    val.textContent = el.display_value || el.value;
    if (el.description) val.title = el.description;
    const btn = document.createElement("button");
    btn.className = "ccopy";
    btn.textContent = "Копировать";
    btn.addEventListener("click", (e) => {
      copyText(el.value).then(ok => flashCopy(e.target, ok));
    });
    chip.appendChild(name);
    chip.appendChild(val);
    chip.appendChild(btn);
    wrap.appendChild(chip);
  });
  $("copyall").disabled = !(data.content);
  if ($("copyhri")) $("copyhri").disabled = !(data.content_hri);
}

function setCrptStatus(text, color) {
  const el = $("crptstatus");
  if (!el) return;
  el.textContent = text;
  el.style.color = color || "#78909c";
}

function resetCrpt() {
  state.crptInfo = null;
  setCrptStatus("Не проверено", "#78909c");
  setCrptHelp("");
  const box = $("crptinfo");
  if (box) box.innerHTML = "";
}

function setCrptHelp(text) {
  const el = $("crpthelp");
  if (el) el.textContent = text || "";
}

function crptResultHint(info) {
  if (!info || info.error || info.ok === false) {
    return "Проверьте подключение и повторите запрос позже — качество " +
      "печати и отчёт считаются без сети.";
  }
  if (info.found && info.check) {
    return "Код зарегистрирован и криптохвост подтверждён. Сверьте товар, " +
      "производителя и срок годности с упаковкой.";
  }
  if (info.found) {
    return "Код есть в ГИС МТ, но криптоподпись не подтверждена: так " +
      "отвечают демо-коды, коды с повреждённым криптохвостом и подделки. " +
      "Переснимите код и сверьте товар с упаковкой.";
  }
  return "Кода нет в ГИС МТ: проверьте, что считан весь код (AI 01, 21 " +
    "и 91–93), и попробуйте переснять изображение.";
}

function crptAvailabilityHint(data) {
  const code = data && (data.content_raw || data.content);
  if (!code) {
    return "Код не распознан — сначала добейтесь уверенного чтения.";
  }
  const elements = data.elements || [];
  if (!elements.length) {
    return "Это не GS1-код: для проверки в ЧЗ нужен код маркировки " +
      "с AI 01, 21 и криптохвостом.";
  }
  const hasCrypto = elements.some(
    (el) => ["91", "92", "93"].includes(String(el.ai)));
  if (!hasCrypto) {
    return "В коде нет криптохвоста (AI 91–93): ЧЗ, скорее всего, ответит " +
      "«не найден» или «проверка не пройдена».";
  }
  return "Код содержит криптохвост — можно отправлять на проверку в ЧЗ.";
}

function crptRow(label, value) {
  const row = document.createElement("div");
  row.className = "crptrow";
  const key = document.createElement("div");
  key.className = "crptkey";
  key.textContent = label;
  const val = document.createElement("div");
  val.className = "crptval";
  val.textContent = value;
  row.appendChild(key);
  row.appendChild(val);
  return row;
}

function renderCrpt(info) {
  const box = $("crptinfo");
  if (!box) return;
  box.innerHTML = "";
  if (!info || info.error || info.ok === false) {
    state.crptInfo = null;
    setCrptStatus("Ошибка запроса", "#c62828");
    setCrptHelp(crptResultHint(info));
    box.appendChild(crptRow("Ошибка",
      info && info.error ? info.error : "неизвестная ошибка"));
    return;
  }
  state.crptInfo = info;
  if (info.found && info.check) {
    setCrptStatus("Найден, проверка пройдена", "#2e7d32");
  } else if (info.found) {
    setCrptStatus("Найден, проверка не пройдена", "#f9a825");
  } else {
    setCrptStatus("Не найден в ГИС МТ", "#c62828");
  }
  setCrptHelp(crptResultHint(info));
  const fields = [
    ["Статус", info.status_text],
    ["Проверка кода", info.check_status_text],
    ["Товар", info.product_name],
    ["Категория", info.category_text],
    ["Производитель", info.producer],
    ["Владелец", info.owner],
    ["ИНН владельца", info.owner_inn],
    ["Бренд", info.brand],
    ["Страна", info.country],
    ["GTIN", info.gtin],
    ["Серийный номер", info.serial],
    ["Срок годности", info.expiry],
    ["Дата производства", info.produced],
    ["Сообщение", info.message],
    ["Предупреждение", info.warning_text],
  ];
  fields.forEach(([label, value]) => {
    if (value) box.appendChild(crptRow(label, value));
  });
  const attrs = info.attributes || {};
  Object.keys(attrs).forEach(name => {
    box.appendChild(crptRow(name, attrs[name]));
  });
}

function renderReport(data) {
  const lines = [];
  lines.push("Класс: " + data.overall_class);
  if (data.class_code) lines.push("Код класса (машинный): " + data.class_code);
  lines.push("Чтение: " + (data.validation === "OK" ? "OK" : "НЕ ДЕКОДИРОВАНО"));
  const gs1 = data.gs1_status === "ok" ? "OK"
    : (data.gs1_status === "warn"
      ? ((data.gs1_warnings || []).length + " предупр.") : "—");
  lines.push("GS1: " + gs1);
  const quality = data.quality_ok ? "ГОДЕН" : (data.read_ok ? "БРАК" : "—");
  const grade = data.min_grade != null
    ? data.min_grade.toFixed(1).replace(".", ",") : "—";
  lines.push("Качество: " + quality + " (грейд " + grade + ")");
  if (data.calibration_note) lines.push(data.calibration_note);
  if (data.calibration_warning) {
    lines.push("ВНИМАНИЕ: " + data.calibration_warning);
  }
  lines.push("Символ: " + (data.symbology || "—"));
  lines.push("Содержимое: " + (data.content || "(не декодировано)"));
  if (data.content_hri) lines.push("HRI: " + data.content_hri);
  lines.push("Размер символа: " + data.symbol_size);
  lines.push("X-размерность: " + data.x_dim_um.toFixed(0) + " мкм | Y: " +
             data.y_dim_um.toFixed(0) + " мкм | Апертура: " +
             data.aperture_um + " мкм");
  lines.push("");
  lines.push("Параметры ISO 15415 (оценка, не сертификация):");
  (data.params || []).forEach(p => {
    const mark = p.level === "ok" ? "OK" : (p.level === "warn" ? "WARN" : "FAIL");
    lines.push("  [" + mark + "] " + p.name + ": " + (p.display || p.value));
  });
  lines.push("");
  lines.push("Шкала оценок 4/3/2/1:");
  (data.params || []).forEach(p => {
    if (p.scale) lines.push("  " + p.name + ": " + p.scale);
  });
  if ((data.gs1_warnings || []).length) {
    lines.push("");
    lines.push("Предупреждения GS1 (" + data.gs1_warnings.length + "):");
    data.gs1_warnings.forEach(w => lines.push("  ! " + w));
  }
  lines.push("");
  lines.push("Данные GS1:");
  (data.elements || []).forEach(el => {
    lines.push("  " + (el.label || el.name) + " = " +
               (el.display_value || el.value));
  });
  if (!(data.elements || []).length) lines.push("  (нет)");
  lines.push("");
  lines.push("Грейды — оценка по ISO/IEC 15415, не сертификация.");
  $("reporttext").textContent = lines.join("\n");
}

// ------------------------------------------------------------- history (IndexedDB)

const HISTORY_DB = "dm_verifier";
const HISTORY_STORE = "history";
const HISTORY_LIMIT = 50;
let _historyDb = null;

function openHistoryDb() {
  if (!("indexedDB" in window)) {
    return Promise.reject(new Error("IndexedDB недоступен"));
  }
  if (_historyDb) return _historyDb;
  _historyDb = new Promise((resolve, reject) => {
    const req = indexedDB.open(HISTORY_DB, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(HISTORY_STORE)) {
        db.createObjectStore(HISTORY_STORE, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return _historyDb;
}

async function historyAll() {
  try {
    const db = await openHistoryDb();
    return await new Promise((resolve, reject) => {
      const tx = db.transaction(HISTORY_STORE, "readonly");
      const req = tx.objectStore(HISTORY_STORE).getAll();
      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  } catch (e) {
    return (state.history || []).slice();
  }
}

async function historyPut(entry) {
  state.history = [entry, ...(state.history || [])
    .filter((e) => e.id !== entry.id)]
    .sort((a, b) => b.ts - a.ts)
    .slice(0, HISTORY_LIMIT);
  try {
    const db = await openHistoryDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(HISTORY_STORE, "readwrite");
      tx.objectStore(HISTORY_STORE).put(entry);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) { /* fall back to the in-memory list */ }
}

async function historyDelete(id) {
  state.history = (state.history || []).filter((e) => e.id !== id);
  try {
    const db = await openHistoryDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(HISTORY_STORE, "readwrite");
      tx.objectStore(HISTORY_STORE).delete(id);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) { /* ignore */ }
}

async function historyClearAll() {
  state.history = [];
  try {
    const db = await openHistoryDb();
    await new Promise((resolve, reject) => {
      const tx = db.transaction(HISTORY_STORE, "readwrite");
      tx.objectStore(HISTORY_STORE).clear();
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch (e) { /* ignore */ }
}

async function historyTrim() {
  const all = await historyAll();
  all.sort((a, b) => b.ts - a.ts);
  for (const entry of all.slice(HISTORY_LIMIT)) {
    await historyDelete(entry.id);
  }
}

function makeThumb(blob) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => {
      const W = 176, H = 120;
      const canvas = document.createElement("canvas");
      canvas.width = W;
      canvas.height = H;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#f1f5f9";
      ctx.fillRect(0, 0, W, H);
      const scale = Math.min(W / img.width, H / img.height);
      const w = img.width * scale, h = img.height * scale;
      ctx.drawImage(img, (W - w) / 2, (H - h) / 2, w, h);
      URL.revokeObjectURL(url);
      resolve(canvas.toDataURL("image/jpeg", 0.75));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      resolve("");
    };
    img.src = url;
  });
}

async function saveHistory(file, results, um, replaceId) {
  if (!file || !results || !results.length) return;
  if (replaceId) await historyDelete(replaceId);
  const thumb = await makeThumb(file);
  const base = Date.now() / 1000;
  for (let i = 0; i < results.length; i++) {
    const result = results[i];
    const entry = {
      id: result.result_id || ("r" + base + i),
      ts: base + i * 0.001,
      thumb,
      payload: result,
      image: file,
      um: um || "",
      crpt: (state.crptInfo && state.crptCode &&
        (result.content_raw || result.content) === state.crptCode)
        ? state.crptInfo : null,
      result_index: i,
      file_name: file.name || state.lastFileName || "изображение",
    };
    await historyPut(entry);
  }
  await historyTrim();
  await loadHistory();
}

async function loadHistory() {
  const all = await historyAll();
  state.history = all.sort((a, b) => b.ts - a.ts);
  renderHistory();
}

function historyTime(ts) {
  return new Date(ts * 1000).toLocaleString("ru-RU");
}

function historyGs1(d) {
  if (d.gs1_status === "warn") {
    return (d.gs1_warnings || []).length + " предупр.";
  }
  if (d.gs1_status === "ok") return "OK";
  return "—";
}

function historyQuality(d) {
  if (d.quality_ok) return "ГОДЕН";
  if (d.read_ok) return "БРАК";
  return "—";
}

function renderHistory() {
  const strip = $("historystrip");
  if (!strip) return;
  strip.innerHTML = "";
  const items = state.history || [];
  const ok = items.filter((it) => it.payload && it.payload.good).length;
  $("history").textContent = "Проанализировано: " + items.length + " кодов. " +
    ok + " - OK, " + (items.length - ok) + " - Брак";
  const countEl = $("histcount");
  if (countEl) countEl.textContent = items.length ? String(items.length) : "";
  const activeId = state.result && state.result.result_id;
  items.forEach((it) => {
    const d = it.payload || {};
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "histitem " + (d.good ? "ok" : "bad") +
      (it.id === activeId ? " active" : "");
    const read = d.read_ok ? "Чтение: OK" : "Чтение: ошибка";
    const qual = historyQuality(d);
    btn.title = read + " · Качество: " + qual + " · " +
      (d.overall_class || "") + " · " + (d.content || "(не декодировано)");
    const img = document.createElement("img");
    img.src = it.thumb || "";
    img.alt = "";
    const cap = document.createElement("span");
    cap.className = "histcap";
    const time = it.ts
      ? new Date(it.ts * 1000).toLocaleTimeString("ru-RU",
          { hour: "2-digit", minute: "2-digit" })
      : "";
    cap.textContent = (d.good ? "OK" : "БРАК") + " · " + (d.score ?? "—") +
      (time ? " · " + time : "");
    btn.appendChild(img);
    btn.appendChild(cap);
    btn.addEventListener("click", () => loadHistoryEntry(it));
    strip.appendChild(btn);
  });
}

function loadHistoryEntry(entry) {
  if (!entry || !entry.image) return;
  state.lastFile = entry.image;
  state.lastFileName = entry.file_name || "изображение";
  state.lastUm = entry.um || "";
  state.calibration = state.lastUm;
  const umInput = $("umpp");
  if (umInput) umInput.value = state.lastUm;
  const nameEl = $("filename");
  if (nameEl) nameEl.textContent = entry.file_name || "изображение";
  state.crptInfo = entry.crpt || null;
  state.crptCode = entry.crpt
    ? (entry.payload.content_raw || entry.payload.content || null)
    : null;
  const url = URL.createObjectURL(entry.image);
  setImage(url);
  state.results = [entry.payload];
  state.current = 0;
  render({ results: [entry.payload], crpt: entry.crpt || null });
}

function historyRow(entry) {
  const d = entry.payload || {};
  return {
    ts_text: historyTime(entry.ts),
    validation: d.validation,
    overall_class: d.overall_class,
    score: d.score,
    content: d.content,
    good: d.good,
    gs1_status: d.gs1_status,
    gs1_warnings: d.gs1_warnings || [],
    read_ok: d.read_ok,
    quality_ok: d.quality_ok,
  };
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[;"\r\n]/.test(text)) return '"' + text.replace(/"/g, '""') + '"';
  return text;
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function historyCsv() {
  if (!state.history.length) {
    $("validation").textContent = "История пуста";
    $("validation").style.color = "#c62828";
    return;
  }
  const lines = [[
    "Время", "Чтение", "GS1", "Качество", "Класс", "Оценка",
    "Символ", "Содержимое", "Калибровка", "Данные GS1",
  ].map(csvCell).join(";")];
  state.history.forEach((entry) => {
    const d = entry.payload || {};
    const elems = (d.elements || []).map((el) =>
      (el.label || el.name) + "=" + (el.display_value || el.value)).join("; ");
    lines.push([
      historyTime(entry.ts),
      d.read_ok ? "OK" : "ошибка",
      historyGs1(d),
      historyQuality(d),
      d.overall_class || "",
      d.score ?? "",
      d.symbol_size || "",
      d.content || "",
      d.calibration_note || "",
      elems,
    ].map(csvCell).join(";"));
  });
  downloadBlob(new Blob(["\ufeff" + lines.join("\r\n")],
    { type: "text/csv;charset=utf-8" }), "history.csv");
}

function historyTxt() {
  const lines = state.history.map((entry) => {
    const d = entry.payload || {};
    return (d.content_plain || d.content || "")
      .replace(/[\r\n]+/g, " ");
  }).filter(Boolean);
  if (!lines.length) {
    $("validation").textContent = "История пуста";
    $("validation").style.color = "#c62828";
    return;
  }
  downloadBlob(new Blob([lines.join("\r\n") + "\r\n"],
    { type: "text/plain;charset=utf-8" }), "history.txt");
}

async function historyPdf() {
  if (!state.history.length) {
    $("validation").textContent = "История пуста";
    $("validation").style.color = "#c62828";
    return;
  }
  try {
    const resp = await fetch("api/history.pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: state.history.map(historyRow) }),
    });
    if (!resp.ok) {
      let msg = "Ошибка PDF";
      try { msg = (await resp.json()).error || msg; } catch (e) { /* ignore */ }
      $("validation").textContent = msg;
      $("validation").style.color = "#c62828";
      return;
    }
    downloadBlob(await resp.blob(), "history.pdf");
  } catch (e) {
    $("validation").textContent = "Ошибка сети: " + e;
    $("validation").style.color = "#c62828";
  }
}

async function updateHistoryCrpt(id, info) {
  if (!id) return;
  const entry = state.history.find((e) => e.id === id);
  if (!entry) return;
  entry.crpt = info;
  await historyPut(entry);
}

// ------------------------------------------------------------- analysis

function setImage(dataUrl) {
  const img = new Image();
  img.onload = () => {
    state.img = img;
    state.zoom = 1;
    state.panX = 0;
    state.panY = 0;
    state.rotate = 0;
    $("dropmsg").hidden = true;
    $("dropzone").classList.add("has-image");
    drawScene();
    if (dataUrl.startsWith("blob:")) URL.revokeObjectURL(dataUrl);
  };
  img.src = dataUrl;
}

function analyze(file, options = {}) {
  if (window.__stopCamera) window.__stopCamera();
  const fd = new FormData();
  fd.append("image", file);
  const fileName = (file && file.name) || options.fileName ||
    state.lastFileName || "изображение";
  state.lastFileName = fileName;
  const nameEl = $("filename");
  if (nameEl) nameEl.textContent = fileName;
  const um = ($("umpp").value || "").trim();
  if (um) fd.append("um_per_px", um.replace(",", "."));
  state.lastFile = file;
  state.lastUm = um;
  if (!options.replaceId) {
    state.crptInfo = null;
    state.crptCode = null;
  }
  $("validation").textContent = "Анализ...";
  $("validation").style.color = "#f9a825";
  startProgress("Загрузка изображения...");

  const xhr = new XMLHttpRequest();
  xhr.open("POST", "api/analyze");
  xhr.timeout = 120000;
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    setProgress(e.loaded / e.total * 60, "Загрузка изображения...");
  };
  xhr.upload.onload = () => indeterminateProgress("Анализ изображения...");
  xhr.onload = () => {
    stopProgress();
    let data = {};
    try { data = JSON.parse(xhr.responseText || "{}"); } catch (e) { data = {}; }
    if (!data.image) {
      $("validation").textContent =
        data.error || ("Ошибка анализа (HTTP " + xhr.status + ")");
      $("validation").style.color = "#c62828";
      return;
    }
    setImage(data.image);
    render(data);
    if (data.results && data.results.length) {
      saveHistory(file, data.results, um, options.replaceId);
    } else {
      loadHistory();
    }
  };
  xhr.onerror = () => {
    stopProgress();
    $("validation").textContent = "Ошибка сети";
    $("validation").style.color = "#c62828";
  };
  xhr.ontimeout = () => {
    stopProgress();
    $("validation").textContent = "Превышено время анализа";
    $("validation").style.color = "#c62828";
  };
  xhr.send(fd);
}

// ------------------------------------------------------------- input

function wireDropzone() {
  const dz = $("dropzone");
  const file = $("file");
  const pick = $("pickbtn");
  if (pick) {
    pick.addEventListener("click", (e) => {
      e.stopPropagation();
      file.click();
    });
  }
  dz.addEventListener("click", (e) => {
    if (state.suppressClick) {
      state.suppressClick = false;
      return;
    }
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
  const video = $("video");
  const btn = $("cambtn");

  function stopCamera() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    video.hidden = true;
    video.srcObject = null;
    btn.textContent = "📷 Камера";
    if (!state.img) $("dropmsg").hidden = false;
  }

  btn.addEventListener("click", async () => {
    if (!stream) {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
        });
      } catch (e) {
        $("validation").textContent = "Камера недоступна: " + e.message;
        $("validation").style.color = "#c62828";
        return;
      }
      video.srcObject = stream;
      video.hidden = false;
      $("dropmsg").hidden = true;
      btn.textContent = "📸 Снять кадр";
      try { await video.play(); } catch (e) { /* autoplay may be blocked */ }
      return;
    }

    if (!video.videoWidth || !video.videoHeight) {
      $("validation").textContent = "Камера ещё не готова";
      $("validation").style.color = "#f9a825";
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    const blob = await new Promise(res => canvas.toBlob(res, "image/jpeg", 0.9));
    stopCamera();
    if (blob) {
      const f = new File([blob], "camera.jpg", { type: "image/jpeg" });
      analyze(f);
    }
  });
  window.__stopCamera = stopCamera;
  window.addEventListener("beforeunload", stopCamera);
}

function saveCalibration(value) {
  try {
    if (value) localStorage.setItem("dm_um_per_px", value);
    else localStorage.removeItem("dm_um_per_px");
  } catch (e) { /* storage disabled */ }
}

function reanalyzeCurrent() {
  if (!state.lastFile) return;
  const cur = state.results[state.current];
  analyze(state.lastFile, {
    replaceId: cur ? cur.result_id : null,
    fileName: state.lastFileName,
  });
}

function wireCalibration() {
  const el = $("umpp");
  if (!el) return;
  try {
    const saved = localStorage.getItem("dm_um_per_px");
    if (saved) el.value = saved;
  } catch (e) { /* storage disabled */ }
  state.calibration = (el.value || "").trim();
  el.addEventListener("change", () => {
    const value = (el.value || "").trim();
    if (value === state.calibration) return;
    if (value) {
      const parsed = Number(value.replace(",", "."));
      if (!isFinite(parsed) || parsed <= 0) {
        $("validation").textContent = "Некорректная калибровка";
        $("validation").style.color = "#c62828";
        return;
      }
    }
    state.calibration = value;
    saveCalibration(value);
    reanalyzeCurrent();
  });
  el.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      el.blur();
    }
  });
}

function wireCalibDialog() {
  const dlg = $("calibdialog");
  const nominal = $("calibnominal");
  const error = $("caliberror");
  if (!dlg || !nominal || !error) return;

  function apply() {
    const r = state.result;
    if (!r || !r.module_px_x) return;
    const parsed = Number((nominal.value || "").replace(",", "."));
    if (!isFinite(parsed) || parsed <= 0) {
      error.textContent = "Введите положительное число";
      error.hidden = false;
      return;
    }
    const um = parsed / r.module_px_x;
    const text = Number(um.toFixed(3)).toLocaleString("ru-RU",
      { maximumFractionDigits: 3 });
    $("umpp").value = text;
    state.calibration = text;
    saveCalibration(text);
    if (dlg.open) dlg.close();
    reanalyzeCurrent();
  }

  $("calibbtn").addEventListener("click", () => {
    const r = state.result;
    if (!r || !r.module_px_x) return;
    nominal.value = r.x_dim_um != null ? String(Math.round(r.x_dim_um)) : "";
    error.hidden = true;
    if (typeof dlg.showModal === "function") {
      if (!dlg.open) dlg.showModal();
    } else {
      const value = window.prompt("Номинальный X-dim, мкм:", nominal.value);
      if (value !== null) {
        nominal.value = value;
        apply();
      }
    }
  });
  $("calibcancel").addEventListener("click", () => dlg.close());
  $("calibapply").addEventListener("click", apply);
  nominal.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      apply();
    }
  });
}

function wireCrpt() {
  const btn = $("crptbtn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const cur = state.results[state.current];
    const code = cur && (cur.content_raw || cur.content);
    if (!code) return;
    const rid = cur.result_id;
    btn.disabled = true;
    setCrptStatus("Запрос в Честный знак...", "#f9a825");
    const box = $("crptinfo");
    if (box) box.innerHTML = "";
    try {
      const resp = await fetch("api/crpt", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code: code }),
      });
      let data = {};
      try { data = await resp.json(); } catch (e) { /* non-JSON */ }
      if (!resp.ok) {
        renderCrpt({ ok: false, error: data.error || ("HTTP " + resp.status) });
        return;
      }
      // Ignore a late response if the user switched to another code.
      const now = state.results[state.current];
      if (!now || now.result_id !== rid) return;
      state.crptCode = code;
      renderCrpt(data);
      state.crptInfo = data;
      updateHistoryCrpt(rid, data);
    } catch (e) {
      renderCrpt({ ok: false, error: "Ошибка сети: " + e });
    } finally {
      const now = state.results[state.current];
      btn.disabled = !(now && now.content_raw);
    }
  });
}

function activateTab(id) {
  document.querySelectorAll(".tab").forEach((btn) => {
    const active = btn.dataset.tab === id;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  document.querySelectorAll(".tabpane").forEach((pane) => {
    pane.classList.toggle("active", pane.id === id);
  });
}

function wireTabs() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });
  activateTab("tab-data");
}

function wireSceneNavigation() {
  const dz = $("dropzone");
  const canvas = $("scene");
  let dragging = false;
  let pointerId = null;
  let lastX = 0;
  let lastY = 0;
  let moved = 0;

  dz.addEventListener("pointerdown", (e) => {
    if (!state.img || e.button !== 0) return;
    if (e.target.tagName === "VIDEO") return;
    if (e.target.closest && e.target.closest("button")) return;
    dragging = true;
    pointerId = e.pointerId;
    lastX = e.clientX;
    lastY = e.clientY;
    moved = 0;
    state.suppressClick = false;
    dz.classList.add("dragging");
    if (dz.setPointerCapture) {
      try { dz.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
    }
  });

  dz.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.clientX - lastX;
    const dy = e.clientY - lastY;
    lastX = e.clientX;
    lastY = e.clientY;
    moved += Math.abs(dx) + Math.abs(dy);
    if (moved > 3) {
      state.suppressClick = true;
      state.panX += dx;
      state.panY += dy;
      drawScene();
    }
  });

  function stopDrag() {
    if (!dragging) return;
    dragging = false;
    dz.classList.remove("dragging");
    if (pointerId !== null && dz.releasePointerCapture) {
      try { dz.releasePointerCapture(pointerId); } catch (err) { /* ignore */ }
    }
    pointerId = null;
  }
  dz.addEventListener("pointerup", stopDrag);
  dz.addEventListener("pointercancel", stopDrag);
  dz.addEventListener("pointerleave", stopDrag);

  dz.addEventListener("wheel", (e) => {
    if (!state.img) return;
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const ax = e.clientX - rect.left - canvas.clientWidth / 2;
    const ay = e.clientY - rect.top - canvas.clientHeight / 2;
    zoomAt(ax, ay, Math.exp(-e.deltaY * 0.0015));
  }, { passive: false });

  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => drawScene()).observe(dz);
  } else {
    window.addEventListener("resize", drawScene);
  }
}

function wireControls() {
  $("zoomin").addEventListener("click", () => zoomAt(0, 0, 1.25));
  $("zoomout").addEventListener("click", () => zoomAt(0, 0, 0.8));
  $("rotate").addEventListener("click", () => {
    state.rotate = (state.rotate + 1) % 4;
    state.panX = 0;
    state.panY = 0;
    drawScene();
  });
  $("resetview").addEventListener("click", resetView);
  $("fullscreen").addEventListener("click", async () => {
    const scene = document.querySelector(".scene");
    try {
      if (!document.fullscreenElement) await scene.requestFullscreen();
      else await document.exitFullscreen();
    } catch (e) { /* browsers may deny */ }
  });
  document.addEventListener("fullscreenchange", () => {
    $("fullscreen").textContent = document.fullscreenElement
      ? "⛶ Выйти" : "⛶ На весь экран";
    requestAnimationFrame(() => requestAnimationFrame(drawScene));
  });
  $("channel").addEventListener("change", (e) => { state.channel = e.target.value; drawScene(); });
  var overlayToggle = $("overlaytoggle");
  if (overlayToggle) {
    overlayToggle.addEventListener("change", (e) => { state.showOverlay = e.target.checked; drawScene(); });
  }
  $("copyall").addEventListener("click", (e) => {
    if (state.result && state.result.content) {
      const text = state.result.content_plain || state.result.content.replace(/[()]/g, "");
      copyText(text).then(ok => flashCopy(e.target, ok));
    }
  });
  const hriBtn = $("copyhri");
  if (hriBtn) hriBtn.addEventListener("click", (e) => {
    if (state.result && state.result.content_hri) {
      copyText(state.result.content_hri).then(ok => flashCopy(e.target, ok));
    }
  });
  $("pdfbtn").addEventListener("click", async (e) => {
    const cur = state.results[state.current];
    if (!cur || !state.lastFile) return;
    const btn = e.target;
    btn.disabled = true;
    const fd = new FormData();
    fd.append("image", state.lastFile, state.lastFile.name || "image.jpg");
    const um = ($("umpp").value || "").trim();
    if (um) fd.append("um_per_px", um.replace(",", "."));
    fd.append("result_index", String(state.current));
    if (cur.content_raw) fd.append("code", cur.content_raw);
    if (state.crptInfo) fd.append("crpt", JSON.stringify(state.crptInfo));
    try {
      const resp = await fetch("api/pdf", { method: "POST", body: fd });
      if (!resp.ok) {
        let msg = "Ошибка PDF";
        try { msg = (await resp.json()).error || msg; } catch (err) { /* ignore */ }
        $("validation").textContent = msg;
        $("validation").style.color = "#c62828";
        return;
      }
      downloadBlob(await resp.blob(), "verification.pdf");
    } catch (err) {
      $("validation").textContent = "Ошибка сети: " + err;
      $("validation").style.color = "#c62828";
    } finally {
      btn.disabled = false;
    }
  });
}

function wireHistoryExports() {
  const csv = $("csvbtn");
  if (csv) csv.addEventListener("click", historyCsv);
  const txt = $("txtbtn");
  if (txt) txt.addEventListener("click", historyTxt);
  const pdf = $("hpdfbtn");
  if (pdf) pdf.addEventListener("click", historyPdf);
  const clear = $("clearhist");
  if (clear) clear.addEventListener("click", async () => {
    if (!confirm("Очистить историю проверок в этом браузере?")) return;
    await historyClearAll();
    renderHistory();
  });
}

fetchVersion();
wireDropzone();
wireCamera();
wireCalibration();
wireCalibDialog();
wireCrpt();
wireTabs();
wireSceneNavigation();
wireControls();
wireHistoryExports();
initEmptyState();
loadHistory();