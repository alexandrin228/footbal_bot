"""
Model statistic bazat pe distribuția Poisson, cu îmbunătățiri față de versiunea
inițială (naivă):

 1. FORȚĂ RELATIVĂ LA MEDIA LIGII (metodă "Dixon-Coles-lite"): în loc să
    comparăm doar cele două echipe între ele, calculăm cât de mult atacă/apără
    fiecare echipă FAȚĂ DE MEDIA LIGII. O echipă care marchează 2 goluri/meci
    într-o ligă cu media 1.2 e mult mai periculoasă decât aceeași cifră
    într-o ligă cu media 3.0. Asta e o îmbunătățire reală, folosită și de
    modele profesioniste ca punct de plecare.
 2. PONDERARE PE RECENȚĂ: ultimele meciuri contează mai mult decât cele mai
    vechi (formă recentă > formă de acum 2 luni), printr-o "scădere
    exponențială" a importanței pe măsură ce ne depărtăm în timp.
 3. HEAD-TO-HEAD: dacă există cel puțin 2 meciuri directe în sezonul curent
    între cele două echipe, media lor de goluri e amestecată (cu pondere
    mică, ~15%) în calculul final.
 4. CORNERE ȘI CARTONAȘE REALE: calculate din date reale per echipă (sursă
    football-data.co.uk), cu aceeași ponderare pe recență - NU mai sunt o
    medie generică fixă, decât atunci când o echipă nu poate fi identificată
    în acea sursă (fallback automat, ca botul să nu se blocheze).

LIMITĂRI HONESTE (nu pot fi rezolvate fără date plătite):
 - Nu știe despre accidentări, suspendări, oboseală, motivație, meciuri
   europene în paralel, vreme, arbitru.
 - Nu folosește xG (expected goals) real - doar goluri efectiv marcate.
 - Head-to-head e limitat la sezonul curent (limitare a sursei gratuite).
 - Cornere/cartonașe depind de potrivirea numelui echipei între cele două
   surse de date; când potrivirea eșuează, se revine la o medie implicită.
"""
import math
from datetime import datetime, timezone

RECENCY_DECAY = 0.85    # cât de repede scade importanța meciurilor mai vechi
H2H_WEIGHT = 0.15       # cât cântărește istoricul direct în estimarea finală
DEFAULT_CORNERS_TOTAL = 10.0  # fallback dacă nu găsim echipa în sursa de cornere
DEFAULT_CARDS_TOTAL = 4.0     # fallback dacă nu găsim echipa în sursa de cartonașe


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def _weighted_avg(values: list, decay: float = RECENCY_DECAY) -> float:
    """Media ponderată, presupunând values[0] = cel mai recent meci."""
    if not values:
        return None
    weights = [decay ** i for i in range(len(values))]
    return sum(v * w for v, w in zip(values, weights)) / sum(weights)


def team_scored_conceded(matches: list, team_name: str, side: str = "any"):
    """
    Extrage listele (nu media încă) de goluri marcate/încasate pentru o echipă,
    păstrând ordinea cronologică (recent -> vechi), ca să putem pondera.
    side: "home", "away" sau "any".
    """
    scored, conceded = [], []
    name_lower = team_name.lower()
    for m in matches:  # matches e deja sortat recent -> vechi
        home_name = m["homeTeam"]["name"].lower()
        away_name = m["awayTeam"]["name"].lower()
        score = m.get("score", {}).get("fullTime", {})
        h_goals, a_goals = score.get("home"), score.get("away")
        if h_goals is None or a_goals is None:
            continue

        is_home = name_lower in home_name or home_name in name_lower
        if side == "home" and not is_home:
            continue
        if side == "away" and is_home:
            continue

        if is_home:
            scored.append(h_goals)
            conceded.append(a_goals)
        else:
            scored.append(a_goals)
            conceded.append(h_goals)

    return scored, conceded


def league_reference_averages(all_matches: list):
    """
    Media de goluri marcate de echipele-gazdă și de echipele-oaspete, la
    nivelul întregii ligi (folosită ca reper de normalizare - vezi Dixon-Coles).
    """
    home_goals, away_goals = [], []
    for m in all_matches:
        score = m.get("score", {}).get("fullTime", {})
        h, a = score.get("home"), score.get("away")
        if h is None or a is None:
            continue
        home_goals.append(h)
        away_goals.append(a)

    league_home_avg = sum(home_goals) / len(home_goals) if home_goals else 1.4
    league_away_avg = sum(away_goals) / len(away_goals) if away_goals else 1.1
    return league_home_avg, league_away_avg


