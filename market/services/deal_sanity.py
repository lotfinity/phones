"""Listing metadata + condition inspector using NVIDIA Vision API.

Single prompt: confirm metadata, extract visible text, classify device condition.
No pricing opinion. No deal believability. No market analysis.
"""

import base64
import json
import mimetypes
import re
from pathlib import Path

from django.conf import settings


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


# ── NVIDIA Vision API call ───────────────────────────────────────────────────

def _call_nvidia_vision(prompt, image_bytes=None, mime_type=None, max_tokens=1024):
    """Call NVIDIA Vision API. Returns (text, error)."""
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


# ── JSON extraction helper ──────────────────────────────────────────────────

def _extract_json(raw_text):
    """Extract JSON object from LLM response. Returns dict or None."""
    if not raw_text:
        return None
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try fixing truncated JSON by adding missing closing braces
    opens = text.count("{")
    closes = text.count("}")
    if opens > closes:
        try:
            return json.loads(text + "}" * (opens - closes))
        except json.JSONDecodeError:
            pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        candidate = m.group()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass
        # Try fixing truncated JSON in the extracted match
        opens = candidate.count("{")
        closes = candidate.count("}")
        if opens > closes:
            try:
                return json.loads(candidate + "}" * (opens - closes))
            except json.JSONDecodeError:
                pass
    return None


# ── Single combined prompt ──────────────────────────────────────────────────

