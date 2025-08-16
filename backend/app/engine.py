from __future__ import annotations
from decimal import Decimal, getcontext, ROUND_FLOOR
from typing import Dict, List, Optional

getcontext().prec = 28  # high precision for money

def is_on_grid(x: Decimal, step: Decimal) -> bool:
    """True if x is an exact integer multiple of step (no rounding)."""
    q = x / step
    return q == q.to_integral_value()

def floor_to_step(price: Decimal, step: Decimal) -> Decimal:
    return (price / step).to_integral_value(rounding=ROUND_FLOOR) * step

def crossed_up(p0: Decimal, p1: Decimal, target: Decimal) -> bool:
    return p0 < target <= p1

def crossed_down(p0: Decimal, p1: Decimal, level: Decimal) -> bool:
    return p0 > level >= p1

class GridEngine:
    """
    Long-only grid cycle counter.

    exact_only=False (default): gap-aware crossing logic.
    exact_only=True  : only exact prints at L (arm) and L+spread (close).
                       Prints like 2.245 on a 0.01 grid are ignored.
    Optional level_min/level_max filter counts cycles only for bases in that band.
    """
    def __init__(
        self,
        step: Decimal,
        spread: Decimal,
        exact_only: bool = False,
        level_min: Optional[Decimal] = None,
        level_max: Optional[Decimal] = None,
    ):
        if step <= 0 or spread <= 0:
            raise ValueError("step and spread must be positive Decimals")

        self.step = step
        self.spread = spread
        self.exact_only = exact_only
        self.level_min = level_min
        self.level_max = level_max

        self.armed: Dict[Decimal, bool] = {}
        self.armed_ns: Dict[Decimal, int] = {}

        self.cycles: Dict[Decimal, int] = {}
        self.first_close_ns: Dict[Decimal, int] = {}
        self.last_close_ns: Dict[Decimal, int] = {}
        self.durations_s: Dict[Decimal, List[float]] = {}

        self.prev_price: Optional[Decimal] = None
        self.prev_ns: Optional[int] = None
        self.samples: int = 0

    def _in_band(self, L: Decimal) -> bool:
        if self.level_min is not None and L < self.level_min:
            return False
        if self.level_max is not None and L > self.level_max:
            return False
        return True

    def _arm(self, L: Decimal, ns: int):
        if not self._in_band(L):
            return
        if not self.armed.get(L, False):
            self.armed[L] = True
            self.armed_ns[L] = ns

    def _close(self, L: Decimal, ns: int):
        if not self._in_band(L):
            return
        self.cycles[L] = self.cycles.get(L, 0) + 1
        self.last_close_ns[L] = ns
        if L not in self.first_close_ns:
            self.first_close_ns[L] = ns
        arm_ns = self.armed_ns.get(L)
        if arm_ns is not None:
            dur = (ns - arm_ns) / 1_000_000_000
            self.durations_s.setdefault(L, []).append(dur)
        self.armed[L] = False
        self.armed_ns.pop(L, None)

    def _close_if_hit(self, p0: Decimal, p1: Decimal, L: Decimal, ns: int):
        if self.armed.get(L, False):
            T = L + self.spread
            if crossed_up(p0, p1, T):
                self._close(L, ns)

    def feed(self, price: Decimal, ns: int):
        """Feed one tick. price must be Decimal-from-string, ns=nanoseconds int."""
        self.samples += 1

        # Exact-only: only act on exact base/target prints
        if self.exact_only:
            Lc = price - self.spread
            if is_on_grid(Lc, self.step) and self.armed.get(Lc, False):
                self._close(Lc, ns)
            if is_on_grid(price, self.step):
                self._arm(price, ns)
            self.prev_price, self.prev_ns = price, ns
            return

        # Crossing logic
        if self.prev_price is None:
            self.prev_price, self.prev_ns = price, ns
            return

        p0, p1 = self.prev_price, price

        if p1 < p0:
            # enumerate grid levels crossed down
            L = floor_to_step(p0, self.step)
            end_L = floor_to_step(p1, self.step)
            while L >= end_L:
                if crossed_down(p0, p1, L):
                    self._arm(L, ns)
                L -= self.step

        elif p1 > p0:
            # check armed levels for target crosses
            for L in list(self.armed.keys()):
                if self.armed[L]:
                    self._close_if_hit(p0, p1, L, ns)

        self.prev_price, self.prev_ns = p1, ns

    @staticmethod
    def _median(xs: List[float]) -> Optional[float]:
        n = len(xs)
        if n == 0:
            return None
        xs = sorted(xs)
        m = n // 2
        return xs[m] if n % 2 else (xs[m - 1] + xs[m]) / 2

    def finalize(self):
        # Keep exact string of Decimal to avoid forced 2dp formatting.
        totals = {str(k): v for k, v in sorted(self.cycles.items(), key=lambda kv: kv[0])}
        top_rows: List[Dict] = []
        for L, cnt in sorted(self.cycles.items(), key=lambda kv: kv[1], reverse=True)[:25]:
            top_rows.append({
                "level": str(L),
                "cycles": cnt,
                "first_close_ns": self.first_close_ns.get(L),
                "last_close_ns": self.last_close_ns.get(L),
                "median_secs": self._median(self.durations_s.get(L, [])),
            })
        return {"totals": totals, "top_levels": top_rows, "samples": self.samples}
