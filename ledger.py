"""
Folosește chiar repo-ul GitHub al botului ca bază de date persistentă GRATUITĂ
(Render, planul gratuit, șterge orice fișier local la fiecare repornire - asta
ocolește limitarea, fără să coste nimic în plus).

Mecanism: GitHub Contents API (GET/PUT) citește și scrie direct un fișier JSON
în repo, ca un commit normal, vizibil în istoricul repo-ului. Necesită un
Personal Access Token fine-grained, limitat STRICT la acest repo, cu
permisiune doar "Contents: Read and write" (vezi README pentru pași).

Dacă GITHUB_TOKEN sau GITHUB_REPO nu sunt configurate, toate funcțiile de mai
jos devin "no-op" (nu fac nimic, nu blochează restul botului) - asta e o
funcționalitate OPȚIONALĂ; analiza + alertele Telegram merg normal fără ea.
"""
import base64
import json

import requests

import config

GITHUB_API_BASE = "https://api.github.com"


def is_configured() -> bool:
    return bool(config.GITHUB_TOKEN and config.GITHUB_REPO)


def _headers():
    return {
        "Authorization": f"Bearer {config.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_file(path: str):
    """Returnează (conținut_text, sha) sau (None, None) dacă fișierul nu există încă."""
    url = f"{GITHUB_API_BASE}/repos/{config.GITHUB_REPO}/contents/{path}"
    try:
        resp = requests.get(url, headers=_headers(), timeout=20)
        if resp.status_code == 404:
            return None, None
        resp.raise_for_status()
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        return content, data["sha"]
    except requests.RequestException as e:
        print(f"[ledger] Eroare la citirea {path} din GitHub: {e}")
        return None, None


def _put_file(path: str, content: str, sha, message: str) -> bool:
    url = f"{GITHUB_API_BASE}/repos/{config.GITHUB_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
    }
    if sha:
        payload["sha"] = sha
    try:
        resp = requests.put(url, headers=_headers(), json=payload, timeout=20)
        resp.raise_for_status()
        return True
    except requests.RequestException as e:
        print(f"[ledger] Eroare la scrierea {path} pe GitHub: {e}")
        return False


def _parse_jsonl(content: str) -> list:
    if not content:
        return []
    entries = []
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _to_jsonl(entries: list) -> str:
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n"


def read_predictions() -> list:
    """Citește tot registrul de predicții (Prediction Ledger)."""
    if not is_configured():
        return []
    content, _ = _get_file(config.LEDGER_PATH)
    return _parse_jsonl(content)


def sync_ledger(new_entries: list, reconciled_updates: dict) -> bool:
    """
    O SINGURĂ operație read-modify-write: adaugă predicții noi ȘI aplică
    rezultate pentru cele deja existente, într-un singur commit (ca să nu
    umplem istoricul repo-ului cu zeci de commit-uri mici pe oră).
    """
    if not is_configured():
        return False
    if not new_entries and not reconciled_updates:
        return False

    content, sha = _get_file(config.LEDGER_PATH)
    entries = _parse_jsonl(content)
    by_id = {e.get("id"): e for e in entries if e.get("id")}

    for match_id, result in reconciled_updates.items():
        if match_id in by_id:
            by_id[match_id]["result"] = result

    for entry in new_entries:
        if entry["id"] not in by_id:
            by_id[entry["id"]] = entry

    all_entries = sorted(by_id.values(), key=lambda e: e.get("kickoff", ""))
    message = f"Actualizare ledger: +{len(new_entries)} predicții noi, {len(reconciled_updates)} rezolvate"
    return _put_file(config.LEDGER_PATH, _to_jsonl(all_entries), sha, message)


def get_state() -> dict:
    """Citește starea mică a botului (ex. când a fost trimis ultimul raport)."""
    if not is_configured():
        return {}
    content, _ = _get_file(config.STATE_PATH)
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {}


def set_state(state: dict):
    if not is_configured():
        return
    _, sha = _get_file(config.STATE_PATH)
    _put_file(config.STATE_PATH, json.dumps(state, ensure_ascii=False, indent=2), sha, "Actualizare stare bot")
