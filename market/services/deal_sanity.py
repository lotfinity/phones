"""LLM-based deal sanity checker using NVIDIA Vision API.

Reuses the same API call pattern as market.parsers.ocr_backend.NvidiaVisionBackend
but with a deal-audit prompt and structured JSON output.
"""

import base64
import json
import mimetypes
import re
from pathlib import Path

from django.conf import settings

# ── Red-flag words/phrases to detect from image text or freeform description ──
RED_FLAG_PATTERNS = [
    r"afficheur",
    r"écran\s*inconnu",
    r"écran\s+unknown",
    r"pièces?\s+et\s+r[ée]paration",
    r"parts?\s*[&a]\s*service",
    r"repair\s+information\s+section",
    r"repair\s+(status|info|history|screen|section)",
    r"parts?\s+and\s+service",
    r"display\s+changed",
    r"screen\s+replaced",
    r"repaired",
    r"r[ée]paration",
    r"\bdemo\b",
    r"showcase",
    r"vitrine",
    r"non[- ]?original",
    r"unknown\s+part",
    r"face\s*id\s+(issue|problem|not|missing)",
    r"true\s*tone\s+(issue|problem|not|missing)",
    r"\bcycles?\b",  # battery cycles
    r"مستعمل",  # Arabic: used
    r"مستعم\s*ل",  # Arabic: used (variant)
    r".statut.*batterie",  # French battery status
    r"battery\s+health",
    r"prix\s+\d+",  # Prix followed by number
]
_RED_FLAG_RE = re.compile("|".join(RED_FLAG_PATTERNS), re.IGNORECASE)


def extract_red_flags(text):
    """Extract red-flag matches from text. Skips negated mentions."""
    if not text:
        return []
    flags = set()
    for match in _RED_FLAG_RE.finditer(text):
        flag = match.group(0).lower().strip()
        # Get surrounding context (250 chars before the match)
        start = max(0, match.start() - 250)
        context = text[start:match.start()].lower()
        # Skip negated mentions
        negations = ["no ", "not ", "without ", "don't see ", "doesn't appear ",
                     "no visible ", "no mention ", "not visible ", "not detected ",
                     "not present ", "no sign of ", "didn't find ",
                     "no visible information that suggests",
                     "does not appear to be"]
        if any(neg in context for neg in negations):
            continue
        flags.add(flag)
    return list(flags)


# ── Deal text block (shared by all prompts) ──────────────────────────────────

def _build_deal_text_block(deal):
    """Build the text portion of the audit prompt from a DealSnapshot."""
    lines = [
        f"Brand: {deal.brand_name}",
        f"Model: {deal.model_name}",
        f"Storage: {deal.storage_gb or 'unknown'} GB",
        f"Listing title: {deal.title}",
        f"Condition: {deal.condition or 'unknown'}",
        f"Source: {deal.source_name or deal.source_code or 'unknown'}",
        f"Price (EUR): {deal.price_eur}",
        f"Margin: {deal.margin_pct:.1f}% (EUR {deal.margin_eur})",
        f"Sahibinden matches: {deal.sah_count}",
        f"Sahibinden median (EUR): {deal.sah_median_eur}",
        f"Listing URL: {deal.listing_url or '(missing)'}",
    ]
    if deal.sah_urls:
        lines.append(f"Sahibinden reference URLs: {', '.join(deal.sah_urls[:3])}")
    return "\n".join(lines)


# ── Verdict prompt (text-only audit) ─────────────────────────────────────────

