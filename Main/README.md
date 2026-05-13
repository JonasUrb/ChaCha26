source /home/j.urban/Documents/Uni/ChaCha26/Main/zerowaste/venv/bin/activate
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
# 🌿 ZeroWaste Kitchen Bot

**Chatbot gegen Lebensmittelverschwendung**
Kurs: *Generative AI & Sustainability* – TU Berlin / OVGU Magdeburg
Bezug: UN SDG 12 – Responsible Consumption and Production

---

## Inhaltsverzeichnis

1. [Projektübersicht](#projektübersicht)
2. [Tech-Stack](#tech-stack)
3. [Projektstruktur](#projektstruktur)
4. [Installation auf Fedora](#installation-auf-fedora)
5. [Starten ohne Docker](#starten-ohne-docker)
6. [Starten mit Docker](#starten-mit-docker)
7. [API-Endpunkte](#api-endpunkte)
8. [Nutzung des Chatbots](#nutzung-des-chatbots)
9. [Datenbank](#datenbank)
10. [Nachhaltigkeitsbezug](#nachhaltigkeitsbezug)
11. [Erweiterungsideen](#erweiterungsideen)

---

## Projektübersicht

Der ZeroWaste Kitchen Bot hilft dabei, Lebensmittelverschwendung im Alltag zu reduzieren. Nutzer pflegen eine persönliche Vorratsliste, der Bot schlägt passende Rezepte vor und warnt bei ablaufenden Zutaten.

**Kernfunktionen:**
- Vorrat verwalten (Zutaten hinzufügen, entfernen, Ablaufdatum setzen)
- 3 Rezeptvorschläge basierend auf vorhandenen Zutaten
- Ablaufwarnungen für Lebensmittel
- Kochhistorie mit Bewertungssystem
- Impact-Statistiken (CO₂-Einsparung, gerettete Lebensmittel)
- Web-Interface im Browser

---

## Tech-Stack

| Komponente | Technologie |
|---|---|
| Frontend | HTML, CSS, JavaScript |
| Backend | Python 3.11 + FastAPI |
| Datenbank | SQLite |
| LLM | Meta Llama 3.1 70B via Academic Cloud (KISSKI/GWDG) |
| Deployment | Docker + Docker Compose |
| Versionskontrolle | Git + GitHub |

---

## Projektstruktur

```
zerowaste/
├── backend/
│   ├── main.py          ← FastAPI-Server, alle API-Endpunkte
│   └── database.py      ← SQLite-Datenbankmodul (CRUD-Funktionen)
├── frontend/
│   └── index.html       ← Komplettes Web-Interface (HTML + CSS + JS)
├── data/
│   └── zerowaste.db     ← SQLite-Datenbank (wird automatisch erstellt)
├── Dockerfile           ← Container-Bauanleitung
├── docker-compose.yml   ← Startet alles mit einem Befehl
├── requirements.txt     ← Python-Abhängigkeiten
├── .env.example         ← Vorlage für Umgebungsvariablen
├── .env                 ← Dein API-Key (NICHT in Git commiten!)
└── .gitignore
```

---

## Installation auf Fedora

### Schritt 1 – System aktualisieren

```bash
sudo dnf update -y
```

### Schritt 2 – Python 3.11 installieren

```bash
sudo dnf install -y python3.11 python3.11-pip python3-virtualenv
```

Python-Version prüfen:

```bash
python3.11 --version
```

### Schritt 3 – Git installieren (falls noch nicht vorhanden)

```bash
sudo dnf install -y git
```

### Schritt 4 – Repository klonen

```bash
git clone https://github.com/EUER-USERNAME/zerowaste-kitchen-bot.git
cd zerowaste-kitchen-bot
```

Oder einfach den heruntergeladenen ZIP-Ordner nutzen:

```bash
unzip zerowaste_kitchen_bot.zip
cd zerowaste
```

### Schritt 5 – Virtuelle Python-Umgebung erstellen

```bash
python3.11 -m venv venv
source venv/bin/activate
```

Die Umgebung ist aktiv wenn `(venv)` in der Konsole erscheint.

### Schritt 6 – Abhängigkeiten installieren

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### Schritt 7 – Umgebungsvariablen einrichten

```bash
cp .env.example .env
nano .env
```

In der `.env`-Datei den API-Key eintragen:

```
ACADEMIC_CLOUD_API_KEY=dein_api_key_hier
LLM_MODEL=meta-llama-3.1-70b-instruct
```

API-Key bekommst du über das KISSKI-Portal:
https://docs.hpc.gwdg.de/services/saia/index.html

Datei speichern mit `Strg+O`, dann `Strg+X` zum Beenden.

### Schritt 8 – Docker installieren (für den Docker-Start)

```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

Docker-Dienst starten und autostart aktivieren:

```bash
sudo systemctl start docker
sudo systemctl enable docker
```

Docker ohne `sudo` nutzen (einmalig, danach neu einloggen):

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Installation prüfen:

```bash
docker --version
docker compose version
```

---

## Starten ohne Docker

Wenn du ohne Docker arbeiten möchtest (z.B. zum Entwickeln):

```bash
# Virtuelle Umgebung aktivieren (falls noch nicht aktiv)
source venv/bin/activate

# Server starten
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Browser öffnen: **http://localhost:8000**

Der `--reload`-Flag startet den Server automatisch neu wenn du Code änderst – praktisch beim Entwickeln.

---

## Starten mit Docker

### Erster Start (Image bauen + starten)

```bash
docker compose up --build
```

### Normaler Start (nach dem ersten Mal)

```bash
docker compose up
```

### Im Hintergrund starten

```bash
docker compose up -d
```

### Status prüfen

```bash
docker compose ps
```

### Logs anzeigen

```bash
docker compose logs -f
```

### Stoppen

```bash
docker compose down
```

Browser öffnen: **http://localhost:8000**

Die SQLite-Datenbank wird im `data/`-Ordner gespeichert und bleibt auch nach Container-Neustarts erhalten.

---

## API-Endpunkte

Der Server stellt folgende REST-Endpunkte bereit:

| Methode | Pfad | Funktion |
|---|---|---|
| `GET` | `/` | Web-Interface (Frontend) |
| `GET` | `/api/inventory` | Gesamte Vorratsliste abrufen |
| `POST` | `/api/inventory/add` | Zutat hinzufügen |
| `DELETE` | `/api/inventory/remove` | Zutat entfernen |
| `GET` | `/api/inventory/expiring` | Bald ablaufende Zutaten |
| `POST` | `/api/chat/suggest` | 3 Rezeptvorschläge generieren |
| `POST` | `/api/chat/recipe` | Vollständiges Rezept abrufen |
| `POST` | `/api/chat/message` | Allgemeine Chat-Nachricht |
| `POST` | `/api/recipes/rate` | Rezept bewerten (1–5 Sterne) |
| `GET` | `/api/history` | Kochhistorie abrufen |
| `GET` | `/api/stats` | Impact-Statistiken abrufen |

Interaktive API-Dokumentation (automatisch von FastAPI generiert):
**http://localhost:8000/docs**

---

## Nutzung des Chatbots

### Vorrat verwalten

Zutaten können über die Sidebar im Web-Interface hinzugefügt werden, oder per Chat:

- `Ich habe Tomaten, Käse und Nudeln`
- `Füge hinzu Paprika und Zwiebeln`
- `Entferne Tomaten`
- `liste` / `vorrat` – Vorrat anzeigen

### Rezepte finden

- `Was kann ich kochen?`
- `Ich habe Lust auf etwas Mediterranes`
- `Was kann ich schnell kochen? Unter 20 Minuten`

Der Bot zeigt 3 Rezeptkarten zur Auswahl. Per Klick oder Eingabe von `1`, `2` oder `3` wird das vollständige Rezept angezeigt.

### Weitere Funktionen

- `Was wird bald schlecht?` – Ablaufwarnungen
- `Gib mir einen Nachhaltigkeitstipp` – SDG 12 Tipps
- Schnellaktions-Buttons im Interface für häufige Anfragen

---

## Datenbank

Die SQLite-Datenbank wird automatisch beim ersten Start erstellt unter `data/zerowaste.db`.

### Tabelle: `inventory`

| Spalte | Typ | Beschreibung |
|---|---|---|
| `id` | INTEGER | Primärschlüssel |
| `name` | TEXT | Name der Zutat |
| `menge` | TEXT | Menge (optional, z.B. "500g") |
| `haltbar_bis` | TEXT | Ablaufdatum im Format YYYY-MM-DD |
| `hinzugefuegt` | TEXT | Datum des Hinzufügens |

### Tabelle: `recipes_history`

| Spalte | Typ | Beschreibung |
|---|---|---|
| `id` | INTEGER | Primärschlüssel |
| `rezept_name` | TEXT | Name des Rezepts |
| `zutaten` | TEXT | Verwendete Zutaten |
| `gekocht_am` | TEXT | Kochdatum |
| `bewertung` | INTEGER | Bewertung 1–5 Sterne |
| `notiz` | TEXT | Optionale Notiz |

Datenbank direkt einsehen (optional):

```bash
sudo dnf install -y sqlite
sqlite3 data/zerowaste.db
.tables
SELECT * FROM inventory;
.quit
```

---

## Nachhaltigkeitsbezug

Laut UN FAO werden ca. ein Drittel aller Lebensmittel weltweit verschwendet. Das entspricht etwa 8% der globalen Treibhausgasemissionen.

**SDG 12.3** setzt das Ziel, die Lebensmittelverschwendung bis 2030 zu halbieren.

Der ZeroWaste Kitchen Bot unterstützt dieses Ziel durch:
- Resteverwertung durch intelligente Rezeptvorschläge
- Priorisierung ablaufender Lebensmittel
- Bewusstseinsbildung durch Impact-Statistiken
- Schätzung der eingesparten CO₂-Emissionen

---

## Erweiterungsideen

Für spätere Meilensteine (Milestone 2, Final):

- Nutzerevaluation (User Study mit Fragebogen)
- Einkaufslistengenerator (fehlende Zutaten für ein Rezept)
- Ernährungspräferenzen (vegan, glutenfrei, etc.)
- Foto-Upload zur automatischen Zutaten-Erkennung (Vision LLM)
- Mehrsprachigkeit (Englisch, Türkisch, etc.)
- Gamification (Streak-System, Abzeichen)

---

## Kontakt & Kurs

Stefan Hillmann – stefan.hillmann@tu-berlin.de
ISIS-Kurs: https://isis.tu-berlin.de/course/view.php?id=48692
