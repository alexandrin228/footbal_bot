"""
Preia date brute din trei surse externe:
 - The Odds API       -> cote în timp real (1X2, Over/Under)
 - football-data.org  -> rezultate recente (formă, goluri), necesită cheie API
 - football-data.co.uk -> cornere, cartonașe, șuturi, faulturi REALE per meci,
                          sursă complet gratuită, FĂRĂ cheie API, actualizată
                          constant pe durata sezonului curent.

NOTĂ de eficiență: pentru fiecare ligă, luăm O SINGURĂ DATĂ toate meciurile
finalizate (din fiecare sursă), apoi filtrăm local (fără cereri noi) forma
fiecărei echipe, head-to-head, cornere și cartonașe.
"""
import csv
import difflib
import io
import time
from datetime import datetime, timezone

import requests

import config

ODDS_BASE = "https://api.the-odds-api.com/v4"
FD_BASE = "https://api.football-data.org/v4"
FD_CO_UK_BASE = "https://www.football-data.co.uk"


# =============================================================================
# THE ODDS API
# =============================================================================

def get_upcoming_odds(league_key: str):
    """Returnează meciurile viitoare cu cote 1X2 și totaluri (Over/Under)."""
    url = f"{ODDS_BASE}/sports/{league_key}/odds"
    params = {
        "apiKey": config.ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h,totals",
        "oddsFormat": "decimal",
    }
    try:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"[data_fetcher] Eroare la preluarea cotelor pentru {league_key}: {e}")
        return []


# =============================================================================
# FOOTBALL-DATA.ORG (formă, goluri, head-to-head)
# =============================================================================

def get_competition_matches(competition_code: str):
    """O singură cerere: toate meciurile FINALIZATE ale competiției (sezon curent)."""
    headers = {"X-Auth-Token": config.FOOTBALL_DATA_API_KEY}
    url = f"{FD_BASE}/competitions/{competition_code}/matches"
    params = {"status": "FINISHED"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=20)
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        matches.sort(key=lambda m: m["utcDate"], reverse=True)
        return matches
    except requests.RequestException as e:
        print(f"[data_fetcher] Eroare football-data.org ({competition_code}): {e}")
        return []


def filter_team_matches(all_matches: list, team_name: str, limit: int = 8):
    """Filtrare LOCALĂ: ultimele meciuri ale unei echipe (fără cerere API nouă)."""
    name_lower = team_name.lower()
    result = []
    for m in all_matches:
        home = m["homeTeam"]["name"].lower()
        away = m["awayTeam"]["name"].lower()
        if name_lower in home or name_lower in away or home in name_lower or away in name_lower:
            result.append(m)
    return result[:limit]


def filter_head_to_head(all_matches: list, home_name: str, away_name: str, limit: int = 5):
    """Filtrare LOCALĂ: meciurile directe dintre cele două echipe (sezonul curent)."""
    h_lower, a_lower = home_name.lower(), away_name.lower()
    result = []
    for m in all_matches:
        home = m["homeTeam"]["name"].lower()
        away = m["awayTeam"]["name"].lower()
        teams = {home, away}
        if (h_lower in teams or any(h_lower in t or t in h_lower for t in teams)) and \
           (a_lower in teams or any(a_lower in t or t in a_lower for t in teams)):
            result.append(m)
    return result[:limit]


def throttle():
    """football-data.org (plan gratuit) permite ~10 cereri/minut."""
    time.sleep(6.5)


# =============================================================================
# FOOTBALL-DATA.CO.UK (cornere, cartonașe, șuturi, faulturi - date REALE, gratuit)
# =============================================================================

# Sufixe de curățat la normalizarea numelor (diferă formatul între cele 2 surse)
_SUFFIXES = (" fc", " cf", " sad", " afc", " ac", " cd", " sd", " as", " ss", " ssc")

# football-data.co.uk folosește nume prescurtate/diferite față de football-data.org.
# Mapare manuală pentru cele mai frecvente cazuri din cele 5 ligi mari - restul
# sunt prinse automat de potrivirea "fuzzy" de mai jos (_find_best_team_match).
_TEAM_ALIASES = {
    "man united": "manchester united",
    "man utd": "manchester united",
    "man city": "manchester city",
    "spurs": "tottenham",
    "wolves": "wolverhampton",
    "nott'm forest": "nottingham forest",
    "forest": "nottingham forest",
    "sheffield utd": "sheffield united",
    "west brom": "west bromwich",
    "ath madrid": "atletico madrid",
    "atl. madrid": "atletico madrid",
    "ath bilbao": "athletic club",
    "sociedad": "real sociedad",
    "betis": "real betis",
    "vallecano": "rayo vallecano",
    "celta": "celta vigo",
    "inter": "internazionale",
    "milan": "ac milan",
    "paris sg": "paris saint germain",
    "psg": "paris saint germain",
}


