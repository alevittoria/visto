"""Screenshot framing checks shared by every Appium platform."""

import struct
import zlib

from visto.application.ports import PortError


def png_size(content: bytes, component: str) -> tuple[int, int]:
    """Check chunk framing/CRC; image interpretation belongs to the model."""
    if content[:8] != b"\x89PNG\r\n\x1a\n":
        raise PortError(f"{component}: screenshot is not PNG")
    offset, dimensions, ended, image_data = 8, None, False, False
    while offset + 12 <= len(content):
        length = struct.unpack(">I", content[offset : offset + 4])[0]
        kind = content[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(content):
            break
        payload = content[offset + 8 : end - 4]
        checksum = struct.unpack(">I", content[end - 4 : end])[0]
        if zlib.crc32(kind + payload) != checksum:
            raise PortError(f"{component}: corrupt screenshot")
        if dimensions is None:
            if kind != b"IHDR" or length != 13:
                raise PortError(f"{component}: invalid PNG header")
            dimensions = struct.unpack(">II", payload[:8])
        if kind == b"IDAT":
            image_data = True
        if kind == b"IEND":
            ended = length == 0 and end == len(content)
            break
        offset = end
    if not ended or not image_data or not dimensions or min(dimensions) < 1:
        raise PortError(f"{component}: incomplete screenshot")
    return dimensions
