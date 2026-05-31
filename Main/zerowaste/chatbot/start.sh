#!/bin/bash
set -e

echo "[SYSTEM] Starting ZeroWaste Kitchen Bot..."

# API server (FastAPI on port 8000)
echo "[SYSTEM] Starting API server on port 8000..."
python api.py 2>&1 | sed 's/^/[API] /' > /proc/1/fd/1 &
API_PID=$!

sleep 2
echo "[SYSTEM] API server started (PID: $API_PID)"
echo "[SYSTEM]   REST API  ->  http://0.0.0.0:8000/api/..."
echo "[SYSTEM]   API docs  ->  http://0.0.0.0:8000/docs"

# UI server (HTML frontend on port 8501)
echo "[SYSTEM] Starting UI server on port 8501..."
python app.py 2>&1 | sed 's/^/[UI] /'

# If the UI exits, stop the API too
kill $API_PID
