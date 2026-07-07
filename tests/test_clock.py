from visualgen.clock import VsyncClock


def test_vsync_clock_uses_injected_time():
    t = [0.0]
    clock = VsyncClock(time_fn=lambda: t[0])
    assert clock.now() == 0.0
    t[0] = 1.5
    assert clock.now() == 1.5


def test_vsync_clock_defaults_to_monotonic():
    clock = VsyncClock()
    a = clock.now()
    b = clock.now()
    assert b >= a
