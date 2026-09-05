"""
Punct de intrare. Rulează în buclă: la fiecare CHECK_INTERVAL_MINUTES,
ia meciurile viitoare din următoarele 48h pentru fiecare ligă configurată,
calculează probabilitățile (model îmbunătățit, 3 surse de date - vezi
model.py și data_fetcher.py) și trimite pe Telegram doar meciurile cu "value".

NOTĂ despre deploy: rulăm ca "Web Service" gratuit pe Render (nu Background
Worker), cu un mic server HTTP care satisface cerința de port, + un serviciu
extern de ping (cron-job.org) care ține botul treaz.
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
    division_code = config.FOOTBALL_DATA_CO_UK_DIVISIONS.get(league_key)

    # Câte O SINGURĂ cerere per sursă per ligă - reutilizate pentru toate
    # fixture-urile de mai jos (formă, head-to-head, medie ligă, cornere, cartonașe).
    all_matches = data_fetcher.get_competition_matches(competition_code)
    data_fetcher.throttle()
    extended_rows = data_fetcher.get_extended_stats_csv(division_code)

    if not all_matches:
        print(f"[main] Fără date de la football-data.org pentru {league_key}, sar peste.")
        return

    league_home_avg, league_away_avg = model.league_reference_averages(all_matches)

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        kickoff = event.get("commence_time", "")
        if not home or not away:
            continue

        # --- formă recentă + head-to-head (football-data.org) ---
        home_matches = data_fetcher.filter_team_matches(all_matches, home, config.FORM_MATCHES)
        away_matches = data_fetcher.filter_team_matches(all_matches, away, config.FORM_MATCHES)
        h2h_matches = data_fetcher.filter_head_to_head(all_matches, home, away)

        lam_home, lam_away = model.expected_goals_v2(
            home_matches, away_matches, home, away,
            league_home_avg, league_away_avg, h2h_matches=h2h_matches,
        )
        probs = model.match_probabilities(lam_home, lam_away)

        # --- cornere + cartonașe reale (football-data.co.uk) ---
        h_cf, h_ca, h_kf, h_ka = data_fetcher.get_team_corner_card_series(extended_rows, home, config.FORM_MATCHES)
        a_cf, a_ca, a_kf, a_ka = data_fetcher.get_team_corner_card_series(extended_rows, away, config.FORM_MATCHES)

        corners_missing = not h_cf or not a_cf
        cards_missing = not h_kf or not a_kf

        exp_corners = model.expected_total_corners(h_cf, h_ca, a_cf, a_ca)
        exp_cards = model.expected_total_cards(h_kf, h_ka, a_kf, a_ka)
        probs["corners"] = model.corners_probability(exp_corners, is_estimated=corners_missing)
        probs["cards"] = model.cards_probability(exp_cards, is_estimated=cards_missing)

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
    threading.Thread(target=start_health_server, daemon=True).start()

    while True:
        run_once()
        print(f"[main] Aștept {config.CHECK_INTERVAL_MINUTES} minute până la următoarea verificare...")
        time.sleep(config.CHECK_INTERVAL_MINUTES * 60)
