import subprocess
import tempfile
from pathlib import Path

from django.conf import settings


class OCRBackend:
    def read_text(self, image_path):
        raise NotImplementedError


class DummyOCRBackend(OCRBackend):
    def read_text(self, image_path):
        return "", 0.0


class PaddleOCRBackend(OCRBackend):
    def __init__(self):
        from paddleocr import PaddleOCR

        self.ocr = PaddleOCR(use_angle_cls=True, lang="latin")

    def read_text(self, image_path):
        result = self.ocr.ocr(image_path, cls=True)
        texts = []
        confidences = []
        for page in result or []:
            for item in page or []:
                if len(item) >= 2:
                    text, confidence = item[1]
                    texts.append(text)
                    confidences.append(float(confidence))
        avg = sum(confidences) / len(confidences) if confidences else 0.0
        return "\n".join(texts), avg


class EasyOCRBackend(OCRBackend):
    def __init__(self, languages=None):
        import easyocr

        self.reader = easyocr.Reader(languages or ["en", "fr", "ar", "tr"], gpu=False)

    def read_text(self, image_path):
        image_path = Path(image_path)
        if not image_path.exists():
            return "", 0.0
        result = self.reader.readtext(str(image_path), detail=1, paragraph=False)
        texts = []
        confidences = []
        for item in result or []:
            if len(item) >= 3:
                _, text, confidence = item[:3]
                texts.append(str(text))
                confidences.append(float(confidence))
        avg = sum(confidences) / len(confidences) if confidences else 0.0
        return "\n".join(texts), avg


class TesseractOCRBackend(OCRBackend):
    def __init__(self, languages="eng+fra+ara+tur"):
        self.languages = languages

    def read_text(self, image_path):
        image_path = Path(image_path)
        if not image_path.exists():
            return "", 0.0

        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = [image_path]
            try:
                from PIL import Image, ImageOps, ImageFilter, ImageEnhance

                image = Image.open(image_path).convert("L")
                width, height = image.size
                variants = {
                    "prepared.png": ImageOps.autocontrast(image).filter(ImageFilter.SHARPEN),
                    "inverted.png": ImageOps.invert(ImageOps.autocontrast(image)).filter(ImageFilter.SHARPEN),
                    "top.png": ImageOps.autocontrast(image.crop((0, 0, width, int(height * 0.45)))).filter(ImageFilter.SHARPEN),
                    "top_inverted.png": ImageOps.invert(
                        ImageOps.autocontrast(image.crop((0, 0, width, int(height * 0.45))))
                    ).filter(ImageFilter.SHARPEN),
                }
                price_boxes = [
                    (0.72, 0.18, 0.98, 0.28),
                    (0.62, 0.17, 0.99, 0.28),
                    (0.65, 0.16, 0.99, 0.32),
                ]
                for index, box in enumerate(price_boxes, start=1):
                    left, top, right, bottom = box
                    crop = image.crop((int(width * left), int(height * top), int(width * right), int(height * bottom)))
                    for mode, candidate in {
                        "normal": crop,
                        "inverted": ImageOps.invert(crop),
                    }.items():
                        candidate = ImageOps.autocontrast(candidate)
                        candidate = ImageEnhance.Contrast(candidate).enhance(3)
                        candidate = candidate.resize((candidate.width * 6, candidate.height * 6))
                        variants[f"price_box_{index}_{mode}.png"] = candidate.filter(ImageFilter.SHARPEN)
                inputs = []
                for filename, variant in variants.items():
                    path = Path(tmpdir) / filename
                    variant.save(path)
                    inputs.append(path)
            except Exception:
                inputs = [image_path]

            lines = []
            seen = set()
            for input_path in inputs:
                is_price_box = input_path.name.startswith("price_box_")
                command = [
                    "tesseract",
                    str(input_path),
                    "stdout",
                    "-l",
                    "eng" if is_price_box else self.languages,
                    "--psm",
                    "7" if is_price_box else "6",
                ]
                if is_price_box:
                    command.extend(["-c", "tessedit_char_whitelist=0123456789"])
                try:
                    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
                except (OSError, subprocess.SubprocessError):
                    continue
                for line in result.stdout.splitlines():
                    line = line.strip()
                    key = line.lower()
                    if line and key not in seen:
                        seen.add(key)
                        lines.append(line)
        text = "\n".join(lines)
        return text, 0.55 if text else 0.0


class OCRSpaceBackend(OCRBackend):
    endpoint = "https://api.ocr.space/parse/image"

    def __init__(self, api_key=None, language=None, engine=None):
        self.api_key = api_key or settings.OCR_SPACE_API_KEY
        self.language = language or settings.OCR_SPACE_LANGUAGE
        self.engine = engine or settings.OCR_SPACE_ENGINE
        if not self.api_key:
            raise RuntimeError("OCR_SPACE_API_KEY is required for OCR.space backend.")

    def read_text(self, image_path):
        image_path = Path(image_path)
        if not image_path.exists():
            return "", 0.0
        try:
            import requests

            with image_path.open("rb") as handle:
                response = requests.post(
                    self.endpoint,
                    headers={"apikey": self.api_key},
                    data={
                        "language": self.language,
                        "OCREngine": self.engine,
                        "scale": "true",
                        "isOverlayRequired": "false",
                    },
                    files={"file": (image_path.name, handle, "image/jpeg")},
                    timeout=60,
                )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return "", 0.0

        if payload.get("IsErroredOnProcessing"):
            return "", 0.0
        texts = []
        for result in payload.get("ParsedResults") or []:
            text = result.get("ParsedText") or ""
            if text.strip():
                texts.append(text.strip())
        text = "\n".join(texts).strip()
        return text, 0.7 if text else 0.0


def get_ocr_backend(name):
    backend = (name or "").lower()
    if backend in {"ocrspace", "ocr.space", "ocr_space"}:
        try:
            return OCRSpaceBackend()
        except Exception:
            return TesseractOCRBackend()
    if backend == "easyocr":
        try:
            return EasyOCRBackend()
        except Exception:
            return TesseractOCRBackend()
    if backend == "paddleocr":
        try:
            return PaddleOCRBackend()
        except Exception:
            return TesseractOCRBackend()
    if backend == "tesseract":
        return TesseractOCRBackend()
    return DummyOCRBackend()
