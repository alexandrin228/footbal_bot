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
