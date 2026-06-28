$ErrorActionPreference = "Stop"

python -m pip install pyinstaller
python -m PyInstaller --onefile --name AppleHealthCsvExporter apple_health_app.py

Write-Host "Built dist\AppleHealthCsvExporter.exe"
