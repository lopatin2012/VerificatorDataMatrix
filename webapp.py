"""Web interface for the DataMatrix verifier (Flask + waitress).

Deploy as a service:
    python webapp.py [--host 0.0.0.0] [--port 8000]
"""
import base64
import csv
import datetime
import io
import os
import threading
import time
import uuid

import cv2
from flask import (Flask, Response, jsonify, request, send_file,
                   send_from_directory)
from PIL import Image

from report import build_history_pdf, build_pdf
from verifier import analyze_all, to_dict
from version import VERSION

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBUI_DIR = os.path.join(BASE_DIR, "webui")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


@app.after_request
def _no_cache(resp):
    """Prevent browser from caching HTML/JS/CSS so updates are visible immediately."""
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    elif request.path.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-store"
    return resp

ANALYZE_LOCK = threading.Lock()
RESULTS = {}          # id -> {res, img, payload, thumb, ts}
RESULTS_ORDER = []    # LRU
RESULTS_MAX = 50


def _image_data_url(img, quality=85):
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _thumb_data_url(img, res, good):
    disp = img.copy()
    if res.corner_points is not None:
        pts = res.corner_points.astype(int)
        x0, y0 = int(pts[:, 0].min()), int(pts[:, 1].min())
        x1, y1 = int(pts[:, 0].max()), int(pts[:, 1].max())
        m = max(6, int(0.08 * max(x1 - x0, y1 - y0)))
        color = (46, 125, 50) if good else (40, 40, 198)
        cv2.rectangle(disp, (x0 - m, y0 - m), (x1 + m, y1 + m), color, 3)
    pil = Image.fromarray(cv2.cvtColor(disp, cv2.COLOR_BGR2RGB))
    pil.thumbnail((176, 120))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=75)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _history_items():
    """Newest-first list of lightweight history entries."""
    items = []
    for rid in reversed(RESULTS_ORDER):
        e = RESULTS.get(rid)
        if not e:
            continue
        d = e["payload"]
        items.append({
            "result_id": rid,
            "thumb": e["thumb"],
            "ts": e["ts"],
            "good": d["good"],
            "score": d["score"],
            "color": d["color"],
            "validation": d["validation"],
            "overall_class": d["overall_class"],
            "content": d["content"],
            "symbol_size": d["symbol_size"],
            "elements": [{"name": el["name"], "value": el["value"]}
                         for el in d["elements"]],
        })
    return items


@app.get("/")
def index():
    return send_from_directory(WEBUI_DIR, "index.html")


@app.get("/api/version")
def api_version():
    return jsonify({"version": VERSION})


@app.get("/favicon.ico")
def favicon():
    return send_from_directory(BASE_DIR, "favicon.ico")


@app.get("/<path:filename>")
def static_files(filename):
    return send_from_directory(WEBUI_DIR, filename)


def _decode_image(data):
    arr = np_from_bytes(data)
    if arr is None:
        return None
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def np_from_bytes(data):
    import numpy as np
    return np.frombuffer(data, dtype=np.uint8)


@app.post("/api/analyze")
def api_analyze():
    f = request.files.get("image")
    if f is None:
        return jsonify({"error": "Изображение не получено"}), 400
    img = _decode_image(f.read())
    if img is None or img.size == 0:
        return jsonify({"error": "Не удалось прочитать изображение"}), 400

    um = request.form.get("um_per_px", type=float, default=10.0)
    try:
        with ANALYZE_LOCK:
            results = analyze_all(img, um_per_px=um)
    except Exception as exc:
        return jsonify({"error": f"Ошибка анализа: {exc}"}), 500

    if not results:
        return jsonify({"error": "Код не найден"}), 200

    payload = {"image": "", "results": []}
    for res in results:
        rid = uuid.uuid4().hex[:12]
        d = to_dict(res)
        d["result_id"] = rid
        with ANALYZE_LOCK:
            RESULTS[rid] = {
                "res": res, "img": img, "payload": d,
                "thumb": _thumb_data_url(img, res, d["good"]),
                "ts": time.time(),
            }
            RESULTS_ORDER.append(rid)
            if len(RESULTS_ORDER) > RESULTS_MAX:
                old = RESULTS_ORDER.pop(0)
                RESULTS.pop(old, None)
        payload["results"].append(d)

    # base image (no overlay); heatmap is drawn client-side for interactivity
    payload["image"] = _image_data_url(img)

    return jsonify(payload)


