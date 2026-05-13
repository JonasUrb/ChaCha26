"""
main.py – FastAPI Backend für den ZeroWaste Kitchen Bot
Startet mit: uvicorn main:app --reload  (oder via Docker)
"""

import json
import os
from contextlib import asynccontextmanager
from openai import OpenAI
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import database as db

# ─── Konfiguration ────────────────────────────────────────────────────────────
API_KEY  = os.getenv("ACADEMIC_CLOUD_API_KEY", "90718c8494d63cf613bd4a4d62534b3b")
BASE_URL = "https://chat-ai.academiccloud.de/v1"
MODEL    = os.getenv("LLM_MODEL", "meta-llama-3.1-70b-instruct")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ─── System-Prompts ───────────────────────────────────────────────────────────
SYSTEM_PROMPT_BASE = """
Du bist der ZeroWaste Kitchen Bot – ein freundlicher Kochassistent gegen Lebensmittelverschwendung.
Antworte auf Deutsch. Nutze Markdown für Formatierungen (**, -, 1.).
Beziehe dich auf Nachhaltigkeit und SDG 12 wenn passend.
Der aktuelle Vorrat wird dir als Kontext mitgegeben. Nutze immer zuerst Zutaten die bald ablaufen.
{allergy_block}
"""

SUGGESTION_PROMPT_BASE = """
Erstelle GENAU 3 Rezeptvorschläge basierend auf dem Vorrat. Antworte NUR als JSON ohne Backticks:
{{
  "vorschlaege": [
    {{"name": "...", "beschreibung": "Ein Satz", "zutaten_genutzt": ["..."], "schwierigkeit": "einfach", "dauer_min": 20}},
    {{"name": "...", "beschreibung": "Ein Satz", "zutaten_genutzt": ["..."], "schwierigkeit": "mittel", "dauer_min": 35}},
    {{"name": "...", "beschreibung": "Ein Satz", "zutaten_genutzt": ["..."], "schwierigkeit": "einfach", "dauer_min": 15}}
  ]
}}
Schwierigkeit: nur "einfach", "mittel" oder "aufwändig". Variiere die Gerichte. Priorisiere ablaufende Zutaten.
{allergy_block}
"""

RECIPE_PROMPT_BASE = """
Gib ein vollständiges Rezept auf Deutsch aus. Nutze dieses Markdown-Format:

## 🍽️ [Rezeptname]

**Dauer:** X Minuten | **Schwierigkeit:** einfach/mittel/aufwändig | **Portionen:** 2

### 📋 Zutaten
- Zutat + Menge

### 👨‍🍳 Zubereitung
1. Schritt...

### 🌱 Nachhaltigkeitstipp
Kurzer Tipp zu Food Waste / SDG 12.

### ⚠️ Lagerhinweis
Welche Zutaten bald aufgebraucht werden sollten.

{allergy_block}
"""


def build_allergy_block() -> str:
    """Liest aktuelle Allergien aus der DB und baut den Warnblock für den Prompt."""
    allergies = db.get_allergy_names()
    if not allergies:
        return ""
    allergy_list = ", ".join(allergies)
    return (
        f"\n⚠️ ALLERGIEN/UNVERTRÄGLICHKEITEN DES NUTZERS: {allergy_list}\n"
        "- Verwende KEINE Zutaten die diese Allergene enthalten.\n"
        "- Weise IMMER explizit auf Allergene hin falls ein Rezept sie trotzdem enthält.\n"
        "- Schlage bei Bedarf allergenfreie Alternativen vor.\n"
    )


# ─── App & DB Init ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield

app = FastAPI(title="ZeroWaste Kitchen Bot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if os.path.exists(frontend_path):
    app.mount("/static", StaticFiles(directory=frontend_path), name="static")

# ─── Pydantic Models ──────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    message: str
    history: list[dict] = []

class IngredientAdd(BaseModel):
    name: str
    menge: float = Field(..., gt=0, description="Menge als Zahl, z.B. 500")
    einheit: str = Field(..., description="Einheit: g, kg, ml, l oder Stück")
    haltbar_bis: str = Field(..., description="Haltbarkeitsdatum im Format YYYY-MM-DD")

    def validate_einheit(self):
        allowed = {"g", "kg", "ml", "l", "Stück"}
        if self.einheit not in allowed:
            raise ValueError(f"Einheit muss eine von {allowed} sein.")

class IngredientRemove(BaseModel):
    name: str

class RatingRequest(BaseModel):
    bewertung: int  # 1-5
    notiz: str = None

class RecipeRequest(BaseModel):
    recipe_name: str
    history: list[dict] = []

class AllergyAdd(BaseModel):
    name: str = Field(..., description="Name der Allergie, z.B. Laktose, Gluten, Nüsse")

class AllergyRemove(BaseModel):
    name: str

# ─── Hilfsfunktion ────────────────────────────────────────────────────────────
def format_inventory_for_prompt() -> str:
    ingredients = db.get_all_ingredients()
    if not ingredients:
        return "(Vorratsliste ist leer)"
    lines = []
    for i in ingredients:
        # Zeigt z.B. "Tomaten (500 g) [MHD: 2025-05-14]"
        line = f"{i['name']} ({i['menge']} {i['einheit']}) [MHD: {i['haltbar_bis']}]"
        lines.append(line)
    return ", ".join(lines)

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "ZeroWaste Kitchen Bot API läuft!"}


