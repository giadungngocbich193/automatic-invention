# -*- coding: utf-8 -*-
"""Sim: Auto PK approach F1=6m / F2=12m; move stops at page range."""
from __future__ import annotations

AUTO_PK_APPROACH_BY_PAGE = {'F1': 6.0, 'F2': 12.0, 'F3': 6.0}
AUTO_PK_APPROACH_RANGE = 6.0


def auto_pk_approach_range(page):
    return float(AUTO_PK_APPROACH_BY_PAGE.get(str(page), AUTO_PK_APPROACH_RANGE))


def ready_and_stop(page, distance):
    rng = auto_pk_approach_range(page)
    if distance <= rng:
        return True, None
    stop_at = max(1.0, rng - 0.5)
    frac = (distance - stop_at) / distance if distance > stop_at else 0.0
    return False, stop_at, frac


def main():
    ok, _ = ready_and_stop('F1', 5.5)
    assert ok
    ready, stop_at, frac = ready_and_stop('F1', 15.0)
    assert not ready and abs(stop_at - 5.5) < 0.01
    ready, stop_at, frac = ready_and_stop('F2', 15.0)
    assert not ready and abs(stop_at - 11.5) < 0.01
    # Old bug: always stop_at=4 → bow pulled in
    old_stop = 4.0
    assert stop_at > old_stop + 5
    ok2, _ = ready_and_stop('F2', 11.0)
    assert ok2
    print('SHIP_OK approach_per_page F1=6 F2=12')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