def _build_prompt(deal, structured_vision=None, freeform_text=None, red_flags=None):
    """Full text prompt for the LLM. Optionally includes vision context."""
    deal_text = _build_deal_text_block(deal)
    vision_block = ""
    if structured_vision:
        vision_block += "\nStructured image inspection:\n"
        vision_block += json.dumps(structured_vision, indent=2) + "\n"
    if freeform_text:
        vision_block += f"\nFree-form image description:\n{freeform_text}\n"
    if red_flags:
        vision_block += f"\nRed-flag words detected in image/text: {', '.join(red_flags)}\n"

    return (
        "You are a market analyst auditing phone resale deals in Algeria.\n"
        "A deal was found by matching an Algeria listing against Türkiye market prices.\n"
        "Your job is to judge whether the deal looks BELIEVABLE or SUSPICIOUS.\n\n"
        "Deal data:\n"
        f"{deal_text}\n"
        f"{vision_block}\n"
        "Scoring rules:\n"
        "- margin > 50% is suspicious unless well-evidenced (sah_count >= 5)\n"
        "- sah_count <= 2 means weak Türkiye evidence\n"
        "- Budget phones (Redmi, low-end) at huge margins are suspicious\n"
        "- New/rare models (Z Fold 7, iPhone 17) with few matches may have stale medians\n"
        "- Unknown condition is a risk factor\n"
        "- Missing listing URL or image is a risk factor\n"
        "- Price_eur far below sah_median_eur is suspicious (too cheap)\n"
        "- Afficheur/display/demo unit = reject or watch (not a normal consumer phone)\n"
        "- Écran inconnu / screen replaced / repaired = watch or reject\n"
        "- مستعمل (used) in text = watch if listing claims sealed/new\n"
        "- Non-original parts mentioned = reject\n\n"
        "CRITICAL RULE: Do NOT question whether a phone model exists or is real.\n"
        "The deal data comes from our catalog matching system. If the model is listed,\n"
        "it is valid. Do NOT reject based on 'not a real model' or 'future model' or\n"
        "'Apple has not released this'. Only flag model mismatch if the image/text\n"
        "clearly shows a DIFFERENT model than what the deal claims.\n\n"
        "Return ONLY valid JSON with these fields:\n"
        '{"verdict": "keep" | "watch" | "reject", '
        '"confidence": <0-100>, '
        '"reasons": ["short reason 1", "short reason 2", ...], '
        '"recommended_action": "short action sentence"}\n\n'
        "Verdict guide:\n"
        "- keep: deal looks plausible, proceed\n"
        "- watch: plausible but needs manual verification\n"
        "- reject: likely bad data, unrealistic pricing, or matching error\n\n"
        "CRITICAL: Return ONLY a single JSON object. No markdown. No code fences. "
        "No explanation before or after. Just the raw JSON."
    )


# ── Image fetch ──────────────────────────────────────────────────────────────

def _fetch_image_bytes(image_path_str):
    """Read image from local path or fetch from URL. Returns (bytes, mime_type) or (None, None)."""
    if not image_path_str:
        return None, None
    try:
        p = Path(image_path_str)
        if p.exists() and p.is_file():
            mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
            return p.read_bytes(), mime
    except (OSError, ValueError):
        pass
    # Try as URL
    if image_path_str.startswith("http://") or image_path_str.startswith("https://"):
        try:
            import requests
            resp = requests.get(image_path_str, timeout=15)
            resp.raise_for_status()
            mime = resp.headers.get("Content-Type", "image/jpeg").split(";")[0].strip()
            return resp.content, mime
        except Exception:
            return None, None
    return None, None


# ── Structured vision inspection ─────────────────────────────────────────────

