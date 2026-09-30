"""Upload policy for the whole app: one place for size limits and file-type checks.

Files are identified by their magic bytes and (for images) a real decode, never by the
client-supplied filename or MIME type alone.
"""
import io
import os
import zipfile
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename

MB = 1024 * 1024
MAX_IMAGE_BYTES = 5 * MB
MAX_RESUME_BYTES = 5 * MB
# Covers a screenshot/resume plus form fields; also bounds the legacy bulk /send (CSV + resume).
MAX_REQUEST_BYTES = 12 * MB

MAX_IMAGE_PIXELS = 40_000_000  # ~ 8K x 5K; stops decompression bombs before decoding
MAX_IMAGE_SIDE = 12_000
MIN_IMAGE_SIDE = 16

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
IMAGE_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
RESUME_TYPES = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


class UploadError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class ValidatedImage:
    data: bytes
    mime: str
    width: int
    height: int


def _read_limited(file_storage, limit, too_large_message):
    data = file_storage.stream.read(limit + 1)
    if len(data) > limit:
        raise UploadError(too_large_message, 413)
    if not data:
        raise UploadError("The uploaded file is empty.")
    return data


def _sniff_image(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if data.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def validate_image(file_storage):
    invalid = "Please upload a valid image (PNG, JPG or WEBP)."
    if file_storage is None or not file_storage.filename:
        raise UploadError("Choose a screenshot to upload.")

    extension = os.path.splitext(file_storage.filename)[1].lower()
    if extension not in IMAGE_EXTENSIONS:
        raise UploadError(invalid, 415)
    declared = (file_storage.mimetype or "").lower()
    if declared and declared != "application/octet-stream" and not declared.startswith("image/"):
        raise UploadError(invalid, 415)

    data = _read_limited(file_storage, MAX_IMAGE_BYTES, f"Image exceeds the maximum allowed size ({MAX_IMAGE_BYTES // MB} MB).")
    sniffed = _sniff_image(data)
    if sniffed is None:
        raise UploadError(invalid, 415)

    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format != sniffed:
                raise UploadError(invalid, 415)
            width, height = image.size
            if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
                raise UploadError("This image is too small to read. Upload a larger screenshot.")
            if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE or width * height > MAX_IMAGE_PIXELS:
                raise UploadError("Image dimensions are too large. Crop the screenshot and try again.", 413)
            image.verify()
    except UploadError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise UploadError(invalid, 415) from exc

    return ValidatedImage(data=data, mime=IMAGE_FORMATS[sniffed], width=width, height=height)


def _is_docx(data):
    if not data.startswith(b"PK\x03\x04"):
        return False
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
    except zipfile.BadZipFile:
        return False
    return "[Content_Types].xml" in names and "word/document.xml" in names


def validate_resume(file_storage):
    """Returns (data, safe_filename, mime) for a PDF or DOCX resume."""
    invalid = "Upload your resume as a PDF or DOCX file."
    if file_storage is None or not file_storage.filename:
        raise UploadError("Choose a resume file to upload.")

    extension = os.path.splitext(file_storage.filename)[1].lower()
    if extension not in RESUME_TYPES:
        raise UploadError(invalid, 415)

    data = _read_limited(file_storage, MAX_RESUME_BYTES, f"Resume exceeds the maximum allowed size ({MAX_RESUME_BYTES // MB} MB).")
    if extension == ".pdf" and not data.startswith(b"%PDF-"):
        raise UploadError(invalid, 415)
    if extension == ".docx" and not _is_docx(data):
        raise UploadError(invalid, 415)

    basename = file_storage.filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = secure_filename(os.path.splitext(basename)[0])[:80] or "resume"
    return data, f"{stem}{extension}", RESUME_TYPES[extension]
