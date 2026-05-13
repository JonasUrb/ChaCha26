"""
database.py – SQLite database module for the ZeroWaste Kitchen Bot
Tables:
  - inventory       : Pantry list with quantity, unit, and best-before date
  - recipes_history : Cooked recipes + rating (for Evaluation Milestone 2)
  - allergies       : User's saved allergies and intolerances
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "zerowaste.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Creates all tables if they don't exist yet."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS inventory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                menge        REAL NOT NULL,
                einheit      TEXT NOT NULL CHECK(einheit IN ('g', 'kg', 'ml', 'l', 'pcs')),
                haltbar_bis  TEXT NOT NULL,
                hinzugefuegt TEXT DEFAULT (date('now'))
            );

            CREATE TABLE IF NOT EXISTS recipes_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                rezept_name TEXT NOT NULL,
                zutaten     TEXT,
                gekocht_am  TEXT DEFAULT (date('now')),
                bewertung   INTEGER CHECK(bewertung BETWEEN 1 AND 5),
                notiz       TEXT
            );

            CREATE TABLE IF NOT EXISTS allergies (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                hinzugefuegt TEXT DEFAULT (date('now'))
            );
        """)


# ─── Inventory CRUD ───────────────────────────────────────────────────────────

def add_ingredient(name: str, menge: float, einheit: str, haltbar_bis: str) -> bool:
    """
    Adds an ingredient to the pantry. All fields are required.
    Returns True if new, False if already exists.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO inventory (name, menge, einheit, haltbar_bis) VALUES (?, ?, ?, ?)",
                (name.strip().capitalize(), menge, einheit, haltbar_bis)
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_ingredient(name: str) -> bool:
    """Removes an ingredient (partial match). Returns True if found."""
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM inventory WHERE name LIKE ?",
            (f"%{name.strip()}%",)
        )
        return result.rowcount > 0


def get_all_ingredients() -> list[dict]:
    """Returns all pantry ingredients as a list."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM inventory ORDER BY haltbar_bis ASC, name ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_expiring_soon(days: int = 3) -> list[dict]:
    """Returns ingredients expiring within the given number of days."""
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT * FROM inventory
               WHERE date(haltbar_bis) <= date('now', ? || ' days')
               AND date(haltbar_bis) >= date('now')
               ORDER BY haltbar_bis ASC""",
            (str(days),)
        ).fetchall()
        return [dict(row) for row in rows]


def update_expiry(name: str, haltbar_bis: str) -> bool:
    """Updates the best-before date of an ingredient."""
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE inventory SET haltbar_bis = ? WHERE name LIKE ?",
            (haltbar_bis, f"%{name.strip()}%")
        )
        return result.rowcount > 0


# ─── Allergy CRUD ─────────────────────────────────────────────────────────────

def add_allergy(name: str) -> bool:
    """
    Adds an allergy or intolerance.
    Returns True if new, False if already exists.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO allergies (name) VALUES (?)",
                (name.strip().capitalize(),)
            )
        return True
    except sqlite3.IntegrityError:
        return False


def remove_allergy(name: str) -> bool:
    """Removes an allergy. Returns True if found."""
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM allergies WHERE name LIKE ?",
            (f"%{name.strip()}%",)
        )
        return result.rowcount > 0


def get_all_allergies() -> list[dict]:
    """Returns all saved allergies."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM allergies ORDER BY name ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_allergy_names() -> list[str]:
    """Returns only the allergy names (used for prompt injection)."""
    return [a["name"] for a in get_all_allergies()]


# ─── Recipe History ───────────────────────────────────────────────────────────

def save_recipe(rezept_name: str, zutaten: list[str] = None):
    """Saves a cooked recipe to the history."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO recipes_history (rezept_name, zutaten) VALUES (?, ?)",
            (rezept_name, ", ".join(zutaten) if zutaten else None)
        )


def rate_last_recipe(bewertung: int, notiz: str = None):
    """Rates the most recently cooked recipe."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE recipes_history SET bewertung = ?, notiz = ?
               WHERE id = (SELECT MAX(id) FROM recipes_history)""",
            (bewertung, notiz)
        )


def get_recipe_history(limit: int = 10) -> list[dict]:
    """Returns the most recently cooked recipes."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM recipes_history ORDER BY gekocht_am DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_stats() -> dict:
    """Returns impact statistics for the stats widget."""
    with get_connection() as conn:
        total_cooked = conn.execute("SELECT COUNT(*) FROM recipes_history").fetchone()[0]
        avg_rating = conn.execute(
            "SELECT AVG(bewertung) FROM recipes_history WHERE bewertung IS NOT NULL"
        ).fetchone()[0]
        ingredients_saved = conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0]

    return {
        "rezepte_gekocht": total_cooked,
        "durchschnittsbewertung": round(avg_rating, 1) if avg_rating else None,
        "zutaten_im_vorrat": ingredients_saved,
        "co2_gespart_kg": round(total_cooked * 0.5, 1),
    }