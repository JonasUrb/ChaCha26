# api.py – FastAPI HTTP layer for the ZeroWaste Kitchen Bot
# Mirrors the AnimalBot architecture: thin transport layer, delegates all logic
# to ZeroWasteAgent (zerowaste_bot.py). Logs every interaction via LogWriter.
#
# Start with:  python api.py
# Or via Docker/compose.yml

from __future__ import annotations

import os
import re
from contextlib import asynccontextmanager
from datetime import date
from typing import Optional

from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import database as db
from zerowaste_bot import ZeroWasteAgent, LogWriter

# ─── App setup ───────────────────────────────────────────────────────────────

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

# ─── Shared agent + log writer (one instance per server process) ─────────────

agent = ZeroWasteAgent()
log_writer = LogWriter()

# ─── Request / Response models ────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)

class IngredientAdd(BaseModel):
    name: str
    menge: float = Field(..., gt=0)
    einheit: str = Field(..., description="g, kg, ml, l or pcs")
    haltbar_bis: str = Field(..., description="YYYY-MM-DD")

class IngredientRemove(BaseModel):
    name: str

class RatingRequest(BaseModel):
    bewertung: int
    notiz: Optional[str] = None

class RecipeRequest(BaseModel):
    recipe_name: str
    history: list[dict] = Field(default_factory=list)

class AllergyAdd(BaseModel):
    name: str

class AllergyRemove(BaseModel):
    name: str

class DietAdd(BaseModel):
    name: str

class DietRemove(BaseModel):
    name: str

FOOD_RESCUE_SCOPE_RE = re.compile(
    r"\b("
    r"food|foods|ingredient|ingredients|pantry|fridge|freezer|kitchen|recipe|recipes|cook|cooking|cooked|meal|meals|"
    r"breakfast|lunch|dinner|snack|dish|leftover|leftovers|expiry|expire|expires|expired|shelf life|best before|"
    r"use-by|use by|food safety|shopping list|grocery|groceries|allergy|allergies|intolerance|diet|vegan|vegetarian|"
    r"halal|kosher|pescatarian|low-carb|sustainability|sustainable|waste|zero waste|"
    r"milk|bread|egg|eggs|cheese|yogurt|yoghurt|meat|fish|chicken|beef|pork|tofu|rice|pasta|potato|potatoes|"
    r"tomato|tomatoes|vegetable|vegetables|fruit|fruits|apple|banana|salad|soup|sauce|flour|sugar|oil|butter|"
    r"zutat|zutaten|vorrat|kueche|küche|kuehlschrank|kühlschrank|rezept|rezepte|kochen|gekocht|essen|mahlzeit|"
    r"fruehstueck|frühstück|mittagessen|abendessen|reste|haltbar|haltbarkeit|abgelaufen|mhd|verbrauchsdatum|"
    r"lebensmittel|lebensmittelsicherheit|lebensmittelverschwendung|einkauf|einkaufsliste|allergen|allergene|"
    r"allergie|unvertraeglichkeit|unverträglichkeit|diaet|diät|ernaehrung|ernährung|vegetarisch|nachhaltig"
    r")\b",
    re.IGNORECASE,
)

APP_HELP_RE = re.compile(
    r"^\s*(hi|hello|hey|help|hilfe|what can you do|what do you do|was kannst du|wie funktioniert das)\s*[.!?]*\s*$",
    re.IGNORECASE,
)

CONTINUATION_RE = re.compile(
    r"^\s*(yes|no|ok|okay|sure|please|thanks|thank you|more|again|cancel|ja|nein|bitte|danke|weiter|mehr|"
    r"nochmal|abbrechen|[1-3])\s*[.!?]*\s*$",
    re.IGNORECASE,
)

OFF_TOPIC_QUESTION_RE = re.compile(
    r"\b(why|what|how|who|where|when|explain|tell me|wieso|warum|was|wie|wer|wo|wann|erklaer|erklär)\b",
    re.IGNORECASE,
)

GERMAN_HINT_RE = re.compile(
    r"[äöüß]|\b(wieso|warum|was|wie|kannst|erklär|erklaer|himmel|frage|antwort)\b",
    re.IGNORECASE,
)


