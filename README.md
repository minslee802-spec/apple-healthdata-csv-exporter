# Apple Health Data CSV Exporter

Apple Health Data CSV Exporter is a local drag-and-drop app for iPhone Health data exports.

Drop the `export.zip` file created by **Health app > profile icon > Export All Health Data**, and the app creates:

- A ZIP containing every generated CSV
- Type-specific CSV files such as `step_count.csv`, `sleep_analysis.csv`, `heart_rate.csv`, and `active_energy_burned.csv`
- Workout, activity summary, metadata, ECG, and route-related CSV files
- A local HTML dashboard for steps, sleep, heart rate, activity, workouts, VO2 Max, and more

## Privacy

This app runs locally on your computer at `http://127.0.0.1:8765/`.

Your Apple Health export is not uploaded to any external server by this app. Uploaded ZIP files and generated outputs are stored locally in:

- `app_uploads/`
- `app_jobs/`

Delete those folders whenever you want to remove local health data.

## Windows: easiest usage

Download the release ZIP, unzip it, then run:

```text
AppleHealthCsvExporter.exe
```

No Python installation is required for this Windows release. The executable already includes the Python runtime and the app code.

Your browser opens automatically. Drag `export.zip` onto the page, wait for conversion, then choose:

- **Download CSV ZIP**
- **Open dashboard**

You can share the release ZIP with another Windows user. They only need to unzip it and run `AppleHealthCsvExporter.exe`.

Note: the packaged executable is Windows-only. macOS or Linux users should run from source or use a separately built package for their operating system.

## Run from source

Requires Python 3.10 or newer.

```powershell
python apple_health_app.py
```

Or double-click:

```text
run_app.bat
```

## Command-line conversion

```powershell
python apple_health_csv_converter.py "C:\path\to\export.zip" "C:\path\to\output_folder"
```

The output folder will contain `apple_health_all_csv.zip` and `health_dashboard.html`.

## Output structure

The generated CSV ZIP uses readable folder and file names:

| Path | Meaning |
| --- | --- |
| `all_health_records.csv` | Every Apple Health record in one CSV. This is the full raw record table. |
| `health_data_by_type/` | The same health records split into one CSV per metric type. This is usually the easiest folder to use for analysis. |
| `health_data_by_type/step_count.csv` | Step count records. |
| `health_data_by_type/sleep_analysis.csv` | Sleep records, including sleep stages such as Awake, REM, Core, and Deep when available. |
| `health_data_by_type/heart_rate.csv` | Heart rate records. |
| `health_data_by_type/resting_heart_rate.csv` | Resting heart rate records. |
| `health_data_by_type/active_energy_burned.csv` | Active energy burned records. |
| `health_data_by_type/distance_walking_running.csv` | Walking and running distance records. |
| `daily_activity_summaries.csv` | Daily Activity Ring style summaries: active energy, exercise time, stand hours, and goals. |
| `workouts.csv` | Workout sessions such as Running, Walking, Cycling, and Swimming. |
| `workout_statistics.csv` | Per-workout statistics such as distance, calories, pace, and heart rate. |
| `workout_events.csv` | Workout events such as pauses, laps, or segments when present. |
| `workout_routes.csv` | Metadata and file references for workout GPS routes. |
| `record_metadata.csv` | Extra metadata attached to Health records or workouts. |
| `hrv_instantaneous_bpm.csv` | Beat-by-beat BPM values nested under heart rate variability records. |
| `ecg/` | Electrocardiogram CSV files copied from the Apple Health export. Apple exports ECG as separate CSV files, so they stay grouped here. |
| `profile.csv` | Profile fields exported by Apple Health, such as biological sex or date of birth when present. |
| `export_info.csv` | Export timestamp and related export metadata. |

Why folders? `health_data_by_type/` contains many metric-specific CSV files, and `ecg/` contains multiple ECG files that Apple Health already exports separately. Single-table outputs stay at the top level.

## Build the Windows executable

Install PyInstaller:

```powershell
python -m pip install pyinstaller
```

Build:

```powershell
pyinstaller --onefile --name AppleHealthCsvExporter apple_health_app.py
```

The executable will be created in `dist/`.
