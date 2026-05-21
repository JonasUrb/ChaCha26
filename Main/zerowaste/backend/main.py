# main.py – FastAPI Backend for the ZeroWaste Kitchen Bot
# Start with:
# uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

import json
import os
import base64
from contextlib import asynccontextmanager

from openai import OpenAI
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import database as db
from backend.config import (
    ACADEMIC_CLOUD_API_KEY,
    ACADEMIC_CLOUD_BASE_URL,
    LLM_MODEL,
)

# ─── OpenAI Client ────────────────────────────────────────────────────────────

client = OpenAI(
    api_key=ACADEMIC_CLOUD_API_KEY,
    base_url=ACADEMIC_CLOUD_BASE_URL,
    timeout=30.0,
)

# ─── Prompts ──────────────────────────────────────────────────────────────────

SYSTEM_PROMPT_BASE = """
You are the Food Rescue Chatbot.

Your goal:
You help users reduce food waste in everyday life.

You can:
- analyze available ingredients
- suggest suitable recipes based on what the user already has
- prioritize ingredients that are about to expire
- explain food shelf life
- explain the difference between best-before dates and use-by dates
- consider allergies and intolerances
- give practical tips for using leftovers

Rules:
- The application language is English.
- Use English for interface-style wording, recipe structure, headings, labels, and default responses.
- If the user writes in another language, you may answer in that language to be helpful.
- If the user explicitly asks for a specific language, use that language.
- Be friendly, calm, clear, practical, and easy to understand.
- Be empathetic and reassuring when users are unsure whether food is still safe.
- If the user's information suggests the food is still likely okay, gently reassure them instead of making them more anxious.
- Explain simple checks the user can do: smell, appearance, texture, packaging, storage conditions, and date label.
- Do not casually suggest throwing food away.
- Do not create unnecessary fear around food safety.
- When food safety is involved, be careful and responsible.
- If there are clear warning signs such as mold, bad smell, slimy texture, unusual color, damaged packaging, or unsafe storage, clearly warn the user.
- For high-risk foods such as meat, fish, seafood, raw eggs, dairy, and prepared meals, be extra careful.
- Explain the difference between "best-before" and "use-by" dates in a simple way when relevant.
- If the food is past a best-before date but looks, smells, and tastes normal, explain that it may still be usable depending on the food type.
- If the food is past a use-by date, explain that the user should be more cautious, especially with high-risk foods.
- Explain briefly why certain ingredients should be used first.
- Suggest realistic recipes that people would actually cook.
- Mention food waste reduction and sustainability when relevant.
{allergy_block}
"""

SUGGESTION_PROMPT_BASE = """
You are a professional chef with 20 years of experience. Your task is to suggest exactly 3 recipes based on the user's pantry.

STRICT RULES — follow every one without exception:
1. CULINARY SANITY: Only suggest dishes that are genuinely delicious and would be served in a real restaurant or home kitchen. Never combine ingredients that don't belong together.
2. BASICS ARE ALWAYS AVAILABLE: Assume the user always has salt, pepper, oil, butter, garlic, onions, and water — even if not listed in the pantry.
3. USER WISH IS HIGHEST PRIORITY: If the user expresses a specific craving or preference, ALL 3 suggestions must match that wish exactly.
4. MISSING INGREDIENTS: If a key ingredient for the requested dish isn't in the pantry, you may still suggest the dish — mark missing items with "(buy if needed)" in the ingredients list.
5. EXPIRY FIRST: Prioritize ingredients that expire soonest, visible from the [BBD: date] tag in the pantry.
6. VARIETY: The 3 dishes must be meaningfully different from each other.
7. QUALITY OVER QUANTITY: Each suggestion should feel appealing and appetizing.

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

IMAGE_ANALYSIS_PROMPT = """
You are the Food Rescue Chatbot.

Analyze the uploaded food or fridge image.
Identify visible ingredients as accurately as possible.

