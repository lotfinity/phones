"""Helpers for normalizing phone model names across marketplace text variants."""

import re

BRAND_PREFIXES = {
    "apple",
    "samsung",
    "xiaomi",
    "redmi",  # kept for plain Redmi rows below through model pattern handling
}


def ascii_fold(value):
    """Fold Turkish casing variants and common dotted-I variants for matching."""
    return (
        str(value or "")
        .replace("İ", "I")
        .replace("ı", "i")
        .replace("ş", "s")
        .replace("Ş", "S")
        .replace("ğ", "g")
        .replace("Ğ", "G")
        .replace("ü", "u")
        .replace("Ü", "U")
        .replace("ö", "o")
        .replace("Ö", "O")
        .replace("ç", "c")
        .replace("Ç", "C")
    )


def normalize_phone_model_key(brand_name, model_name):
    """Return a stable key for grouping equivalent PhoneModel rows.

    The key intentionally ignores casing, repeated brand prefixes, Turkish dotted-I,
    and common glued words such as `Promax`, `ProMax`, `Zflip`, `S21Fe`.
    """
    brand = ascii_fold(brand_name).lower().strip()
    text = ascii_fold(model_name).lower().strip()
    text = text.replace("+", " plus ")
    text = re.sub(r"(?<=\d)(fe)\b", r" \1", text)
    text = re.sub(r"(?<=\d)(pro|max|plus|ultra|mini)\b", r" \1", text)
    text = re.sub(r"promax", "pro max", text)
    text = re.sub(r"pro\s*max", "pro max", text)
    text = re.sub(r"z\s*flip", "z flip", text)
    text = re.sub(r"z\s*fold", "z fold", text)
    text = re.sub(r"note\s*", "note ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = text.split()

    # Drop repeated explicit brand tokens but keep product-family tokens like Redmi/Poco/Galaxy/iPhone.
    drop = {brand} if brand else set()
    if brand == "samsung":
        drop.add("samsung")
    if brand == "apple":
        drop.add("apple")
    if brand == "xiaomi":
        drop.add("xiaomi")

    tokens = [token for token in tokens if token not in drop]
    return brand, " ".join(tokens)


def canonical_phone_model_name(brand_name, model_name):
    """Format a readable canonical model name from a noisy marketplace model string."""
    brand, key = normalize_phone_model_key(brand_name, model_name)
    tokens = key.split()
    if not tokens:
        return str(model_name or "").strip()

    if tokens[0] == "iphone":
        out = ["iPhone"]
        for token in tokens[1:]:
            if token == "pro":
                out.append("Pro")
            elif token == "max":
                out.append("Max")
            elif token == "plus":
                out.append("Plus")
            elif token == "mini":
                out.append("mini")
            else:
                out.append(token.upper() if token == "se" else token)
        return " ".join(out)

    if tokens[0] == "galaxy":
        out = ["Galaxy"]
        for token in tokens[1:]:
            upper = token.upper()
            if re.fullmatch(r"s\d+", token):
                out.append(upper)
            elif re.fullmatch(r"a\d+", token):
                out.append(upper)
            elif token == "z":
                out.append("Z")
            elif token in {"fold", "flip", "note", "plus", "ultra", "fe"}:
                out.append(token.upper() if token == "fe" else token.title())
            else:
                out.append(token.title())
        return " ".join(out)

    if tokens[0] == "redmi":
        out = ["Redmi"]
        for token in tokens[1:]:
            if token == "note":
                out.append("Note")
            elif token == "pro":
                out.append("Pro")
            elif token == "plus":
                out.append("Plus")
            else:
                out.append(token.upper() if token in {"nfc"} else token.title())
        return " ".join(out)

    if tokens[0] == "poco":
        out = ["POCO"]
        out.extend(token.upper() if re.fullmatch(r"[a-z]\d+", token) else token.title() for token in tokens[1:])
        return " ".join(out)

    if tokens[0] == "pixel":
        return " ".join(["Pixel"] + [token.upper() if token == "pro" else token.title() for token in tokens[1:]])

    if tokens[0] == "oneplus":
        return " ".join(["OnePlus"] + [token.upper() if token in {"ce", "rt"} else token.title() for token in tokens[1:]])

    return " ".join(token.upper() if len(token) <= 2 and token.isalpha() else token.title() for token in tokens)