def _build_inspect_prompt(deal, product_type="phone"):
    """Build the single metadata + condition inspection prompt.

    product_type is "phone" or "laptop" — it only changes inspection cues,
    not the condition classification logic.
    """
    is_laptop = product_type == "laptop"
    device_word = "laptop" if is_laptop else "phone"
    meta_block = (
        f"Current metadata from our system:\n"
        f"- Brand: {deal.brand_name}\n"
        f"- Model: {deal.model_name}\n"
        f"- Storage: {deal.storage_gb or 'unknown'} GB\n"
        f"- Listing title: {deal.title}\n"
        f"- Condition text: {deal.condition or 'unknown'}\n"
        f"- Source: {deal.source_name or deal.source_code or 'unknown'}\n"
    )
    if is_laptop:
        inspect_cues = (
            "- Main product (laptop or sealed box in center)\n"
            "- Black overlay text (white/red text on dark background)\n"
            "- Screen: dead pixels, scratches, cracks, pressure marks, yellow tint\n"
            "- Keyboard: missing/loose keys, sticky keys, backlight issues\n"
            "- Hinges, trackpad, body: dents, cracks, wobble\n"
            "- Charger / box inclusion (is the original charger or box shown?)\n"
            "- Arabic text (مستعمل, etc.)\n"
            "- French text (afficheur, écran inconnu, pièces et réparation, etc.)\n"
            "- Repair / parts warnings, serial or config text\n"
        )
    else:
        inspect_cues = (
            "- Main product (phone or box in center)\n"
            "- Black overlay text (white/red text on dark background)\n"
            "- Circular/square inset images (iOS settings, battery, repair info)\n"
            "- Arabic text (مستعمل, etc.)\n"
            "- French text (afficheur, écran inconnu, pièces et réparation, etc.)\n"
            "- iOS parts/repair screens\n"
            "- Battery cycles, price text, SIM/storage text\n"
        )
    return (
        f"You are inspecting a {device_word} listing image and its metadata.\n"
        "Your job is simple:\n"
        "1. Check if the current metadata matches what the image shows.\n"
        "2. Extract ALL visible text from the image.\n"
        "3. Classify the device condition.\n\n"
        f"{meta_block}\n"
        "IMPORTANT RULES:\n"
        "- Do NOT give pricing opinions.\n"
        "- Do NOT judge if the deal is good or bad.\n"
        "- Do NOT mention margin, Sahibinden, supplier prices, or business risk.\n"
        "- If the metadata says iPhone 17 Pro 256GB and the image also says iPhone 17 Pro 256GB,\n"
        "  mark model_correct = true. Do NOT question whether the model exists.\n"
        "- Do NOT use world knowledge about release dates or whether a model is real.\n"
        "- Only flag mismatch if the image text clearly shows a DIFFERENT model/storage/brand.\n\n"
        f"Inspect ALL parts of the image:\n{inspect_cues}\n"
        "HOW TO DETERMINE CONDITION_CLASS:\n"
        "A) If the image has overlay text / listing text / inset screenshots with repair info:\n"
        "   Use that text to classify. Look for: Afficheur, Écran inconnu, Pièces et réparation,\n"
        "   screen replaced, non-original, cracked, demo, مستعمل (used), sealed, new, etc.\n"
        "   BUT ALSO look at the actual device in the image — text alone is not enough.\n"
        "   If text says one thing but the device looks different, trust what you SEE.\n\n"
        f"B) If the image has NO overlay text (just a photo of a {device_word} or box):\n"
        "   - ONLY a box visible, NO device out of the box? = brand_new_closed_box. ALWAYS.\n"
        f"     A box with no device visible means the {device_word} is still inside. This is sealed/new.\n"
        "   - Device out of box, looks clean? = used_clean\n"
        "   - Device with visible wear, scratches, cracks? = used_repaired_or_needs_repair\n"
        "   - Stock photo / product render where real condition cannot be determined? = unknown\n\n"
        "C) When in doubt, DESCRIBE what you actually see in the image:\n"
        "   - Is there a real physical device or just a product render?\n"
        "   - Is the device in a hand, on a table, in a store display?\n"
        "   - Is there a box? Is the device inside or outside the box?\n"
        "   - Any visible wear, scratches, cracks, damage?\n"
        "   - Then pick the best condition_class based on what you SEE, not just text.\n\n"
        "Condition categories (pick exactly one):\n"
        "- brand_new_closed_box: sealed, closed box, unopened, new retail box\n"
        "- used_clean: used/second-hand but no visible issues, no repair warnings, no major damage\n"
        "- used_repaired_or_needs_repair: repaired, repair history, parts warning, unknown display,\n"
        "  Afficheur, Écran inconnu, Pièces et réparation, screen replaced, non-original part,\n"
        "  Face ID issue, True Tone issue, cracked/broken/damaged, display/demo unit\n"
        "- unknown: no image, image unclear, not enough evidence, conflicting evidence,\n"
        "  stock photo / product render where real condition cannot be determined\n\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "metadata_check": {\n'
        '    "brand_correct": true|false|null,\n'
        '    "model_correct": true|false|null,\n'
        '    "storage_correct": true|false|null,\n'
        '    "sim_correct": true|false|null,\n'
        '    "battery_correct": true|false|null,\n'
        '    "corrections": {\n'
        '      "brand": "",\n'
        '      "model": "",\n'
        '      "storage_gb": null,\n'
        '      "sim": "",\n'
        '      "battery_health": null,\n'
        '      "battery_cycles": null,\n'
        '      "price_text": "",\n'
        '      "condition_text": ""\n'
        "    },\n"
        '    "missing_visible_info": ["..."]\n'
        "  },\n"
        '  "visible_text": {\n'
        '    "all_text": "ALL text you can read (max 300 chars). If no text, say no text visible.",\n'
        '    "overlay_text": "black overlay text (max 200 chars). If none, say none.",\n'
        '    "inset_text": "text in insets (max 200 chars). If none, say none."\n'
        "  },\n"
        '  "condition_class": "brand_new_closed_box"|"used_clean"|"used_repaired_or_needs_repair"|"unknown",\n'
        '  "condition_note": "short note explaining your reasoning (max 150 chars)",\n'
        '  "confidence": 0-100\n'
        "}\n\n"
        "CRITICAL: Return ONLY a single JSON object. No markdown. No code fences. "
        "No explanation before or after. Just the raw JSON."
    )