Rules:
- The application language is English.
- Use English by default, but if the user asks in another language, you may respond in that language.
- List only ingredients you can reasonably see.
- If something is uncertain, mark it as "possibly".
- Do not invent ingredients.
- Suggest which visible ingredients should be used first if they look perishable.
- Mention food waste reduction when relevant.
"""

# ─── Helpers ─────────────────────────────────────────────────────────────────

def build_allergy_block() -> str:
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


def format_inventory_for_prompt() -> str:
    ingredients = db.get_all_ingredients()

    if not ingredients:
        return "(pantry is empty)"

    lines = []

    for item in ingredients:
        line = f"{item['name']} ({item['menge']} {item['einheit']}) [BBD: {item['haltbar_bis']}]"
        lines.append(line)

    return ", ".join(lines)


def build_context(ingredients=None, allergies=None) -> str:
    ingredients = ingredients or []
    allergies = allergies or []

    ingredient_text = "No ingredients provided."

    if ingredients:
        ingredient_lines = []

        for item in ingredients:
            line = f"- {item.get('name')}"

            if item.get("menge") is not None and item.get("einheit"):
                line += f" ({item['menge']} {item['einheit']})"

            if item.get("haltbar_bis"):
                line += f", best before: {item['haltbar_bis']}"

            ingredient_lines.append(line)

        ingredient_text = "\n".join(ingredient_lines)

    allergy_text = "No allergies or intolerances provided."

    if allergies:
        if isinstance(allergies[0], dict):
            allergy_text = ", ".join([a.get("name", "") for a in allergies])
        else:
            allergy_text = ", ".join(allergies)

    return f"""
Current ingredients:
{ingredient_text}

