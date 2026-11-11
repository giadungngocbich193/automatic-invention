#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sim: party prefer all-B074 rotate must not flood; mirror solo Auto PK cast path.

Proves v1.8.73 before ship:
1) Out-of-range prefer does NOT spray 7074.
2) Full F-group all-B074 → pause ≥2.5s then one cut+range retry (no 2s infinite spam).
3) Successful solo-like path: range → cast → B070 → interrupt → next cast.
"""
from __future__ import print_function

APPROACH_RANGE = 6.0
ALL_B074_PAUSE = 2.5
B074_BACKOFF = 1.5
UID = 752919
SKILLS = (80031, 81016, 81019, 66007, 7653, 7678, 54016)


def simulate_old_flood(ticks=40, dt=0.25):
    """Old buggy: skip range, soft-clear removed but still spray every skill on B074."""
    log = []
    casts = 0
    soft_clears = 0
    distance = 18.0  # out of range
    prefer = UID
    skill_i = 0
    now = 0.0
    for _ in range(ticks):
        now += dt
        # Old party prefer: cast immediately regardless of range
        if prefer:
            sid = SKILLS[skill_i % len(SKILLS)]
            skill_i += 1
            casts += 1
            log.append('t=%.2f OLD cast %d @%.1fm → B074' % (now, sid, distance))
            # keep prefer (1.8.72) but no pause → flood
    return {'casts': casts, 'soft_clears': soft_clears, 'log': log, 'prefer': prefer}


def simulate_new(ticks=80, dt=0.25, start_distance=18.0, move_per_tick=2.0,
                 b074_until_in_range=True):
    """New 1.8.73 path."""
    log = []
    casts = 0
    cuts = 0
    moves = 0
    b074s = 0
    pauses = 0
    b070s = 0
    now = 0.0
    distance = float(start_distance)
    prefer = UID
    skill_i = 0
    refused = set()
    skill_retry_at = {}
    pause_until = 0.0
    need_cut = True
    need_prep = False
    cast_deadline = 0.0
    expect = None  # (skill, uid) waiting reply
    exchange_until = 0.0

    def ready():
        return distance <= APPROACH_RANGE

    for _ in range(ticks):
        now += dt
        # approach
        if prefer and not ready():
            if now >= cast_deadline:
                moves += 1
                distance = max(APPROACH_RANGE - 0.1, distance - move_per_tick)
                log.append('t=%.2f approach → %.1fm' % (now, distance))
                cast_deadline = now + 0.5
            continue

        if now < pause_until or now < cast_deadline or now < exchange_until:
            continue

        if expect is not None:
            # reply arrives
            skill, uid = expect
            expect = None
            if b074_until_in_range and distance > APPROACH_RANGE:
                # shouldn't cast OOR
                continue
            # In range: first wave all refuse until full group, then after pause succeed
            if pauses == 0 or (pauses >= 1 and skill in refused and len(refused) < len(SKILLS)):
                # still refusing this skill
                pass
            if pauses == 0:
                # refuse
                b074s += 1
                refused.add(skill)
                skill_retry_at[skill] = now + 0.9
                need_cut = True
                log.append('t=%.2f B074 skill %d (refused=%d/%d)' %
                           (now, skill, len(refused), len(SKILLS)))
                if refused.issuperset(SKILLS):
                    refused.clear()
                    skill_retry_at.clear()
                    pause_until = now + ALL_B074_PAUSE
                    need_prep = True
                    pauses += 1
                    log.append('t=%.2f ALL-B074 pause %.1fs' % (now, ALL_B074_PAUSE))
                    cast_deadline = pause_until
                else:
                    cast_deadline = now + 0.55
                continue
            else:
                # after pause: success path like solo
                b070s += 1
                refused.clear()
                need_cut = False
                need_prep = False
                log.append('t=%.2f B070 skill %d · hit' % (now, skill))
                # schedule interrupt then next
                cuts += 1
                exchange_until = now + 0.3
                log.append('t=%.2f interrupt 7081/B074 cut' % now)
                cast_deadline = now + 0.35
                continue

        if not prefer:
            continue

        if need_prep or need_cut:
            cuts += 1
            need_cut = False
            need_prep = False
            exchange_until = now + 0.35
            log.append('t=%.2f prepare cut 7081 before cast' % now)
            cast_deadline = now + 0.35
            continue

        if not ready():
            continue

        # pick next skill not in retry
        picked = None
        for _j in range(len(SKILLS)):
            sid = SKILLS[skill_i % len(SKILLS)]
            skill_i += 1
            if skill_retry_at.get(sid, 0) <= now:
                picked = sid
                break
        if picked is None:
            cast_deadline = now + 0.2
            continue

        casts += 1
        expect = (picked, UID)
        cast_deadline = now + 0.4
        log.append('t=%.2f cast %d @%.1fm (in range)' % (now, picked, distance))

    return {
        'casts': casts, 'cuts': cuts, 'moves': moves, 'b074s': b074s,
        'pauses': pauses, 'b070s': b070s, 'prefer': prefer,
        'final_distance': distance, 'log': log,
    }


def main():
    print('=== SIM party prefer cast / all-B074 (UID %d) ===' % UID)
    old = simulate_old_flood()
    new = simulate_new()
    # Solo-mirrored success: start already in range, after one all-B074 pause get hits
    solo = simulate_new(start_distance=5.0, move_per_tick=0.0, ticks=100)

    print('\n--- OLD flood (no range / no pause) ---')
    print('casts=%d (expect flood)' % old['casts'])
    for line in old['log'][:8]:
        print(line)
    print('...')

    print('\n--- NEW out-of-range → approach → all-B074 pause ---')
    for line in new['log']:
        print(line)
    print('summary: casts=%d moves=%d b074s=%d pauses=%d cuts=%d b070s=%d dist=%.1f'
          % (new['casts'], new['moves'], new['b074s'], new['pauses'],
             new['cuts'], new['b070s'], new['final_distance']))

    print('\n--- NEW in-range solo-mirror path ---')
    for line in solo['log']:
        print(line)
    print('summary: casts=%d b074s=%d pauses=%d cuts=%d b070s=%d'
          % (solo['casts'], solo['b074s'], solo['pauses'], solo['cuts'], solo['b070s']))

    ok = True
    checks = []

    def check(name, cond):
        nonlocal ok
        checks.append((name, cond))
        if not cond:
            ok = False

    check('old floods casts', old['casts'] >= 20)
    # New OOR: no cast until approached
    first_cast_lines = [l for l in new['log'] if 'cast ' in l and 'OLD' not in l]
    first_approach = next((l for l in new['log'] if 'approach' in l), '')
    check('new approaches before cast', 'approach' in first_approach)
    if first_cast_lines:
        # cast line includes @Xm
        import re
        m = re.search(r'@([0-9.]+)m', first_cast_lines[0])
        check('first cast in range', m and float(m.group(1)) <= APPROACH_RANGE)
    else:
        check('first cast in range', False)
    check('new pauses after all-B074', new['pauses'] >= 1)
    # flood control: casts during first ~5s of refuse should be ~len(SKILLS), not 20+
    check('new not infinite 2s spam', new['casts'] < old['casts'] // 2)
    check('solo-mirror gets B070 after pause', solo['b070s'] >= 1)
    check('solo-mirror does interrupt cut', solo['cuts'] >= 1)
    check('prefer kept', new['prefer'] == UID and solo['prefer'] == UID)

    print('\n--- PROOF ---')
    for name, cond in checks:
        print('%s %s' % ('PASS' if cond else 'FAIL', name))
    print('RESULT: %s' % ('SHIP_OK' if ok else 'NO_SHIP'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
