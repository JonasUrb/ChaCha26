"""
database.py – SQLite-Datenbankmodul für den ZeroWaste Kitchen Bot
Tabellen:
  - inventory       : Vorratsliste mit optionalem Ablaufdatum
  - recipes_history : Gekochte Rezepte + Bewertung (für Evaluation Milestone 2)
  - allergies       : Gespeicherte Allergien/Unverträglichkeiten des Nutzers
"""

import sqlite3
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "zerowaste.db"


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Zeilen als dict-ähnliche Objekte
    return conn


def init_db():
    """Erstellt alle Tabellen falls sie noch nicht existieren."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS inventory (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                menge        REAL NOT NULL,
                einheit      TEXT NOT NULL CHECK(einheit IN ('g', 'kg', 'ml', 'l', 'Stück')),
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
    Fügt eine Zutat hinzu. Alle Felder sind Pflicht.
    Gibt True zurück wenn neu, False wenn bereits vorhanden.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO inventory (name, menge, einheit, haltbar_bis) VALUES (?, ?, ?, ?)",
                (name.strip().capitalize(), menge, einheit, haltbar_bis)
            )
        return True
    except sqlite3.IntegrityError:
        return False  # bereits vorhanden


def remove_ingredient(name: str) -> bool:
    """Entfernt eine Zutat (Teilstring-Match). Gibt True zurück wenn gefunden."""
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM inventory WHERE name LIKE ?",
            (f"%{name.strip()}%",)
        )
        return result.rowcount > 0


def get_all_ingredients() -> list[dict]:
    """Gibt alle Zutaten als Liste zurück."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM inventory ORDER BY haltbar_bis ASC, name ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_expiring_soon(days: int = 3) -> list[dict]:
    """Gibt Zutaten zurück, die in `days` Tagen ablaufen."""
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
    """Aktualisiert das Ablaufdatum einer Zutat."""
    with get_connection() as conn:
        result = conn.execute(
            "UPDATE inventory SET haltbar_bis = ? WHERE name LIKE ?",
            (haltbar_bis, f"%{name.strip()}%")
        )
        return result.rowcount > 0


# ─── Allergien CRUD ───────────────────────────────────────────────────────────

def add_allergy(name: str) -> bool:
    """
    Fügt eine Allergie/Unverträglichkeit hinzu.
    Gibt True zurück wenn neu, False wenn bereits vorhanden.
    """
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO allergies (name) VALUES (?)",
                (name.strip().capitalize(),)
            )
        return True
    except sqlite3.IntegrityError:
        return False  # bereits vorhanden


def remove_allergy(name: str) -> bool:
    """Entfernt eine Allergie. Gibt True zurück wenn gefunden."""
    with get_connection() as conn:
        result = conn.execute(
            "DELETE FROM allergies WHERE name LIKE ?",
            (f"%{name.strip()}%",)
        )
        return result.rowcount > 0


def get_all_allergies() -> list[dict]:
    """Gibt alle gespeicherten Allergien zurück."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM allergies ORDER BY name ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_allergy_names() -> list[str]:
    """Gibt nur die Namen der Allergien zurück (für den System-Prompt)."""
    return [a["name"] for a in get_all_allergies()]


# ─── Recipe History ───────────────────────────────────────────────────────────

def save_recipe(rezept_name: str, zutaten: list[str] = None):
    """Speichert ein gekochtes Rezept in der History."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO recipes_history (rezept_name, zutaten) VALUES (?, ?)",
            (rezept_name, ", ".join(zutaten) if zutaten else None)
        )


def rate_last_recipe(bewertung: int, notiz: str = None):
    """Bewertet das zuletzt gekochte Rezept."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE recipes_history SET bewertung = ?, notiz = ?
               WHERE id = (SELECT MAX(id) FROM recipes_history)""",
            (bewertung, notiz)
        )


def get_recipe_history(limit: int = 10) -> list[dict]:
    """Gibt die letzten gekochten Rezepte zurück."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM recipes_history ORDER BY gekocht_am DESC LIMIT ?",
            (limit,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_stats() -> dict:
    """Gibt Statistiken zurück (für das Impact-Widget im Frontend)."""
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