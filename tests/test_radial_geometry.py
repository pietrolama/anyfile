import pytest

from anyfile.ui.radial_geometry import CENTER, Ring, clockwise_angle, groups, polar, step


@pytest.mark.parametrize("dx,dy,angle", [(0, -1, 0), (1, 0, 90), (0, 1, 180), (-1, 0, 270)])
def test_clockwise_angle_from_twelve(dx, dy, angle):
    assert clockwise_angle(dx, dy) == pytest.approx(angle)


def test_polar_roundtrip():
    for a in (0, 33, 90, 200, 359):
        x, y = polar(a, 10)
        assert clockwise_angle(x, y) == pytest.approx(a, abs=1e-6)


def test_hit():
    ring = Ring(inner=50, outer=150, count=4, reach=20)
    assert ring.hit(0, 0) == CENTER
    assert ring.hit(10, -100) == 0      # top, just right of 12 o'clock
    assert ring.hit(100, 10) == 1       # right
    assert ring.hit(-10, 100) == 2      # bottom
    assert ring.hit(-100, -10) == 3     # left
    assert ring.hit(0, -165) == 0       # beyond the ring but within the tolerance
    assert ring.hit(0, -200) is None    # outside: closes the menu
    assert Ring(50, 150, 0).hit(0, -100) is None


def test_groups_and_step():
    assert groups(["a", "a", "b", "a"]) == [("a", 0, 2), ("b", 2, 3), ("a", 3, 4)]
    assert step(None, 1, 5) == 0 and step(None, -1, 5) == 4
    assert step(4, 1, 5) == 0 and step(0, -1, 5) == 4
    assert step(CENTER, 1, 3) == 0 and step(1, 1, 0) is None
