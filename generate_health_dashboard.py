#!/usr/bin/env python3
"""Generate a static Apple Health dashboard from converted CSV files."""

from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "converted_health_csv"
DEFAULT_OUTPUT = ROOT / "health_dashboard.html"


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def day_from(value: str) -> str:
    return (value or "")[:10]


def parse_apple_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def read_rows(path: Path):
    if not path.exists():
        return
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


def sum_record_by_day(path: Path, convert=None) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for row in read_rows(path) or []:
        value = parse_float(row.get("value", ""))
        if value is None:
            continue
        if convert:
            value = convert(value, row.get("unit", ""))
        day = day_from(row.get("startDate", ""))
        if day:
            totals[day] += value
    return dict(sorted(totals.items()))


def avg_record_by_day(path: Path) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    counts: defaultdict[str, int] = defaultdict(int)
    for row in read_rows(path) or []:
        value = parse_float(row.get("value", ""))
        day = day_from(row.get("startDate", ""))
        if value is None or not day:
            continue
        totals[day] += value
        counts[day] += 1
    return {day: round(totals[day] / counts[day], 2) for day in sorted(totals)}


def latest_record_points(path: Path, limit: int = 120) -> list[dict[str, float | str]]:
    points = []
    for row in read_rows(path) or []:
        value = parse_float(row.get("value", ""))
        date = row.get("startDate", "")
        if value is not None and date:
            points.append({"date": date[:10], "value": value})
    return points[-limit:]


def distance_to_km(value: float, unit: str) -> float:
    unit = (unit or "").lower()
    if unit in {"m", "meter", "meters"}:
        return value / 1000
    if unit in {"mi", "mile", "miles"}:
        return value * 1.609344
    return value


def sleep_hours_by_day(path: Path) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for row in read_rows(path) or []:
        if "Asleep" not in row.get("value", ""):
            continue
        start = parse_apple_date(row.get("startDate", ""))
        end = parse_apple_date(row.get("endDate", ""))
        if not start or not end:
            continue
        hours = max((end - start).total_seconds() / 3600, 0)
        day = start.date().isoformat()
        totals[day] += hours
    return {day: round(value, 2) for day, value in sorted(totals.items())}


def sleep_stage_name(value: str) -> str:
    if value.endswith("AsleepCore"):
        return "Core"
    if value.endswith("AsleepDeep"):
        return "Deep"
    if value.endswith("AsleepREM"):
        return "REM"
    if value.endswith("Awake"):
        return "Awake"
    if value.endswith("InBed"):
        return "In Bed"
    if "Asleep" in value:
        return "Asleep"
    return value.replace("HKCategoryValueSleepAnalysis", "") or "Sleep"


def sleep_day_for(start: datetime, end: datetime) -> str:
    if start.hour >= 18 and end.date() != start.date():
        return end.date().isoformat()
    return start.date().isoformat()


def sleep_details(path: Path, limit: int = 14) -> list[dict]:
    nights: dict[str, dict] = {}
    for row in read_rows(path) or []:
        start = parse_apple_date(row.get("startDate", ""))
        end = parse_apple_date(row.get("endDate", ""))
        if not start or not end or end <= start:
            continue
        stage = sleep_stage_name(row.get("value", ""))
        if stage == "In Bed":
            continue
        day = sleep_day_for(start, end)
        night = nights.setdefault(day, {"date": day, "segments": [], "stages": defaultdict(float)})
        minutes = (end - start).total_seconds() / 60
        night["segments"].append(
            {
                "stage": stage,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "minutes": round(minutes, 1),
            }
        )
        night["stages"][stage] += minutes

    result = []
    for day in sorted(nights)[-limit:]:
        night = nights[day]
        segments = sorted(night["segments"], key=lambda item: item["start"])
        stages = {stage: round(minutes / 60, 2) for stage, minutes in sorted(night["stages"].items())}
        asleep = sum(minutes for stage, minutes in night["stages"].items() if stage != "Awake")
        awake = night["stages"].get("Awake", 0)
        result.append(
            {
                "date": day,
                "segments": segments,
                "stages": stages,
                "asleep_hours": round(asleep / 60, 2),
                "awake_minutes": round(awake, 1),
            }
        )
    return result


