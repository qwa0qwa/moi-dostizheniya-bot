import re
from datetime import datetime

def normalize_text(value: str) -> str:
    value = (value or "").casefold().replace("ё", "е")
    value = re.sub(r"[^a-zа-я0-9]+", " ", value)
    return " ".join(value.split())

def parse_full_name(value: str):
    parts = (value or "").strip().split()
    if len(parts) not in (2, 3):
        return None
    return parts[0], parts[1], parts[2] if len(parts) == 3 else ""

def parse_birth_date(value: str) -> str | None:
    value = (value or "").strip()
    for fmt in ("%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None