def _build_vision_inspection_prompt(deal):
    """Prompt for inspecting listing image physical condition."""
    deal_text = _build_deal_text_block(deal)
    return (
        "You are inspecting a phone listing image for physical condition and authenticity.\n"
        "Analyze the image carefully and report what you see.\n\n"
        "Deal context:\n"
        f"{deal_text}\n\n"
        "IMPORTANT: Inspect ALL parts of the image:\n"
        "1. MAIN PRODUCT: the phone or box in the center\n"
        "2. BLACK OVERLAY TEXT: text overlaid on the image (often white/red on black)\n"
        "3. CIRCULAR INSET IMAGES: small round/square insets showing settings, repair screens, etc.\n"
        "4. PRICE/CYCLES TEXT: any price tags, cycle counts, battery health indicators\n"
        "5. ARABIC/FRENCH TEXT: مستعمل, afficheur, écran inconnu, pièces et réparation, etc.\n"
        "6. SETTINGS SCREENSHOTS: iOS settings screens showing battery, parts, display info\n"
        "7. REPAIR/PARTS SCREENS: screens mentioning display replacement, unknown parts\n\n"
        "Look for these specific red-flag indicators:\n"
        "- مستعمل = used (Arabic)\n"
        "- Afficheur = display/demo unit (French)\n"
        "- Écran inconnu = unknown/replaced display (French)\n"
        "- Pièces et réparation = parts and repair history (French)\n"
        "- Cycles = battery cycle count\n"
        "- Prix = price\n"
        "- Any iOS settings screen showing 'Unknown Part' or 'Display'\n\n"
        "For damage fields: ONLY report damage you can ACTUALLY SEE.\n"
        "If unsure, say \"unknown\". Do NOT guess.\n\n"
        "Return ONLY valid JSON with these fields:\n"
        '{'
        '"visible_product": true|false, '
        '"device_type": "phone"|"box"|"unknown", '
        '"condition_visible": "sealed"|"boxed"|"used"|"damaged"|"unknown", '
        '"screen_damage": "none"|"minor"|"major"|"unknown", '
        '"body_damage": "none"|"minor"|"major"|"unknown", '
        '"back_damage": "none"|"minor"|"major"|"unknown", '
        '"camera_damage": "none"|"minor"|"major"|"unknown", '
        '"scratches_or_scuffs": "none"|"minor"|"major"|"unknown", '
        '"box_or_accessories_visible": "yes"|"no"|"unknown", '
        '"model_text_visible": "short text or empty string", '
        '"all_visible_text": "ALL text you can read from the image, any language, including overlay text, inset text, Arabic, French, price, cycles", '
        '"overlay_text": "all black overlay / overlaid text visible on the image", '
        '"inset_text": "text visible in any circular or square inset images", '
        '"visible_notes": ["short factual observation 1", "short factual observation 2"], '
        '"vision_confidence": <0-100>'
        '}\n\n'
        "CRITICAL: Return ONLY a single JSON object. No markdown. No code fences. "
        "No explanation before or after. Just the raw JSON."
    )


def _parse_vision_inspection(raw_text):
    """Parse JSON vision inspection from LLM response. Returns dict or fallback."""
    fallback = {
        "visible_product": False,
        "device_type": "unknown",
        "condition_visible": "unknown",
        "screen_damage": "unknown",
        "body_damage": "unknown",
        "back_damage": "unknown",
        "camera_damage": "unknown",
        "scratches_or_scuffs": "unknown",
        "box_or_accessories_visible": "unknown",
        "model_text_visible": "",
        "all_visible_text": "",
        "overlay_text": "",
        "inset_text": "",
        "visible_notes": ["Failed to parse vision response"],
        "vision_confidence": 0,
    }
    if not raw_text:
        return fallback

    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Attempt 1: direct JSON parse
    try:
        data = json.loads(text)
        return _validate_vision(data, fallback)
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract JSON object via regex
    json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return _validate_vision(data, fallback)
        except json.JSONDecodeError:
            pass

    # Attempt 3: markdown code block
    json_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block:
        try:
            data = json.loads(json_block.group(1))
            return _validate_vision(data, fallback)
        except json.JSONDecodeError:
            pass

    # Attempt 4: heuristic from markdown
    notes = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            notes.append(line[2:].strip())
    fallback["visible_notes"] = notes[:3] if notes else ["Vision model returned non-JSON response"]
    fallback["all_visible_text"] = text[:500]
    return fallback


