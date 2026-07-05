import base64
import mimetypes
import re
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


class NvidiaVisionBackend(OCRBackend):
    def __init__(self, api_key=None, endpoint=None, model=None):
        self.api_key = api_key or settings.NVIDIA_API_KEY
        self.endpoint = endpoint or settings.NVIDIA_VISION_ENDPOINT
        self.model = model or settings.NVIDIA_VISION_MODEL
        if not self.api_key:
            raise RuntimeError("NVIDIA_API_KEY or NVIDIA_NIM_API_KEY is required for NVIDIA vision OCR.")

    def read_text(self, image_path):
        image_path = Path(image_path)
        if not image_path.exists():
            return "", 0.0

        try:
            import requests

            mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
            encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
            prompt = (
                "You are an OCR engine. Extract only the literal visible text from this "
                "phone-store Instagram listing image. Preserve useful line breaks. Do not "
                "summarize, label fields, add markdown, translate, normalize, infer missing "
                "words, or infer currencies. Return only text that is visibly present in the image."
            )
            response = requests.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                                },
                            ],
                        }
                    ],
                    "max_tokens": 1024,
                    "temperature": 0,
                    "top_p": 1,
                    "stream": False,
                },
                timeout=90,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return "", 0.0

        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return "", 0.0

        if isinstance(content, list):
            text = "\n".join(
                part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
            )
        else:
            text = str(content)
        text = self._clean_text(text)
        return text, 0.8 if text else 0.0

    def _clean_text(self, text):
        text = (text or "").strip()
        text = re.sub(
            r"(?is)^\s*(?:the\s+)?(?:visible\s+)?text(?:\s+displayed)?(?:\s+on[^:]{0,80})?\s+(?:reads|is)\s*:\s*",
            "",
            text,
        )
        text = re.sub(r"(?is)^\s*(?:here is|here's)\s+(?:the\s+)?(?:extracted|visible)\s+text\s*:\s*", "", text)
        text = text.replace("**", "").replace("* ", "")
        lines = [line.strip(" -\t") for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()


def get_ocr_backend(name):
    backend = (name or "").lower()
    if backend in {"ocrspace", "ocr.space", "ocr_space"}:
        try:
            return OCRSpaceBackend()
        except Exception:
            return TesseractOCRBackend()
    if backend in {"nvidia", "nvidia_vision", "nvidia-vlm", "nim"}:
        return NvidiaVisionBackend()
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
