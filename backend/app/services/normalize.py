"""Stored normalization (ADR 0006) so matching is indexable."""
import re

COMPANY_SUFFIXES = {"llc", "inc", "corp", "corporation", "lp", "llp", "lllp", "ltd", "co", "company", "incorporated", "pllc"}
STREET = {"street": "st", "avenue": "ave", "boulevard": "blvd", "road": "rd", "drive": "dr", "lane": "ln", "highway": "hwy",
          "parkway": "pkwy", "court": "ct", "place": "pl", "circle": "cir", "way": "way", "north": "n", "south": "s",
          "east": "e", "west": "w", "suite": "ste"}


def norm_email(e: str | None) -> str | None:
    return e.strip().lower() if e and e.strip() else None


def norm_phone(p: str | None) -> str | None:
    if not p:
        return None
    digits = re.sub(r"\D", "", p)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return "+1" + digits
    return "+" + digits if len(digits) >= 8 else None


def norm_company_name(n: str | None) -> str:
    if not n:
        return ""
    s = re.sub(r"[^a-z0-9 ]", " ", n.lower().replace(".", ""))
    s = re.sub(r"\bl\s*l\s*c\b", "llc", s)
    toks = [t for t in s.split() if t not in COMPANY_SUFFIXES]
    return " ".join(toks)


def norm_domain(website: str | None) -> str | None:
    if not website:
        return None
    w = re.sub(r"^https?://", "", website.strip().lower())
    w = w.split("/")[0]
    return w[4:] if w.startswith("www.") else (w or None)


def norm_address(addr: str | None, city: str | None = None) -> str:
    s = (addr or "").lower()
    s = re.sub(r"\b(suite|ste|unit|#)\s*\w+\b", "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    toks = [STREET.get(t, t) for t in s.split()]
    out = " ".join(toks)
    if city:
        out += " " + re.sub(r"[^a-z0-9]", "", city.lower())
    return out.strip()


def norm_apn(apn: str | None) -> str | None:
    return re.sub(r"[^0-9a-z]", "", apn.lower()) if apn else None
