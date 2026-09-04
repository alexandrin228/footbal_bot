# Bot Telegram de analiză fotbal (cote + statistici)

Acest bot:
- ia automat cotele în timp real pentru meciurile din următoarele 48h (5 ligi mari europene, configurabil în `config.py`)
- calculează probabilități statistice (model Poisson) pentru 1X2, Over/Under goluri, BTTS și o estimare pentru cornere
- compară probabilitatea calculată cu cea implicită de cotă și trimite pe Telegram doar meciurile unde vede o diferență ("value bet")
- rulează în buclă, non-stop, o dată pe oră (configurabil)

⚠️ **Nu este un instrument care garantează câștig.** E o estimare statistică bazată pe forma recentă. Cotele bookmakerilor sunt de obicei foarte eficiente; folosește botul ca ajutor de decizie, nu ca adevăr absolut.

---

## Pasul 1 — Obții cele 3 chei necesare

1. **The Odds API** (cote): mergi pe https://the-odds-api.com/ → "Get API Key" → cont gratuit (500 cereri/lună). Copiezi cheia.
2. **football-data.org** (statistici meciuri): mergi pe https://www.football-data.org/client/register → cont gratuit → copiezi token-ul primit pe email.
3. **Bot Telegram**: în Telegram, cauți `@BotFather` → trimiți `/newbot` → alegi un nume și un username (trebuie să se termine în "bot") → primești un **token**.
4. **Chat ID**: trimiți orice mesaj botului tău nou creat, apoi accesezi în browser (înlocuind `<TOKEN>`):
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
   Cauți în răspuns `"chat":{"id": ...}` — acel număr e `TELEGRAM_CHAT_ID`.
   (Dacă vrei să trimită într-un canal/grup, adaugi botul acolo ca admin și folosești ID-ul grupului, de obicei negativ.)

## Pasul 2 — Urci codul pe GitHub

1. Creezi cont gratuit pe https://github.com dacă nu ai.
2. Creezi un repository nou (ex. `football-bot`), public sau privat.
3. Încarci toate fișierele din acest folder în repository (buton "Add file" → "Upload files" pe github.com, cel mai simplu, tragi fișierele direct).

## Pasul 3 — Deploy pe Render (gratuit)

1. Cont pe https://render.com (te poți loga direct cu GitHub).
2. "New" → "Background Worker" → alegi repository-ul `football-bot`.
3. La "Build Command": `pip install -r requirements.txt`
4. La "Start Command": `python main.py`
5. La secțiunea **Environment** adaugi variabilele:
   - `ODDS_API_KEY` = cheia de la pasul 1
   - `FOOTBALL_DATA_API_KEY` = token-ul de la pasul 1
   - `TELEGRAM_BOT_TOKEN` = token-ul botului
   - `TELEGRAM_CHAT_ID` = ID-ul obținut mai sus
6. "Create Background Worker" — Render instalează și pornește automat botul. Îl vezi rulând în tab-ul "Logs".

De acum botul verifică automat, non-stop, meciurile viitoare și trimite pe Telegram doar cele cu diferență clară între modelul propriu și cota pieței.

---

## Limitări actuale (de știut)

- **Cornerele**: planul gratuit football-data.org nu oferă statistici de cornere, deci momentan botul folosește o medie generică (10 cornere/meci) în loc de date reale per echipă. Pentru cornere reale ar trebui adăugată o sursă suplimentară (ex. API-Football via RapidAPI) — pot să te ajut să o integrezi quando ai nevoie.
- **Cartonașe**: nu sunt incluse încă în acest MVP; se pot adăuga ulterior cu aceeași metodă (medie recentă → Poisson).
- Modelul e simplu și transparent intenționat (Poisson pe medii recente) — e un punct de plecare solid, nu un model de nivel profesionist cu xG avansat, accidentări, motivație etc.
- The Odds API gratuit = 500 cereri/lună. La 5 ligi verificate o dată pe oră, poți depăși cota rapid — ajustează `CHECK_INTERVAL_MINUTES` sau numărul de ligi din `config.py` dacă vezi erori de limită.

## Cum modifici ușor botul

- Adaugi/scoți ligi: editezi listele `LEAGUES` și `FOOTBALL_DATA_COMPETITIONS` din `config.py`.
- Schimbi pragul de "value" (cât de mare trebuie să fie diferența ca să primești alertă): `VALUE_THRESHOLD` în `config.py`.
- Schimbi frecvența de verificare: `CHECK_INTERVAL_MINUTES` în `config.py`.
