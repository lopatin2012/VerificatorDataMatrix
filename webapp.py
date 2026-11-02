"""Web interface for the DataMatrix verifier (Flask + waitress).

Deploy as a service:
    python webapp.py [--host 0.0.0.0] [--port 8010]
"""
import base64
import io
import json
import os
import tempfile
import threading
import uuid

import cv2
import numpy as np
from flask import (Flask, jsonify, request, send_file, send_from_directory)
from PIL import Image

import crpt
from report import build_history_pdf, build_pdf
from verifier import analyze_all, to_dict
from version import VERSION

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBUI_DIR = os.path.join(BASE_DIR, "webui")
# Reports are built here, not under webui/, so they are never served publicly.
PDF_DIR = tempfile.mkdtemp(prefix="dm_verify_")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024


@app.after_request
def _no_cache(resp):
    """Prevent browser from caching HTML/JS/CSS so updates are visible immediately."""
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    elif request.path == "/" or request.path.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-store"
    return resp

# Analysis is CPU-heavy; keep one at a time per process. There is no
# server-side result/history cache: the browser stores its own history.
ANALYZE_LOCK = threading.Lock()

# Opt-in Chestny Znak product cache (keyed by marking code, not user history).
CRPT_LOCK = threading.Lock()
CRPT_CACHE = {}
CRPT_CACHE_MAX = 100


def _image_data_url(img, quality=85):
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


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


@app.errorhandler(413)
def _too_large(_exc):
    return jsonify({"error": "Файл больше 25 МБ"}), 413


def _decode_image(data):
    if not data:
        return None
    arr = np.frombuffer(data, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _parse_calibration(raw):
    """Return (um_per_px or None, error_message or None)."""
    if raw is None:
        return None, None
    raw = str(raw).strip()
    if not raw:
        return None, None
    try:
        um = float(raw.replace(",", "."))
    except ValueError:
        return None, "Некорректная калибровка"
    if um <= 0:
        return None, "Калибровка должна быть больше нуля"
    return um, None


def _payload_for_results(img, results):
    """Build the response; the client keeps the only copy of the history."""
    payload = {"image": _image_data_url(img), "results": []}
    for res in results:
        d = to_dict(res)
        d["result_id"] = uuid.uuid4().hex[:12]
        payload["results"].append(d)
    return payload


def _analyze_payload(img, um):
    try:
        with ANALYZE_LOCK:
            results = analyze_all(img, um_per_px=um)
    except Exception as exc:
        return None, f"Ошибка анализа: {exc}"
    if not results:
        return {"error": "Код не найден", "image": _image_data_url(img)}, None
    return _payload_for_results(img, results), None


@app.post("/api/analyze")
def api_analyze():
    f = request.files.get("image")
    if f is None:
        return jsonify({"error": "Изображение не получено"}), 400
    img = _decode_image(f.read())
    if img is None or img.size == 0:
        return jsonify({"error": "Не удалось прочитать изображение"}), 400

    um, error = _parse_calibration(request.form.get("um_per_px"))
    if error:
        return jsonify({"error": error}), 400
    payload, error = _analyze_payload(img, um)
    if error:
        return jsonify({"error": error}), 500
    return jsonify(payload)


@app.post("/api/crpt")
def api_crpt():
    """Explicit, opt-in product lookup in Chestny Znak (no auth)."""
    data = request.get_json(silent=True) or {}
    code = str(data.get("code") or "").strip(" \t\r\n")
    if not code:
        return jsonify({"error": "Нет кода для проверки"}), 400

    with CRPT_LOCK:
        cached = CRPT_CACHE.get(code)
    if cached is not None:
        return jsonify(cached)

    try:
        info = crpt.lookup(code)
    except crpt.CrptError as exc:
        return jsonify({"error": str(exc)}), 502
    public = {k: v for k, v in info.items() if k != "raw"}
    with CRPT_LOCK:
        CRPT_CACHE[code] = public
        if len(CRPT_CACHE) > CRPT_CACHE_MAX:
            CRPT_CACHE.pop(next(iter(CRPT_CACHE)))
    return jsonify(public)


@app.post("/api/history.pdf")
def api_history_pdf():
    """Build a history summary from client-supplied rows (no server state)."""
    data = request.get_json(silent=True) or {}
    rows = data.get("items")
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "История пуста"}), 400
    rows = [row for row in rows if isinstance(row, dict)][:500]
    if not rows:
        return jsonify({"error": "История пуста"}), 400
    pdf_path = os.path.join(PDF_DIR, f"history_{uuid.uuid4().hex}.pdf")
    try:
        build_history_pdf(rows, pdf_path)
    except Exception as exc:
        return jsonify({"error": f"Ошибка формирования PDF: {exc}"}), 500
    return send_file(pdf_path, as_attachment=True,
                     download_name="history.pdf",
                     mimetype="application/pdf")


@app.post("/api/pdf")
def api_pdf():
    """Build a report from the uploaded image, so the server keeps no history."""
    f = request.files.get("image")
    if f is None:
        return jsonify({"error": "Изображение не получено"}), 400
    img = _decode_image(f.read())
    if img is None or img.size == 0:
        return jsonify({"error": "Не удалось прочитать изображение"}), 400
    um, error = _parse_calibration(request.form.get("um_per_px"))
    if error:
        return jsonify({"error": error}), 400

    crpt_info = None
    raw_crpt = request.form.get("crpt")
    if raw_crpt:
        try:
            crpt_info = json.loads(raw_crpt)
        except (TypeError, ValueError):
            crpt_info = None
        if not isinstance(crpt_info, dict):
            crpt_info = None

    try:
        with ANALYZE_LOCK:
            results = analyze_all(img, um_per_px=um)
    except Exception as exc:
        return jsonify({"error": f"Ошибка анализа: {exc}"}), 500
    if not results:
        return jsonify({"error": "Код не найден"}), 404
    index = request.form.get("result_index", type=int, default=0) or 0
    expected = request.form.get("code") or ""
    if expected:
        for i, result in enumerate(results):
            if (result.content_raw == expected
                    or result.content == expected):
                index = i
                break
    index = max(0, min(len(results) - 1, index))
    pdf_path = os.path.join(PDF_DIR, f"report_{uuid.uuid4().hex}.pdf")
    try:
        build_pdf(results[index], img, pdf_path, crpt_info=crpt_info)
    except Exception as exc:
        return jsonify({"error": f"Ошибка формирования PDF: {exc}"}), 500
    return send_file(pdf_path, as_attachment=True,
                     download_name="verification.pdf",
                     mimetype="application/pdf")


def main(host=None, port=None, debug=False):
    if host is None or port is None:
        import argparse
        ap = argparse.ArgumentParser(description="DataMatrix Verifier web service")
        ap.add_argument("--host", default="127.0.0.1")
        ap.add_argument("--port", type=int, default=8010)
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