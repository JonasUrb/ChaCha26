"""
main.py – FastAPI Backend for the ZeroWaste Kitchen Bot
Start with: uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
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

# ─── Configuration ────────────────────────────────────────────────────────────
API_KEY  = os.getenv("ACADEMIC_CLOUD_API_KEY", "90718c8494d63cf613bd4a4d62534b3b")
BASE_URL = "https://chat-ai.academiccloud.de/v1"
MODEL    = os.getenv("LLM_MODEL", "meta-llama-3.1-70b-instruct")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

# ─── Prompts ──────────────────────────────────────────────────────────────────
SYSTEM_PROMPT_BASE = """
You are the ZeroWaste Kitchen Bot — a knowledgeable, friendly cooking assistant dedicated to reducing food waste.
Always respond in English. Use Markdown formatting (**, -, 1.) to structure your answers clearly.
Reference sustainability and UN SDG 12 (Responsible Consumption) where relevant.
You will be given the user's current pantry as context. Always prioritize ingredients that are expiring soon.
Never suggest throwing food away — always find a use for it.
{allergy_block}
"""

SUGGESTION_PROMPT_BASE = """
You are a professional chef with 20 years of experience. Your task is to suggest exactly 3 recipes based on the user's pantry.

STRICT RULES — follow every one without exception:
1. CULINARY SANITY: Only suggest dishes that are genuinely delicious and would be served in a real restaurant or home kitchen. Never combine ingredients that don't belong together (e.g. Nutella with meat, sweet spreads as marinades, or any other absurd pairing). Ask yourself: "Would a real cook actually make this?" If the answer is no, do not suggest it.
2. BASICS ARE ALWAYS AVAILABLE: Assume the user always has salt, pepper, oil, butter, garlic, onions, and water — even if not listed in the pantry.
3. USER WISH IS HIGHEST PRIORITY: If the user expresses a specific craving or preference (e.g. "pasta", "something spicy", "Mediterranean", "vegetarian"), ALL 3 suggestions must match that wish exactly. Never ignore it.
4. MISSING INGREDIENTS: If a key ingredient for the requested dish isn't in the pantry, you may still suggest the dish — mark missing items with "(buy if needed)" in the ingredients list.
5. EXPIRY FIRST: Prioritize ingredients that expire soonest (visible from the [BBD: date] tag in the pantry).
6. VARIETY: The 3 dishes must be meaningfully different from each other — not the same dish with minor variations.
7. QUALITY OVER QUANTITY: Each suggestion should feel appealing and appetizing, as if written for a food magazine.

Respond ONLY with raw JSON — no backticks, no explanation, no comments:
{{
  "suggestions": [
    {{"name": "...", "description": "One enticing sentence", "ingredients_used": ["..."], "difficulty": "easy", "duration_min": 20}},
    {{"name": "...", "description": "One enticing sentence", "ingredients_used": ["..."], "difficulty": "medium", "duration_min": 35}},
    {{"name": "...", "description": "One enticing sentence", "ingredients_used": ["..."], "difficulty": "easy", "duration_min": 15}}
  ]
}}
Difficulty must be exactly one of: "easy", "medium", "advanced".
{allergy_block}
"""

RECIPE_PROMPT_BASE = """
You are a professional chef. Write a complete, well-structured, and genuinely delicious recipe in English.
The recipe must be realistic and practical — exactly as it would appear in a high-quality cookbook.
You may always use salt, pepper, oil, butter, and other basic pantry staples even if not listed in the inventory.
Be specific with quantities, temperatures, and timings. Use sensory language to make the recipe inviting.

Use this exact Markdown format:

## 🍽️ [Recipe Name]

**Time:** X minutes | **Difficulty:** easy/medium/advanced | **Serves:** 2

### 📋 Ingredients
- ingredient + quantity

### 👨‍🍳 Instructions
1. Step...

### 💡 Tips & Variations
One or two practical tips to improve or vary the dish.

### 🌱 Sustainability Note
A short, specific tip related to food waste reduction and SDG 12.

### ⚠️ Use First
Which pantry ingredients should be used up soon and why.

