import requests
from PIL import Image
import io
import easyocr
import numpy as np

# URL of the image containing text with dotted blurs
image_url = 'https://i.ibb.co/kgcFFpN/asdfasd.png'

# Download the image from the URL
response = requests.get(image_url)

# Open the downloaded image using the Pillow library
image = Image.open(io.BytesIO(response.content))

# Convert the PIL image to a NumPy array
image_np = np.array(image)

# Initialize the OCR reader
reader = easyocr.Reader(['en'])

# Perform OCR on the image to extract text
result = reader.readtext(image_np)

# Extract the recognized text

print(result)
