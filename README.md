# Bot Telegram de analiză fotbal (ensemble de modele + Prediction Ledger)

Acest bot:
- ia automat cotele în timp real pentru meciurile din următoarele zile (5 ligi mari europene, configurabil în `config.py`)
- calculează 1X2 printr-un **ensemble de 3 modele independente** (formă/Poisson, Elo, piață de-vigged) + un scor de acord între ele
- calculează Over/Under, BTTS, cornere și cartonașe (cornere/cartonașe din date reale per echipă)
- compară probabilitatea finală cu cea implicită de cotă și trimite pe Telegram doar meciurile cu diferență clară ("value bet") - **o singură dată per meci**, nu repetat la fiecare verificare
- salvează fiecare predicție într-un **Prediction Ledger** persistent (chiar în acest repo GitHub - opțional), pe care îl reconciliază automat cu rezultatul real și trimite periodic (la 48h) un raport de performanță (Brier Score, hit rate, calibrare)
- rulează în buclă, non-stop, ca serviciu web gratuit pe Render

⚠️ **Nu este un instrument care garantează câștig.** E o estimare statistică. Cotele bookmakerilor sunt de obicei foarte eficiente; folosește botul ca ajutor de decizie, nu ca adevăr absolut.

---

## Pasul 1 — Obții cele 4 chei/token-uri necesare

(Sursele pentru cornere/cartonașe și Elo sunt complet gratuite și NU cer cont — nimic de făcut pentru ele.)

1. **The Odds API** (cote): https://the-odds-api.com/ → "Get API Key" → cont gratuit (500 cereri/lună).
2. **football-data.org** (formă, goluri): https://www.football-data.org/client/register → cont gratuit → token pe email.
3. **Bot Telegram**: în Telegram, `@BotFather` → `/newbot` → nume + username (termină în "bot") → primești un **token**.
4. **Chat ID**: trimiți un mesaj botului tău, apoi accesezi în browser `https://api.telegram.org/bot<TOKEN>/getUpdates` → cauți `"chat":{"id": ...}`.

## Pasul 2 — (Opțional, dar recomandat) Token GitHub pentru Prediction Ledger

Ca botul să-și amintească predicțiile între repornări (Render șterge orice altceva local), folosim chiar acest repo ca bază de date:

1. Link direct: https://github.com/settings/personal-access-tokens/new
2. **Repository access**: "Only select repositories" → alegi acest repo.
3. **Permissions** → **Contents** → **Read and write** (restul rămân "No access").
4. **Generate token** → copiezi codul (`github_pat_...`) - apare o singură dată.

⚠️ Ține acest token doar în Environment Variables pe Render, niciodată altundeva. Dacă crezi că a ajuns undeva nepotrivit, îl poți revoca și genera altul instant, gratuit, din aceeași pagină.

Fără acest pas, botul funcționează normal mai departe (analiză + alerte) - doar fără jurnal/raport de performanță, și cu deduplicarea anti-spam mai puțin robustă (vezi mai jos).

## Pasul 3 — Urci codul pe GitHub

Repository nou → încarci toate fișierele din acest folder ("Add file" → "Upload files").

## Pasul 4 — Deploy pe Render (gratuit, ca Web Service)

