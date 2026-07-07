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


def _build_prompt(deal):
    """Full text prompt for the LLM."""
    deal_text = _build_deal_text_block(deal)
    return (
        "You are a market analyst auditing phone resale deals in Algeria.\n"
        "A deal was found by matching an Algeria listing against Türkiye market prices.\n"
        "Your job is to judge whether the deal looks BELIEVABLE or SUSPICIOUS.\n\n"
        "Deal data:\n"
        f"{deal_text}\n\n"
        "Scoring rules:\n"
        "- margin > 50% is suspicious unless well-evidenced (sah_count >= 5)\n"
        "- sah_count <= 2 means weak Türkiye evidence\n"
        "- Budget phones (Redmi, low-end) at huge margins are suspicious\n"
        "- New/rare models (Z Fold 7, iPhone 17) with few matches may have stale medians\n"
        "- Unknown condition is a risk factor\n"
        "- Missing listing URL or image is a risk factor\n"
        "- Price_eur far below sah_median_eur is suspicious (too cheap)\n\n"
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


def _call_nvidia_vision(prompt, image_bytes=None, mime_type=None):
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
                "max_tokens": 512,
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
    # Strip markdown fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Attempt 1: direct JSON parse
    try:
        data = json.loads(text)
        return _validate_verdict(data)
    except json.JSONDecodeError:
        pass

    # Attempt 2: extract JSON object from text using regex
    json_match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return _validate_verdict(data)
        except json.JSONDecodeError:
            pass

    # Attempt 3: extract JSON block from markdown
    json_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block:
        try:
            data = json.loads(json_block.group(1))
            return _validate_verdict(data)
        except json.JSONDecodeError:
            pass

    # Attempt 4: heuristic extraction from markdown text
    verdict = "watch"
    reasons = []
    action = "Manual review"
    text_lower = text.lower()
    if "reject" in text_lower:
        verdict = "reject"
    elif "keep" in text_lower and "watch" not in text_lower:
        verdict = "keep"
    # Extract reasons from bullet points
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("- ") or line.startswith("* "):
            reasons.append(line[2:].strip())
    if not reasons:
        # Take first 2 non-empty lines as reasons
        reasons = [l.strip() for l in text.splitlines() if l.strip()][:2]
    # Extract confidence if present
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


def audit_deal(deal, image_bytes=None, mime_type=None):
    """Audit a single DealSnapshot. Returns dict with verdict/confidence/reasons/action.

    Reuses the NVIDIA Vision API pattern from ocr_backend.NvidiaVisionBackend.
    """
    prompt = _build_prompt(deal)
    raw_text, error = _call_nvidia_vision(prompt, image_bytes, mime_type)
    if error:
        return {
            "verdict": "watch",
            "confidence": 0,
            "reasons": [error],
            "recommended_action": "Check NVIDIA API key and connectivity",
        }
    return _parse_verdict(raw_text)
