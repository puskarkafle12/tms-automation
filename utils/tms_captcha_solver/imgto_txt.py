from PIL import Image
import io
import easyocr
import numpy as np
import asyncio

reader = easyocr.Reader(['en'])  # Initialize once at module level (important for performance!)

async def get_text_from_image(byte_image):
    def process_image():
        image = Image.open(io.BytesIO(byte_image))
        image_np = np.array(image)
        text = reader.readtext(image_np)[0][1]
        return text

    text = await asyncio.to_thread(process_image)
    return text

async def solve_captcha(binary_byte_image):
    return await get_text_from_image(binary_byte_image)

