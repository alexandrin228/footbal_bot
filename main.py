"""
Punct de intrare. Rulează în buclă: la fiecare CHECK_INTERVAL_MINUTES,
ia meciurile viitoare din următoarele 48h pentru fiecare ligă configurată,
calculează probabilitățile și trimite pe Telegram doar meciurile cu "value".

NOTĂ despre cornere: planul gratuit al football-data.org NU oferă statistici
de cornere (doar scoruri). Momentan folosim o medie de ligă implicită
(DEFAULT_CORNERS_AVG în acest fișier) ca aproximare. Dacă vrei cornere reale
per echipă, trebuie conectată o sursă suplimentară (ex. API-Football pe
RapidAPI) în data_fetcher.py - pot să te ajut când ajungi acolo.

NOTĂ despre deploy: planul gratuit Render pentru "Background Worker" poate
necesita plată în anumite cazuri. Ca alternativă gratuită, rulăm botul ca
"Web Service": pornim un mic server HTTP (doar răspunde "OK", nu face nimic
altceva) pe portul cerut de Render, într-un fir separat, în timp ce bucla
principală de analiză rulează normal mai jos. Un serviciu extern gratuit de
"ping" (ex. cron-job.org sau UptimeRobot) trebuie configurat să acceseze
URL-ul public al botului la fiecare ~10 minute, ca să nu adoarmă din
inactivitate.
"""
import os
import time
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timezone

import config
import data_fetcher
import model
import telegram_bot

DEFAULT_CORNERS_AVG = 10.0  # medie generică ligi mari europene, folosită ca fallback


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Football bot is running.")

    def log_message(self, format, *args):
        pass  # nu murdărim logurile cu fiecare ping


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    print(f"[main] Server de sanatate pornit pe portul {port} (pentru Render).")
    server.serve_forever()


def process_league(league_key: str):
    events = data_fetcher.get_upcoming_odds(league_key)
    competition_code = config.FOOTBALL_DATA_COMPETITIONS.get(league_key)

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        kickoff = event.get("commence_time", "")
        if not home or not away:
            continue

        # --- statistici recente pentru model ---
        home_matches = data_fetcher.get_team_recent_matches(competition_code, home, config.FORM_MATCHES)
        data_fetcher.throttle()
        away_matches = data_fetcher.get_team_recent_matches(competition_code, away, config.FORM_MATCHES)
        data_fetcher.throttle()

        home_scored, home_conceded = model.team_average_goals(home_matches, home, side="home")
        away_scored, away_conceded = model.team_average_goals(away_matches, away, side="away")

        lam_home, lam_away = model.expected_goals(home_scored, home_conceded, away_scored, away_conceded)
        probs = model.match_probabilities(lam_home, lam_away)
        probs["corners"] = model.corners_probability(DEFAULT_CORNERS_AVG)

        # --- extrage cele mai bune cote disponibile din bookmakerii returnați ---
        best_odds = extract_best_odds(event)

        # --- caută value bets pe piețele cu cote disponibile ---
        value_bets = []
        if best_odds.get("home"):
            v = model.find_value(probs["1x2"]["home"], best_odds["home"], config.VALUE_THRESHOLD)
            if v:
                value_bets.append({**v, "market": f"Victorie {home}"})
        if best_odds.get("draw"):
            v = model.find_value(probs["1x2"]["draw"], best_odds["draw"], config.VALUE_THRESHOLD)
            if v:
                value_bets.append({**v, "market": "Egal"})
        if best_odds.get("away"):
            v = model.find_value(probs["1x2"]["away"], best_odds["away"], config.VALUE_THRESHOLD)
            if v:
                value_bets.append({**v, "market": f"Victorie {away}"})
        if best_odds.get("over_2.5"):
            v = model.find_value(probs["over_under"][2.5]["over"], best_odds["over_2.5"], config.VALUE_THRESHOLD)
            if v:
                value_bets.append({**v, "market": "Over 2.5 goluri"})
        if best_odds.get("btts_yes"):
            v = model.find_value(probs["btts"]["yes"], best_odds["btts_yes"], config.VALUE_THRESHOLD)
            if v:
                value_bets.append({**v, "market": "BTTS Da"})

        # Trimitem doar meciurile care au cel puțin un value bet, ca să nu spămăm canalul.
        if value_bets:
            msg = telegram_bot.format_match_report(home, away, kickoff, probs, value_bets)
            telegram_bot.send_message(msg)


def extract_best_odds(event: dict) -> dict:
    """Parcurge bookmakerii din răspunsul The Odds API și extrage cea mai bună cotă per piață."""
    best = {}
    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            key = market.get("key")
            for outcome in market.get("outcomes", []):
                name = outcome.get("name", "").lower()
                price = outcome.get("price")
                point = outcome.get("point")

                if key == "h2h":
                    if name == event["home_team"].lower():
                        best["home"] = max(best.get("home", 0), price)
                    elif name == event["away_team"].lower():
                        best["away"] = max(best.get("away", 0), price)
                    elif name == "draw":
                        best["draw"] = max(best.get("draw", 0), price)

                elif key == "totals" and point == 2.5:
                    if name == "over":
                        best["over_2.5"] = max(best.get("over_2.5", 0), price)
                    elif name == "under":
                        best["under_2.5"] = max(best.get("under_2.5", 0), price)

                elif key == "btts":
                    if name == "yes":
                        best["btts_yes"] = max(best.get("btts_yes", 0), price)
                    elif name == "no":
                        best["btts_no"] = max(best.get("btts_no", 0), price)
    return best


def run_once():
    print(f"[main] Rulare la {datetime.now(timezone.utc).isoformat()}")
    for league in config.LEAGUES:
        try:
            process_league(league)
        except Exception as e:
            print(f"[main] Eroare la procesarea ligii {league}: {e}")


if __name__ == "__main__":
    # Pornim serverul de "sănătate" într-un fir separat, ca Render să vadă
    # un port deschis (cerință pentru Web Service). Botul propriu-zis rulează
    # mai departe, normal, în firul principal.
    threading.Thread(target=start_health_server, daemon=True).start()

    while True:
        run_once()
        print(f"[main] Aștept {config.CHECK_INTERVAL_MINUTES} minute până la următoarea verificare...")
        time.sleep(config.CHECK_INTERVAL_MINUTES * 60)