def team_strength(matches: list, team_name: str, side: str, league_avg_for: float, league_avg_against: float):
    """
    Calculează "puterea de atac" și "puterea de apărare" a unei echipe,
    relativ la media ligii (1.0 = exact media ligii, 1.3 = atacă 30% mai
    mult decât media, 0.7 = apără 30% mai bine decât media, etc.)
    """
    scored, conceded = team_scored_conceded(matches, team_name, side=side)
    avg_scored = _weighted_avg(scored)
    avg_conceded = _weighted_avg(conceded)

    if avg_scored is None:
        avg_scored = league_avg_for
    if avg_conceded is None:
        avg_conceded = league_avg_against

    attack_strength = avg_scored / league_avg_for if league_avg_for else 1.0
    defense_strength = avg_conceded / league_avg_against if league_avg_against else 1.0
    return attack_strength, defense_strength


def head_to_head_avg_goals(h2h_matches: list, home_name: str, away_name: str):
    """Media de goluri marcate de fiecare echipă în meciurile directe (dacă există destule)."""
    if len(h2h_matches) < 2:
        return None, None

    home_goals, away_goals = [], []
    name_lower = home_name.lower()
    for m in h2h_matches:
        score = m.get("score", {}).get("fullTime", {})
        h, a = score.get("home"), score.get("away")
        if h is None or a is None:
            continue
        m_home = m["homeTeam"]["name"].lower()
        if name_lower in m_home or m_home in name_lower:
            home_goals.append(h)
            away_goals.append(a)
        else:
            home_goals.append(a)
            away_goals.append(h)

    if not home_goals:
        return None, None
    return sum(home_goals) / len(home_goals), sum(away_goals) / len(away_goals)


def expected_goals_v2(home_matches, away_matches, home_name, away_name,
                       league_home_avg, league_away_avg, h2h_matches=None):
    """
    Calculează golurile așteptate folosind puterea de atac/apărare normalizată
    pe media ligii, apoi amestecă (opțional) cu istoricul direct.
    """
    home_attack, home_defense = team_strength(home_matches, home_name, "home", league_home_avg, league_away_avg)
    away_attack, away_defense = team_strength(away_matches, away_name, "away", league_away_avg, league_home_avg)

    lam_home = home_attack * away_defense * league_home_avg
    lam_away = away_attack * home_defense * league_away_avg

    if h2h_matches:
        h2h_home, h2h_away = head_to_head_avg_goals(h2h_matches, home_name, away_name)
        if h2h_home is not None:
            lam_home = (1 - H2H_WEIGHT) * lam_home + H2H_WEIGHT * h2h_home
            lam_away = (1 - H2H_WEIGHT) * lam_away + H2H_WEIGHT * h2h_away

    # limite de siguranță ca să evităm valori aberante din puține date
    lam_home = max(0.3, min(lam_home, 4.5))
    lam_away = max(0.3, min(lam_away, 4.5))
    return lam_home, lam_away


def match_probabilities(lam_home: float, lam_away: float, max_goals: int = 8):
    """
    Construiește matricea de probabilități pentru fiecare scor posibil (Poisson
    independent pentru cele două echipe) și derivă din ea toate piețele cerute.
    """
    grid = {}
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            grid[(h, a)] = _poisson_pmf(h, lam_home) * _poisson_pmf(a, lam_away)

    p_home = sum(p for (h, a), p in grid.items() if h > a)
    p_draw = sum(p for (h, a), p in grid.items() if h == a)
    p_away = sum(p for (h, a), p in grid.items() if h < a)

    over_under = {}
    for line in [1.5, 2.5, 3.5]:
        p_over = sum(p for (h, a), p in grid.items() if h + a > line)
        over_under[line] = {"over": p_over, "under": 1 - p_over}

    p_btts_yes = sum(p for (h, a), p in grid.items() if h > 0 and a > 0)

    return {
        "1x2": {"home": p_home, "draw": p_draw, "away": p_away},
        "over_under": over_under,
        "btts": {"yes": p_btts_yes, "no": 1 - p_btts_yes},
        "expected_goals": {"home": round(lam_home, 2), "away": round(lam_away, 2)},
    }


