# zerowaste_bot.py – Core logic for the ZeroWaste Kitchen Bot
# Mirrors the AnimalBot architecture: bot logic is separated from API and logging.
# Usage: imported by api.py

import os
import json
import base64
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))

# ─── Config ──────────────────────────────────────────────────────────────────

API_KEY      = os.getenv("ACADEMIC_CLOUD_API_KEY")
BASE_URL     = os.getenv("ACADEMIC_CLOUD_BASE_URL", "https://chat-ai.academiccloud.de/v1")
LLM_MODEL    = os.getenv("LLM_MODEL", "meta-llama-3.1-8b-instruct")

if not API_KEY:
    raise RuntimeError("ACADEMIC_CLOUD_API_KEY is missing. Please set it in your .env file.")

# ─── Prompts ─────────────────────────────────────────────────────────────────

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
- If the user is unsure about a specific ingredient, respond to that concern immediately before suggesting recipes.
- Start with direct safety guidance for the named ingredient(s). If key details are missing, ask for them, but still provide simple checks.
- Only recommend cooking with an uncertain ingredient after explaining how the user can verify that it is safe.
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


# ─── ZeroWasteAgent ──────────────────────────────────────────────────────────

class ZeroWasteAgent:
    """
    Core bot logic for the ZeroWaste Kitchen Bot.
    Handles all LLM interactions and returns (response, log_message) tuples,
    mirroring the AnimalBot pattern of separating logic from transport.
    """

    def __init__(self):
        self.client = OpenAI(
            api_key=API_KEY,
            base_url=BASE_URL,
            timeout=30.0,
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _build_allergy_block(self, allergies: list) -> str:
        if not allergies:
            return ""
        names = [a["name"] if isinstance(a, dict) else a for a in allergies]
        allergy_list = ", ".join(names)
        return (
            f"\n⚠️ USER ALLERGIES / INTOLERANCES: {allergy_list}\n"
            "- Do NOT use any ingredients containing these allergens.\n"
            "- If a suggested recipe unavoidably contains an allergen, flag it clearly with a warning.\n"
            "- Always suggest allergen-free alternatives where possible.\n"
        )

    def _format_inventory(self, ingredients: list) -> str:
        if not ingredients:
            return "(pantry is empty)"
        lines = []
        for item in ingredients:
            line = f"{item['name']} ({item['menge']} {item['einheit']}) [BBD: {item['haltbar_bis']}]"
            lines.append(line)
        return ", ".join(lines)

    def _build_context(self, ingredients: list, allergies: list) -> str:
        ingredient_lines = []
        for item in ingredients:
            line = f"- {item.get('name')}"
            if item.get("menge") is not None and item.get("einheit"):
                line += f" ({item['menge']} {item['einheit']})"
            if item.get("haltbar_bis"):
                line += f", best before: {item['haltbar_bis']}"
            ingredient_lines.append(line)

        ingredient_text = "\n".join(ingredient_lines) if ingredient_lines else "No ingredients provided."

        if allergies:
            allergy_text = ", ".join([a["name"] if isinstance(a, dict) else a for a in allergies])
        else:
            allergy_text = "No allergies or intolerances provided."

        return f"\nCurrent ingredients:\n{ingredient_text}\n\nAllergies / intolerances:\n{allergy_text}\n"

    def _parse_suggestions(self, raw: str) -> dict:
        cleaned = raw.strip().replace("```json", "").replace("```", "").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}") + 1
            if start != -1 and end > start:
                try:
                    return json.loads(cleaned[start:end])
                except json.JSONDecodeError:
                    pass
        raise ValueError(f"Failed to parse recipe suggestions. Raw response: {cleaned[:500]}")

    # ── Public methods ────────────────────────────────────────────────────

    def get_suggestions(self, user_wish: str, ingredients: list, allergies: list):
        """
        Suggest 3 recipes based on pantry and optional user wish.
        Returns (suggestions_list, log_message).
        """
        inventory_str = self._format_inventory(ingredients)
        allergy_block = self._build_allergy_block(allergies)

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

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": SUGGESTION_PROMPT_BASE.format(allergy_block=allergy_block)},
                {"role": "user", "content": prompt},
            ],
            max_tokens=900,
            temperature=0.6,
        )

        raw = response.choices[0].message.content.strip()
        data = self._parse_suggestions(raw)
        suggestions = data.get("suggestions", [])

        log_message = {
            "type": "suggest",
            "user_wish": user_wish,
            "inventory": inventory_str,
            "raw_response": raw,
            "suggestions_count": len(suggestions),
            "model": LLM_MODEL,
        }

        return suggestions, log_message

    def get_recipe(self, recipe_name: str, history: list, ingredients: list, allergies: list):
        """
        Generate a full recipe for a named dish.
        Returns (recipe_text, log_message).
        """
        inventory_str = self._format_inventory(ingredients)
        allergy_block = self._build_allergy_block(allergies)

        prompt = (
            f"Pantry: {inventory_str}\n\n"
            f"Write the full recipe for: '{recipe_name}'\n"
            "Use pantry ingredients as the base. Salt, pepper, oil, and other basics can always be added."
        )

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": RECIPE_PROMPT_BASE.format(allergy_block=allergy_block)},
                *history[-4:],
                {"role": "user", "content": prompt},
            ],
            max_tokens=1400,
            temperature=0.5,
        )

        recipe_text = response.choices[0].message.content.strip()

        log_message = {
            "type": "recipe",
            "recipe_name": recipe_name,
            "inventory": inventory_str,
            "recipe_length": len(recipe_text),
            "model": LLM_MODEL,
        }

        return recipe_text, log_message

    def chat_message(self, message: str, history: list, ingredients: list, allergies: list):
        """
        Handle a general chat message.
        Returns (reply_text, log_message).
        """
        allergy_block = self._build_allergy_block(allergies)
        system_prompt = SYSTEM_PROMPT_BASE.format(allergy_block=allergy_block)
        context = self._build_context(ingredients, allergies)
        inventory_str = self._format_inventory(ingredients)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": context},
            *history[-10:],
            {"role": "user", "content": message},
        ]

        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1000,
        )

        reply = response.choices[0].message.content.strip()

        log_message = {
            "type": "chat",
            "user_message": message,
            "chatbot_response": reply,
            "inventory": inventory_str,
            "history_length": len(history),
            "model": LLM_MODEL,
        }

        return reply, log_message

    def analyze_image(self, image_bytes: bytes, mime_type: str):
        """
        Analyze a food/fridge image and identify ingredients.
        Returns (reply_text, log_message).
        """
        encoded_image = base64.b64encode(image_bytes).decode("utf-8")

        response = self.client.chat.completions.create(
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
                            "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
                        },
                    ],
                },
            ],
            temperature=0.4,
            max_tokens=1000,
        )

        reply = response.choices[0].message.content.strip()

        log_message = {
            "type": "image_analysis",
            "mime_type": mime_type,
            "image_size_bytes": len(image_bytes),
            "chatbot_response": reply,
            "model": LLM_MODEL,
        }

        return reply, log_message

    def debug_model(self):
        """Quick model connectivity check."""
        response = self.client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": "Say only: OK"}],
            temperature=0,
            max_tokens=10,
        )
        return response.choices[0].message.content


