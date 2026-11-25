"""Turning an uploaded image into the files we store.

The upload itself is never stored. Pillow decodes it and the pixels are written
out again as fresh WebP files, so nothing rides along: no EXIF or XMP metadata
(which can hold a photo's GPS location), no comments, no second file appended
after the image data.

Memory matters more than speed here: the web task is small and shared with
every participant, and a tiny file can hold a huge image. So the size is
checked before decoding, JPEGs are decoded at reduced scale, images are shrunk
before any further copy is made, and the task decodes one upload at a time.
"""
import io
import os
import tempfile
import threading
import warnings
from contextlib import contextmanager
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

ACCEPTED_FORMATS = {'PNG', 'JPEG', 'WEBP'}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Checked from the header before decoding, so a small file that would expand
# to gigabytes of pixels (a "decompression bomb") is refused unopened. JPEGs
# decode at reduced scale, so they can be larger (24-megapixel phone photos);
# PNG and WebP decode at full size (about 300 MB for 16 megapixels of WebP).
MAX_PIXELS = {'JPEG': 25_000_000, 'PNG': 16_000_000, 'WEBP': 16_000_000}
# Longest side of each stored rendition. Images are only ever shrunk.
RENDITION_SIZES = {'display': 2048, 'thumb': 320}
CONTENT_TYPE = 'image/webp'
EXTENSION = 'webp'

_thread_lock = threading.Lock()
_LOCK_FILE = os.path.join(tempfile.gettempdir(), 'cloze-image-decode.lock')


@contextmanager
def _one_at_a_time():
    """Decode one upload at a time across every worker process and thread on
    this machine, so simultaneous uploads can't add up to more memory than one."""
    try:
        import fcntl
    except ImportError:  # no flock (Windows): one at a time per process
        with _thread_lock:
            yield
        return
    with open(_LOCK_FILE, 'a') as f:  # a fresh descriptor, so threads exclude each other too
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


class ImageRejected(ValueError):
    """The upload isn't an image we accept. The message is safe to show the researcher."""


@dataclass
class Rendition:
    data: bytes
    width: int
    height: int


@dataclass
class ProcessedImage:
    width: int
    height: int
    renditions: dict = field(default_factory=dict)


def _open(data):
    """Read the header only: format and dimensions, no pixels."""
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            img = Image.open(io.BytesIO(data))
        except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise ImageRejected('That file is not a PNG, JPEG or WebP image.') from None
    if img.format not in ACCEPTED_FORMATS:
        raise ImageRejected('Only PNG, JPEG and WebP images can be uploaded.')
    limit = MAX_PIXELS[img.format]
    if img.width * img.height > limit:
        raise ImageRejected(f'That image is too large. Use one under {limit // 1_000_000} megapixels.')
    return img


def _fit(size, longest):
    """size scaled down (never up) so its longer side is at most `longest`."""
    ratio = min(1.0, longest / max(size))
    return max(1, round(size[0] * ratio)), max(1, round(size[1] * ratio))


def _decode(data):
    """The image at display size at most, upright, in a fresh image that
    carries no metadata."""
    img = _open(data)
    longest = RENDITION_SIZES['display']
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        try:
            img.seek(0)  # first frame of an animated PNG or WebP
            if img.format == 'JPEG':
                # Decode at 1/2, 1/4 or 1/8 scale where that still covers the target.
                img.draft('RGB', _fit(img.size, longest))
            img.load()
            has_alpha = img.mode in ('RGBA', 'LA', 'PA') or (img.mode == 'P' and 'transparency' in img.info)
            mode = 'RGBA' if has_alpha else 'RGB'
            if img.mode != mode:
                img = img.convert(mode)
            img.thumbnail((longest, longest), Image.LANCZOS)  # in place
            img = ImageOps.exif_transpose(img)  # rotate the small copy, not the original
        except Exception:
            raise ImageRejected('That image could not be read. It may be damaged.') from None
    return Image.frombytes(img.mode, img.size, img.tobytes())


def _webp(img):
    out = io.BytesIO()
    img.save(out, 'WEBP', quality=85, method=4)
    return Rendition(out.getvalue(), img.width, img.height)


def process_image(data):
    """Validate an upload and build its renditions. Raises ImageRejected."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageRejected('That image is over 10 MB.')
    with _one_at_a_time():
        display = _decode(data)
        thumb = display.copy()
        thumb.thumbnail((RENDITION_SIZES['thumb'],) * 2, Image.LANCZOS)
        renditions = {'display': _webp(display), 'thumb': _webp(thumb)}
    return ProcessedImage(width=display.width, height=display.height, renditions=renditions)
