"""Attachment files: limits, type by content, metadata removal, text extraction, safe names.

The type is decided by the file's own bytes (signature and structure), never by
the extension or the Content-Type header the browser sends. Metadata that can
identify a person — EXIF of photos (camera, GPS, time) and the author fields of
documents — is removed before anything is stored.
"""

from __future__ import annotations

import io
import os
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path

KINDS = {
    "pdf": ("application/pdf", ".pdf", "PDF"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx", "Word"),
    "jpeg": ("image/jpeg", ".jpg", "JPEG"),
    "png": ("image/png", ".png", "PNG"),
}
ALLOWED_TEXT = "PDF, DOCX, JPEG или PNG"
MAX_IMAGE_PIXELS = 40_000_000
MAX_DOCX_UNPACKED = 60 * 1024 * 1024
MAX_DOCX_ENTRIES = 1000


class AttachmentError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Limits:
    max_files: int
    max_bytes: int

    @property
    def max_mb(self) -> int:
        return self.max_bytes // (1024 * 1024)


def limits() -> Limits:
    """ATTACHMENT_MAX_FILES (per message, default 5) and ATTACHMENT_MAX_MB (per file, default 10)."""
    def number(name: str, default: int) -> int:
        try:
            return max(1, int(os.environ.get(name, default)))
        except ValueError:
            return default

    return Limits(max_files=number("ATTACHMENT_MAX_FILES", 5), max_bytes=number("ATTACHMENT_MAX_MB", 10) * 1024 * 1024)


def storage_dir() -> Path:
    """ATTACHMENTS_DIR: outside the public static files; `serve` points it into the state directory."""
    path = Path(os.environ.get("ATTACHMENTS_DIR") or ".local-state/attachments")
    path.mkdir(parents=True, exist_ok=True)
    return path


def sniff(data: bytes) -> str:
    """pdf | docx | jpeg | png by content; anything else is refused with a clear message."""
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = set(archive.namelist())
                infos = archive.infolist()
        except zipfile.BadZipFile:
            raise AttachmentError("bad_file", "Файл повреждён: архив Word не открывается.") from None
        if "[Content_Types].xml" in names and "word/document.xml" in names:
            if len(infos) > MAX_DOCX_ENTRIES or sum(i.file_size for i in infos) > MAX_DOCX_UNPACKED:
                raise AttachmentError("too_complex", "Документ Word слишком большой после распаковки.")
            return "docx"
    raise AttachmentError("unsupported_type", f"Такой тип файла не поддерживается. Можно прикрепить {ALLOWED_TEXT}.")


def check_size(size: int) -> None:
    limit = limits()
    if size == 0:
        raise AttachmentError("empty_file", "Файл пустой.")
    if size > limit.max_bytes:
        raise AttachmentError("too_large", f"Файл больше {limit.max_mb} МБ. Сожмите его или разделите на части.", status=413)


def safe_name(name: str | None, kind: str) -> str:
    """The original name for display and download: no paths, no control or special characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = unicodedata.normalize("NFC", base)
    base = "".join(ch for ch in base if unicodedata.category(ch)[0] != "C")
    base = re.sub(r'[<>:"|?*;=%\x00]', "_", base)
    base = re.sub(r"\s+", " ", base).strip(" .")
    stem, _, ext = base.rpartition(".")
    stem = (stem if ext else base)[:100].strip(" .") or "файл"
    return f"{stem}{KINDS[kind][1]}"  # the extension follows the real type, not the one the file claimed


# ---- metadata -------------------------------------------------------------------------

def _clean_image(data: bytes, kind: str) -> bytes:
    from PIL import Image, ImageOps

    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)  # keep the photo upright once EXIF is gone
            image.load()
            out = io.BytesIO()
            if kind == "jpeg":
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.save(out, "JPEG", quality=90, optimize=True)  # no exif=, no comments
            else:
                image.save(out, "PNG", optimize=True)  # no pnginfo: text chunks are dropped
            return out.getvalue()
    except Image.DecompressionBombError:
        raise AttachmentError("too_complex", "Изображение слишком большое по количеству точек.") from None
    except AttachmentError:
        raise
    except Exception:
        raise AttachmentError("bad_file", "Изображение повреждено и не открывается.") from None


CORE = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"/>')
APP = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties '
       'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"/>')
CUSTOM = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Properties '
          'xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties"/>')
DOCX_METADATA = {"docProps/core.xml": CORE, "docProps/app.xml": APP, "docProps/custom.xml": CUSTOM}


def _clean_docx(data: bytes) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            if info.filename in DOCX_METADATA:
                target.writestr(info.filename, DOCX_METADATA[info.filename])  # author, editor, company — gone
            else:
                target.writestr(info.filename, source.read(info.filename))
    return out.getvalue()


def _clean_pdf(data: bytes) -> bytes:
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import NameObject

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise AttachmentError("encrypted", "PDF защищён паролем — снимите защиту и прикрепите снова.")
        writer = PdfWriter(clone_from=reader)
        writer.metadata = None  # the Info dictionary: author, creator, producer, dates
        root = writer._root_object
        if NameObject("/Metadata") in root:
            del root[NameObject("/Metadata")]  # XMP metadata stream
        out = io.BytesIO()
        writer.write(out)
        return out.getvalue()
    except AttachmentError:
        raise
    except Exception:
        raise AttachmentError("bad_file", "PDF повреждён и не открывается.") from None


def strip_metadata(kind: str, data: bytes) -> bytes:
    if kind in ("jpeg", "png"):
        return _clean_image(data, kind)
    if kind == "docx":
        return _clean_docx(data)
    return _clean_pdf(data)


# ---- text ------------------------------------------------------------------------------

def extract_text(kind: str, data: bytes, limit: int = 20_000) -> str | None:
    """Text of pdf/docx for the content check; None for images or when nothing can be read."""
    try:
        if kind == "pdf":
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:30])
        elif kind == "docx":
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
            paragraphs = xml.split("</w:p>")
            text = "\n".join("".join(re.findall(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>", p)) for p in paragraphs)
            text = re.sub(r"&lt;", "<", re.sub(r"&gt;", ">", re.sub(r"&quot;", '"', text))).replace("&amp;", "&")
        else:
            return None
    except Exception:
        return None
    text = re.sub(r"[ \t]+", " ", text).strip()
    return text[:limit] or None


@dataclass
class Prepared:
    kind: str
    mime: str
    name: str
    data: bytes  # metadata removed


def prepare(raw: bytes, filename: str | None) -> Prepared:
    """Size and type checks, then metadata removal. Raises AttachmentError with a message for the user."""
    check_size(len(raw))
    kind = sniff(raw)
    clean = strip_metadata(kind, raw)
    return Prepared(kind=kind, mime=KINDS[kind][0], name=safe_name(filename, kind), data=clean)
