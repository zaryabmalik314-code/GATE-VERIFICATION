"""
OCR + field extraction for LGU student ID cards.

Takes a raw photo of the card and pulls out:
  - roll_number  (e.g. "Fa-2025-BS CMAI-055")
  - session_end_year (e.g. 2029, parsed from "Session: Fa-2025-29")

Deliberately tolerant of messy phone-camera photos: runs a couple of
lightweight preprocessing steps before OCR (grayscale + contrast boost),
and uses regexes that don't require the whole card to be read perfectly
- only the two lines we actually care about.
"""
import re
import io
import cv2
import numpy as np
import pytesseract
from PIL import Image


class CardReadError(Exception):
    """Raised when the roll number or session can't be confidently extracted."""
    pass


def _preprocess(image_bytes: bytes) -> Image.Image:
    """Light preprocessing to improve OCR accuracy on phone-camera photos."""
    file_bytes = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    if img is None:
        raise CardReadError("Could not decode image. Please upload a valid photo.")

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Upscale small images - phone photos of a card from a distance can be low-res
    h, w = gray.shape
    if max(h, w) < 1200:
        scale = 1200 / max(h, w)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    # Contrast boost (CLAHE) - helps with glare / uneven lighting on plastic cards
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # Mild denoise
    gray = cv2.fastNlMeansDenoising(gray, h=10)

    return Image.fromarray(gray)


def extract_text(image_bytes: bytes) -> str:
    processed = _preprocess(image_bytes)
    # psm 6 = "assume a uniform block of text" - works well for this card layout
    config = "--psm 6"
    return pytesseract.image_to_string(processed, config=config)


# Roll No line looks like: "Roll No: Fa-2025-BS CMAI-055"
ROLL_NO_PATTERN = re.compile(
    r"Roll\s*No[:\.\s]*([A-Za-z]{2}\s*-\s*\d{4}\s*-\s*[A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)*\s*-\s*\d+)",
    re.IGNORECASE,
)

# Session line looks like: "Session: Fa-2025-29"
SESSION_PATTERN = re.compile(
    r"Session[:\.\s]*[A-Za-z]{2}\s*-\s*(\d{4})\s*-\s*(\d{2,4})",
    re.IGNORECASE,
)


def parse_roll_number(text: str) -> str:
    match = ROLL_NO_PATTERN.search(text)
    if not match:
        raise CardReadError(
            "Could not read the Roll No field clearly. Please retake the photo "
            "(good lighting, card flat, no glare) or enter the roll number manually."
        )
    # Normalize whitespace around dashes
    raw = match.group(1)
    return re.sub(r"\s*-\s*", "-", raw).strip()


def parse_session_end_year(text: str) -> int:
    match = SESSION_PATTERN.search(text)
    if not match:
        raise CardReadError(
            "Could not read the Session field clearly. Please retake the photo "
            "or enter the session manually (e.g. Fa-2025-29)."
        )
    start_year = int(match.group(1))
    end_suffix = match.group(2)

    if len(end_suffix) == 2:
        # "29" -> 2029. Assumes same century as start_year.
        end_year = (start_year // 100) * 100 + int(end_suffix)
    else:
        end_year = int(end_suffix)

    return end_year


def read_card(image_bytes: bytes) -> dict:
    """
    Full pipeline: image bytes -> extracted fields.
    Raises CardReadError if either field can't be confidently parsed.
    """
    text = extract_text(image_bytes)
    roll_number = parse_roll_number(text)
    session_end_year = parse_session_end_year(text)
    return {
        "roll_number": roll_number,
        "session_end_year": session_end_year,
        "raw_ocr_text": text.strip(),
    }