def expected_total_corners(home_for: list, home_against: list, away_for: list, away_against: list) -> float:
    """
    Cornere totale așteptate în meci, combinând cornerele obținute de gazdă cu
    cele primite de oaspete (și invers) - aceeași logică drept ca la goluri,
    dar simplificată (fără normalizare pe media ligii, mai puțin relevantă
    pentru cornere). Revine la o valoare implicită dacă lipsesc date pentru o
    echipă (nepotrivire de nume între surse).
    """
    h_for = _weighted_avg(home_for)
    h_against = _weighted_avg(home_against)
    a_for = _weighted_avg(away_for)
    a_against = _weighted_avg(away_against)

    lam_home = (h_for + a_against) / 2 if (h_for is not None and a_against is not None) else DEFAULT_CORNERS_TOTAL / 2
    lam_away = (a_for + h_against) / 2 if (a_for is not None and h_against is not None) else DEFAULT_CORNERS_TOTAL / 2
    return round(lam_home + lam_away, 2)


def expected_total_cards(home_for: list, home_against: list, away_for: list, away_against: list) -> float:
    """Aceeași logică ca la cornere, aplicată cartonașelor (galben=1, roșu=2)."""
    h_for = _weighted_avg(home_for)
    h_against = _weighted_avg(home_against)
    a_for = _weighted_avg(away_for)
    a_against = _weighted_avg(away_against)

    lam_home = (h_for + a_against) / 2 if (h_for is not None and a_against is not None) else DEFAULT_CARDS_TOTAL / 2
    lam_away = (a_for + h_against) / 2 if (a_for is not None and h_against is not None) else DEFAULT_CARDS_TOTAL / 2
    return round(lam_home + lam_away, 2)


def corners_probability(avg_corners_total: float, line: float = 9.5, is_estimated: bool = False):
    """Distribuție Poisson pentru totalul de cornere din meci."""
    max_c = 25
    p_over = sum(_poisson_pmf(c, avg_corners_total) for c in range(math.ceil(line), max_c))
    return {
        "over": p_over,
        "under": 1 - p_over,
        "expected_corners": round(avg_corners_total, 2),
        "estimated": is_estimated,  # True = medie generică (nu am găsit echipa în sursă)
    }


def cards_probability(avg_cards_total: float, line: float = 4.5, is_estimated: bool = False):
    """Distribuție Poisson pentru totalul de cartonașe (galben=1pt, roșu=2pt) din meci."""
    max_c = 15
    p_over = sum(_poisson_pmf(c, avg_cards_total) for c in range(math.ceil(line), max_c))
    return {
        "over": p_over,
        "under": 1 - p_over,
        "expected_cards": round(avg_cards_total, 2),
        "estimated": is_estimated,
    }


def implied_probability(decimal_odds: float) -> float:
    """Probabilitatea implicită de o cotă zecimală (fără ajustare de marjă, per cotă individuală)."""
    if not decimal_odds or decimal_odds <= 1:
        return 0.0
    return 1 / decimal_odds


def find_value(model_prob: float, market_odds: float, threshold: float):
    """
    Compară probabilitatea modelului cu cea implicită de cotă.
    Returnează detalii doar dacă diferența depășește pragul (posibil "value bet").
    """
    if not market_odds:
        return None
    implied = implied_probability(market_odds)
    edge = model_prob - implied
    if edge >= threshold:
        return {
            "model_prob": round(model_prob * 100, 1),
            "implied_prob": round(implied * 100, 1),
            "edge_points": round(edge * 100, 1),
            "odds": market_odds,
        }
    return None


# =============================================================================
# ENSEMBLE: 3 modele independente pentru 1X2 (formă, Elo, piață) + acord
#
# ONESTITATE IMPORTANTĂ: nu există date gratuite reale pentru xG, accidentări,
# formații sau un "model AI contextual" - orice ar afișa asemenea module ar fi
# fie inventat, fie mereu "NECONFIRMAT". De-aia ensemble-ul de mai jos are
# 3 modele, nu 5: sunt singurele calculabile din date reale, verificabile,
# fără cost. Modelul "Formă" NU e xG real (doar goluri efectiv marcate).
# =============================================================================

