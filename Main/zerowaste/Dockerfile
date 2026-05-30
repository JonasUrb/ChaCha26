# Dockerfile – ZeroWaste Kitchen Bot
# Two services in one container (like AnimalBot):
#   Port 8000 → FastAPI REST API  (api.py)
#   Port 8511 → HTML Frontend     (app.py)
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot logic, API, UI, and database module
COPY chatbot/ .

# Copy the HTML frontend (served by app.py)
COPY frontend/ ./frontend/

# Data directory – overridden by a Docker volume in production
RUN mkdir -p /app/data

# Non-root user for security (mirrors AnimalBot)
RUN useradd -m dev && \
    chown -R dev:dev /app && \
    chmod +x start.sh

USER dev

ENV PYTHONUNBUFFERED=1

# API port + UI port
EXPOSE 8000 8511

CMD ["sh", "start.sh"]
