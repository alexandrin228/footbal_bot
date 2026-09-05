"""Trimite mesajele formatate către chat-ul/canalul Telegram configurat."""
from datetime import datetime

import requests

import config

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Bucharest")
except Exception:
    _TZ = None  # dacă baza de date de fuse orare lipsește, afișăm ora UTC brută

_LUNI_RO = [
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
]


def send_message(text: str):
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("[telegram_bot] Lipsește TELEGRAM_BOT_TOKEN sau TELEGRAM_CHAT_ID.")
        return
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, data=payload, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[telegram_bot] Eroare la trimiterea mesajului: {e}")


def _format_kickoff(iso_time: str) -> str:
    """Transformă '2026-09-06T15:00:00Z' în '6 septembrie, 18:00 (ora RO/MD)'."""
    try:
        dt_utc = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(_TZ) if _TZ else dt_utc
        suffix = "" if _TZ else " UTC"
        return f"{dt_local.day} {_LUNI_RO[dt_local.month - 1]}, {dt_local.strftime('%H:%M')}{suffix}"
    except Exception:
        return iso_time  # fallback, ca botul să nu cadă dacă formatul e neașteptat


def _pct_row(label: str, value: float, width: int = 16) -> str:
    return f"{label:<{width}}{value * 100:>5.1f}%"


def format_match_report(home: str, away: str, kickoff: str, probs: dict, value_bets: list) -> str:
    sep = "───────────────────"
    lines = [
        f"⚽ <b>{home} vs {away}</b>",
        f"🕒 {_format_kickoff(kickoff)}",
        sep,
        "<b>📊 REZULTAT FINAL</b>",
        "<code>",
        _pct_row("1 (gazde)", probs["1x2"]["home"]),
        _pct_row("X (egal)", probs["1x2"]["draw"]),
        _pct_row("2 (oaspeți)", probs["1x2"]["away"]),
        "</code>",
        sep,
        "<b>⚽ GOLURI</b>",
        "<code>",
    ]
    for line, ou in probs["over_under"].items():
        lines.append(_pct_row(f"Peste {line}", ou["over"]))
    lines.append(_pct_row("BTTS Da", probs["btts"]["yes"]))
    lines.append("</code>")
    lines.append(
        f"Scor așteptat: <b>{probs['expected_goals']['home']} - {probs['expected_goals']['away']}</b>"
    )

    if "corners" in probs or "cards" in probs:
        lines.append(sep)
        lines.append("<b>🚩 CORNERE &amp; CARTONAȘE</b>")
        if "corners" in probs:
            c = probs["corners"]
            tag = "estimare generică" if c.get("estimated") else "date reale"
            lines.append(f"Cornere: ~{c['expected_corners']} <i>({tag})</i>")
        if "cards" in probs:
            k = probs["cards"]
            tag = "estimare generică" if k.get("estimated") else "date reale"
            lines.append(f"Cartonașe (echiv. galben): ~{k['expected_cards']} <i>({tag})</i>")

    lines.append(sep)
    if value_bets:
        lines.append("<b>🎯 VALUE BETS</b>")
        for vb in value_bets:
            lines.append(f"✅ <b>{vb['market']}</b> — cotă {vb['odds']}")
            lines.append(f"   Model {vb['model_prob']}% · Piață {vb['implied_prob']}% · Edge +{vb['edge_points']}pp")
    else:
        lines.append("Niciun edge clar față de cotele curente pe piețele analizate.")

    lines.append("")
    lines.append("⚠️ <i>Estimare statistică, nu garanție. Pariază responsabil.</i>")
    return "\n".join(lines)
