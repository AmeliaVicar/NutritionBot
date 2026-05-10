import os
import uuid
from pdf2image import convert_from_path
from PIL import Image

# если poppler в PATH — poppler_path не нужен
# иначе: poppler_path=r"C:\poppler\Library\bin"


def pdf_to_jpeg(pdf_path: str) -> str:
    pages = convert_from_path(pdf_path, dpi=200)
    if not pages:
        raise RuntimeError(f"No pages rendered from PDF: {pdf_path}")

    if len(pages) == 1:
        img = pages[0]
    else:
        width = max(page.width for page in pages)
        height = sum(page.height for page in pages)
        img = Image.new("RGB", (width, height), "white")

        y = 0
        for page in pages:
            x = (width - page.width) // 2
            img.paste(page, (x, y))
            y += page.height

    out_dir = os.path.dirname(pdf_path)

    jpg_path = os.path.join(out_dir, f"report_{uuid.uuid4().hex}.jpg")
    img.save(jpg_path, "JPEG", quality=90, optimize=True)
    return jpg_path