{allergy_block}
"""


def build_allergy_block() -> str:
    """Reads current allergies from DB and builds the warning block for the prompt."""
    allergies = db.get_allergy_names()
    if not allergies:
        return ""
    allergy_list = ", ".join(allergies)
    return (
        f"\n⚠️ USER ALLERGIES / INTOLERANCES: {allergy_list}\n"
        "- Do NOT use any ingredients containing these allergens.\n"
        "- If a suggested recipe unavoidably contains an allergen, flag it clearly with a warning.\n"
        "- Always suggest allergen-free alternatives where possible.\n"
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
    menge: float = Field(..., gt=0, description="Quantity as a number, e.g. 500")
    einheit: str = Field(..., description="Unit: g, kg, ml, l or pcs")
    haltbar_bis: str = Field(..., description="Best-before date in format YYYY-MM-DD")

class IngredientRemove(BaseModel):
    name: str

class RatingRequest(BaseModel):
    bewertung: int  # 1-5
    notiz: str = None

class RecipeRequest(BaseModel):
    recipe_name: str
    history: list[dict] = []

class AllergyAdd(BaseModel):
    name: str = Field(..., description="Name of the allergy, e.g. Lactose, Gluten, Nuts")

class AllergyRemove(BaseModel):
    name: str

# ─── Helper ───────────────────────────────────────────────────────────────────
def format_inventory_for_prompt() -> str:
    ingredients = db.get_all_ingredients()
    if not ingredients:
        return "(pantry is empty)"
    lines = []
    for i in ingredients:
        line = f"{i['name']} ({i['menge']} {i['einheit']}) [BBD: {i['haltbar_bis']}]"
        lines.append(line)
    return ", ".join(lines)

# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "ZeroWaste Kitchen Bot API is running!"}


@app.get("/api/inventory")
async def get_inventory():
    """Returns the full pantry list."""
    return {"inventory": db.get_all_ingredients()}


@app.post("/api/inventory/add")
async def add_ingredient(item: IngredientAdd):
    """Adds an ingredient to the pantry. All fields are required."""
    allowed_units = {"g", "kg", "ml", "l", "pcs"}
    if item.einheit not in allowed_units:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid unit '{item.einheit}'. Allowed: {', '.join(sorted(allowed_units))}"
        )
    added = db.add_ingredient(item.name, item.menge, item.einheit, item.haltbar_bis)
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' is already in the pantry.")
    return {
        "success": True,
        "message": f"✅ '{item.name}' added ({item.menge} {item.einheit}, BBD: {item.haltbar_bis}).",
        "inventory": db.get_all_ingredients()
    }


@app.delete("/api/inventory/remove")
async def remove_ingredient(item: IngredientRemove):
    """Removes an ingredient from the pantry."""
    removed = db.remove_ingredient(item.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' not found.")
    return {"success": True, "message": f"🗑️ '{item.name}' removed.", "inventory": db.get_all_ingredients()}


@app.get("/api/inventory/expiring")
async def get_expiring(days: int = 3):
    """Returns ingredients expiring within the given number of days."""
    return {"expiring": db.get_expiring_soon(days)}


# ─── Allergy Endpoints ────────────────────────────────────────────────────────

@app.get("/api/allergies")
async def get_allergies():
    """Returns all saved allergies."""
    return {"allergies": db.get_all_allergies()}


@app.post("/api/allergies/add")
async def add_allergy(item: AllergyAdd):
    """Adds an allergy or intolerance."""
    added = db.add_allergy(item.name)
    if not added:
        raise HTTPException(status_code=409, detail=f"'{item.name}' is already saved.")
    return {
        "success": True,
        "message": f"⚠️ Allergy '{item.name}' saved.",
        "allergies": db.get_all_allergies()
    }


@app.delete("/api/allergies/remove")
async def remove_allergy(item: AllergyRemove):
    """Removes an allergy."""
    removed = db.remove_allergy(item.name)
    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' not found.")
    return {
        "success": True,
        "message": f"✅ Allergy '{item.name}' removed.",
        "allergies": db.get_all_allergies()
    }


# ─── Chat Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/chat/suggest")
async def suggest_recipes(req: ChatMessage):
    """Returns 3 recipe suggestions based on the current pantry."""
    inventory_str = format_inventory_for_prompt()
    allergy_block = build_allergy_block()

    user_wish = req.message.strip()
    if user_wish:
        prompt = (
            f"Pantry: {inventory_str}\n\n"
            f"USER REQUEST (highest priority — all 3 recipes must match this): {user_wish}\n\n"
            "Suggest 3 recipes that match the user's request and make good use of pantry ingredients."
        )
    else:
        prompt = (
            f"Pantry: {inventory_str}\n\n"
            "Suggest 3 delicious and sensible recipes using the pantry ingredients."
        )

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SUGGESTION_PROMPT_BASE.format(allergy_block=allergy_block)},
                {"role": "user", "content": prompt}
            ],
            max_tokens=900,
            temperature=0.6,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        data = json.loads(raw)
        return {"suggestions": data.get("suggestions", [])}
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Failed to parse recipe suggestions.")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/recipe")
async def get_recipe(req: RecipeRequest):
    """Returns the full recipe for a selected suggestion."""
    inventory_str = format_inventory_for_prompt()
    allergy_block = build_allergy_block()
    prompt = (
        f"Pantry: {inventory_str}\n\n"
        f"Write the full recipe for: '{req.recipe_name}'\n"
        "Use pantry ingredients as the base. Salt, pepper, oil, and other basics can always be added."
    )
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": RECIPE_PROMPT_BASE.format(allergy_block=allergy_block)},
                *req.history[-4:],
                {"role": "user", "content": prompt}
            ],
            max_tokens=1400,
            temperature=0.5,
        )
        recipe_text = response.choices[0].message.content.strip()
        db.save_recipe(req.recipe_name)
        return {"recipe": recipe_text, "recipe_name": req.recipe_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/message")
async def chat(req: ChatMessage):
    """General chat conversation."""
    inventory_str = format_inventory_for_prompt()
    allergy_block = build_allergy_block()
    context = f"[Current pantry: {inventory_str}]\n\n{req.message}"
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
    """Rates the last cooked recipe."""
    db.rate_last_recipe(req.bewertung, req.notiz)
    return {"success": True, "message": f"Rating saved: {req.bewertung}⭐"}


@app.get("/api/history")
async def get_history(limit: int = 10):
    """Returns the cooking history."""
    return {"history": db.get_recipe_history(limit)}


@app.get("/api/stats")
async def get_stats():
    """Returns impact statistics."""
    return db.get_stats()