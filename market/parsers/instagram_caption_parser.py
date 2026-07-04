from market.parsers.ocr_parser import parse_ocr_text


def parse_caption(text):
    return parse_ocr_text(text or "")
