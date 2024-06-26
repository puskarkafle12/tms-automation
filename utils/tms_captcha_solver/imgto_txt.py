
from PIL import Image
import io
import easyocr
import numpy as np

def get_text_from_image(byte_image):
    image = Image.open(io.BytesIO(byte_image))

    image_np = np.array(image)

    # Initialize the OCR reader
    reader = easyocr.Reader(['en'])

    # Perform OCR on the image to extract text
    text = reader.readtext(image_np)[0][1]
    # Extract the recognized text
    return text

def solve_captcha (binary_byte_image):
    # decoded_image=decode_binary_data_to_utf(binary_byte_image)
    return get_text_from_image(binary_byte_image)
