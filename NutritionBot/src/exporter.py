import os
import uuid
from pdf2image import convert_from_path

# если poppler в PATH — poppler_path не нужен
# иначе: poppler_path=r"C:\poppler\Library\bin"

def pdf_to_jpeg(pdf_path: str) -> str:
    pages = convert_from_path(pdf_path)  # first page is enough
    img = pages[0]

    out_dir = os.path.join(os.path.dirname(pdf_path), "out")
    os.makedirs(out_dir, exist_ok=True)

    jpg_path = os.path.join(out_dir, f"report_{uuid.uuid4().hex}.jpg")
    img.save(jpg_path, "JPEG", quality=90)
    return jpg_path