def _validate_vision(data, fallback):
    """Validate and normalize a parsed vision inspection dict."""
    valid_severity = ("none", "minor", "major", "unknown")
    valid_device = ("phone", "box", "unknown")
    valid_cond = ("sealed", "boxed", "used", "damaged", "unknown")

    result = dict(fallback)
    result["visible_product"] = bool(data.get("visible_product", False))
    dt = data.get("device_type", "unknown")
    result["device_type"] = dt if dt in valid_device else "unknown"
    cv = data.get("condition_visible", "unknown")
    result["condition_visible"] = cv if cv in valid_cond else "unknown"
    for field in ("screen_damage", "body_damage", "back_damage", "camera_damage", "scratches_or_scuffs"):
        val = data.get(field, "unknown")
        result[field] = val if val in valid_severity else "unknown"
    bov = data.get("box_or_accessories_visible", "unknown")
    result["box_or_accessories_visible"] = bov if bov in ("yes", "no", "unknown") else "unknown"
    result["model_text_visible"] = str(data.get("model_text_visible", ""))[:200]
    result["all_visible_text"] = str(data.get("all_visible_text", ""))[:500]
    result["overlay_text"] = str(data.get("overlay_text", ""))[:300]
    result["inset_text"] = str(data.get("inset_text", ""))[:300]
    notes = data.get("visible_notes", [])
    if not isinstance(notes, list):
        notes = [str(notes)]
    result["visible_notes"] = [str(n)[:120] for n in notes[:5]]
    try:
        result["vision_confidence"] = max(0, min(100, int(data.get("vision_confidence", 0))))
    except (TypeError, ValueError):
        result["vision_confidence"] = 0
    return result


def inspect_deal_image(deal, image_bytes=None, mime_type=None):
    """Inspect a deal's listing image for physical condition. Returns structured vision dict."""
    prompt = _build_vision_inspection_prompt(deal)
    raw_text, error = _call_nvidia_vision(prompt, image_bytes, mime_type, max_tokens=768)
    if error:
        return {
            "visible_product": False,
            "device_type": "unknown",
            "condition_visible": "unknown",
            "screen_damage": "unknown",
            "body_damage": "unknown",
            "back_damage": "unknown",
            "camera_damage": "unknown",
            "scratches_or_scuffs": "unknown",
            "box_or_accessories_visible": "unknown",
            "model_text_visible": "",
            "all_visible_text": "",
            "overlay_text": "",
            "inset_text": "",
            "visible_notes": [error],
            "vision_confidence": 0,
        }
    return _parse_vision_inspection(raw_text)


# ── Free-form vision description ─────────────────────────────────────────────

def _build_freeform_vision_prompt(deal):
    """Prompt for free-form image description — no JSON constraint."""
    deal_text = _build_deal_text_block(deal)
    return (
        "Look at this phone listing image. Here is the deal info:\n\n"
        f"{deal_text}\n\n"
        "Inspect ALL parts of the image thoroughly:\n"
        "1. MAIN PRODUCT: the phone or box in the center\n"
        "2. BLACK OVERLAY TEXT: any text overlaid on the image (white/red text on dark background)\n"
        "3. CIRCULAR/SQUARE INSET IMAGES: small insets showing iOS settings, battery, repair info\n"
        "4. PRICE AND CYCLES: any price tags, cycle counts, battery health numbers\n"
        "5. ALL TEXT in ANY language — Arabic (مستعمل), French (afficheur, écran inconnu, réparation), English\n\n"
        "Describe EVERYTHING you see:\n"
        "- Phone color, model, condition, any visible damage\n"
        "- ALL visible text — quote it exactly, including Arabic and French\n"
        "- Whether it looks new, used, sealed, display/demo, repaired\n"
        "- Whether there are circular insets showing iOS settings or repair screens\n"
        "- Any mention of battery cycles, display status, unknown parts\n"
        "- Anything suspicious or mismatched with the deal data\n\n"
        "Do NOT repeat these instructions back. Just describe the image."
    )


def inspect_deal_image_freeform(deal, image_bytes=None, mime_type=None):
    """Get free-form vision description. Returns string (the description text)."""
    prompt = _build_freeform_vision_prompt(deal)
    raw_text, error = _call_nvidia_vision(prompt, image_bytes, mime_type, max_tokens=1024)
    if error:
        return f"(Vision freeform failed: {error})"
    return _trim_echoed_prompt(raw_text or "(No description returned)")


