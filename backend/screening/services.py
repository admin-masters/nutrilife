from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

@dataclass
class RiskResult:
    level: str                 # "GREEN" | "AMBER" | "RED"
    red_flags: List[str]       # list of machine-friendly reasons

def _bmi(height_cm: Optional[float], weight_kg: Optional[float]) -> Optional[float]:
    if not height_cm or not weight_kg or height_cm <= 0:
        return None
    m = float(height_cm) / 100.0
    return float(weight_kg) / (m * m)

def compute_risk(
    age_years: Optional[float],
    gender: str,
    height_cm: Optional[float],
    weight_kg: Optional[float],
    answers: Dict[str, bool],
) -> RiskResult:
    """
    Simplified rules (replace with z-score lookups in a later sprint):
    - If BMI missing: AMBER (needs measurement)
    - If BMI below heuristic threshold => RED
    - If 2+ symptom answers TRUE => AMBER, if 3+ => RED
    - If diet_diversity_low TRUE => AMBER
    """
    reasons: List[str] = []
    bmi = _bmi(height_cm, weight_kg)
    symptoms = sum(1 for k, v in answers.items() if v and k.startswith("symptom_"))
    diet_low = answers.get("diet_diversity_low", False)

    # Heuristic BMI cutoffs: 6–10y <14.0; 11–14y <15.0; fallback <14.5
    if bmi is None:
        reasons.append("measurement_incomplete")
        level = "AMBER"
    else:
        cutoff = 14.5
        if age_years is not None:
            a = float(age_years)
            cutoff = 14.0 if a <= 10 else 15.0 if a <= 14 else 16.0
        if bmi < cutoff:
            reasons.append("bmi_low")

    if diet_low:
        reasons.append("diet_diversity_low")

    if symptoms >= 3:
        reasons.append("multiple_symptoms")
    elif symptoms >= 2:
        reasons.append("symptoms_present")

    # Decision
    level = "GREEN"
    if "bmi_low" in reasons or "multiple_symptoms" in reasons:
        level = "RED"
    elif "measurement_incomplete" in reasons or "diet_diversity_low" in reasons or "symptoms_present" in reasons:
        level = "AMBER"

    return RiskResult(level=level, red_flags=reasons)
