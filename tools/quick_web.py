"""Start the DataMatrix Verifier web service and open it in a browser.

Usage (normally called by tools/quick_web.bat):
    .venv\\Scripts\\python.exe tools\\quick_web.py [--port 8010]
                                                [--host 127.0.0.1]
                                                [--no-browser]

If the requested port is busy (e.g. an old server is still running) the next
free port is used, so a stale process can never serve old code silently.
"""
import argparse
import os
import socket
import sys
import threading
import time
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from version import VERSION  # noqa: E402


def _port_free(host, port):
    """True if we can bind the port (no SO_REUSEADDR: a listener must fail)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def _choose_port(host, preferred):
    for port in range(preferred, preferred + 20):
        if _port_free(host, port):
            return port
    raise SystemExit(f"Нет свободного порта в диапазоне {preferred}-{preferred + 19}")


def _open_when_ready(url, connect_host, port):
    """Wait until the server accepts connections, then open the browser."""
    deadline = time.time() + 15.0
    while time.time() < deadline:
        try:
            with socket.create_connection((connect_host, port), timeout=0.3):
                break
        except OSError:
            time.sleep(0.2)
    webbrowser.open(url)


def main():
    ap = argparse.ArgumentParser(description="Quick web-server launcher")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--host", default="127.0.0.1",
                    help="0.0.0.0 makes the service reachable from the LAN")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    port = _choose_port(args.host, args.port)
    connect_host = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host
    url = f"http://{connect_host}:{port}/"

    print(f"DataMatrix Verifier v{VERSION} — web service", flush=True)
    if port != args.port:
        print(f"Порт {args.port} занят, использую {port}.", flush=True)
    print(f"Открывайте: {url}", flush=True)
    if args.host == "0.0.0.0":
        print("Доступен из локальной сети (авторизации нет).", flush=True)
    print("Остановка: Ctrl+C", flush=True)
    print(flush=True)

    if not args.no_browser:
        threading.Thread(target=_open_when_ready,
                         args=(url, connect_host, port), daemon=True).start()

    import webapp
    try:
        webapp.main(host=args.host, port=port)
    except KeyboardInterrupt:
        print("\nСервер остановлен.")


if __name__ == "__main__":
    main()
