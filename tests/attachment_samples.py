"""Made-up files for attachment tests: generated in memory, no real documents or people."""

from __future__ import annotations

import io
import zipfile


def png(text: str = "TEST") -> bytes:
    from PIL import Image, ImageDraw
    from PIL.PngImagePlugin import PngInfo

    image = Image.new("RGB", (200, 60), "white")
    ImageDraw.Draw(image).text((10, 20), text, fill="black")
    info = PngInfo()
    info.add_text("Author", "Иван Выдуманный")  # metadata that must disappear
    out = io.BytesIO()
    image.save(out, "PNG", pnginfo=info)
    return out.getvalue()


def jpeg_with_exif() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (120, 80), "blue")
    exif = Image.Exif()
    exif[0x013B] = "Иван Выдуманный"  # Artist
    exif[0x010F] = "FakeCam"  # Make
    out = io.BytesIO()
    image.save(out, "JPEG", exif=exif)
    return out.getvalue()


def pdf(text: str = "Тестовый документ без смысла") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.setAuthor("Иван Выдуманный")
    c.setTitle("Секретный заголовок")
    c.drawString(72, 750, text.encode("ascii", "replace").decode() if not text.isascii() else text)
    c.save()
    return out.getvalue()


def docx(text: str = "Тестовый документ Word без смысла", author: str = "Иван Выдуманный") -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="xml" ContentType="application/xml"/></Types>')
        z.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
        z.writestr("docProps/core.xml", '<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                   f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>{author}</dc:creator></cp:coreProperties>')
    return out.getvalue()


def exe_named_pdf() -> bytes:
    return b"MZ\x90\x00" + b"\x00" * 200  # a Windows executable header, whatever the name says