def _trim_echoed_prompt(text):
    """Remove echoed prompt/instruction text that the LLM sometimes includes."""
    # Cut at common echo markers
    markers = [
        "\n\nScoring rules:",
        "\n\nReturn ONLY valid JSON",
        "\n\nCRITICAL:",
        "\nDo NOT repeat these instructions",
        "\n\nDeal data:",
        "\n\nIMPORTANT:",
    ]
    for marker in markers:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx].rstrip()
    return text


# ── NVIDIA Vision API call ───────────────────────────────────────────────────

def _call_nvidia_vision(prompt, image_bytes=None, mime_type=None, max_tokens=512):
    """Call NVIDIA Vision API. Same pattern as ocr_backend.NvidiaVisionBackend."""
    api_key = settings.NVIDIA_API_KEY
    endpoint = settings.NVIDIA_VISION_ENDPOINT
    model = settings.NVIDIA_VISION_MODEL
    if not api_key:
        return None, "NVIDIA_API_KEY not set"

    import requests as req

    messages_content = [{"type": "text", "text": prompt}]
    if image_bytes and mime_type:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        messages_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
        })

    try:
        resp = req.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": messages_content}],
                "max_tokens": max_tokens,
                "temperature": 0,
                "top_p": 1,
                "stream": False,
            },
            timeout=90,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as exc:
        return None, f"API request failed: {exc}"

    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None, f"Unexpected API response: {json.dumps(payload)[:200]}"

    if isinstance(content, list):
        text = "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    else:
        text = str(content)
    return text.strip(), None


# ── Verdict parsing ──────────────────────────────────────────────────────────

def _parse_verdict(raw_text):
    """Parse JSON verdict from LLM response. Returns dict or fallback."""
    fallback = {
        "verdict": "watch",
        "confidence": 0,
        "reasons": ["Failed to parse LLM response"],
        "recommended_action": "Manual review needed",
    }
    if not raw_text:
        return fallback

    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        return _validate_verdict(data)
    except json.JSONDecodeError:
        pass

    json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return _validate_verdict(data)
        except json.JSONDecodeError:
            pass

    json_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block:
        try:
            data = json.loads(json_block.group(1))
            return _validate_verdict(data)
        except json.JSONDecodeError:
            pass

    verdict = "watch"
    reasons = []
    action = "Manual review"
    text_lower = text.lower()
    if "reject" in text_lower:
        verdict = "reject"
    elif "keep" in text_lower and "watch" not in text_lower:
        verdict = "keep"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            reasons.append(line[2:].strip())
    if not reasons:
        reasons = [l.strip() for l in text.splitlines() if l.strip()][:2]
    conf_match = re.search(r"conf(?:idence)?[:\s]*(\d+)", text_lower)
    confidence = int(conf_match.group(1)) if conf_match else 50
    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons[:3] if reasons else ["LLM returned non-JSON response"],
        "recommended_action": action,
    }


def _validate_verdict(data):
    """Validate and normalize a parsed verdict dict."""
    verdict = data.get("verdict", "watch")
    if verdict not in ("keep", "watch", "reject"):
        verdict = "watch"
    confidence = data.get("confidence", 0)
    try:
        confidence = max(0, min(100, int(confidence)))
    except (TypeError, ValueError):
        confidence = 0
    reasons = data.get("reasons", [])
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    action = data.get("recommended_action", "Manual review")
    return {
        "verdict": verdict,
        "confidence": confidence,
        "reasons": reasons,
        "recommended_action": action,
    }


# ── Chain vision into verdict ────────────────────────────────────────────────