@app.get("/api/inventory")
async def get_inventory():
    """Gibt die gesamte Vorratsliste zurück."""
    return {"inventory": db.get_all_ingredients()}


@app.post("/api/inventory/add")
async def add_ingredient(item: IngredientAdd):
    """
    Fügt eine Zutat zur Vorratsliste hinzu.
    Pflichtfelder: name, menge (Zahl), einheit (g/kg/ml/l/Stück), haltbar_bis (YYYY-MM-DD)
    """
    allowed_einheiten = {"g", "kg", "ml", "l", "Stück"}
    if item.einheit not in allowed_einheiten:
        raise HTTPException(
            status_code=422,
            detail=f"Ungültige Einheit '{item.einheit}'. Erlaubt: {', '.join(sorted(allowed_einheiten))}"
        )

    added = db.add_ingredient(item.name, item.menge, item.einheit, item.haltbar_bis)
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' ist bereits in der Liste.")
    return {
        "success": True,
        "message": f"✅ '{item.name}' hinzugefügt ({item.menge} {item.einheit}, MHD: {item.haltbar_bis}).",
        "inventory": db.get_all_ingredients()
    }


@app.delete("/api/inventory/remove")
async def remove_ingredient(item: IngredientRemove):
    """Entfernt eine Zutat aus der Vorratsliste."""
    removed = db.remove_ingredient(item.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' nicht gefunden.")
    return {"success": True, "message": f"🗑️ '{item.name}' entfernt.", "inventory": db.get_all_ingredients()}


@app.get("/api/inventory/expiring")
async def get_expiring(days: int = 3):
    """Gibt Zutaten zurück die bald ablaufen."""
    return {"expiring": db.get_expiring_soon(days)}


# ─── Allergien Endpoints ──────────────────────────────────────────────────────

@app.get("/api/allergies")
async def get_allergies():
    """Gibt alle gespeicherten Allergien zurück."""
    return {"allergies": db.get_all_allergies()}


@app.post("/api/allergies/add")
async def add_allergy(item: AllergyAdd):
    """Fügt eine Allergie/Unverträglichkeit hinzu."""
    added = db.add_allergy(item.name)
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' ist bereits eingetragen.")
    return {
        "success": True,
        "message": f"⚠️ Allergie '{item.name}' gespeichert.",
        "allergies": db.get_all_allergies()
    }


@app.delete("/api/allergies/remove")
async def remove_allergy(item: AllergyRemove):
    """Entfernt eine Allergie."""
    removed = db.remove_allergy(item.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' nicht gefunden.")
    return {
        "success": True,
        "message": f"✅ Allergie '{item.name}' entfernt.",
        "allergies": db.get_all_allergies()
    }


# ─── Chat Endpoints (jetzt mit dynamischem Allergie-Block) ────────────────────

@app.post("/api/chat/suggest")
async def suggest_recipes(req: ChatMessage):
    """Gibt 3 Rezeptvorschläge basierend auf dem aktuellen Vorrat zurück."""
    inventory_str = format_inventory_for_prompt()
    allergy_block = build_allergy_block()
    prompt = f"Vorrat: {inventory_str}\nNutzerwunsch: {req.message}"
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SUGGESTION_PROMPT_BASE.format(allergy_block=allergy_block)},
                {"role": "user", "content": prompt}
            ],
            max_tokens=800,
            temperature=0.8,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        return {"suggestions": data.get("vorschlaege", [])}
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Fehler beim Parsen der Vorschläge.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/recipe")
async def get_recipe(req: RecipeRequest):
    """Gibt das vollständige Rezept für einen ausgewählten Vorschlag zurück."""
    inventory_str = format_inventory_for_prompt()
    allergy_block = build_allergy_block()
    prompt = f"Vorrat: {inventory_str}\nRezept: '{req.recipe_name}'"
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": RECIPE_PROMPT_BASE.format(allergy_block=allergy_block)},
                *req.history[-4:],
                {"role": "user", "content": prompt}
            ],
            max_tokens=1200,
            temperature=0.6,
        )
        recipe_text = response.choices[0].message.content.strip()
        db.save_recipe(req.recipe_name)
        return {"recipe": recipe_text, "recipe_name": req.recipe_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/message")
async def chat(req: ChatMessage):
    """Allgemeine Chat-Konversation."""
    inventory_str = format_inventory_for_prompt()
    allergy_block = build_allergy_block()
    context = f"[Aktueller Vorrat: {inventory_str}]\n\n{req.message}"
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_BASE.format(allergy_block=allergy_block)},
        *req.history[-10:],
        {"role": "user", "content": context}
    ]
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            max_tokens=1000,
            temperature=0.7,
        )
        return {"reply": response.choices[0].message.content.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recipes/rate")
async def rate_recipe(req: RatingRequest):
    """Bewertet das zuletzt gekochte Rezept."""
    db.rate_last_recipe(req.bewertung, req.notiz)
    return {"success": True, "message": f"Bewertung gespeichert: {req.bewertung}⭐"}


@app.get("/api/history")
async def get_history(limit: int = 10):
    """Gibt die Kochhistorie zurück."""
    return {"history": db.get_recipe_history(limit)}


@app.get("/api/stats")
async def get_stats():
    """Gibt Impact-Statistiken zurück."""
    return db.get_stats()