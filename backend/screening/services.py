from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

from .bmi_reference import bmi_to_baz

@dataclass
class RiskResult:
    level: str                 # "GREEN" | "YELLOW" | "RED"
    flags: List[str]           # machine-friendly reasons
    derived: Dict[str, Any]    # computed metrics for storage/debug

def _bmi(height_cm: Optional[float], weight_kg: Optional[float]) -> Optional[float]:
    if height_cm is None or weight_kg is None:
        return None
    if float(height_cm) <= 0:
        return None
    m = float(height_cm) / 100.0
    return float(weight_kg) / (m * m)

def _muac_flag(muac_cm: Optional[float], age_months: Optional[int]) -> Optional[str]:
    # MUAC thresholds apply only for age 6–59 months per sheet
    if muac_cm is None or age_months is None:
        return None
    if age_months < 6 or age_months > 59:
        return None
    x = float(muac_cm)
    if x < 11.5:
        return "RED"
    if 11.5 <= x <= 12.5:
        return "YELLOW"
    return "GREEN"

def _baz_category(baz: float) -> Tuple[str, str]:
    # Sheet thresholds:
    # RED: < -3 (severe thinness), > +2 (obesity)
    # YELLOW: < -2 (thinness), > +1 (overweight)
    # GREEN: [-2, +1]
    if baz < -3:
        return "RED", "severe_thinness"
    if baz < -2:
        return "YELLOW", "thinness"
    if baz > 2:
        return "RED", "obesity"
    if baz > 1:
        return "YELLOW", "overweight"
    return "GREEN", "normal"

_HEALTH_REDFLAG_KEYS = [
    "health_general_poor",
    "health_pallor",
    "health_fatigue_dizzy_faint",
    "health_breathlessness",
    "health_frequent_infections",
    "health_chronic_cough_or_diarrhea",
    "health_visible_worms",
    "health_dental_or_gum_or_ulcers",
    "health_night_vision_difficulty",
    "health_bone_or_joint_pain",
]

