import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost")
API_PORT     = os.environ.get("API_PORT", "8010")
API_URL      = f"{API_BASE_URL}:{API_PORT}"

FRONTEND_PATH = os.path.join(os.path.dirname(__file__), "frontend")

print(f"[UI] Frontend server starting on port 8501")
print(f"[UI] API URL injected into frontend: {API_URL}")

app = FastAPI(title="ZeroWaste Kitchen Bot UI")
app.mount("/static", StaticFiles(directory=FRONTEND_PATH), name="static")

@app.get("/")
async def serve_frontend():
    index_path = os.path.join(FRONTEND_PATH, "index.html")
    with open(index_path, encoding="utf-8") as f:
        html = f.read()
    html = html.replace("const API = '';", f"const API = '{API_URL}';")
    return HTMLResponse(content=html, status_code=200)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8501)