def is_food_rescue_request(message: str, ingredients: Optional[list[dict]] = None, history: Optional[list[dict]] = None) -> bool:
    text = (message or "").strip()
    if not text:
        return True

    if APP_HELP_RE.search(text):
        return True

    if history and len(text) <= 80 and CONTINUATION_RE.search(text):
        return True

    if FOOD_RESCUE_SCOPE_RE.search(text):
        return True

    normalized = text.lower()
    for item in ingredients or []:
        name = str(item.get("name", "")).strip().lower()
        if len(name) >= 3 and re.search(rf"\b{re.escape(name)}\b", normalized):
            return True

    return False


def out_of_scope_reply(message: str) -> str:
    if GERMAN_HINT_RE.search(message or ""):
        return (
            "Ich kann nur bei Food-Rescue-Themen helfen: Vorrat, Zutaten, Haltbarkeit/MHD, "
            "Rezepte, Einkaufsliste, Allergene, Ernährung und Lebensmittelverschwendung. "
            "Frag mich gern dazu."
        )

    return (
        "I can only help with food rescue topics: pantry ingredients, expiry dates, shelf life, "
        "recipes, shopping lists, allergies, diet preferences, and reducing food waste. "
        "Ask me something in that area and I’ll help."
    )


@app.get("/")
async def root():
    return {"message": "ZeroWaste Kitchen Bot API is running!", "docs": "/docs"}

# ─── Inventory endpoints ──────────────────────────────────────────────────────

@app.get("/api/inventory")
async def get_inventory():
    return {"inventory": db.get_all_ingredients()}

@app.post("/api/inventory/add")
async def add_ingredient(item: IngredientAdd):
    allowed_units = {"g", "kg", "ml", "l", "pcs"}
    if item.einheit not in allowed_units:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid unit '{item.einheit}'. Allowed: {', '.join(sorted(allowed_units))}",
        )
    try:
        best_before = date.fromisoformat(item.haltbar_bis)
    except ValueError:
        raise HTTPException(status_code=422, detail="haltbar_bis must be a valid YYYY-MM-DD date.")

    added = db.add_ingredient(item.name, item.menge, item.einheit, best_before.isoformat())
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' is already in the pantry.")
    return {
        "success": True,
        "message": f"✅ '{item.name}' added ({item.menge} {item.einheit}, BBD: {best_before.isoformat()}).",
        "inventory": db.get_all_ingredients(),
    }

