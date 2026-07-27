#!/usr/bin/env python3
"""
Run this while server.py is running to load mock games into the admin.
Usage: python load_mock_data.py
"""
import requests

BASE = "http://127.0.0.1:8000"

def create(slot, sport):
    requests.post(f"{BASE}/manual/slots/{slot}", json={"sport": sport})

def add(slot, home, away, league, time, market, odds, status="prematch", score=None, home_logo=None, away_logo=None):
    import time as t
    game = {
        "event_id": f"mock_{int(t.time()*1000)}",
        "status": status,
        "time": {"raw": time},
        "tournament": {"name": league},
        "competitors": {
            "home": {"name": home, "logo": home_logo},
            "away": {"name": away,  "logo": away_logo},
        },
        "score": {"home": score[0] if score else None, "away": score[1] if score else None},
        "market": {"name": market, "type": market, "odds": odds},
    }
    r = requests.post(f"{BASE}/manual/slots/{slot}/games", json=game)
    print(f"  + {home} vs {away} → {r.status_code}")

print("Loading mock data...\n")

# ── FOOTBALL ──────────────────────────────────────────────
print("⚽ Football")
create("football_hot", "football")
add("football_hot",
    "Colo-Colo", "Universidad de Chile",
    "Chile. Primera División", "Hoy, 20:00",
    "1x2", {"p1": "1.85", "draw": "3.40", "p2": "4.20", "more_odds": False},
    home_logo="https://jugabet.cl/static/iolite/icons/colo-colo.webp",
    away_logo="https://jugabet.cl/static/iolite/icons/universidad-de-chile.webp")

add("football_hot",
    "Real Madrid", "Barcelona",
    "España. La Liga", "Mañana, 21:00",
    "1x2", {"p1": "2.10", "draw": "3.60", "p2": "3.20", "more_odds": False})

add("football_hot",
    "River Plate", "Boca Juniors",
    "Argentina. Liga Profesional", "21 may, 22:00",
    "1x2", {"p1": "2.30", "draw": "3.10", "p2": "3.00", "more_odds": False},
    status="live", score=[1, 0])

create("football_vip", "football")
add("football_vip",
    "Manchester City", "Arsenal",
    "Inglaterra. Premier League", "Hoy, 22:45",
    "1x2", {"p1": "1.55", "draw": "4.20", "p2": "5.80", "more_odds": False})

# ── BASKETBALL ────────────────────────────────────────────
print("\n🏀 Basketball")
create("basketball_hot", "basketball")
add("basketball_hot",
    "Los Angeles Lakers", "Golden State Warriors",
    "NBA", "Hoy, 02:30",
    "winner", {"p1": "1.72", "p2": "2.10", "more_odds": False})

add("basketball_hot",
    "Boston Celtics", "Miami Heat",
    "NBA", "Mañana, 01:00",
    "winner", {"p1": "1.45", "p2": "2.80", "more_odds": False},
    status="live", score=[87, 91])

# ── TENNIS ───────────────────────────────────────────────
print("\n🎾 Tennis")
create("tennis_hot", "tennis")
add("tennis_hot",
    "Carlos Alcaraz", "Novak Djokovic",
    "Roland Garros", "Hoy, 14:00",
    "winner", {"p1": "1.90", "p2": "1.95", "more_odds": False})

add("tennis_hot",
    "Jannik Sinner", "Alexander Zverev",
    "Roland Garros", "Mañana, 11:00",
    "winner", {"p1": "1.60", "p2": "2.35", "more_odds": False})

# ── CYBERSPORT ───────────────────────────────────────────
print("\n🎮 Cybersport")
create("cyber_hot", "cybersport")
add("cyber_hot",
    "NAVI", "G2 Esports",
    "CS2. ESL Pro League", "Hoy, 18:00",
    "winner", {"p1": "1.75", "p2": "2.05", "more_odds": False})

add("cyber_hot",
    "T1", "Cloud9",
    "LoL. Worlds 2025", "Mañana, 09:00",
    "winner", {"p1": "1.40", "p2": "2.90", "more_odds": False})

# ── FIGHTS ──────────────────────────────────────────────
print("\n🥊 Fights")
create("fights_hot", "fights")
add("fights_hot",
    "Israel Adesanya", "Sean Strickland",
    "UFC 310 · Middleweight", "Hoy, 03:00",
    "winner", {"p1": "1.85", "p2": "2.00", "more_odds": False})

add("fights_hot",
    "Canelo Álvarez", "David Benavidez",
    "Boxing · Super Middleweight", "22 may, 04:00",
    "winner", {"p1": "1.55", "p2": "2.50", "more_odds": False})

print("\n✅ Done! Open http://127.0.0.1:8000/admin")