def compute_risk(
    *,
    age_years: Optional[float],
    age_months: Optional[int],
    sex: str,  # "M" | "F" | "O"
    height_cm: Optional[float],
    weight_kg: Optional[float],
    muac_cm: Optional[float],
    answers: Dict[str, Any],
) -> RiskResult:
    """
    Overall status per sheet:

      GREEN:
        - BAZ between -2 and +1
        - No Section-C health red flags
        - Hunger = "Never true"
        - No diet/program flags

      YELLOW:
        - BAZ between -3 and -2 OR > +1
        - OR any diet/program flags

      RED:
        - BAZ < -3 OR > +2
        - OR any Section-C health red flags
        - OR Hunger Often/Sometimes true
        - OR heavy bleeding (girls)
    """
    flags: List[str] = []
    derived: Dict[str, Any] = {}

    # --- BMI + BAZ ---
    bmi = _bmi(height_cm, weight_kg)
    derived["bmi"] = bmi

    growth_level = "YELLOW"  # default when incomplete/unavailable
    if bmi is not None and age_years is not None and 5.0 <= float(age_years) <= 18.0 and (sex or "").upper() in {"M", "F"}:
        baz, ref_age, median, sd = bmi_to_baz(bmi=float(bmi), age_years=float(age_years), sex=(sex or "").upper())
        derived.update({"baz": baz, "bmi_ref_age_years": ref_age, "bmi_ref_median": median, "bmi_ref_sd": sd})

        # SD boundaries generated via loop (explicitly requested)
        derived["bmi_sd_boundaries"] = {z: float(median) + float(z) * float(sd) for z in (-3, -2, 1, 2)}

        growth_level, baz_cat = _baz_category(float(baz))
        derived["baz_category"] = baz_cat
        flags.append(f"baz_{baz_cat}")
    else:
        flags.append("baz_unavailable")

    # --- MUAC (6–59 months only) ---
    muac_level = _muac_flag(muac_cm, age_months)
    derived["muac_level"] = muac_level
    if muac_level in {"RED", "YELLOW"}:
        flags.append(f"muac_{muac_level.lower()}")

    # --- Section C: Quick Health Red Flags (any YES => RED) ---
    health_red = [k for k in _HEALTH_REDFLAG_KEYS if bool(answers.get(k))]

    if (answers.get("appetite") or "").upper() == "POOR":
        health_red.append("appetite_poor")

    # Adolescent girls (age >=10 only): heavy bleeding + irregular cycles
    if (sex or "").upper() == "F" and age_years is not None and float(age_years) >= 10.0:
        pads_per_day = answers.get("pads_per_day")
        bleeding_clots = bool(answers.get("bleeding_clots"))

        pads = None
        if pads_per_day is not None:
            try:
                pads = int(pads_per_day)
            except Exception:
                pads = None

        if (pads is not None and pads >= 5) or bleeding_clots:
            health_red.append("heavy_bleeding")

        cycle_length_days = answers.get("cycle_length_days")
        if cycle_length_days is not None:
            try:
                days = int(cycle_length_days)
            except Exception:
                days = None
            if days is not None and days > 45:
                health_red.append("irregular_cycles_gt_45")

    derived["health_red_flags"] = health_red

    # --- Section F: Food Security ---
    hunger = (answers.get("hunger_vital_sign") or "").upper()  # OFTEN_TRUE / SOMETIMES_TRUE / NEVER_TRUE
    derived["hunger_vital_sign"] = hunger
    food_security_red = hunger in {"OFTEN_TRUE", "SOMETIMES_TRUE"}
    if food_security_red:
        flags.append("food_insecurity")

    # --- Section D + E: Diet + Program (drives YELLOW) ---
    diet_flags = []
    diet_type = (answers.get("diet_type") or "").upper()  # LACTO_VEG / LACTO_OVO / NON_VEG
    derived["diet_type"] = diet_type

    if answers.get("breakfast_eaten") is False:
        diet_flags.append("breakfast_skipped")
    if answers.get("lunch_eaten") is False:
        diet_flags.append("lunch_skipped")

    def _flag_if_no(key: str, enabled: bool = True):
        if enabled and answers.get(key) is False:
            diet_flags.append(f"missing_{key}")

    _flag_if_no("green_leafy_veg")
    _flag_if_no("other_vegetables")
    _flag_if_no("fruits")
    _flag_if_no("dal_pulses_beans")

    # Conditional logic taken from the sheet:
    _flag_if_no("milk_curd", enabled=(diet_type in {"LACTO_VEG", "NON_VEG"}))
    _flag_if_no("egg", enabled=(diet_type in {"LACTO_OVO", "NON_VEG"}))
    _flag_if_no("fish_chicken_meat", enabled=(diet_type == "NON_VEG"))

    _flag_if_no("nuts_groundnuts")
    _flag_if_no("millet_whole_grains")

    # Negative check: YES => needs attention (sheet marks “Red Flag” on YES)
    if answers.get("ssb_or_packaged_snacks") is True:
        diet_flags.append("ssb_or_packaged_snacks")

    # Program enabler: deworming “No” => flag
    if answers.get("deworming_taken") is False:
        diet_flags.append("deworming_not_recent")

    derived["diet_flags"] = diet_flags
    flags.extend(diet_flags)

    # --- Final status decision ---
    if growth_level == "RED" or muac_level == "RED" or health_red or food_security_red:
        level = "RED"
    elif growth_level == "YELLOW" or muac_level == "YELLOW" or diet_flags or hunger != "NEVER_TRUE":
        level = "YELLOW"
    else:
        level = "GREEN"

    # Helpful debugging strings (kept in DB in Screening.red_flags)
    if derived.get("baz") is not None:
        flags.append(f"baz={derived['baz']:.2f}")
    if derived.get("bmi") is not None:
        flags.append(f"bmi={derived['bmi']:.1f}")

    return RiskResult(level=level, flags=flags, derived=derived)
