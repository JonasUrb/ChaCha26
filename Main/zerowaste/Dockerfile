# Dockerfile – ZeroWaste Kitchen Bot Backend
FROM python:3.11-slim

WORKDIR /app

# Abhängigkeiten installieren
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Backend-Code kopieren
COPY backend/ ./backend/

# Frontend-Code kopieren (wird von FastAPI als static files ausgeliefert)
COPY frontend/ ./frontend/

# Daten-Verzeichnis anlegen (wird via Volume überschrieben)
RUN mkdir -p /app/data

# Port freigeben
EXPOSE 8000

# Server starten
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