1. Cont pe https://render.com (login cu GitHub) → "New" → **"Web Service"** → alegi repository-ul.
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `python -u main.py`
4. **Instance Type**: Free
5. **Environment Variables**:
   - `ODDS_API_KEY`, `FOOTBALL_DATA_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
   - (opțional) `GITHUB_TOKEN`, `GITHUB_REPO` (format `user/repo`)
6. **Create Web Service**.

## Pasul 5 — Ping extern, ca să nu adoarmă

Planul gratuit Render "adoarme" un Web Service după ~15 minute fără trafic.
Cont gratuit pe https://cron-job.org → job nou → URL-ul public al botului → interval **10 minute**.

---

## De unde vin datele (5 surse, toate cu tier gratuit)

| Sursă | Ce oferă | Cont necesar? |
|---|---|---|
| The Odds API | Cote 1X2, Over/Under în timp real | Da (gratuit) |
| football-data.org | Rezultate recente, formă echipe, head-to-head | Da (gratuit) |
| football-data.co.uk | Cornere, cartonașe, șuturi, faulturi reale | **Nu** |
| clubelo.com | Rating Elo per echipă | **Nu** |
| GitHub (acest repo) | Stocare pentru Prediction Ledger (opțional) | Ai deja cont |

## Cum funcționează modelul

**1X2 = ensemble de 3 modele independente**:
- **Formă**: atac/apărare normalizate pe media ligii, ponderare pe recență, plus head-to-head.
- **Elo**: diferența de rating Elo (clubelo.com) transformată în goluri așteptate.
- **Piață**: cota bookmakerului, cu marja eliminată ("de-vigged").

Botul calculează un **scor de acord** (0-100) între cele 3. Dacă modelele sunt foarte împrăștiate, scorul scade drastic și probabilitatea finală e media lor, nu doar cifra celui mai optimist model - exact ca să evite un "edge" fals-mare când un singur model greșește izolat.

- **Over/Under, BTTS**: un singur model (Formă/Poisson) - nu există date gratuite pentru un al doilea model independent aici.
- **Cornere/cartonașe**: date reale per echipă; fallback la o medie generică (marcat transparent) dacă echipa nu se poate identifica în sursă.
- **Value bet**: probabilitatea finală depășește cu un prag (implicit 5pp) probabilitatea implicită a cotei. **Fiecare meci e alertat o singură dată** - dacă rămâne "value" la verificarea următoare, botul nu retrimite (deduplicare prin `id` unic per meci, ținută minte în timpul rulării + în Prediction Ledger dacă e configurat).

## Prediction Ledger (dacă ai configurat GITHUB_TOKEN)

Fiecare predicție cu value bet e salvată în `data/predictions.jsonl` din acest repo (vezi commit-urile). La ~3 ore după kickoff, botul caută scorul final și completează rezultatul real. La fiecare 48h, trimite pe Telegram un raport cu:
- **Brier Score** (1X2) - cât de bine calibrate sunt probabilitățile (0 = perfect, ~0.63 = ghicit la întâmplare)
- Hit rate Over/Under 2.5, BTTS, value bets
- Tabel de calibrare (probabilitate prezisă vs frecvență reală, pe intervale)

**Onest despre scop**: acesta e un jurnal simplu (o singură versiune per predicție, salvată înainte de kickoff) - nu ține versiuni V1/V2/V3 re-calculate aproape de meci, cum ar face un sistem profesionist. Cu puține meciuri (sub 50), cifrele din raport sunt orientative, nu concluzive statistic - botul spune asta explicit în fiecare raport.

## Ce NU face botul (onest, nu pot fi rezolvate fără date plătite)

- Nu știe despre accidentări, suspendări, oboseală din cupe europene, motivație, vreme, arbitru.
- Nu folosește xG real, doar goluri efectiv marcate. Nu există "model AI contextual" - ar însemna fie date inventate, fie mereu "neconfirmat".
- Head-to-head e limitat la sezonul curent.
- The Odds API gratuit = 500 cereri/lună; ajustează `CHECK_INTERVAL_MINUTES` sau numărul de ligi din `config.py` dacă vezi erori de limită.

## Cum modifici ușor botul

- Adaugi/scoți ligi: `LEAGUES`, `FOOTBALL_DATA_COMPETITIONS` și `FOOTBALL_DATA_CO_UK_DIVISIONS` din `config.py` (toate 3 împreună).
- Pragul de "value": `VALUE_THRESHOLD`. Frecvența de verificare: `CHECK_INTERVAL_MINUTES`. Meciuri recente pentru formă: `FORM_MATCHES`. Toate în `config.py`.
- Frecvența raportului de performanță: `REPORT_INTERVAL_HOURS` în `config.py`.
