"""
Model statistic simplu bazat pe distribuția Poisson.

Ideea (metodă standard folosită și de casele de pariuri ca punct de plecare):
 1. Calculăm media de goluri marcate/încasate de fiecare echipă în meciurile
    recente (acasă/deplasare separat, dacă avem destule date).
 2. Combinăm cele două medii ca să estimăm câte goluri e probabil să marcheze
    fiecare echipă în acest meci (goluri așteptate = "expected goals", xG simplu).
 3. Folosim distribuția Poisson ca să transformăm acele medii în probabilități
    pentru fiecare scor posibil, apoi le însumăm pentru 1X2, Over/Under, BTTS.
 4. Același principiu (medie recentă -> Poisson) se aplică și la cornere.
 5. Comparăm probabilitatea modelului cu probabilitatea implicită a cotei
    (1 / cotă, ajustată de marja bookmakerului) ca să găsim "value".
"""
import math
from statistics import mean


def _poisson_pmf(k: int, lam: float) -> float:
    return (lam ** k) * math.exp(-lam) / math.factorial(k)


def team_average_goals(recent_matches: list, team_name: str, side: str = "any"):
    """
    side: "home", "away" sau "any" - dacă vrei media doar din meciurile de acasă/deplasare.
    Returnează (medie_marcate, medie_incasate).
    """
    scored, conceded = [], []
    name_lower = team_name.lower()
    for m in recent_matches:
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

    avg_scored = mean(scored) if scored else 1.2  # valoare implicită neutră
    avg_conceded = mean(conceded) if conceded else 1.2
    return avg_scored, avg_conceded


def expected_goals(home_scored, home_conceded, away_scored, away_conceded):
    """Combină atacul unei echipe cu apărarea celeilalte pentru golurile așteptate."""
    lam_home = (home_scored + away_conceded) / 2
    lam_away = (away_scored + home_conceded) / 2
    # limite de siguranță ca să evităm valori aberante din puține date
    lam_home = max(0.3, min(lam_home, 4.0))
    lam_away = max(0.3, min(lam_away, 4.0))
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


def corners_probability(avg_corners_total: float, line: float = 9.5):
    """Aceeași logică Poisson, aplicată la totalul de cornere din meci."""
    max_c = 25
    p_over = sum(_poisson_pmf(c, avg_corners_total) for c in range(math.ceil(line), max_c))
    return {"over": p_over, "under": 1 - p_over, "expected_corners": round(avg_corners_total, 2)}


def implied_probability(decimal_odds: float, margin_removal: bool = False) -> float:
    """Probabilitatea implicită de o cotă zecimală (fără ajustare de marjă, per cotă individuală)."""
    if not decimal_odds or decimal_odds <= 1:
        return 0.0
    return 1 / decimal_odds


def find_value(model_prob: float, market_odds: float, threshold: float) -> dict | None:
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