# ─── LogWriter ───────────────────────────────────────────────────────────────

class LogWriter:
    """
    Appends structured JSON log entries to a .jsonp conversation log file.
    Mirrors the AnimalBot LogWriter pattern for server-side auditability.
    """

    def __init__(self, log_dir: str = None):
        if log_dir is None:
            log_dir = os.environ.get("DATA_DIR", "/app/data")
        os.makedirs(log_dir, exist_ok=True)
        self.logfile = os.path.join(log_dir, "conversation.jsonp")

    def _make_json_safe(self, value):
        if isinstance(value, list):
            return [self._make_json_safe(x) for x in value]
        elif isinstance(value, dict):
            return {k: self._make_json_safe(v) for k, v in value.items()}
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    def write(self, log_message: dict):
        with open(self.logfile, "a") as f:
            f.write(json.dumps(self._make_json_safe(log_message), indent=2))
            f.write("\n")


# ─── Standalone CLI (for testing without the API) ────────────────────────────

if __name__ == "__main__":
    import database as db

    db.init_db()
    agent = ZeroWasteAgent()
    log_writer = LogWriter()
    history = []

    print("ZeroWaste Kitchen Bot – type 'quit' to exit")
    while True:
        user_input = input("You: ").strip()
        if user_input.lower() in ["quit", "exit", "bye"]:
            print("Goodbye!")
            break

        ingredients = db.get_all_ingredients()
        allergies = db.get_all_allergies()

        reply, log = agent.chat_message(user_input, history, ingredients, allergies)
        print(f"Bot: {reply}\n")

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": reply})
        log_writer.write(log)
