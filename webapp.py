"""Web interface for the DataMatrix verifier (Flask + waitress).

Deploy as a service:
    python webapp.py [--host 0.0.0.0] [--port 8000]
"""
import base64
import io
import os
import threading
import uuid

import cv2
from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image

from report import build_pdf
from verifier import analyze_all, to_dict
from version import VERSION

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEBUI_DIR = os.path.join(BASE_DIR, "webui")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024

ANALYZE_LOCK = threading.Lock()
RESULTS = {}          # id -> (res, frame_bgr)
RESULTS_ORDER = []    # LRU
RESULTS_MAX = 50


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
        RESULTS[rid] = (res, img)
        RESULTS_ORDER.append(rid)
        if len(RESULTS_ORDER) > RESULTS_MAX:
            old = RESULTS_ORDER.pop(0)
            RESULTS.pop(old, None)
        d = to_dict(res)
        d["result_id"] = rid
        payload["results"].append(d)

    # base image (no overlay); heatmap is drawn client-side for interactivity
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=85)
    payload["image"] = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    return jsonify(payload)


@app.post("/api/pdf")
def api_pdf():
    data = request.get_json(silent=True) or {}
    rid = data.get("result_id")
    entry = RESULTS.get(rid)
    if entry is None:
        return jsonify({"error": "Результат не найден (истёк)"}), 404
    res, img = entry
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