def _normalize_team_name(name: str) -> str:
    n = (name or "").lower().strip()
    for suf in _SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    return _TEAM_ALIASES.get(n, n)


def _find_best_team_match(target: str, candidates: set):
    """
    Găsește cel mai probabil nume echivalent dintr-un set de nume normalizate.
    Încearcă întâi potrivire directă/substring, apoi potrivire "fuzzy"
    (litere asemănătoare) ca ultimă soluție.
    """
    if target in candidates:
        return target
    substr = [c for c in candidates if target in c or c in target]
    if substr:
        return min(substr, key=lambda c: abs(len(c) - len(target)))
    close = difflib.get_close_matches(target, list(candidates), n=1, cutoff=0.72)
    return close[0] if close else None


def current_season_code() -> str:
    """
    Calculează automat codul sezonului curent pentru football-data.co.uk
    (ex. '2627' pentru sezonul 2026/27) - sezonul european începe vara.
    Se recalculează singur an de an, fără să fie nevoie de modificări manuale.
    """
    now = datetime.now(timezone.utc)
    if now.month >= 7:
        start, end = now.year % 100, (now.year + 1) % 100
    else:
        start, end = (now.year - 1) % 100, now.year % 100
    return f"{start:02d}{end:02d}"


def get_extended_stats_csv(division_code: str):
    """
    O singură cerere HTTP: descarcă fișierul CSV cu statistici detaliate
    (cornere, cartonașe, șuturi, faulturi, arbitru) pentru sezonul curent.
    Sursă complet gratuită, fără cheie API, fără cont.
    """
    url = f"{FD_CO_UK_BASE}/mmz4281/{current_season_code()}/{division_code}.csv"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; football-bot/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        text = resp.content.decode("latin-1")  # nume de arbitri pot avea diacritice
        reader = csv.DictReader(io.StringIO(text))
        rows = [r for r in reader if r.get("HomeTeam") and r.get("Div")]
        rows.reverse()  # fișierul e cronologic vechi->nou; noi vrem recent->vechi
        return rows
    except requests.RequestException as e:
        print(f"[data_fetcher] Eroare football-data.co.uk ({division_code}): {e}")
        return []
    except Exception as e:
        print(f"[data_fetcher] Eroare la parsarea CSV ({division_code}): {e}")
        return []


def get_team_corner_card_series(all_rows: list, team_name: str, limit: int = 8):
    """
    Găsește meciurile recente ale echipei în CSV-ul extins și extrage cornere/
    cartonașe obținute și primite, în ordine recent -> vechi. Returnează liste
    goale dacă echipa nu poate fi identificată în această sursă (ex. nume prea
    diferit) - modelul va folosi atunci o valoare implicită, ca să nu blocheze
    restul analizei.
    """
    target = _normalize_team_name(team_name)
    all_names = {_normalize_team_name(r.get("HomeTeam", "")) for r in all_rows}
    all_names |= {_normalize_team_name(r.get("AwayTeam", "")) for r in all_rows}
    matched = _find_best_team_match(target, all_names)
    if not matched:
        return [], [], [], []

    corners_for, corners_against, cards_for, cards_against = [], [], [], []
    for r in all_rows:
        home_n = _normalize_team_name(r.get("HomeTeam", ""))
        away_n = _normalize_team_name(r.get("AwayTeam", ""))
        if matched not in (home_n, away_n):
            continue
        try:
            hc, ac = int(r.get("HC") or 0), int(r.get("AC") or 0)
            hy, ay = int(r.get("HY") or 0), int(r.get("AY") or 0)
            hr, ar = int(r.get("HR") or 0), int(r.get("AR") or 0)
        except ValueError:
            continue
        is_home = home_n == matched
        if is_home:
            corners_for.append(hc)
            corners_against.append(ac)
            cards_for.append(hy + 2 * hr)   # roșu contează dublu fața de galben
            cards_against.append(ay + 2 * ar)
        else:
            corners_for.append(ac)
            corners_against.append(hc)
            cards_for.append(ay + 2 * ar)
            cards_against.append(hy + 2 * hr)
        if len(corners_for) >= limit:
            break
    return corners_for, corners_against, cards_for, cards_against