def _chain_vision_into_verdict(deal, verdict, structured=None, freeform_text=None):
    """Merge structured vision + freeform description into the text-based verdict."""
    # If no vision data at all, return verdict unchanged
    if not structured and not freeform_text:
        return verdict

    reasons = list(verdict.get("reasons", []))
    action = verdict.get("recommended_action", "Manual review")
    v = verdict["verdict"]
    conf = verdict.get("confidence", 50)

    # ── Red-flag detection from ACTUAL vision output only (not prompt text) ──
    vision_text = ""
    if structured:
        vision_text += " " + structured.get("all_visible_text", "")
        vision_text += " " + structured.get("overlay_text", "")
        vision_text += " " + structured.get("inset_text", "")
        vision_text += " " + " ".join(structured.get("visible_notes", []))
    if freeform_text:
        vision_text += " " + freeform_text
    red_flags = extract_red_flags(vision_text)

    # ── Structured vision signals ──
    if structured:
        notes = structured.get("visible_notes", [])
        cond = structured.get("condition_visible", "unknown")
        screen = structured.get("screen_damage", "unknown")
        body = structured.get("body_damage", "unknown")
        back = structured.get("back_damage", "unknown")
        camera = structured.get("camera_damage", "unknown")
        scratches = structured.get("scratches_or_scuffs", "unknown")
        visible = structured.get("visible_product", False)
        box_vis = structured.get("box_or_accessories_visible", "unknown")

        major_damage = sum(1 for s in (screen, body, back, camera) if s == "major")
        minor_damage = sum(1 for s in (screen, body, back, camera, scratches) if s == "minor")

        if major_damage >= 2:
            v = "reject"
            reasons.insert(0, f"Vision: major damage on {major_damage} areas")
            conf = max(conf, 85)
        elif major_damage == 1:
            if v != "reject":
                v = "watch"
            reasons.insert(0, f"Vision: major damage on one area")
            conf = max(conf, 75)

        if minor_damage >= 3 and v != "reject":
            v = "watch"
            reasons.insert(0, f"Vision: {minor_damage} areas with minor wear")

        deal_cond = (deal.condition or "").lower()
        if deal_cond in ("sealed",) and cond in ("used", "damaged"):
            v = "reject"
            reasons.insert(0, f"Vision: listing says sealed but image shows {cond}")
            conf = max(conf, 80)
        elif deal_cond in ("new",) and cond in ("used", "damaged"):
            v = "watch"
            reasons.insert(0, f"Vision: listing implies new but image shows {cond}")

        if visible and cond in ("sealed", "boxed") and box_vis == "yes":
            reasons.append("Vision: sealed/boxed condition confirmed")

        for n in notes[:2]:
            reasons.append(f"Vision: {n}")

    # ── Freeform description signals ──
    if freeform_text:
        ff_lower = freeform_text.lower()
        has_afficheur = "afficheur" in ff_lower
        has_ecran_inconnu = "écran inconnu" in ff_lower or "ecran inconnu" in ff_lower
        has_repaired = any(w in ff_lower for w in ("screen replaced", "display changed", "repaired", "réparation"))
        has_repair_info = any(w in ff_lower for w in (
            "repair information", "repair status", "repair history",
            "repair screen", "repair section", "parts and service",
            "pièces et réparation",
        ))
        has_non_original = any(w in ff_lower for w in ("non-original", "non original", "unknown part"))
        has_mustamal = "مستعمل" in freeform_text

        # Freeform detects a phone/product even if structured didn't
        freeform_sees_phone = any(w in ff_lower for w in (
            "iphone", "samsung", "xiaomi", "phone", "hand holding",
            "device", "smartphone", "mobile",
        ))

        # Afficheur + Écran inconnu together = strong reject
        if has_afficheur and has_ecran_inconnu:
            v = "reject"
            reasons.insert(0, "Freeform: Afficheur + Écran inconnu — display unit with unknown/replaced screen")
            conf = max(conf, 90)
        # Afficheur + repair_info together = reject
        elif has_afficheur and has_repair_info:
            v = "reject"
            reasons.insert(0, "Freeform: Afficheur + repair/parts screen — display unit with repair history")
            conf = max(conf, 88)
        elif has_afficheur:
            if v != "reject":
                v = "watch"
            reasons.insert(0, "Freeform: Afficheur/display/demo unit detected")
            conf = max(conf, 75)
        elif has_ecran_inconnu:
            v = "reject"
            reasons.insert(0, "Freeform: Écran inconnu — unknown/replaced display detected")
            conf = max(conf, 85)

        if has_repaired:
            v = "reject"
            reasons.insert(0, "Freeform: screen replaced/repaired detected")
            conf = max(conf, 85)
        if has_repair_info:
            if v != "reject":
                v = "watch"
            reasons.insert(0, "Freeform: repair/parts information visible in image")
            conf = max(conf, 70)
        if has_non_original:
            v = "reject"
            reasons.insert(0, "Freeform: non-original parts detected")
            conf = max(conf, 85)
        if has_mustamal:
            reasons.append("Freeform: مستعمل (used) mentioned in listing")

        # "no phone product visible" only if BOTH structured and freeform fail to see a product
        if not visible and not freeform_sees_phone:
            if v != "reject":
                v = "watch"
            reasons.append("Vision: no phone product visible in image")
            conf = min(conf, 60)

        # Attach short freeform excerpt
        excerpt = freeform_text[:200].replace("\n", " ")
        reasons.append(f"Freeform: {excerpt}...")

    # ── Red-flag summary ──
    if red_flags:
        reasons.insert(0, f"Red-flags detected: {', '.join(red_flags[:5])}")

    # ── Recompute action ──
    if v == "reject":
        action = "Reject — vision/red-flag inspection found issues"
    elif v == "watch":
        action = "Watch — verify condition manually"
    else:
        action = "Keep — no major issues detected by vision"

    return {
        "verdict": v,
        "confidence": conf,
        "reasons": reasons[:8],
        "recommended_action": action,
    }


