"""Trimite mesajele formatate către chat-ul/canalul Telegram configurat."""
import requests
import config


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


def format_match_report(home: str, away: str, kickoff: str, probs: dict, value_bets: list) -> str:
    lines = [
        f"⚽ <b>{home} vs {away}</b>",
        f"🕒 {kickoff}",
        "",
        "<b>Probabilități model:</b>",
        f"1: {probs['1x2']['home']*100:.1f}%  X: {probs['1x2']['draw']*100:.1f}%  2: {probs['1x2']['away']*100:.1f}%",
    ]
    for line, ou in probs["over_under"].items():
        lines.append(f"Over {line}: {ou['over']*100:.1f}%  |  Under {line}: {ou['under']*100:.1f}%")
    lines.append(f"BTTS Da: {probs['btts']['yes']*100:.1f}%  |  BTTS Nu: {probs['btts']['no']*100:.1f}%")
    lines.append(
        f"Goluri așteptate: {probs['expected_goals']['home']} - {probs['expected_goals']['away']}"
    )

    if "corners" in probs:
        c = probs["corners"]
        lines.append(f"Cornere așteptate: ~{c['expected_corners']}")

    if value_bets:
        lines.append("")
        lines.append("🎯 <b>Posibile value bets</b> (probabilitate model &gt; probabilitate cotă):")
        for vb in value_bets:
            lines.append(
                f"• {vb['market']}: cotă {vb['odds']} "
                f"(model {vb['model_prob']}% vs piață {vb['implied_prob']}%, edge +{vb['edge_points']}pp)"
            )
    else:
        lines.append("")
        lines.append("Niciun edge clar față de cotele curente pe piețele analizate.")

    lines.append("")
    lines.append("⚠️ Estimare statistică, nu garanție. Pariază responsabil.")
    return "\n".join(lines)