ELO_HOME_ADVANTAGE = 60     # puncte Elo bonus pentru echipa gazdă (convenție comună)
ELO_GOALS_PER_POINT = 250   # aproximare: ~250 puncte Elo diferență ≈ 1 gol diferență
                            # așteptată. E o aproximare rezonabilă din practica
                            # open-source, NU o constantă oficială universală -
                            # poate fi ajustată ulterior, pe măsură ce acumulați
                            # rezultate reale de comparat.


def elo_model_probabilities(elo_home: float, elo_away: float, league_total_avg: float, max_goals: int = 8):
    """
    MODEL B (Elo): transformă diferența de rating Elo într-o supremație de
    goluri așteptată, apoi o combină cu media totală de goluri a ligii ca să
    obțină goluri așteptate separate pentru fiecare echipă, rulate prin
    aceeași distribuție Poisson. Returnează None dacă lipsește Elo-ul uneia
    dintre echipe (nu ghicim).
    """
    if elo_home is None or elo_away is None:
        return None
    goal_diff = ((elo_home + ELO_HOME_ADVANTAGE) - elo_away) / ELO_GOALS_PER_POINT
    base = league_total_avg / 2
    lam_home = max(0.3, min(base + goal_diff / 2, 4.5))
    lam_away = max(0.3, min(base - goal_diff / 2, 4.5))
    return match_probabilities(lam_home, lam_away, max_goals=max_goals)["1x2"]


def market_devigged_probabilities(home_odds: float, draw_odds: float, away_odds: float):
    """
    MODEL C (Piață): elimină marja bookmakerului (overround), împărțind
    proporțional între cele 3 rezultate posibile, ca probabilitățile să
    însumeze exact 100%. Returnează None dacă lipsește vreo cotă.
    """
    if not (home_odds and draw_odds and away_odds):
        return None
    raw = {"home": 1 / home_odds, "draw": 1 / draw_odds, "away": 1 / away_odds}
    total = sum(raw.values())  # > 1.0 din cauza marjei bookmakerului
    if total <= 0:
        return None
    return {k: v / total for k, v in raw.items()}


def ensemble_agreement(models: dict):
    """
    Primește un dict {nume_model: {"home":.., "draw":.., "away":..} sau None}.
    Calculează media modelelor DISPONIBILE (probabilitatea finală afișată) și
    un scor de acord (0-100) bazat pe cât de împrăștiate sunt estimările lor
    de victorie a gazdelor. Puține modele disponibile = acord marcat explicit
    ca nedeterminabil, nu inventat.
    """
    available = {name: p for name, p in models.items() if p is not None}
    if len(available) < 2:
        return {"available": available, "ensemble": None, "score": None, "label": "DATE INSUFICIENTE"}

    ensemble = {
        outcome: sum(p[outcome] for p in available.values()) / len(available)
        for outcome in ("home", "draw", "away")
    }

    home_values = [p["home"] for p in available.values()]
    mean_h = sum(home_values) / len(home_values)
    variance = sum((v - mean_h) ** 2 for v in home_values) / len(home_values)
    std_dev = variance ** 0.5

    score = max(0, min(100, round(100 - std_dev * 500)))
    if score >= 90:
        label = "FOARTE RIDICAT"
    elif score >= 75:
        label = "RIDICAT"
    elif score >= 60:
        label = "MODERAT"
    elif score >= 40:
        label = "SCĂZUT"
    else:
        label = "FOARTE SCĂZUT"

    return {"available": available, "ensemble": ensemble, "score": score, "label": label}


# =============================================================================
# PREDICTION LEDGER: construire intrare, reconciliere cu rezultatul real,
# raport de performanță (Brier Score, hit rate, calibrare)
# =============================================================================

def build_ledger_entry(match_id: str, league: str, home: str, away: str, kickoff: str,
                        final_1x2: dict, agreement: dict, probs: dict, value_bets: list) -> dict:
    """Construiește intrarea de jurnal pentru o predicție nouă, ÎNAINTE de kickoff."""
    return {
        "id": match_id,
        "league": league,
        "home": home,
        "away": away,
        "kickoff": kickoff,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "prediction": {
            "1x2": {k: round(v, 4) for k, v in final_1x2.items()},
            "agreement_score": agreement.get("score"),
            "agreement_label": agreement.get("label"),
            "over_2.5": round(probs["over_under"][2.5]["over"], 4),
            "btts_yes": round(probs["btts"]["yes"], 4),
            "expected_goals": probs["expected_goals"],
        },
        "value_bets": value_bets,
        "result": None,
    }


