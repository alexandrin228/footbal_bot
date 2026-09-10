"""
Punct de intrare. Rulează în buclă: la fiecare CHECK_INTERVAL_MINUTES,
ia meciurile viitoare din următoarele 48h pentru fiecare ligă configurată,
calculează probabilitățile printr-un ENSEMBLE de 3 modele independente
(formă/Poisson, Elo, piață de-vigged) pentru 1X2, plus Over/Under, BTTS,
cornere și cartonașe (model unic - vezi limitări în model.py), și trimite
pe Telegram doar meciurile cu "value" real față de cotele curente.

NOTĂ despre deploy: rulăm ca "Web Service" gratuit pe Render, cu un mic
server HTTP intern + un serviciu extern de ping (cron-job.org).
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
        pass


def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    print(f"[main] Server de sanatate pornit pe portul {port} (pentru Render).")
    server.serve_forever()


def process_league(league_key: str, elo_rows: list):
    events = data_fetcher.get_upcoming_odds(league_key)
    competition_code = config.FOOTBALL_DATA_COMPETITIONS.get(league_key)
    division_code = config.FOOTBALL_DATA_CO_UK_DIVISIONS.get(league_key)

    all_matches = data_fetcher.get_competition_matches(competition_code)
    data_fetcher.throttle()
    extended_rows = data_fetcher.get_extended_stats_csv(division_code)

    if not all_matches:
        print(f"[main] Fără date de la football-data.org pentru {league_key}, sar peste.")
        return

    league_home_avg, league_away_avg = model.league_reference_averages(all_matches)
    league_total_avg = league_home_avg + league_away_avg

    for event in events:
        home = event.get("home_team")
        away = event.get("away_team")
        kickoff = event.get("commence_time", "")
        if not home or not away:
            continue

        best_odds = extract_best_odds(event)

        # --- MODEL A: formă recentă + head-to-head (football-data.org) ---
        home_matches = data_fetcher.filter_team_matches(all_matches, home, config.FORM_MATCHES)
        away_matches = data_fetcher.filter_team_matches(all_matches, away, config.FORM_MATCHES)
        h2h_matches = data_fetcher.filter_head_to_head(all_matches, home, away)

        lam_home, lam_away = model.expected_goals_v2(
            home_matches, away_matches, home, away,
            league_home_avg, league_away_avg, h2h_matches=h2h_matches,
        )
        probs = model.match_probabilities(lam_home, lam_away)

        # --- MODEL B: Elo (clubelo.com) ---
        elo_home = data_fetcher.get_team_elo(elo_rows, home)
        elo_away = data_fetcher.get_team_elo(elo_rows, away)
        elo_probs = model.elo_model_probabilities(elo_home, elo_away, league_total_avg)

        # --- MODEL C: piață (de-vigged) ---
        market_probs = model.market_devigged_probabilities(
            best_odds.get("home"), best_odds.get("draw"), best_odds.get("away")
        )

        agreement = model.ensemble_agreement({"Formă": probs["1x2"], "Elo": elo_probs, "Piață": market_probs})
        probs["agreement"] = agreement
        # Pentru 1X2 folosim probabilitatea ENSEMBLE (dacă avem ≥2 modele) - mai
        # robustă decât un singur model. Dacă nu, revenim la modelul de formă.
        final_1x2 = agreement["ensemble"] if agreement["ensemble"] else probs["1x2"]

        # --- cornere + cartonașe reale (football-data.co.uk) ---
        h_cf, h_ca, h_kf, h_ka = data_fetcher.get_team_corner_card_series(extended_rows, home, config.FORM_MATCHES)
        a_cf, a_ca, a_kf, a_ka = data_fetcher.get_team_corner_card_series(extended_rows, away, config.FORM_MATCHES)
        corners_missing = not h_cf or not a_cf
        cards_missing = not h_kf or not a_kf
        exp_corners = model.expected_total_corners(h_cf, h_ca, a_cf, a_ca)
        exp_cards = model.expected_total_cards(h_kf, h_ka, a_kf, a_ka)
        probs["corners"] = model.corners_probability(exp_corners, is_estimated=corners_missing)
        probs["cards"] = model.cards_probability(exp_cards, is_estimated=cards_missing)

        # --- value bets: 1X2 folosește ensemble-ul; O/U și BTTS folosesc doar
        # modelul de formă (singurul disponibil pentru acele piețe - onest, nu
        # ensemble fals) ---
        value_bets = []
        if best_odds.get("home"):
            v = model.find_value(final_1x2["home"], best_odds["home"], config.VALUE_THRESHOLD)
            if v:
                value_bets.append({**v, "market": f"Victorie {home}"})
        if best_odds.get("draw"):
            v = model.find_value(final_1x2["draw"], best_odds["draw"], config.VALUE_THRESHOLD)
            if v:
                value_bets.append({**v, "market": "Egal"})
        if best_odds.get("away"):
            v = model.find_value(final_1x2["away"], best_odds["away"], config.VALUE_THRESHOLD)
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
    # Clasamentul Elo e comun tuturor ligilor - o singură cerere per rulare completă.
    elo_rows = data_fetcher.get_elo_ratings()
    for league in config.LEAGUES:
        try:
            process_league(league, elo_rows)
        except Exception as e:
            print(f"[main] Eroare la procesarea ligii {league}: {e}")


if __name__ == "__main__":
    threading.Thread(target=start_health_server, daemon=True).start()

    while True:
        run_once()
        print(f"[main] Aștept {config.CHECK_INTERVAL_MINUTES} minute până la următoarea verificare...")
        time.sleep(config.CHECK_INTERVAL_MINUTES * 60)
