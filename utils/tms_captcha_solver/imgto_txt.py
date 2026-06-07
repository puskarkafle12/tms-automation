from PIL import Image
import io
import easyocr
import numpy as np
import asyncio
import re

reader = easyocr.Reader(['en'])  # Initialize once at module level (important for performance!)


def _normalize_captcha(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())[:6]


async def get_text_from_image(byte_image):
    def process_image():
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

