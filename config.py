"""
Configurare centrală. Toate cheile secrete se citesc din variabile de mediu
(niciodată scrise direct în cod) - se setează în Render, în tab-ul "Environment".
"""
import os

# --- Chei API (obligatorii) ---
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
FOOTBALL_DATA_API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# ID-ul chatului/canalului Telegram unde trimite botul semnalele.
# Se obține trimițând un mesaj botului și accesând:
# https://api.telegram.org/bot<TOKEN>/getUpdates
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- Setări generale ---
# Ligile analizate (coduri The Odds API). Poți adăuga/scoate.
LEAGUES = [
    "soccer_epl",              # Premier League
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
]

# Mapare cod football-data.org pentru fiecare ligă (pentru statistici formă/goluri)
FOOTBALL_DATA_COMPETITIONS = {
    "soccer_epl": "PL",
    "soccer_spain_la_liga": "PD",
    "soccer_italy_serie_a": "SA",
    "soccer_germany_bundesliga": "BL1",
    "soccer_france_ligue_one": "FL1",
}

# Câte meciuri recente să folosească pentru calculul mediei de goluri/cornere
FORM_MATCHES = 6

# Prag minim de "value" (diferență între probabilitatea modelului și cea implicită
# a cotei) ca să trimitem alertă. 0.05 = 5 puncte procentuale.
VALUE_THRESHOLD = 0.05

# La cât timp (minute) verifică botul meciurile din următoarele 48h
CHECK_INTERVAL_MINUTES = 60
