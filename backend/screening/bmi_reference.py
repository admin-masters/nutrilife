import json
from functools import lru_cache
from pathlib import Path
from typing import Dict, Tuple

_DATA_DIR = Path(__file__).resolve().parent / "data"
_BOYS_FILE = _DATA_DIR / "bmi_boys_5_18.json"
_GIRLS_FILE = _DATA_DIR / "bmi_girls_5_18.json"

@lru_cache(maxsize=2)
def _load_table(sex: str) -> Dict[float, Dict[str, float]]:
    sex = (sex or "").upper()
    path = _BOYS_FILE if sex == "M" else _GIRLS_FILE
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {float(k): {"median": float(v["median"]), "sd": float(v["sd"])} for k, v in raw.items()}

def nearest_age_key(age_years: float, sex: str) -> float:
    table = _load_table(sex)
    ages = sorted(table.keys())
    if age_years <= ages[0]:
        return ages[0]
    if age_years >= ages[-1]:
        return ages[-1]
    return min(ages, key=lambda a: abs(a - age_years))

def bmi_to_baz(*, bmi: float, age_years: float, sex: str) -> Tuple[float, float, float, float]:
    """
    BAZ = (BMI - median) / SD
    Returns: (baz, ref_age_used, median, sd)
    """
    ref_age = nearest_age_key(age_years, sex)
    ref = _load_table(sex)[ref_age]
    median = ref["median"]
    sd = ref["sd"]
    if sd <= 0:
        raise ValueError("Invalid SD in BMI reference table")
    baz = (float(bmi) - float(median)) / float(sd)
    return baz, ref_age, median, sd
