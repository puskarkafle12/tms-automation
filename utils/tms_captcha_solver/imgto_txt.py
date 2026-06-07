from PIL import Image
import io
import numpy as np
import asyncio
import os
from pathlib import Path
import re

reader = None
EASYOCR_HOME = Path(os.getenv("EASYOCR_MODULE_PATH", "/root/.EasyOCR"))


def _normalize_captcha(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())[:6]


async def get_text_from_image(byte_image):
    def process_image():
        global reader
        if reader is None:
            import easyocr
            (EASYOCR_HOME / "model").mkdir(parents=True, exist_ok=True)
            (EASYOCR_HOME / "user_network").mkdir(parents=True, exist_ok=True)
            reader = easyocr.Reader(['en'])
        image = Image.open(io.BytesIO(byte_image))
        image_np = np.array(image)
        results = reader.readtext(image_np)
        if not results:
            return ""
        return _normalize_captcha(results[0][1])

    text = await asyncio.to_thread(process_image)
    return text

async def solve_captcha(binary_byte_image):
    return await get_text_from_image(binary_byte_image)
