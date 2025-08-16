from decimal import Decimal
from backend.app.engine import GridEngine

def ns(i):  # helper to make nanosecond stamps
    return 1_000_000_000 * i

def test_deterministic_counting():
    # path: 2.50 -> 2.49 -> 2.50 -> 2.51
    eng = GridEngine(Decimal("0.01"), Decimal("0.01"))
    seq = [
        (Decimal("2.50"), ns(0)),
        (Decimal("2.49"), ns(1)),  # arms 2.50 on cross down
        (Decimal("2.50"), ns(2)),
        (Decimal("2.51"), ns(3)),  # closes 2.50 at 2.51
    ]
    for p, t in seq:
        eng.feed(p, t)
    out = eng.finalize()
    assert out["totals"].get("2.50", 0) == 1

def test_gap_crossing_close():
    # arm 2.50 by crossing down through it, then gap up over 2.51 target
    eng = GridEngine(Decimal("0.01"), Decimal("0.01"))
    seq = [
        (Decimal("2.505"), ns(0)),
        (Decimal("2.495"), ns(1)),  # cross down through 2.50, arm
        (Decimal("2.515"), ns(2)),  # cross up through 2.51 target, close
    ]
    for p, t in seq:
        eng.feed(p, t)
    out = eng.finalize()
    assert out["totals"].get("2.50", 0) == 1

def test_three_decimal_no_premature_arm():
    # 2.275 should NOT arm 2.27 for step 0.01
    eng = GridEngine(Decimal("0.01"), Decimal("0.01"))
    seq = [
        (Decimal("2.290"), ns(0)),
        (Decimal("2.275"), ns(1)),  # above 2.27, no arm
        (Decimal("2.269"), ns(2)),  # cross down through 2.27, arm
        (Decimal("2.280"), ns(3)),  # cross up through 2.28 target, close 2.27
    ]
    for p, t in seq:
        eng.feed(p, t)
    out = eng.finalize()
    assert out["totals"].get("2.27", 0) == 1

def test_re_arm_required():
    eng = GridEngine(Decimal("0.01"), Decimal("0.01"))
    seq = [
        (Decimal("2.60"), ns(0)),
        (Decimal("2.49"), ns(1)),  # arms many levels including 2.50
        (Decimal("2.52"), ns(2)),  # closes 2.50
        (Decimal("2.51"), ns(3)),
        (Decimal("2.52"), ns(4)),  # should not count again until re-armed
    ]
    for p, t in seq:
        eng.feed(p, t)
    out = eng.finalize()
    assert out["totals"].get("2.50", 0) == 1