# ── Parse + validate ────────────────────────────────────────────────────────

_VALID_CONDITION = {
    "brand_new_closed_box",
    "used_clean",
    "used_repaired_or_needs_repair",
    "unknown",
}

# Map LLM condition_class to DB condition_class
_CONDITION_MAP = {
    "brand_new_closed_box": "sealed_new",
    "used_clean": "clean_used",
    "used_repaired_or_needs_repair": "issue_used",
    "unknown": "unknown",
}


def _parse_inspect_result(raw_text):
    """Parse and validate the LLM JSON response. Returns dict with normalized fields."""
    fallback = {
        "metadata_check": {
            "brand_correct": None,
            "model_correct": None,
            "storage_correct": None,
            "sim_correct": None,
            "battery_correct": None,
            "corrections": {},
            "missing_visible_info": [],
        },
        "visible_text": {"all_text": "", "overlay_text": "", "inset_text": ""},
        "condition_class": "unknown",
        "condition_note": "Failed to parse LLM response",
        "confidence": 0,
    }
    data = _extract_json(raw_text)
    if not data or not isinstance(data, dict):
        return fallback

    # metadata_check
    mc = data.get("metadata_check", {})
    if not isinstance(mc, dict):
        mc = {}
    corrections = mc.get("corrections", {})
    if not isinstance(corrections, dict):
        corrections = {}
    missing = mc.get("missing_visible_info", [])
    if not isinstance(missing, list):
        missing = [str(missing)]

    result = {
        "metadata_check": {
            "brand_correct": mc.get("brand_correct"),
            "model_correct": mc.get("model_correct"),
            "storage_correct": mc.get("storage_correct"),
            "sim_correct": mc.get("sim_correct"),
            "battery_correct": mc.get("battery_correct"),
            "corrections": {k: v for k, v in corrections.items() if v is not None and v != ""},
            "missing_visible_info": [str(x) for x in missing[:10]],
        },
        "visible_text": {
            "all_text": str(data.get("visible_text", {}).get("all_text", ""))[:1000],
            "overlay_text": str(data.get("visible_text", {}).get("overlay_text", ""))[:500],
            "inset_text": str(data.get("visible_text", {}).get("inset_text", ""))[:500],
        },
        "condition_class": data.get("condition_class", "unknown"),
        "condition_note": str(data.get("condition_note", ""))[:300],
        "confidence": 0,
    }

    if result["condition_class"] not in _VALID_CONDITION:
        result["condition_class"] = "unknown"

    try:
        result["confidence"] = max(0, min(100, int(data.get("confidence", 0))))
    except (TypeError, ValueError):
        result["confidence"] = 0

    return result


# ── Public entry point ──────────────────────────────────────────────────────

def inspect_listing_metadata_and_condition(deal, image_bytes=None, mime_type=None, product_type="phone"):
    """Inspect listing image + metadata. Returns (result_dict, error_string|None).

    The result_dict contains:
      - metadata_check: dict with brand/model/storage correctness + corrections
      - visible_text: dict with all_text, overlay_text, inset_text
      - condition_class: one of brand_new_closed_box, used_clean, used_repaired_or_needs_repair, unknown
      - condition_note: short human-readable explanation
      - confidence: 0-100

    product_type is "phone" or "laptop" and only adjusts inspection cues.
    """
    prompt = _build_inspect_prompt(deal, product_type=product_type)
    raw_text, error = _call_nvidia_vision(prompt, image_bytes, mime_type, max_tokens=4096)
    if error:
        return None, error
    return _parse_inspect_result(raw_text), None