def read_activity_summaries(path: Path) -> dict[str, dict[str, float]]:
    series = {
        "active_energy": {},
        "exercise_time": {},
        "stand_hours": {},
    }
    for row in read_rows(path) or []:
        day = row.get("dateComponents", "")
        if not day:
            continue
        active = parse_float(row.get("activeEnergyBurned", ""))
        exercise = parse_float(row.get("appleExerciseTime", ""))
        stand = parse_float(row.get("appleStandHours", ""))
        if active is not None:
            series["active_energy"][day] = active
        if exercise is not None:
            series["exercise_time"][day] = exercise
        if stand is not None:
            series["stand_hours"][day] = stand
    return series


def read_workouts(path: Path) -> dict:
    by_type = Counter()
    duration_by_type = Counter()
    monthly = Counter()
    recent = []
    for row in read_rows(path) or []:
        kind = row.get("workoutActivityType", "").replace("HKWorkoutActivityType", "") or "Workout"
        duration = parse_float(row.get("duration", "")) or 0
        unit = row.get("durationUnit", "min")
        if unit == "sec":
            duration = duration / 60
        elif unit in {"hr", "hour"}:
            duration = duration * 60
        day = day_from(row.get("startDate", ""))
        by_type[kind] += 1
        duration_by_type[kind] += duration
        if day:
            monthly[day[:7]] += 1
            recent.append({"date": day, "type": kind, "minutes": round(duration, 1)})
    return {
        "by_type": [{"name": key, "count": by_type[key], "minutes": round(duration_by_type[key], 1)} for key, _ in by_type.most_common()],
        "monthly": [{"month": key, "count": monthly[key]} for key in sorted(monthly)],
        "recent": recent[-12:],
        "total_count": sum(by_type.values()),
        "total_minutes": round(sum(duration_by_type.values()), 1),
    }


def average_last(series: dict[str, float], days: int) -> float | None:
    values = [series[key] for key in sorted(series)[-days:] if series[key] is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def latest_value(series: dict[str, float]) -> tuple[str, float] | None:
    keys = sorted(series)
    if not keys:
        return None
    key = keys[-1]
    return key, series[key]


def recent_metric_rows(series: dict[str, float], limit: int = 14) -> dict[str, list[dict[str, float | str]]]:
    return {
        key: [{"date": day, "value": round(value, 2)} for day, value in list(sorted(values.items()))[-limit:]]
        for key, values in series.items()
    }


def build_dashboard_data(input_dir: Path) -> dict:
    records = input_dir / "health_data_by_type"
    activity = read_activity_summaries(input_dir / "daily_activity_summaries.csv")
    series = {
        "steps": sum_record_by_day(records / "step_count.csv"),
        "active_energy": activity["active_energy"],
        "exercise_time": activity["exercise_time"],
        "distance_km": sum_record_by_day(records / "distance_walking_running.csv", convert=distance_to_km),
        "heart_rate": avg_record_by_day(records / "heart_rate.csv"),
        "resting_heart_rate": avg_record_by_day(records / "resting_heart_rate.csv"),
        "sleep_hours": sleep_hours_by_day(records / "sleep_analysis.csv"),
        "vo2max": {point["date"]: point["value"] for point in latest_record_points(records / "vo2_max.csv", limit=200)},
    }
    workouts = read_workouts(input_dir / "workouts.csv")
    cards = {
        "latest_steps": latest_value(series["steps"]),
        "avg_steps_30": average_last(series["steps"], 30),
        "avg_sleep_30": average_last(series["sleep_hours"], 30),
        "avg_resting_hr_30": average_last(series["resting_heart_rate"], 30),
        "total_workouts": workouts["total_count"],
        "total_workout_hours": round(workouts["total_minutes"] / 60, 1),
    }
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "series": series,
        "recent_metrics": recent_metric_rows(series),
        "sleep_detail": sleep_details(records / "sleep_analysis.csv"),
        "workouts": workouts,
        "cards": cards,
    }


