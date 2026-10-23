import pytest

from visto.adapters.ios.geometry import frame, to_points
from visto.application.ports import PortError


def test_integral_scales_are_accepted():
    two = frame(750, 1334, 375, 667)
    assert (two.width, two.height, two.point_width, two.point_height) == (750, 1334, 375, 667)
    assert two.scale == 2.0
    assert frame(1125, 2001, 375, 667).scale == 3.0


def test_non_integral_scale_is_supported():
    f = frame(1080, 1920, 414, 736)
    assert f.scale == pytest.approx(2.6087, abs=1e-4)


def test_non_uniform_scale_is_refused():
    with pytest.raises(PortError, match="ios: inconsistent screen scale"):
        frame(1080, 1920, 414, 667)


def test_tolerance_is_relative_to_the_larger_axis():
    assert frame(1000, 1000, 500, 510).scale == pytest.approx(1.9804, abs=1e-4)
    with pytest.raises(PortError, match="ios: inconsistent screen scale"):
        frame(1000, 1000, 500, 520)
    with pytest.raises(PortError, match="ios: inconsistent screen scale"):
        frame(1000, 1000, 500, 510, tolerance=0.01)


@pytest.mark.parametrize(
    "dims", [(0, 100, 50, 50), (100, -1, 50, 50), (100, 100, 0, 50), (100, 100, 50, -5)]
)
def test_invalid_dimensions_are_refused(dims):
    with pytest.raises(PortError, match="ios: invalid screen dimensions"):
        frame(*dims)


def test_points_round_half_away_from_zero_and_clamp():
    f = frame(1080, 1920, 414, 736)
    assert to_points(f, 0, 0) == (0, 0)
    assert to_points(f, 1079, 1919) == (413, 735)
    assert to_points(f, 540, 960) == (207, 368)
    half = frame(200, 200, 100, 100)
    assert to_points(half, 1, 1) == (1, 1)  # 0.5 rounds up, not to even
    assert to_points(half, 3, 5) == (2, 3)
    assert to_points(half, 199, 199) == (99, 99)
    assert to_points(half, 400, -4) == (99, 0)


def test_landscape_frame_uses_the_reported_orientation_dimensions():
    f = frame(1920, 1080, 736, 414)
    assert (f.point_width, f.point_height) == (736, 414)
    assert to_points(f, 1919, 1079) == (735, 413)
    assert to_points(f, 960, 540) == (368, 207)
