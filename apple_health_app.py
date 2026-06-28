#!/usr/bin/env python3
"""Local drag-and-drop web app for Apple Health exports."""

from __future__ import annotations

import cgi
import json
import mimetypes
import os
import shutil
import sys
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from apple_health_csv_converter import convert


if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
JOBS_DIR = ROOT / "app_jobs"
UPLOADS_DIR = ROOT / "app_uploads"
HOST = "127.0.0.1"
DEFAULT_PORT = 8765


INDEX_HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Apple Health Data CSV Exporter</title>
<style>
:root {
  --bg: #f5f6f8;
  --panel: #ffffff;
  --ink: #17191f;
  --muted: #667085;
  --line: #d8dee8;
  --blue: #2878d7;
  --green: #16875d;
  --red: #d04455;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  font-family: Arial, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
}
main {
  width: min(980px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 34px 0;
}
header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: end;
  margin-bottom: 18px;
}
h1 {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: 0;
}
.sub {
  margin-top: 7px;
  color: var(--muted);
  font-size: 14px;
}
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
}
#dropzone {
  min-height: 270px;
  display: grid;
  place-items: center;
  padding: 28px;
  text-align: center;
  border-style: dashed;
  transition: border-color 160ms ease, background 160ms ease;
}
#dropzone.drag {
  border-color: var(--blue);
  background: #eef6ff;
}
.upload-title {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 8px;
}
.upload-copy {
  color: var(--muted);
  line-height: 1.55;
  margin-bottom: 18px;
}
button, .button {
  height: 38px;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 7px;
  padding: 0 14px;
  color: var(--ink);
  font: inherit;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
}
button.primary, .button.primary {
  background: var(--ink);
  border-color: var(--ink);
  color: #fff;
}
button:disabled {
  cursor: default;
  opacity: .55;
}
#file {
  display: none;
}
.status {
  margin-top: 16px;
  padding: 14px 16px;
  color: var(--muted);
  line-height: 1.45;
}
.status strong {
  color: var(--ink);
}
.progress {
  height: 8px;
  margin-top: 12px;
  background: #eef1f5;
  border-radius: 999px;
  overflow: hidden;
}
.progress div {
  width: 0;
  height: 100%;
  background: var(--blue);
  transition: width 300ms ease;
}
.results {
  display: none;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-top: 16px;
}
.result {
  padding: 16px;
}
.result h2 {
  margin: 0 0 8px;
  font-size: 17px;
  letter-spacing: 0;
}
.result p {
  min-height: 42px;
  margin: 0 0 14px;
  color: var(--muted);
  line-height: 1.45;
}
.details {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-top: 16px;
}
.metric {
  padding: 12px;
}
.metric .k {
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 8px;
}
.metric .v {
  font-weight: 700;
  font-size: 20px;
}
.error {
  color: var(--red);
}
@media (max-width: 760px) {
  header {
    display: block;
  }
  .results, .details {
    grid-template-columns: 1fr;
  }
  main {
    padding-top: 20px;
  }
}
</style>
</head>
<body>
<main>
  <header>
    <div>
      <h1>Apple Health Data CSV Exporter</h1>
      <div class="sub">Drop an iPhone Health data export.zip to create CSV files and a dashboard.</div>
    </div>
    <button id="reset" type="button" style="display:none;">Convert another ZIP</button>
  </header>

  <section id="dropzone" class="panel">
    <div>
      <div class="upload-title">Drop export.zip here</div>
      <div class="upload-copy">The app runs locally on this computer. It converts your Health data export into organized CSV files and a visual dashboard.</div>
      <button id="choose" class="primary" type="button">Choose ZIP</button>
      <input id="file" type="file" accept=".zip,application/zip">
    </div>
  </section>

  <div id="status" class="status panel">
    Waiting for an Apple Health data export ZIP.
    <div class="progress"><div id="bar"></div></div>
  </div>

  <section id="details" class="details"></section>

  <section id="results" class="results">
    <div class="result panel">
      <h2>All CSV files</h2>
      <p>Download a single ZIP containing every generated CSV file.</p>
      <a id="csvZip" class="button primary" href="#">Download CSV ZIP</a>
    </div>
    <div class="result panel">
      <h2>Dashboard</h2>
      <p>Open a visual report for steps, sleep, heart rate, activity, workouts, and more.</p>
      <a id="dashboard" class="button" href="#" target="_blank" rel="noreferrer">Open dashboard</a>
    </div>
  </section>
</main>
<script>
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file");
const choose = document.getElementById("choose");
const statusBox = document.getElementById("status");
const bar = document.getElementById("bar");
const results = document.getElementById("results");
const details = document.getElementById("details");
const csvZip = document.getElementById("csvZip");
const dashboard = document.getElementById("dashboard");
const reset = document.getElementById("reset");
let busy = false;

function setStatus(html, pct = 0, error = false) {
  statusBox.innerHTML = `${error ? '<span class="error">' + html + '</span>' : html}<div class="progress"><div id="barInner" style="width:${pct}%"></div></div>`;
}

function metric(label, value) {
  return `<div class="metric panel"><div class="k">${label}</div><div class="v">${value}</div></div>`;
}

