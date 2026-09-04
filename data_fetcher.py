"""
Preia date brute din cele două surse externe:
 - The Odds API  -> cote în timp real (1X2, Over/Under, BTTS)
 - football-data.org -> rezultate recente, pentru calculul formei echipelor
"""
import requests
import time
from datetime import datetime, timedelta, timezone
import config

ODDS_BASE = "https://api.the-odds-api.com/v4"
FD_BASE = "https://api.football-data.org/v4"


def get_upcoming_odds(league_key: str):
    """Returnează lista de meciuri viitoare cu cote 1X2, totaluri și BTTS."""
    url = f"{ODDS_BASE}/sports/{league_key}/odds"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,totals,btts",
        "oddsFormat": "decimal",
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"[data_fetcher] Eroare la preluarea cotelor pentru {league_key}: {e}")
        return []


def get_team_recent_matches(competition_code: str, team_name: str, limit: int = 6):
    """
    Ia ultimele meciuri finalizate ale unei competiții de la football-data.org
    și filtrează după numele echipei (potrivire aproximativă).
    """
    headers = {"X-Auth-Token": config.FOOTBALL_DATA_API_KEY}
    url = f"{FD_BASE}/competitions/{competition_code}/matches"
    params = {"status": "FINISHED"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json().get("matches", [])
    except requests.RequestException as e:
        print(f"[data_fetcher] Eroare football-data.org ({competition_code}): {e}")
        return []

    team_matches = []
    name_lower = team_name.lower()
    for m in data:
        home = m["homeTeam"]["name"].lower()
        away = m["awayTeam"]["name"].lower()
        if name_lower in home or name_lower in away or home in name_lower or away in name_lower:
            team_matches.append(m)

    team_matches.sort(key=lambda m: m["utcDate"], reverse=True)
    return team_matches[:limit]


def throttle():
    """football-data.org (plan gratuit) permite ~10 cereri/minut."""
    time.sleep(6.5)
