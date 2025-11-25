def mask_phone(p: str) -> str:
    if not p: return ""
    tail = p[-4:]
    return f"{'*'*(len(p)-4)}{tail}"