@app.get("/api/history")
def api_history():
    with ANALYZE_LOCK:
        items = _history_items()
    return jsonify({"items": items})


@app.get("/api/result/<rid>")
def api_result(rid):
    with ANALYZE_LOCK:
        entry = RESULTS.get(rid)
    if entry is None:
        return jsonify({"error": "Результат не найден (истёк)"}), 404
    return jsonify({"image": _image_data_url(entry["img"]),
                    "results": [entry["payload"]]})


def _export_rows():
    """Newest-first payload dicts (each with a formatted `ts_text`)."""
    rows = []
    with ANALYZE_LOCK:
        entries = [RESULTS[r] for r in reversed(RESULTS_ORDER) if r in RESULTS]
    for e in entries:
        d = dict(e["payload"])
        d["ts_text"] = datetime.datetime.fromtimestamp(e["ts"]).strftime(
            "%d.%m.%Y %H:%M:%S")
        rows.append(d)
    return rows


@app.get("/api/history.csv")
def api_history_csv():
    rows = _export_rows()
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow(["Время", "Валидация", "Класс", "Оценка", "Символ",
                "Содержимое", "Данные GS1"])
    for d in rows:
        elems = "; ".join(f'{el["name"]}={el["value"]}'
                          for el in d.get("elements", []))
        w.writerow([d["ts_text"], d["validation"], d["overall_class"] or "",
                    d["score"], d["symbol_size"] or "", d["content"] or "",
                    elems])
    data = "\ufeff" + out.getvalue()  # BOM so Excel reads UTF-8
    return Response(
        data, mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=history.csv"})


@app.get("/api/history.pdf")
def api_history_pdf():
    rows = _export_rows()
    if not rows:
        return jsonify({"error": "История пуста"}), 404
    pdf_path = os.path.join(BASE_DIR, "webui", "_history.pdf")
    try:
        build_history_pdf(rows, pdf_path)
    except Exception as exc:
        return jsonify({"error": f"Ошибка формирования PDF: {exc}"}), 500
    return send_file(pdf_path, as_attachment=True,
                     download_name="history.pdf",
                     mimetype="application/pdf")


@app.post("/api/pdf")
def api_pdf():
    data = request.get_json(silent=True) or {}
    rid = data.get("result_id")
    with ANALYZE_LOCK:
        entry = RESULTS.get(rid)
    if entry is None:
        return jsonify({"error": "Результат не найден (истёк)"}), 404
    res, img = entry["res"], entry["img"]
    pdf_path = os.path.join(BASE_DIR, "webui", "_report.pdf")
    try:
        build_pdf(res, img, pdf_path)
    except Exception as exc:
        return jsonify({"error": f"Ошибка формирования PDF: {exc}"}), 500
    return send_file(pdf_path, as_attachment=True,
                     download_name=f"verification_{rid}.pdf",
                     mimetype="application/pdf")


def main(host=None, port=None, debug=False):
    if host is None or port is None:
        import argparse
        ap = argparse.ArgumentParser(description="DataMatrix Verifier web service")
        ap.add_argument("--host", default="127.0.0.1")
        ap.add_argument("--port", type=int, default=8000)
        ap.add_argument("--debug", action="store_true")
        args = ap.parse_args()
        host = host or args.host
        port = port or args.port
        debug = debug or args.debug

    print(f"DataMatrix Verifier v{VERSION} — web service")
    print(f"http://{host}:{port}")
    if debug:
        app.run(host=host, port=port, debug=True)
    else:
        from waitress import serve
        serve(app, host=host, port=port, threads=8)


if __name__ == "__main__":
    main()