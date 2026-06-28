#!/usr/bin/env python3
"""
Apple Health Export ZIP to CSV converter.

Double-click this file to open a small file picker app, or run:
  python apple_health_csv_converter.py export.zip output_folder
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from xml.etree.ElementTree import iterparse


BASE_RECORD_COLUMNS = [
    "record_id",
    "type",
    "sourceName",
    "sourceVersion",
    "device",
    "unit",
    "creationDate",
    "startDate",
    "endDate",
    "value",
    "extras_json",
]

WORKOUT_COLUMNS = [
    "workout_id",
    "workoutActivityType",
    "duration",
    "durationUnit",
    "sourceName",
    "sourceVersion",
    "device",
    "creationDate",
    "startDate",
    "endDate",
    "extras_json",
]

ACTIVITY_SUMMARY_COLUMNS = [
    "summary_id",
    "dateComponents",
    "activeEnergyBurned",
    "activeEnergyBurnedGoal",
    "activeEnergyBurnedUnit",
    "appleMoveTime",
    "appleMoveTimeGoal",
    "appleExerciseTime",
    "appleExerciseTimeGoal",
    "appleStandHours",
    "appleStandHoursGoal",
    "extras_json",
]

CSV_SPECS = {
    "all_health_records.csv": BASE_RECORD_COLUMNS,
    "workouts.csv": WORKOUT_COLUMNS,
    "daily_activity_summaries.csv": ACTIVITY_SUMMARY_COLUMNS,
    "record_metadata.csv": ["parent_tag", "parent_id", "key", "value"],
    "workout_events.csv": [
        "workout_id",
        "type",
        "date",
        "duration",
        "durationUnit",
        "extras_json",
    ],
    "workout_statistics.csv": [
        "workout_id",
        "type",
        "unit",
        "startDate",
        "endDate",
        "sum",
        "average",
        "minimum",
        "maximum",
        "extras_json",
    ],
    "workout_routes.csv": [
        "route_id",
        "workout_id",
        "sourceName",
        "sourceVersion",
        "creationDate",
        "startDate",
        "endDate",
        "file_path",
        "extras_json",
    ],
    "hrv_instantaneous_bpm.csv": ["record_id", "time", "bpm"],
    "profile.csv": ["key", "value"],
    "export_info.csv": ["key", "value"],
}


class CsvSink:
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.handles = {}
        self.writers = {}

    def writer(self, relative_path: str, columns: list[str]) -> csv.DictWriter:
        if relative_path in self.writers:
            return self.writers[relative_path]
        path = self.output_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("w", newline="", encoding="utf-8-sig")
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        self.handles[relative_path] = handle
        self.writers[relative_path] = writer
        return writer

    def row(self, relative_path: str, columns: list[str], row: dict[str, str]) -> None:
        self.writer(relative_path, columns).writerow(row)

    def close(self) -> None:
        for handle in self.handles.values():
            handle.close()


def safe_name(value: str) -> str:
    value = value.replace("HKQuantityTypeIdentifier", "")
    value = value.replace("HKCategoryTypeIdentifier", "")
    value = value.replace("HKDataType", "")
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return value or "unknown"


def csv_file_name_for_type(value: str) -> str:
    name = safe_name(value)
    name = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    name = name.replace("__", "_").lower()
    aliases = {
        "vo2_max": "vo2_max",
        "body_mass_index": "body_mass_index",
        "heart_rate_variability_s_d_n_n": "heart_rate_variability_sdnn",
    }
    return f"{aliases.get(name, name)}.csv"


def row_from_attrs(attrs: dict[str, str], columns: list[str], id_key: str, id_value: int) -> dict[str, str]:
    base_keys = set(columns) - {"extras_json"}
    row = {key: attrs.get(key, "") for key in columns}
    row[id_key] = str(id_value)
    extras = {key: val for key, val in attrs.items() if key not in base_keys}
    row["extras_json"] = json.dumps(extras, ensure_ascii=False, sort_keys=True) if extras else ""
    return row


def find_export_xml(zip_path: Path) -> str:
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
    matches = [name for name in names if name.endswith("export.xml")]
    if not matches:
        raise FileNotFoundError("export.xml was not found inside the ZIP file.")
    return sorted(matches, key=len)[0]


def copy_existing_csv_and_routes(zip_path: Path, output_dir: Path, log) -> None:
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.namelist():
            lower = member.lower()
            if lower.endswith(".csv") and "/electrocardiograms/" in lower:
                target = output_dir / "ecg" / Path(member).name
            elif lower.endswith(".gpx") and "/workout-routes/" in lower:
                target = output_dir / "workout_routes_gpx" / Path(member).name
            else:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    log("Copied ECG CSV files and workout GPX route files when present.")


def create_all_csv_zip(output_dir: Path, log=print) -> Path:
    zip_path = output_dir / "apple_health_all_csv.zip"
    if zip_path.exists():
        zip_path.unlink()

    csv_files = sorted(output_dir.rglob("*.csv"))
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for csv_file in csv_files:
            archive.write(csv_file, csv_file.relative_to(output_dir).as_posix())

    log(f"CSV package created: {zip_path} ({len(csv_files)} files)")
    return zip_path


def create_dashboard(output_dir: Path, log=print) -> Path | None:
    try:
        from generate_health_dashboard import build_dashboard_data, render_html

        dashboard_path = output_dir / "health_dashboard.html"
        dashboard_path.write_text(render_html(build_dashboard_data(output_dir)), encoding="utf-8")
        log(f"Dashboard created: {dashboard_path}")
        return dashboard_path
    except Exception as exc:
        log(f"Dashboard generation skipped: {exc}")
        return None


def convert(
    zip_path: Path,
    output_dir: Path,
    split_records_by_type: bool = True,
    create_visual_dashboard: bool = True,
    create_csv_package: bool = True,
    log=print,
) -> dict[str, int]:
    zip_path = zip_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    export_member = find_export_xml(zip_path)
    counters = {
        "records": 0,
        "workouts": 0,
        "activity_summaries": 0,
        "metadata_entries": 0,
        "workout_events": 0,
        "workout_statistics": 0,
        "workout_routes": 0,
        "instantaneous_bpm": 0,
    }

    sink = CsvSink(output_dir)
    parent_stack: list[tuple[str, int | None]] = []
    current_route_file: dict[int, str] = {}
    last_log_at = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="apple-health-") as temp:
        temp_dir = Path(temp)
        log(f"Extracting {export_member}...")
        with zipfile.ZipFile(zip_path) as archive:
            archive.extract(export_member, temp_dir)
        xml_path = temp_dir / export_member

        log("Converting XML to CSV. This can take a few minutes for large exports...")
        context = iterparse(xml_path, events=("start", "end"))
        for event, elem in context:
            tag = elem.tag

            if event == "start":
                assigned_id = None
                attrs = dict(elem.attrib)

                if tag == "Record":
                    counters["records"] += 1
                    assigned_id = counters["records"]
                    row = row_from_attrs(attrs, BASE_RECORD_COLUMNS, "record_id", assigned_id)
                    sink.row("all_health_records.csv", BASE_RECORD_COLUMNS, row)
                    if split_records_by_type:
                        record_type = csv_file_name_for_type(attrs.get("type", "unknown"))
                        sink.row(f"health_data_by_type/{record_type}", BASE_RECORD_COLUMNS, row)

                elif tag == "Workout":
                    counters["workouts"] += 1
                    assigned_id = counters["workouts"]
                    row = row_from_attrs(attrs, WORKOUT_COLUMNS, "workout_id", assigned_id)
                    sink.row("workouts.csv", WORKOUT_COLUMNS, row)

                elif tag == "ActivitySummary":
                    counters["activity_summaries"] += 1
                    assigned_id = counters["activity_summaries"]
                    row = row_from_attrs(attrs, ACTIVITY_SUMMARY_COLUMNS, "summary_id", assigned_id)
                    sink.row("daily_activity_summaries.csv", ACTIVITY_SUMMARY_COLUMNS, row)

                elif tag == "WorkoutRoute":
                    counters["workout_routes"] += 1
                    assigned_id = counters["workout_routes"]
                    workout_id = next((pid for ptag, pid in reversed(parent_stack) if ptag == "Workout"), None)
                    row = row_from_attrs(attrs, CSV_SPECS["workout_routes.csv"], "route_id", assigned_id)
                    row["workout_id"] = str(workout_id or "")
                    sink.row("workout_routes.csv", CSV_SPECS["workout_routes.csv"], row)

                elif tag == "Me":
                    for key, value in attrs.items():
                        sink.row("profile.csv", CSV_SPECS["profile.csv"], {"key": key, "value": value})

                elif tag == "ExportDate":
                    sink.row("export_info.csv", CSV_SPECS["export_info.csv"], {"key": "ExportDate", "value": attrs.get("value", "")})

                parent_stack.append((tag, assigned_id))

                now = time.monotonic()
                if counters["records"] and counters["records"] % 100000 == 0 and now - last_log_at > 1:
                    log(f"Processed {counters['records']:,} health records...")
                    last_log_at = now

            else:
                attrs = dict(elem.attrib)

                if tag == "MetadataEntry":
                    parent_tag, parent_id = next(((ptag, pid) for ptag, pid in reversed(parent_stack[:-1]) if pid), ("", None))
                    counters["metadata_entries"] += 1
                    sink.row(
                        "record_metadata.csv",
                        CSV_SPECS["record_metadata.csv"],
                        {
                            "parent_tag": parent_tag,
                            "parent_id": str(parent_id or ""),
                            "key": attrs.get("key", ""),
                            "value": attrs.get("value", ""),
                        },
                    )

                elif tag == "InstantaneousBeatsPerMinute":
                    record_id = next((pid for ptag, pid in reversed(parent_stack[:-1]) if ptag == "Record"), None)
                    counters["instantaneous_bpm"] += 1
                    sink.row(
                        "hrv_instantaneous_bpm.csv",
                        CSV_SPECS["hrv_instantaneous_bpm.csv"],
                        {"record_id": str(record_id or ""), "time": attrs.get("time", ""), "bpm": attrs.get("bpm", "")},
                    )

                elif tag == "WorkoutEvent":
                    workout_id = next((pid for ptag, pid in reversed(parent_stack[:-1]) if ptag == "Workout"), None)
                    counters["workout_events"] += 1
                    row = row_from_attrs(attrs, CSV_SPECS["workout_events.csv"], "workout_id", workout_id or 0)
                    row["workout_id"] = str(workout_id or "")
                    sink.row("workout_events.csv", CSV_SPECS["workout_events.csv"], row)

                elif tag == "WorkoutStatistics":
                    workout_id = next((pid for ptag, pid in reversed(parent_stack[:-1]) if ptag == "Workout"), None)
                    counters["workout_statistics"] += 1
                    row = row_from_attrs(attrs, CSV_SPECS["workout_statistics.csv"], "workout_id", workout_id or 0)
                    row["workout_id"] = str(workout_id or "")
                    sink.row("workout_statistics.csv", CSV_SPECS["workout_statistics.csv"], row)

                elif tag == "FileReference":
                    route_id = next((pid for ptag, pid in reversed(parent_stack[:-1]) if ptag == "WorkoutRoute"), None)
                    if route_id:
                        current_route_file[route_id] = attrs.get("path", "")

                if parent_stack:
                    parent_stack.pop()
                elem.clear()

    sink.close()

    # Patch route file paths after streaming. It is small, so rewriting is simpler than keeping route rows open.
    route_csv = output_dir / "workout_routes.csv"
    if route_csv.exists() and current_route_file:
        with route_csv.open("r", newline="", encoding="utf-8-sig") as src:
            rows = list(csv.DictReader(src))
        with route_csv.open("w", newline="", encoding="utf-8-sig") as dst:
            writer = csv.DictWriter(dst, fieldnames=CSV_SPECS["workout_routes.csv"])
            writer.writeheader()
            for row in rows:
                route_id = int(row["route_id"])
                row["file_path"] = current_route_file.get(route_id, row.get("file_path", ""))
                writer.writerow(row)

    copy_existing_csv_and_routes(zip_path, output_dir, log)
    if create_csv_package:
        create_all_csv_zip(output_dir, log)
    if create_visual_dashboard:
        create_dashboard(output_dir, log)
    log(f"Done. CSV files are in: {output_dir}")
    return counters


def run_gui() -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("Apple Health CSV Converter")
    root.geometry("620x300")
    root.resizable(False, False)

    zip_var = tk.StringVar()
    out_var = tk.StringVar()
    status_var = tk.StringVar(value="Choose an Apple Health export.zip file.")

    def choose_zip():
        path = filedialog.askopenfilename(title="Choose export.zip", filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")])
        if path:
            zip_var.set(path)
            if not out_var.get():
                out_var.set(str(Path(path).with_suffix("").parent / "apple_health_csv"))

    def choose_output():
        path = filedialog.askdirectory(title="Choose output folder")
        if path:
            out_var.set(path)

    def append_status(text: str):
        status_var.set(text)
        root.update_idletasks()

    def start():
        zip_path = Path(zip_var.get())
        out_path = Path(out_var.get())
        if not zip_path.exists():
            messagebox.showerror("Missing ZIP", "Please choose a valid export.zip file.")
            return
        if not out_path:
            messagebox.showerror("Missing output folder", "Please choose an output folder.")
            return
        start_button.config(state="disabled")

        def worker():
            try:
                counters = convert(zip_path, out_path, log=append_status)
                append_status(f"Done: {counters['records']:,} records, {counters['workouts']:,} workouts converted.")
                messagebox.showinfo(
                    "Finished",
                    "CSV files and apple_health_all_csv.zip were created in:\n"
                    f"{out_path}",
                )
            except Exception as exc:
                append_status("Failed.")
                messagebox.showerror("Conversion failed", str(exc))
            finally:
                start_button.config(state="normal")

        threading.Thread(target=worker, daemon=True).start()

    pad = {"padx": 14, "pady": 8}
    ttk.Label(root, text="Apple Health export.zip").grid(row=0, column=0, sticky="w", **pad)
    ttk.Entry(root, textvariable=zip_var, width=64).grid(row=1, column=0, sticky="we", padx=14)
    ttk.Button(root, text="Browse", command=choose_zip).grid(row=1, column=1, padx=10)

    ttk.Label(root, text="Output folder").grid(row=2, column=0, sticky="w", **pad)
    ttk.Entry(root, textvariable=out_var, width=64).grid(row=3, column=0, sticky="we", padx=14)
    ttk.Button(root, text="Browse", command=choose_output).grid(row=3, column=1, padx=10)

    start_button = ttk.Button(root, text="Convert to CSV", command=start)
    start_button.grid(row=4, column=0, sticky="w", **pad)
    ttk.Label(root, textvariable=status_var, wraplength=580).grid(row=5, column=0, columnspan=2, sticky="w", **pad)

    root.mainloop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Convert Apple Health export.zip to CSV files.")
    parser.add_argument("zip", nargs="?", help="Path to Apple Health export.zip")
    parser.add_argument("output", nargs="?", help="Folder where CSV files should be created")
    parser.add_argument("--no-split-by-type", action="store_true", help="Do not create health_data_by_type/*.csv files")
    parser.add_argument("--no-dashboard", action="store_true", help="Do not create health_dashboard.html after conversion")
    parser.add_argument("--no-csv-zip", action="store_true", help="Do not create apple_health_all_csv.zip after conversion")
    args = parser.parse_args(argv)

    if not args.zip and not args.output:
        return run_gui()
    if not args.zip or not args.output:
        parser.error("zip and output are both required in command-line mode")

    counters = convert(
        Path(args.zip),
        Path(args.output),
        split_records_by_type=not args.no_split_by_type,
        create_visual_dashboard=not args.no_dashboard,
        create_csv_package=not args.no_csv_zip,
    )
    print(json.dumps(counters, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