@app.delete("/api/inventory/remove")
async def remove_ingredient(item: IngredientRemove):
    removed = db.remove_ingredient(item.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' not found.")
    return {"success": True, "message": f"🗑️ '{item.name}' removed.", "inventory": db.get_all_ingredients()}

@app.delete("/api/inventory/clear")
async def clear_inventory():
    for item in db.get_all_ingredients():
        db.remove_ingredient(item["name"])
    return {"success": True, "message": "Pantry cleared.", "inventory": []}

@app.get("/api/inventory/expiring")
async def get_expiring(days: int = Query(3, ge=0, le=365), today: Optional[str] = None):
    today_date = None
    if today:
        try:
            today_date = date.fromisoformat(today)
        except ValueError:
            raise HTTPException(status_code=422, detail="today must be a valid YYYY-MM-DD date.")

    return {"expiring": db.get_expiring_soon(days, today_date)}

# ─── Allergy endpoints ────────────────────────────────────────────────────────

@app.get("/api/allergies")
async def get_allergies():
    return {"allergies": db.get_all_allergies()}

@app.post("/api/allergies/add")
async def add_allergy(item: AllergyAdd):
    added = db.add_allergy(item.name)
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' is already saved.")
    return {"success": True, "message": f"⚠️ Allergy '{item.name}' saved.", "allergies": db.get_all_allergies()}

@app.delete("/api/allergies/remove")
async def remove_allergy(item: AllergyRemove):
    removed = db.remove_allergy(item.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' not found.")
    return {"success": True, "message": f"✅ Allergy '{item.name}' removed.", "allergies": db.get_all_allergies()}

@app.delete("/api/allergies/clear")
async def clear_allergies():
    db.clear_allergies()
    return {"success": True, "message": "Allergies cleared.", "allergies": []}

# ─── Diet preference endpoints ────────────────────────────────────────────────

@app.get("/api/diets")
async def get_diets():
    return {"diets": db.get_all_diet_preferences()}

@app.post("/api/diets/add")
async def add_diet(item: DietAdd):
    added = db.add_diet_preference(item.name)
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' is already saved.")
    return {"success": True, "message": f"🥗 Diet preference '{item.name}' saved.", "diets": db.get_all_diet_preferences()}

@app.delete("/api/diets/remove")
async def remove_diet(item: DietRemove):
    removed = db.remove_diet_preference(item.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' not found.")
    return {"success": True, "message": f"✅ Diet preference '{item.name}' removed.", "diets": db.get_all_diet_preferences()}

@app.delete("/api/diets/clear")
async def clear_diets():
    db.clear_diet_preferences()
    return {"success": True, "message": "Diet preferences cleared.", "diets": []}

# ─── Chat endpoints ───────────────────────────────────────────────────────────

@app.post("/api/chat/suggest")
async def suggest_recipes(req: ChatMessage):
    """Return 3 recipe card suggestions based on the pantry."""
    try:
        ingredients = db.get_all_ingredients()
        allergies   = db.get_all_allergies()
        diets       = db.get_all_diet_preferences()
        if not is_food_rescue_request(req.message, ingredients, req.history):
            raise HTTPException(status_code=400, detail=out_of_scope_reply(req.message))

        suggestions, log = agent.get_suggestions(req.message, ingredients, allergies, diets)
        log_writer.write(log)
        if not suggestions:
            raise HTTPException(status_code=500, detail="No suggestions returned by model.")
        return {"suggestions": suggestions}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/recipe")
async def get_recipe(req: RecipeRequest):
    """Generate the full Markdown recipe for a named dish."""
    try:
        ingredients = db.get_all_ingredients()
        allergies   = db.get_all_allergies()
        diets       = db.get_all_diet_preferences()
        if OFF_TOPIC_QUESTION_RE.search(req.recipe_name) and not is_food_rescue_request(req.recipe_name, ingredients, req.history):
            raise HTTPException(status_code=400, detail=out_of_scope_reply(req.recipe_name))

        recipe_text, log = agent.get_recipe(req.recipe_name, req.history, ingredients, allergies, diets)
        log_writer.write(log)
        db.save_recipe(req.recipe_name)
        return {"recipe": recipe_text, "recipe_name": req.recipe_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/shopping-list")
async def get_shopping_list(req: ChatMessage):
    """Generate a short, low-waste shopping list based on the pantry."""
    try:
        ingredients = db.get_all_ingredients()
        allergies   = db.get_all_allergies()
        diets       = db.get_all_diet_preferences()
        if not is_food_rescue_request(req.message, ingredients, req.history):
            raise HTTPException(status_code=400, detail=out_of_scope_reply(req.message))

        reply, log = agent.get_shopping_list(req.message, ingredients, allergies, diets)
        log_writer.write(log)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/message")
async def chat(req: ChatMessage):
    """Handle a general conversational message."""
    try:
        ingredients = db.get_all_ingredients()
        allergies   = db.get_all_allergies()
        diets       = db.get_all_diet_preferences()
        if not is_food_rescue_request(req.message, ingredients, req.history):
            reply = out_of_scope_reply(req.message)
            log_writer.write({
                "type": "out_of_scope",
                "user_message": req.message,
                "chatbot_response": reply,
                "history_length": len(req.history),
            })
            return {"reply": reply}

        context_message = f"[Current pantry: {', '.join(i['name'] for i in ingredients) or 'empty'}]\n\n{req.message}"
        reply, log = agent.chat_message(context_message, req.history, ingredients, allergies, diets)
        log_writer.write(log)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/image")
async def chat_image(file: UploadFile = File(...)):
    """Analyze an uploaded food/fridge image."""
    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only JPEG, PNG and WEBP images are supported.")

    image_bytes = await file.read()
    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image too large. Max 5 MB.")

    try:
        reply, log = agent.analyze_image(image_bytes, file.content_type)
        log_writer.write(log)
        return {"reply": reply}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ─── Recipe history & stats ───────────────────────────────────────────────────

@app.post("/api/recipes/rate")
async def rate_recipe(req: RatingRequest):
    db.rate_last_recipe(req.bewertung, req.notiz)
    return {"success": True, "message": f"Rating saved: {req.bewertung}⭐"}

@app.get("/api/history")
async def get_history(limit: int = 10):
    return {"history": db.get_recipe_history(limit)}

@app.get("/api/stats")
async def get_stats():
    return db.get_stats()

# ─── Debug ───────────────────────────────────────────────────────────────────

@app.get("/api/debug/model")
async def debug_model():
    try:
        reply = agent.debug_model()
        return {"ok": True, "model": agent.client.base_url, "reply": reply}
    except Exception as e:
        return {"ok": False, "error": str(e)}

# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
