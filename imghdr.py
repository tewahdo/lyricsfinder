# Minimal imghdr replacement to detect common image types.
# This is intentionally small and only implements the parts used by
# python-telegram-bot (imghdr.what). It will be imported from the
# project root before the stdlib version, so it works even if the
# system Python is missing imghdr (Python 3.14 removal or similar).

from __future__ import annotations
from typing import Optional

def _is_jpeg(h: bytes) -> bool:
    return h.startswith(b"\xff\xd8")

def _is_png(h: bytes) -> bool:
    return h.startswith(b"\x89PNG\r\n\x1a\n")

def _is_gif(h: bytes) -> bool:
    return h[:6] in (b"GIF87a", b"GIF89a")

def _is_bmp(h: bytes) -> bool:
    return h.startswith(b"BM")

def _is_webp(h: bytes) -> bool:
    # WebP: RIFF....WEBP
    return len(h) >= 12 and h[0:4] == b"RIFF" and h[8:12] == b"WEBP"


def what(file: object, h: Optional[bytes] = None) -> Optional[str]:
    """Return a string describing the image type, or None.

    file may be a filename or a file-like object. h, if provided, should
    be the header bytes to inspect.
    """
    # If header not provided, try to obtain it from file
    if h is None:
        try:
            # If file is header bytes already (bytes/bytearray), use it
            if isinstance(file, (bytes, bytearray)):
                h = bytes(file)
            # If file is a path-like string, open it
            elif isinstance(file, str):
                with open(file, "rb") as f:
                    h = f.read(32)
            else:
                # Assume file-like
                pos = None
                try:
                    pos = file.tell()
                except Exception:
                    pos = None
                try:
                    h = file.read(32)
                except Exception:
                    return None
                # reset the file position if possible
                try:
                    if pos is not None:
                        file.seek(pos)
                except Exception:
                    pass
        except Exception:
            return None

    if not h:
        return None
    if isinstance(h, str):
        h = h.encode("utf-8", errors="ignore")

    if _is_jpeg(h):
        return "jpeg"
    if _is_png(h):
        return "png"
    if _is_gif(h):
        return "gif"
    if _is_webp(h):
        return "webp"
    if _is_bmp(h):
        return "bmp"
    return None