def save_condition_audit(deal, inspect_result, image_source="", model_used=""):
    """Save or update a ListingConditionAudit from inspect_listing_metadata_and_condition output."""
    from market.models import ListingConditionAudit

    condition_class_raw = inspect_result.get("condition_class", "unknown")
    condition_class = _CONDITION_MAP.get(condition_class_raw, "unknown")

    # Build reasons from condition_note + metadata corrections
    reasons = []
    note = inspect_result.get("condition_note", "")
    if note:
        reasons.append(note)
    mc = inspect_result.get("metadata_check", {})
    corrections = mc.get("corrections", {})
    if corrections:
        for k, v in corrections.items():
            reasons.append(f"Correction: {k} = {v}")
    missing = mc.get("missing_visible_info", [])
    for m in missing[:3]:
        reasons.append(f"Missing: {m}")

    # Extract red flags from visible text only
    visible = inspect_result.get("visible_text", {})
    all_text = visible.get("all_text", "") + " " + visible.get("overlay_text", "") + " " + visible.get("inset_text", "")
    red_flags = _extract_red_flags_from_text(all_text)

    audit, created = ListingConditionAudit.objects.update_or_create(
        listing=deal.listing,
        defaults={
            "condition_class": condition_class,
            "verdict": "keep" if condition_class in ("sealed_new", "clean_used") else (
                "reject" if condition_class == "issue_used" else "watch"
            ),
            "confidence": inspect_result.get("confidence", 0),
            "red_flags": red_flags,
            "reasons": reasons[:8],
            "structured_vision": inspect_result,
            "freeform_vision_text": note,
            "image_source": image_source,
            "model_used": model_used,
        },
    )
    return audit, created


# ── Red-flag extraction from visible text ───────────────────────────────────

_RED_FLAG_PATTERNS = [
    r"afficheur",
    r"écran\s*inconnu",
    r"pièces?\s+et\s+r[ée]paration",
    r"repair\s+(information|status|history|screen|section)",
    r"parts?\s+and\s+service",
    r"screen\s+replaced",
    r"display\s+changed",
    r"repaired",
    r"r[ée]paration",
    r"\bdemo\b",
    r"showcase",
    r"vitrine",
    r"non[- ]?original",
    r"unknown\s+part",
    r"face\s*id\s+(issue|problem|not|missing)",
    r"true\s*tone\s+(issue|problem|not|missing)",
    r"مستعمل",
    r"مستعم\s*ل",
]
_RED_FLAG_RE = re.compile("|".join(_RED_FLAG_PATTERNS), re.IGNORECASE)


def _extract_red_flags_from_text(text):
    """Extract red-flag words from visible text."""
    if not text:
        return []
    flags = set()
    for match in _RED_FLAG_RE.finditer(text):
        flag = match.group(0).lower().strip()
        start = max(0, match.start() - 250)
        context = text[start:match.start()].lower()
        negations = ["no ", "not ", "without ", "don't see ", "doesn't appear ",
                     "no visible ", "not visible ", "not detected "]
        if any(neg in context for neg in negations):
            continue
        flags.add(flag)
    return list(flags)


# ── Keep old functions for backward compat (audit command still imports them) ──

def extract_red_flags(text):
    """Legacy: extract red-flag matches from text."""
    return _extract_red_flags_from_text(text)


def audit_deal(deal, image_bytes=None, mime_type=None,
               structured_vision=None, freeform_text=None):
    """Legacy stub — kept for import compatibility. Use inspect_listing_metadata_and_condition instead."""
    return {
        "verdict": "watch",
        "confidence": 0,
        "reasons": ["Legacy audit_deal called — use inspect_listing_metadata_and_condition"],
        "recommended_action": "Migrate to new inspect function",
    }


def inspect_deal_image(deal, image_bytes=None, mime_type=None):
    """Legacy stub."""
    return {"visible_product": False, "all_visible_text": "", "visible_notes": ["legacy stub"]}


def inspect_deal_image_freeform(deal, image_bytes=None, mime_type=None):
    """Legacy stub."""
    return "(legacy stub)"