def compute_actual_outcomes(home: str, away: str, home_goals: int, away_goals: int, value_bets: list) -> dict:
    """La final de meci: transformă scorul real în rezultate verificabile per piață."""
    if home_goals > away_goals:
        actual_1x2 = "home"
    elif home_goals < away_goals:
        actual_1x2 = "away"
    else:
        actual_1x2 = "draw"

    actual_over_2_5 = (home_goals + away_goals) > 2.5
    actual_btts = home_goals > 0 and away_goals > 0

    hits = []
    for vb in value_bets:
        market = vb["market"]
        if market == f"Victorie {home}":
            hit = actual_1x2 == "home"
        elif market == f"Victorie {away}":
            hit = actual_1x2 == "away"
        elif market == "Egal":
            hit = actual_1x2 == "draw"
        elif market == "Over 2.5 goluri":
            hit = actual_over_2_5
        elif market == "BTTS Da":
            hit = actual_btts
        else:
            hit = None
        hits.append({"market": market, "hit": hit})

    return {
        "final_score": {"home": home_goals, "away": away_goals},
        "actual_1x2": actual_1x2,
        "actual_over_2.5": actual_over_2_5,
        "actual_btts": actual_btts,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
        "value_bets_hit": hits,
    }


def performance_report(entries: list) -> dict:
    """
    Calculează Brier Score, hit rate per piață și un tabel simplu de calibrare
    din predicțiile deja REZOLVATE (cu rezultat real cunoscut). Cu puține
    meciuri, semnalează explicit că rezultatele sunt premature - nu ascunde
    incertitudinea statistică din spatele unei cifre aparent precise.
    """
    resolved = [e for e in entries if e.get("result")]
    n = len(resolved)
    if n == 0:
        return {"n": 0}

    brier_sum = 0.0
    ou_correct = ou_total = 0
    btts_correct = btts_total = 0
    value_hits = value_total = 0
    bins = {i: {"count": 0, "sum_pred": 0.0, "hits": 0} for i in range(0, 100, 10)}

    for e in resolved:
        pred = e["prediction"]["1x2"]
        res = e["result"]
        actual = res["actual_1x2"]

        for outcome in ("home", "draw", "away"):
            indicator = 1.0 if outcome == actual else 0.0
            brier_sum += (pred[outcome] - indicator) ** 2

        ou_total += 1
        if (e["prediction"]["over_2.5"] >= 0.5) == res["actual_over_2.5"]:
            ou_correct += 1

        btts_total += 1
        if (e["prediction"]["btts_yes"] >= 0.5) == res["actual_btts"]:
            btts_correct += 1

        for vb_hit in res.get("value_bets_hit", []):
            if vb_hit["hit"] is not None:
                value_total += 1
                if vb_hit["hit"]:
                    value_hits += 1

        top_outcome = max(pred, key=pred.get)
        top_prob = pred[top_outcome]
        bucket = min(90, int(top_prob * 100) // 10 * 10)
        bins[bucket]["count"] += 1
        bins[bucket]["sum_pred"] += top_prob
        if top_outcome == actual:
            bins[bucket]["hits"] += 1

    calibration = []
    for bucket in sorted(bins):
        data = bins[bucket]
        if data["count"] == 0:
            continue
        calibration.append({
            "range": f"{bucket}-{bucket+10}%",
            "n": data["count"],
            "predicted_avg": round(data["sum_pred"] / data["count"] * 100, 1),
            "actual_freq": round(data["hits"] / data["count"] * 100, 1),
        })

    return {
        "n": n,
        "brier_score": round(brier_sum / n, 4),
        "over_2_5_hit_rate": round(ou_correct / ou_total * 100, 1) if ou_total else None,
        "btts_hit_rate": round(btts_correct / btts_total * 100, 1) if btts_total else None,
        "value_bet_hit_rate": round(value_hits / value_total * 100, 1) if value_total else None,
        "value_bet_count": value_total,
        "calibration": calibration,
    }