# ── Public audit entry point ─────────────────────────────────────────────────

def audit_deal(deal, image_bytes=None, mime_type=None,
               structured_vision=None, freeform_text=None):
    """Audit a single DealSnapshot. Returns dict with verdict/confidence/reasons/action.

    Reuses the NVIDIA Vision API pattern from ocr_backend.NvidiaVisionBackend.
    If structured_vision and/or freeform_text are provided, they are chained into
    the final verdict.
    """
    prompt = _build_prompt(deal, structured_vision=structured_vision,
                           freeform_text=freeform_text)
    raw_text, error = _call_nvidia_vision(prompt, image_bytes, mime_type)
    if error:
        verdict = {
            "verdict": "watch",
            "confidence": 0,
            "reasons": [error],
            "recommended_action": "Check NVIDIA API key and connectivity",
        }
    else:
        verdict = _parse_verdict(raw_text)

    # Chain vision results if provided
    if structured_vision or freeform_text:
        verdict = _chain_vision_into_verdict(
            deal, verdict,
            structured=structured_vision,
            freeform_text=freeform_text,
        )
    return verdict


# ── Condition classification ─────────────────────────────────────────────────

# Red-flag patterns that force issue_used regardless of other signals.
_ISSUE_PATTERNS = [
    r"afficheur",
    r"écran\s*inconnu",
    r"écran\s+unknown",
    r"pièces?\s+et\s+r[ée]paration",
    r"repair\s+(information|status|history|screen|section)",
    r"parts?\s+and\s+service",
    r"parts?\s*[&a]\s*service",
    r"screen\s+replaced",
    r"display\s+changed",
    r"repaired",
    r"r[ée]paration",
    r"non[- ]?original",
    r"unknown\s+part",
    r"unknown\s+part\s+detected",
    r"demo\s+unit",
    r"showcase",
    r"vitrine",
    r"broken\s+screen",
    r"cracked\s+screen",
    r"major\s+damage",
    r"face\s*id\s+(issue|problem|not|missing)",
    r"true\s+tone\s+(issue|problem|not|missing)",
    r"repair/parts",
    r"repair_info",
    r"repair_info_section",
]
_ISSUE_RE = re.compile("|".join(_ISSUE_PATTERNS), re.IGNORECASE)