def render_html(data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Apple Health Dashboard</title>
<style>
:root {{
  color-scheme: light;
  --bg: #f6f7f9;
  --panel: #ffffff;
  --ink: #17191f;
  --muted: #667085;
  --line: #d8dee8;
  --red: #e74b5b;
  --green: #18a66a;
  --blue: #2878d7;
  --amber: #c88719;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: Arial, "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
}}
header {{
  padding: 28px 32px 16px;
  background: var(--panel);
  border-bottom: 1px solid var(--line);
}}
h1 {{
  margin: 0 0 6px;
  font-size: 28px;
  line-height: 1.2;
  letter-spacing: 0;
}}
.sub {{ color: var(--muted); font-size: 14px; }}
main {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
.cards {{
  display: grid;
  grid-template-columns: repeat(6, minmax(150px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}}
.card {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  min-height: 92px;
}}
.label {{ color: var(--muted); font-size: 12px; margin-bottom: 10px; }}
.value {{ font-size: 24px; font-weight: 700; line-height: 1.15; }}
.unit {{ color: var(--muted); font-size: 12px; margin-top: 5px; }}
.grid {{
  display: grid;
  grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);
  gap: 16px;
}}
section {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 16px;
}}
.toolbar {{
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}}
select, button {{
  height: 34px;
  border: 1px solid var(--line);
  background: #fff;
  border-radius: 7px;
  padding: 0 10px;
  color: var(--ink);
}}
.segmented {{ display: flex; gap: 6px; }}
.segmented button.active {{ background: var(--ink); color: white; border-color: var(--ink); }}
canvas {{ width: 100%; height: 380px; display: block; }}
.bars {{ display: grid; gap: 10px; }}
.bar-row {{
  display: grid;
  grid-template-columns: 90px minmax(110px, 1fr) 132px;
  gap: 8px;
  align-items: center;
  font-size: 13px;
}}
.bar-track {{ height: 10px; background: #eef1f5; border-radius: 999px; overflow: hidden; }}
.bar-fill {{ height: 100%; background: var(--blue); }}
.bar-value {{ color: var(--muted); white-space: nowrap; text-align: right; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
td, th {{ padding: 8px 4px; border-bottom: 1px solid var(--line); text-align: left; }}
th {{ color: var(--muted); font-weight: 600; }}
.stack {{ display: grid; gap: 16px; }}
.mini-table {{ max-height: 260px; overflow: auto; }}
.sleep-head {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}}
.sleep-head h2 {{ font-size: 18px; margin: 0; }}
.stage-summary {{
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 12px;
}}
.stage-chip {{
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 8px;
  font-size: 12px;
}}
.stage-chip strong {{ display: block; font-size: 15px; margin-top: 4px; }}
.sleep-window {{
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 8px;
}}
.timeline {{
  position: relative;
  height: 52px;
  background: #eef1f5;
  border-radius: 7px;
  overflow: hidden;
  border: 1px solid var(--line);
}}
.segment {{
  position: absolute;
  top: 0;
  bottom: 0;
  min-width: 2px;
}}
.stage-Awake {{ background: #e74b5b; }}
.stage-REM {{ background: #8f68d8; }}
.stage-Core {{ background: #2878d7; }}
.stage-Deep {{ background: #1d4f91; }}
.stage-Asleep {{ background: #18a66a; }}
.legend {{
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 10px;
  color: var(--muted);
  font-size: 12px;
}}
.legend span::before {{
  content: "";
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 2px;
  margin-right: 5px;
  vertical-align: -1px;
  background: currentColor;
}}
@media (max-width: 980px) {{
  .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  .grid {{ grid-template-columns: 1fr; }}
  header {{ padding: 22px 18px 14px; }}
  main {{ padding: 14px; }}
  .toolbar {{ align-items: stretch; flex-direction: column; }}
}}
</style>
</head>
<body>
<header>
  <h1>Apple Health Dashboard</h1>
  <div class="sub">Generated {html.escape(data["generated_at"])} from local Apple Health CSV exports</div>
</header>
<main>
  <div class="cards" id="cards"></div>
  <div class="grid">
    <section>
      <div class="toolbar">
        <select id="metric"></select>
        <div class="segmented">
          <button data-range="90">90D</button>
          <button data-range="365" class="active">1Y</button>
          <button data-range="all">All</button>
        </div>
      </div>
      <canvas id="chart" width="1100" height="420"></canvas>
    </section>
    <div class="stack">
      <section>
        <h2 style="font-size:18px;margin:0 0 14px;">Workouts</h2>
        <div class="bars" id="workoutBars"></div>
      </section>
      <section>
        <div class="toolbar" style="margin-bottom:10px;">
          <h2 style="font-size:18px;margin:0;">Recent Data</h2>
          <select id="recentDataType">
            <option value="workouts">Workout</option>
            <option value="steps">Step</option>
            <option value="heart_rate">Heart Rate</option>
            <option value="sleep_hours">Sleep</option>
            <option value="active_energy">Active Energy</option>
            <option value="distance_km">Distance</option>
          </select>
        </div>
        <div class="mini-table">
          <table>
            <thead id="recentDataHead"></thead>
            <tbody id="recentDataRows"></tbody>
          </table>
        </div>
      </section>
    </div>
  </div>
  <section style="margin-top:16px;">
    <div class="sleep-head">
      <h2>Sleep Stages</h2>
      <select id="sleepDate"></select>
    </div>
    <div class="stage-summary" id="stageSummary"></div>
    <div class="sleep-window" id="sleepWindow"></div>
    <div class="timeline" id="sleepTimeline"></div>
    <div class="legend">
      <span style="color:#e74b5b;">Awake</span>
      <span style="color:#8f68d8;">REM</span>
      <span style="color:#2878d7;">Core</span>
      <span style="color:#1d4f91;">Deep</span>
    </div>
  </section>
</main>
<script>
const DATA = {payload};
const METRICS = [
  ["steps", "Steps", "steps", "#2878d7"],
  ["active_energy", "Active Energy", "kcal", "#e74b5b"],
  ["exercise_time", "Exercise Time", "min", "#18a66a"],
  ["distance_km", "Walking + Running Distance", "km", "#c88719"],
  ["heart_rate", "Heart Rate Average", "bpm", "#d94f91"],
  ["resting_heart_rate", "Resting Heart Rate", "bpm", "#6d63d9"],
  ["sleep_hours", "Sleep", "hours", "#1e8f8a"],
  ["vo2max", "VO2 Max", "ml/kg/min", "#2f855a"]
];
let currentRange = 365;

function fmt(value, digits = 0) {{
  if (value === null || value === undefined) return "-";
  return Number(value).toLocaleString(undefined, {{ maximumFractionDigits: digits }});
}}

function card(title, value, unit) {{
  return `<div class="card"><div class="label">${{title}}</div><div class="value">${{value}}</div><div class="unit">${{unit}}</div></div>`;
}}

function renderCards() {{
  const c = DATA.cards;
  const latest = c.latest_steps || ["", 0];
  document.getElementById("cards").innerHTML = [
    card("Latest Steps", fmt(latest[1]), latest[0]),
    card("Avg Steps", fmt(c.avg_steps_30), "last 30 days"),
    card("Avg Sleep", fmt(c.avg_sleep_30, 1), "hours, last 30 days"),
    card("Resting HR", fmt(c.avg_resting_hr_30, 1), "bpm, last 30 days"),
    card("Workouts", fmt(c.total_workouts), "sessions"),
    card("Workout Time", fmt(c.total_workout_hours, 1), "hours")
  ].join("");
}}

function seriesFor(key) {{
  const entries = Object.entries(DATA.series[key] || {{}}).sort(([a], [b]) => a.localeCompare(b));
  if (currentRange === "all") return entries;
  return entries.slice(-Number(currentRange));
}}

function drawChart() {{
  const select = document.getElementById("metric");
  const metric = METRICS.find(m => m[0] === select.value) || METRICS[0];
  const rows = seriesFor(metric[0]);
  const canvas = document.getElementById("chart");
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, w, h);
  const pad = {{ left: 70, right: 24, top: 24, bottom: 48 }};
  const vals = rows.map(r => Number(r[1])).filter(Number.isFinite);
  if (!vals.length) {{
    ctx.fillStyle = "#667085";
    ctx.font = "16px Arial";
    ctx.fillText("No data for this metric.", pad.left, 80);
    return;
  }}
  const min = Math.min(0, Math.min(...vals));
  const max = Math.max(...vals);
  const span = max - min || 1;
  const x = i => pad.left + (rows.length === 1 ? 0 : i * (w - pad.left - pad.right) / (rows.length - 1));
  const y = v => h - pad.bottom - ((v - min) / span) * (h - pad.top - pad.bottom);

  ctx.strokeStyle = "#d8dee8";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#667085";
  ctx.font = "12px Arial";
  for (let i = 0; i <= 4; i++) {{
    const value = min + span * i / 4;
    const yy = y(value);
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(w - pad.right, yy);
    ctx.stroke();
    ctx.fillText(fmt(value, 1), 10, yy + 4);
  }}

  ctx.strokeStyle = metric[3];
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  rows.forEach(([date, value], i) => {{
    const xx = x(i), yy = y(Number(value));
    if (i === 0) ctx.moveTo(xx, yy); else ctx.lineTo(xx, yy);
  }});
  ctx.stroke();

  const grad = ctx.createLinearGradient(0, pad.top, 0, h - pad.bottom);
  grad.addColorStop(0, metric[3] + "33");
  grad.addColorStop(1, metric[3] + "00");
  ctx.lineTo(x(rows.length - 1), h - pad.bottom);
  ctx.lineTo(x(0), h - pad.bottom);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  ctx.fillStyle = "#17191f";
  ctx.font = "bold 16px Arial";
  ctx.fillText(`${{metric[1]}} (${{metric[2]}})`, pad.left, 18);
  ctx.fillStyle = "#667085";
  ctx.font = "12px Arial";
  ctx.fillText(rows[0][0], pad.left, h - 18);
  ctx.textAlign = "right";
  ctx.fillText(rows[rows.length - 1][0], w - pad.right, h - 18);
  ctx.textAlign = "left";
}}

function renderWorkouts() {{
  const rows = DATA.workouts.by_type || [];
  const max = Math.max(...rows.map(r => r.count), 1);
  document.getElementById("workoutBars").innerHTML = rows.map(r => `
    <div class="bar-row">
      <div>${{r.name}}</div>
      <div class="bar-track"><div class="bar-fill" style="width:${{100 * r.count / max}}%"></div></div>
      <div class="bar-value">${{r.count}} sessions | ${{fmt(r.minutes / 60, 1)}} hr</div>
    </div>
  `).join("");
}}

function metricByKey(key) {{
  return METRICS.find(m => m[0] === key) || METRICS[0];
}}

function renderRecentData() {{
  const type = document.getElementById("recentDataType").value;
  const head = document.getElementById("recentDataHead");
  const body = document.getElementById("recentDataRows");
  if (type === "workouts") {{
    head.innerHTML = `<tr><th>Date</th><th>Type</th><th>Minutes</th></tr>`;
    body.innerHTML = (DATA.workouts.recent || []).slice().reverse().map(r => `
      <tr><td>${{r.date}}</td><td>${{r.type}}</td><td>${{fmt(r.minutes, 1)}}</td></tr>
    `).join("");
    return;
  }}
  const metric = metricByKey(type);
  const rows = (DATA.recent_metrics && DATA.recent_metrics[type]) || [];
  head.innerHTML = `<tr><th>Date</th><th>${{metric[1]}}</th><th>Unit</th></tr>`;
  body.innerHTML = rows.slice().reverse().map(row => `
    <tr><td>${{row.date}}</td><td>${{fmt(row.value, type === "distance_km" || type === "sleep_hours" ? 2 : 1)}}</td><td>${{metric[2]}}</td></tr>
  `).join("");
}}

function formatTime(value) {{
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString([], {{ hour: "2-digit", minute: "2-digit" }});
}}

function stageClass(stage) {{
  return "stage-" + String(stage || "Asleep").replace(/[^A-Za-z0-9_-]/g, "");
}}

function renderSleepDetail() {{
  const nights = DATA.sleep_detail || [];
  const select = document.getElementById("sleepDate");
  if (!nights.length) {{
    select.innerHTML = `<option>No sleep data</option>`;
    document.getElementById("stageSummary").innerHTML = "";
    document.getElementById("sleepWindow").textContent = "No detailed sleep stage records were found.";
    document.getElementById("sleepTimeline").innerHTML = "";
    return;
  }}
  if (!select.value) {{
    select.innerHTML = nights.slice().reverse().map(n => `<option value="${{n.date}}">${{n.date}}</option>`).join("");
  }}
  const night = nights.find(n => n.date === select.value) || nights[nights.length - 1];
  const segments = night.segments || [];
  if (!segments.length) return;

  const start = Math.min(...segments.map(s => new Date(s.start).getTime()));
  const end = Math.max(...segments.map(s => new Date(s.end).getTime()));
  const total = Math.max(end - start, 1);
  const preferred = ["Awake", "REM", "Core", "Deep", "Asleep"];
  const stageRows = preferred
    .filter(stage => night.stages && night.stages[stage])
    .map(stage => `<div class="stage-chip">${{stage}}<strong>${{fmt(night.stages[stage], 2)}}h</strong></div>`);
  document.getElementById("stageSummary").innerHTML = [
    `<div class="stage-chip">Total asleep<strong>${{fmt(night.asleep_hours, 2)}}h</strong></div>`,
    `<div class="stage-chip">Awake<strong>${{fmt(night.awake_minutes, 1)}}m</strong></div>`,
    ...stageRows
  ].join("");
  document.getElementById("sleepWindow").textContent = `${{formatTime(segments[0].start)}} - ${{formatTime(segments[segments.length - 1].end)}}`;
  document.getElementById("sleepTimeline").innerHTML = segments.map(s => {{
    const left = ((new Date(s.start).getTime() - start) / total) * 100;
    const width = Math.max(((new Date(s.end).getTime() - new Date(s.start).getTime()) / total) * 100, 0.4);
    return `<div class="segment ${{stageClass(s.stage)}}" title="${{s.stage}} ${{formatTime(s.start)}}-${{formatTime(s.end)}} (${{s.minutes}}m)" style="left:${{left}}%;width:${{width}}%;"></div>`;
  }}).join("");
}}

function init() {{
  const select = document.getElementById("metric");
  select.innerHTML = METRICS.map(m => `<option value="${{m[0]}}">${{m[1]}}</option>`).join("");
  select.addEventListener("change", drawChart);
  document.getElementById("recentDataType").addEventListener("change", renderRecentData);
  document.getElementById("sleepDate").addEventListener("change", renderSleepDetail);
  document.querySelectorAll("[data-range]").forEach(button => {{
    button.addEventListener("click", () => {{
      currentRange = button.dataset.range;
      document.querySelectorAll("[data-range]").forEach(b => b.classList.remove("active"));
      button.classList.add("active");
      drawChart();
    }});
  }});
  renderCards();
  renderWorkouts();
  renderRecentData();
  renderSleepDetail();
  drawChart();
}}
init();
</script>
</body>
</html>
"""


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Generate a static Apple Health dashboard HTML file.")
    parser.add_argument("input", nargs="?", default=str(DEFAULT_INPUT), help="Converted CSV folder")
    parser.add_argument("output", nargs="?", default=str(DEFAULT_OUTPUT), help="Output HTML path")
    args = parser.parse_args()

    input_dir = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    data = build_dashboard_data(input_dir)
    output_path.write_text(render_html(data), encoding="utf-8")
    print(f"Dashboard written to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
