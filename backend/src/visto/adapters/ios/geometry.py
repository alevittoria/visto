"""Screenshot pixels to gesture points; a ratio we cannot trust refuses the device."""

from dataclasses import dataclass

from visto.application.ports import PortError


@dataclass(frozen=True, slots=True)
class Frame:
    """Pixels are the screenshot, points are the gesture API. `scale` is a diagnostic
    mean only; `to_points` is the sole conversion authority, never derive from `scale`."""

    width: int
    height: int
    point_width: int
    point_height: int
    scale: float


def frame(
    pixel_width: int,
    pixel_height: int,
    point_width: int,
    point_height: int,
    *,
    tolerance: float = 0.02,
) -> Frame:
    if min(pixel_width, pixel_height, point_width, point_height) < 1:
        raise PortError("ios: invalid screen dimensions")
    x_scale = pixel_width / point_width
    y_scale = pixel_height / point_height
    # Relative to the larger axis so one tolerance holds for every display class.
    if abs(x_scale - y_scale) / max(x_scale, y_scale) > tolerance:
        raise PortError("ios: inconsistent screen scale")
    return Frame(pixel_width, pixel_height, point_width, point_height, (x_scale + y_scale) / 2)


def to_points(frame: Frame, x: int, y: int) -> tuple[int, int]:
    """Pixel to point per axis: halves round up, result clamped to the last point."""
    return (
        _axis(x, frame.width, frame.point_width),
        _axis(y, frame.height, frame.point_height),
    )


def _axis(value: int, pixels: int, points: int) -> int:
    # Exact integer floor(value * points / pixels + 1/2); built-in round() is banker's.
    # Clamping first keeps off-frame input on the nearest edge point.
    scaled = (2 * max(0, value) * points + pixels) // (2 * pixels)
    return min(scaled, points - 1)