# Sealed/new indicators.
_SEALED_PATTERNS = [
    r"\bsealed\b",
    r"\bclosed\s+box\b",
    r"\bboîte\s+scellée\b",
    r"\bkapalı\s+kutu\b",
    r"\bneuf\b",
    r"\bnew\b",
    r"\bunopened\b",
    r"\bbrand\s+new\b",
    r"condition.*sealed",
    r"condition.*new",
    r"condition.*boxed",
]
_SEALED_RE = re.compile("|".join(_SEALED_PATTERNS), re.IGNORECASE)

# Used indicators (clean or issue).
_USED_PATTERNS = [
    r"\bused\b",
    r"\bsecond\s*hand\b",
    r"\btemiz\b",
    r"مستعمل",
    r"مستعم\s*ل",
]
_USED_RE = re.compile("|".join(_USED_PATTERNS), re.IGNORECASE)


def classify_condition_class(verdict, red_flags, structured=None, freeform_text=None):
    """Classify a listing into condition_class based on audit signals.

    Returns one of: sealed_new, clean_used, issue_used, unknown.
    """
    reasons = verdict.get("reasons", [])
    all_signals = " ".join(reasons) + " " + " ".join(red_flags)
    if structured:
        all_signals += " " + structured.get("all_visible_text", "")
        all_signals += " " + " ".join(structured.get("visible_notes", []))
    if freeform_text:
        all_signals += " " + freeform_text

    # 1. Check for issue indicators — highest priority
    if _ISSUE_RE.search(all_signals):
        return "issue_used"

    # Also check red_flags list directly
    issue_flag_words = {
        "afficheur", "écran inconnu", "écran unknown", "pièces et réparation",
        "pièce et réparation", "repair information section", "repair information",
        "repair status", "repair history", "repair screen", "repair section",
        "parts and service", "parts & service", "screen replaced", "display changed",
        "repaired", "réparation", "non-original", "non original", "unknown part",
        "unknown part detected", "demo", "showcase", "vitrine", "broken screen",
        "cracked screen", "major damage", "face id issue", "face id problem",
        "true tone issue", "true tone problem", "repair/parts", "repair_info",
        "repair_info_section", "battery health", "cycles", "prix 189000",
    }
    for flag in red_flags:
        if flag.lower() in issue_flag_words or flag.lower().startswith("repair"):
            return "issue_used"

    # 2. Check for sealed/new indicators
    if _SEALED_RE.search(all_signals):
        # But only if no issue flags exist (already checked above)
        return "sealed_new"

    # 3. Check for used indicators — clean if no issue flags
    if _USED_RE.search(all_signals):
        return "clean_used"

    # 4. If vision saw damage
    if structured:
        screen = structured.get("screen_damage", "unknown")
        body = structured.get("body_damage", "unknown")
        back = structured.get("back_damage", "unknown")
        camera = structured.get("camera_damage", "unknown")
        scratches = structured.get("scratches_or_scuffs", "unknown")
        major_count = sum(1 for s in (screen, body, back, camera) if s == "major")
        minor_count = sum(1 for s in (screen, body, back, camera, scratches) if s in ("minor", "major"))
        if major_count >= 1:
            return "issue_used"
        if minor_count >= 3:
            return "issue_used"

    # 5. Verdict-based fallback
    if verdict.get("verdict") == "reject":
        return "issue_used"

    # 6. Unknown — no clear evidence
    return "unknown"


def save_condition_audit(deal, verdict, red_flags, structured=None, freeform_text=None,
                         image_source="", model_used=""):
    """Save or update a ListingConditionAudit for a deal's listing."""
    from market.models import ListingConditionAudit

    condition_class = classify_condition_class(verdict, red_flags, structured, freeform_text)

    audit, created = ListingConditionAudit.objects.update_or_create(
        listing=deal.listing,
        defaults={
            "condition_class": condition_class,
            "verdict": verdict.get("verdict", "watch"),
            "confidence": verdict.get("confidence", 0),
            "red_flags": red_flags,
            "reasons": verdict.get("reasons", []),
            "structured_vision": structured,
            "freeform_vision_text": freeform_text or "",
            "image_source": image_source,
            "model_used": model_used,
        },
    )
    return audit, created