Allergies / intolerances:
{allergy_text}
"""


def ask_llm(
    message: str,
    history=None,
    ingredients=None,
    allergies=None,
    system_prompt=None,
    temperature=0.7,
    max_tokens=1200,
) -> str:
    history = history or []

    system_prompt = system_prompt or SYSTEM_PROMPT_BASE.format(
        allergy_block=build_allergy_block()
    )

    context = build_context(ingredients, allergies)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": context},
        *history[-10:],
        {"role": "user", "content": message},
    ]

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    return response.choices[0].message.content.strip()


def parse_recipe_suggestions(raw: str) -> dict:
    print("RAW LLM RESPONSE:", raw, flush=True)

    cleaned = raw.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1

        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(cleaned[start:end])
            except json.JSONDecodeError:
                pass

    raise HTTPException(
        status_code=500,
        detail=f"Failed to parse recipe suggestions. Raw response: {cleaned[:500]}",
    )


def analyze_food_image(image_bytes: bytes, mime_type: str) -> str:
    encoded_image = base64.b64encode(image_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": IMAGE_ANALYSIS_PROMPT},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Please analyze this image and list the visible food ingredients. Then suggest what could be cooked with them.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded_image}"
                        },
                    },
                ],
            },
        ],
        temperature=0.4,
        max_tokens=1000,
    )

    return response.choices[0].message.content.strip()


# ─── App & DB Init ───────────────────────────────────────────────────────────

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


# ─── Models ──────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    message: str
    history: list[dict] = Field(default_factory=list)


class IngredientAdd(BaseModel):
    name: str
    menge: float = Field(..., gt=0, description="Quantity as a number, e.g. 500")
    einheit: str = Field(..., description="Unit: g, kg, ml, l or pcs")
    haltbar_bis: str = Field(..., description="Best-before date in format YYYY-MM-DD")


class IngredientRemove(BaseModel):
    name: str


class RatingRequest(BaseModel):
    bewertung: int
    notiz: str | None = None


class RecipeRequest(BaseModel):
    recipe_name: str
    history: list[dict] = Field(default_factory=list)


class AllergyAdd(BaseModel):
    name: str = Field(..., description="Name of the allergy, e.g. Lactose, Gluten, Nuts")


class AllergyRemove(BaseModel):
    name: str


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/")
async def serve_frontend():
    index_path = os.path.join(frontend_path, "index.html")

    if os.path.exists(index_path):
        return FileResponse(index_path)

    return {"message": "ZeroWaste Kitchen Bot API is running!"}


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
        raise HTTPException(
            status_code=409,
            detail=f"'{item.name}' is already in the pantry.",
        )

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

    return {
        "success": True,
        "message": f"🗑️ '{item.name}' removed.",
        "inventory": db.get_all_ingredients(),
    }
@app.delete("/api/inventory/clear")
async def clear_inventory():
    ingredients = db.get_all_ingredients()

    for item in ingredients:
        db.remove_ingredient(item["name"])

    return {
        "success": True,
        "message": "Pantry cleared.",
        "inventory": db.get_all_ingredients(),
    }


@app.get("/api/inventory/expiring")
async def get_expiring(days: int = 3):
    return {"expiring": db.get_expiring_soon(days)}


@app.get("/api/allergies")
async def get_allergies():
    return {"allergies": db.get_all_allergies()}


@app.post("/api/allergies/add")
async def add_allergy(item: AllergyAdd):
    added = db.add_allergy(item.name)

    if not added:
        raise HTTPException(
            status_code=409,
            detail=f"'{item.name}' is already saved.",
        )

    return {
        "success": True,
        "message": f"⚠️ Allergy '{item.name}' saved.",
        "allergies": db.get_all_allergies(),
    }


@app.delete("/api/allergies/remove")
async def remove_allergy(item: AllergyRemove):
    removed = db.remove_allergy(item.name)

    if not removed:
        raise HTTPException(status_code=404, detail=f"'{item.name}' not found.")

    return {
        "success": True,
        "message": f"✅ Allergy '{item.name}' removed.",
        "allergies": db.get_all_allergies(),
    }


@app.post("/api/chat/suggest")
async def suggest_recipes(req: ChatMessage):
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
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": SUGGESTION_PROMPT_BASE.format(
                        allergy_block=allergy_block
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=0.6,
        )

        raw = response.choices[0].message.content.strip()
        data = parse_recipe_suggestions(raw)

        suggestions = data.get("suggestions", [])

        if not suggestions:
            raise HTTPException(
                status_code=500,
                detail=f"No suggestions found in model response. Raw response: {raw[:500]}",
            )

        return {"suggestions": suggestions}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/recipe")
async def get_recipe(req: RecipeRequest):
    prompt = (
        f"Pantry: {format_inventory_for_prompt()}\n\n"
        f"Write the full recipe for: '{req.recipe_name}'\n"
        "Use pantry ingredients as the base. Salt, pepper, oil, and other basics can always be added."
    )

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": RECIPE_PROMPT_BASE.format(
                        allergy_block=build_allergy_block()
                    ),
                },
                *req.history[-4:],
                {"role": "user", "content": prompt},
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
    inventory = db.get_all_ingredients()
    allergies = db.get_all_allergies()

    context_message = f"[Current pantry: {format_inventory_for_prompt()}]\n\n{req.message}"

    try:
        reply = ask_llm(
            message=context_message,
            history=req.history,
            ingredients=inventory,
            allergies=allergies,
            temperature=0.7,
            max_tokens=1000,
        )

        return {"reply": reply}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/image")
async def chat_image(file: UploadFile = File(...)):
    allowed_types = {"image/jpeg", "image/png", "image/webp"}

    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail="Only JPEG, PNG and WEBP images are supported.",
        )

    image_bytes = await file.read()

    if len(image_bytes) > 5 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Image is too large. Please upload an image under 5 MB.",
        )

    try:
        reply = analyze_food_image(
            image_bytes=image_bytes,
            mime_type=file.content_type,
        )

        return {"reply": reply}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

@app.get("/api/debug/model")
async def debug_model():
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "user", "content": "Say only: OK"}
            ],
            temperature=0,
            max_tokens=10,
        )

        return {
            "ok": True,
            "model": LLM_MODEL,
            "reply": response.choices[0].message.content,
        }

    except Exception as e:
        return {
            "ok": False,
            "model": LLM_MODEL,
            "error": str(e),
        }