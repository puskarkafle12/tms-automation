# Install EasyOCR (if not already installed)
# pip install easyocr

import easyocr

# Specify the language for text detection (e.g., English)
reader = easyocr.Reader(['en'])

# Load the image
image_path = "path/to/your/image.jpg"  # Replace with your image path
output = reader.readtext(image_path)

# Access the extracted text
text = output[0][1]  # [0] is the first detected text block, [1] is the text content
print(text)

# You can now copy the text variable to your clipboard (implementation depends on your OS)