function formatNumber(value) {
  return Number(value || 0).toLocaleString();
}

async function upload(file) {
  if (busy || !file) return;
  if (!file.name.toLowerCase().endsWith(".zip")) {
    setStatus("Please choose an export.zip file.", 0, true);
    return;
  }
  busy = true;
  choose.disabled = true;
  results.style.display = "none";
  details.innerHTML = "";
  setStatus(`<strong>${file.name}</strong> is uploading and converting. Large Health exports can take a few minutes.`, 20);
  const form = new FormData();
  form.append("export_zip", file);
  try {
    const response = await fetch("/api/convert", { method: "POST", body: form });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Conversion failed.");
    setStatus(`<strong>Done.</strong> Created ${formatNumber(payload.csv_file_count)} CSV files.`, 100);
    csvZip.href = payload.csv_zip_url;
    dashboard.href = payload.dashboard_url;
    details.innerHTML = [
      metric("Records", formatNumber(payload.counters.records)),
      metric("Workouts", formatNumber(payload.counters.workouts)),
      metric("Sleep/HR/etc CSV", formatNumber(payload.csv_file_count)),
      metric("Processed At", payload.processed_at || "-")
    ].join("");
    results.style.display = "grid";
    reset.style.display = "inline-flex";
  } catch (err) {
    setStatus(err.message, 0, true);
  } finally {
    busy = false;
    choose.disabled = false;
  }
}

choose.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => upload(fileInput.files[0]));
reset.addEventListener("click", () => {
  fileInput.value = "";
  results.style.display = "none";
  reset.style.display = "none";
  details.innerHTML = "";
    setStatus("Waiting for an Apple Health data export ZIP.", 0);
});

["dragenter", "dragover"].forEach(name => {
  dropzone.addEventListener(name, event => {
    event.preventDefault();
    dropzone.classList.add("drag");
  });
});
["dragleave", "drop"].forEach(name => {
  dropzone.addEventListener(name, event => {
    event.preventDefault();
    dropzone.classList.remove("drag");
  });
});
dropzone.addEventListener("drop", event => {
  upload(event.dataTransfer.files[0]);
});
</script>
</body>
</html>
"""


class AppHandler(BaseHTTPRequestHandler):
    server_version = "AppleHealthCSVApp/1.0"

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_bytes(self, body: bytes, content_type: str, status: int = 200, extra_headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict, status: int = 200) -> None:
        self.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.send_bytes(INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if parsed.path.startswith("/jobs/"):
            self.serve_job_file(parsed.path)
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/convert":
            self.send_error(404)
            return
        try:
            self.handle_convert()
        except Exception as exc:
            self.send_json({"error": str(exc)}, status=500)

    def serve_job_file(self, request_path: str) -> None:
        relative = unquote(request_path.removeprefix("/jobs/"))
        target = (JOBS_DIR / relative).resolve()
        jobs_root = JOBS_DIR.resolve()
        if jobs_root not in target.parents and target != jobs_root:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        headers = {}
        if target.suffix.lower() == ".zip":
            headers["Content-Disposition"] = f'attachment; filename="{target.name}"'
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(target.stat().st_size))
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        with target.open("rb") as handle:
            shutil.copyfileobj(handle, self.wfile)

    def handle_convert(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self.send_json({"error": "Expected multipart/form-data upload."}, status=400)
            return

        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        item = form["export_zip"] if "export_zip" in form else None
        if item is None or not getattr(item, "filename", ""):
            self.send_json({"error": "No ZIP file was uploaded."}, status=400)
            return
        if not item.filename.lower().endswith(".zip"):
            self.send_json({"error": "Please upload a .zip file from Apple Health."}, status=400)
            return

        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        upload_dir = UPLOADS_DIR / job_id
        output_dir = JOBS_DIR / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = upload_dir / "export.zip"
        with zip_path.open("wb") as target:
            shutil.copyfileobj(item.file, target)

        messages: list[str] = []

        def log(message: str) -> None:
            messages.append(message)
            print(f"[{job_id}] {message}", flush=True)

        counters = convert(zip_path, output_dir, log=log)
        csv_zip = output_dir / "apple_health_all_csv.zip"
        dashboard = output_dir / "health_dashboard.html"
        csv_file_count = len(list(output_dir.rglob("*.csv")))

        self.send_json(
            {
                "job_id": job_id,
                "processed_at": time.strftime("%Y-%m-%d %H:%M"),
                "counters": counters,
                "csv_file_count": csv_file_count,
                "csv_zip_url": f"/jobs/{job_id}/{csv_zip.name}",
                "dashboard_url": f"/jobs/{job_id}/{dashboard.name}",
                "log": messages[-12:],
            }
        )


def find_available_port(start: int) -> int:
    import socket

    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((HOST, port))
            except OSError:
                continue
            return port
    raise RuntimeError("No available local port found.")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the Apple Health drag-and-drop CSV app.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    port = find_available_port(args.port)
    url = f"http://{HOST}:{port}/"
    server = ThreadingHTTPServer((HOST, port), AppHandler)
    print(f"Apple Health CSV Exporter is running at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
