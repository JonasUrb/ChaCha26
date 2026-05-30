# api.py – FastAPI HTTP layer for the ZeroWaste Kitchen Bot
# Mirrors the AnimalBot architecture: thin transport layer, delegates all logic
# to ZeroWasteAgent (zerowaste_bot.py). Logs every interaction via LogWriter.
#
# Start with:  python api.py
# Or via Docker/compose.yml

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File
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
    notiz: str | None = None

class RecipeRequest(BaseModel):
    recipe_name: str
    history: list[dict] = Field(default_factory=list)

class AllergyAdd(BaseModel):
    name: str

class AllergyRemove(BaseModel):
    name: str

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
    added = db.add_ingredient(item.name, item.menge, item.einheit, item.haltbar_bis)
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' is already in the pantry.")
    return {
        "success": True,
        "message": f"✅ '{item.name}' added ({item.menge} {item.einheit}, BBD: {item.haltbar_bis}).",
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
async def get_expiring(days: int = 3):
    return {"expiring": db.get_expiring_soon(days)}

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

# ─── Chat endpoints ───────────────────────────────────────────────────────────

@app.post("/api/chat/suggest")
async def suggest_recipes(req: ChatMessage):
    """Return 3 recipe card suggestions based on the pantry."""
    try:
        ingredients = db.get_all_ingredients()
        allergies   = db.get_all_allergies()
        suggestions, log = agent.get_suggestions(req.message, ingredients, allergies)
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
        recipe_text, log = agent.get_recipe(req.recipe_name, req.history, ingredients, allergies)
        log_writer.write(log)
        db.save_recipe(req.recipe_name)
        return {"recipe": recipe_text, "recipe_name": req.recipe_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/chat/message")
async def chat(req: ChatMessage):
    """Handle a general conversational message."""
    try:
        ingredients = db.get_all_ingredients()
        allergies   = db.get_all_allergies()
        context_message = f"[Current pantry: {', '.join(i['name'] for i in ingredients) or 'empty'}]\n\n{req.message}"
        reply, log = agent.chat_message(context_message, req.history, ingredients, allergies)
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
