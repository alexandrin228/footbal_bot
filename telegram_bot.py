"""Trimite mesajele formatate către chat-ul/canalul Telegram configurat."""
from datetime import datetime

import requests

import config

try:
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("Europe/Bucharest")
except Exception:
    _TZ = None

_LUNI_RO = [
    "ianuarie", "februarie", "martie", "aprilie", "mai", "iunie",
    "iulie", "august", "septembrie", "octombrie", "noiembrie", "decembrie",
]

_MODEL_LABELS = {"Formă": "Formă", "Elo": "Elo", "Piață": "Piață"}


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
    try:
        dt_utc = datetime.fromisoformat(iso_time.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(_TZ) if _TZ else dt_utc
        suffix = "" if _TZ else " UTC"
        return f"{dt_local.day} {_LUNI_RO[dt_local.month - 1]}, {dt_local.strftime('%H:%M')}{suffix}"
    except Exception:
        return iso_time


def _pct_row(label: str, value: float, width: int = 16) -> str:
    return f"{label:<{width}}{value * 100:>5.1f}%"


def _model_row(label: str, p: dict, width: int = 9) -> str:
    return f"{label:<{width}}{p['home']*100:>5.1f}% {p['draw']*100:>5.1f}% {p['away']*100:>5.1f}%"


def format_match_report(home: str, away: str, kickoff: str, probs: dict, value_bets: list) -> str:
    sep = "───────────────────"
    lines = [
        f"⚽ <b>{home} vs {away}</b>",
        f"🕒 {_format_kickoff(kickoff)}",
        sep,
    ]

    # --- secțiunea 1X2: ensemble de modele, dacă avem cel puțin 2 disponibile ---
    agreement = probs.get("agreement")
    lines.append("<b>📊 REZULTAT FINAL (1X2)</b>")
    if agreement and agreement.get("ensemble"):
        lines.append("<code>")
        lines.append(f"{'Model':<9}{'  1':>6} {'  X':>6} {'  2':>6}")
        for name, p in agreement["available"].items():
            lines.append(_model_row(_MODEL_LABELS.get(name, name), p))
        lines.append("───────────────")
        lines.append(_model_row("FINAL", agreement["ensemble"]))
        lines.append("</code>")
        lines.append(f"🧠 Acord modele: <b>{agreement['label']}</b> ({agreement['score']}/100)")
    else:
        # Fallback onest: mai puțin de 2 modele disponibile (ex. Elo indisponibil
        # pentru o echipă) - afișăm doar modelul de formă, fără să inventăm acord.
        lines.append("<code>")
        lines.append(_pct_row("1 (gazde)", probs["1x2"]["home"]))
        lines.append(_pct_row("X (egal)", probs["1x2"]["draw"]))
        lines.append(_pct_row("2 (oaspeți)", probs["1x2"]["away"]))
        lines.append("</code>")
        lines.append("<i>(doar model formă - Elo sau piață indisponibile pentru acest meci)</i>")

    lines.append(sep)
    lines.append("<b>⚽ GOLURI</b>")
    lines.append("<code>")
    for line, ou in probs["over_under"].items():
        lines.append(_pct_row(f"Peste {line}", ou["over"]))
    lines.append(_pct_row("BTTS Da", probs["btts"]["yes"]))
    lines.append("</code>")
    lines.append(
        f"Scor așteptat (model formă): <b>{probs['expected_goals']['home']} - {probs['expected_goals']['away']}</b>"
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
