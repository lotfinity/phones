"""Helpers for detected text segments with offset tracking."""

LABELS = frozenset({
    "brand", "model", "series", "storage", "ram", "sim", "price",
    "currency", "condition", "battery_health", "battery_cycles",
    "cpu", "gpu", "screen_size", "resolution", "refresh_rate",
    "location", "date", "unknown",
})

SEGMENT_COLORS = {
    "brand": "#3b82f6",
    "model": "#a855f7",
    "series": "#a855f7",
    "storage": "#22c55e",
    "ram": "#eab308",
    "sim": "#6366f1",
    "price": "#ef4444",
    "currency": "#f97316",
    "condition": "#6b7280",
    "battery_health": "#f97316",
    "battery_cycles": "#f97316",
    "cpu": "#06b6d4",
    "gpu": "#ec4899",
    "screen_size": "#14b8a6",
    "resolution": "#14b8a6",
    "refresh_rate": "#14b8a6",
    "location": "#78716c",
    "date": "#78716c",
    "unknown": "#9ca3af",
}


def make_segment(label, text, start, end, confidence=0.0):
    return {
        "label": label,
        "text": text,
        "start": start,
        "end": end,
        "confidence": round(confidence, 3),
    }


def find_regex_segments(text, pattern, label, flags=0):
    import re
    segments = []
    for m in re.finditer(pattern, text, flags):
        segments.append(make_segment(label, m.group(), m.start(), m.end(), 0.9))
    return segments


def merge_segments(segments):
    """Remove fully contained segments; keep the outermost for overlapping spans."""
    if not segments:
        return segments
    segments = sorted(segments, key=lambda s: (s["start"], -(s["end"] - s["start"])))
    merged = []
    for seg in segments:
        if merged and seg["start"] >= merged[-1]["start"] and seg["end"] <= merged[-1]["end"]:
            if seg["confidence"] > merged[-1]["confidence"]:
                merged[-1] = seg
            continue
        merged.append(seg)
    return merged


def sort_segments(segments):
    return sorted(segments, key=lambda s: (s["start"], s["end"]))


def segments_to_html(text, segments):
    if not segments:
        from django.utils.html import escape
        return f"<span>{escape(text)}</span>"
    segments = sort_segments(segments)
    parts = []
    pos = 0
    for seg in segments:
        start = max(seg["start"], pos)
        if start > pos:
            from django.utils.html import escape
            parts.append(f"<span>{escape(text[pos:start])}</span>")
        color = SEGMENT_COLORS.get(seg["label"], "#9ca3af")
        from django.utils.html import escape
        parts.append(
            f'<span style="background-color:{color}33;border-bottom:2px solid {color};'
            f'padding:1px 2px;border-radius:2px" title="{seg["label"]} '
            f'({seg["confidence"]:.0%})">{escape(text[start:seg["end"]])}</span>'
        )
        pos = seg["end"]
    if pos < len(text):
        from django.utils.html import escape
        parts.append(f"<span>{escape(text[pos:])}</span>")
    return "\n".join(parts)
