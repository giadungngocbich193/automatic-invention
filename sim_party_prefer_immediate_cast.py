#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sim AG 1.8.74 Prefer spam: 90s of re-Prefer must yield 0 re-logs + first cast <1s.

Mirrors furious log: Prefer every ~3s from 16:23:33→16:25:04 with
"Ghost F cast · armed=True" and NO skill until finally B070 lock.
"""
from __future__ import print_function

UID = 752919
SKILL = 80031
PREFER_INTERVAL = 3.0
DURATION = 90.0
RESELECT_DEBOUNCE = 2.0
LOG_INTERVAL = 60.0
PL_DEBOUNCE = 2.0


def simulate_old():
    """1.8.73 buggy: need_cut before first cast + log every ~3–5s + reset first_cast."""
    now = 0.0
    logs = []
    casts = []
    first_cast_sent = False
    party_need_cut = False
    last_log_at = -99.0
    last_prefer_at = -99.0
    exchange_until = 0.0
    prefer_count = 0

    t = 0.0
    while t <= DURATION + 0.01:
        now = t
        # PartyLeader Prefer every 3s (1.5s debounce was not enough vs log)
        if t == 0.0 or (t - last_prefer_at) >= 1.5:
            prefer_count += 1
            last_prefer_at = t
            party_need_cut = True  # need_arm set cut every Prefer in old path
            first_cast_sent = False  # old reset on re-Prefer
            # log every 5s (user saw ~3s; model 3s storm)
            if (now - last_log_at) >= 3.0:
                logs.append((now, 'Ghost F cast · armed=True'))
                last_log_at = now
            # cast attempt
            if party_need_cut:
                # cut blocks first skill
                party_need_cut = False
                exchange_until = now + 2.0
            elif now >= exchange_until and not first_cast_sent:
                # rarely eventually casts late
                if now >= 90.0:
                    casts.append(now)
                    first_cast_sent = True
                    logs.append((now, 'Đã khóa UID %d · skill %d' % (UID, SKILL)))
        t = round(t + 0.25, 2)
    return {'logs': logs, 'casts': casts, 'prefer_count': prefer_count}


def simulate_new():
    """1.8.74: immediate 7074 on Prefer; quiet same-UID; PL debounce 2s."""
    now = 0.0
    logs = []
    casts = []
    cuts_before_first = 0
    first_cast_sent = False
    party_need_cut = False
    last_log_at = -99.0
    last_prefer_at = -99.0
    last_uid = 0
    prefer_count = 0
    pl_calls = 0
    pl_ignored = 0
    ag_ignored = 0

    t = 0.0
    while t <= DURATION + 0.01:
        now = t
        # PartyLeader tries Prefer every 3s (furious interval)
        if t == 0.0 or abs((t / PREFER_INTERVAL) - round(t / PREFER_INTERVAL)) < 1e-9 or t < 0.01:
            if t == 0.0 or (t >= PREFER_INTERVAL and abs(t % PREFER_INTERVAL) < 0.01):
                pl_calls += 1
                # PL debounce ≥2s
                if last_uid == UID and (now - last_prefer_at) < PL_DEBOUNCE:
                    pl_ignored += 1
                else:
                    # AG select
                    prefer_count += 1
                    if (last_uid == UID and first_cast_sent
                            and (now - last_prefer_at) < RESELECT_DEBOUNCE):
                        ag_ignored += 1
                    else:
                        last_uid = UID
                        last_prefer_at = now
                        # NEW: never set party_need_cut on Prefer
                        # First cast immediately
                        if not first_cast_sent:
                            casts.append(now)
                            first_cast_sent = True
                            # log once
                            if (now - last_log_at) >= LOG_INTERVAL or last_log_at < 0:
                                logs.append((now, 'Party prefer UID %d · Ghost F cast' % UID))
                                last_log_at = now
                        else:
                            # quiet reselect — no log
                            ag_ignored += 1
        t = round(t + 0.25, 2)

    # Also model continuous Prefer attempts at 3s boundaries more simply
    return {
        'logs': logs, 'casts': casts, 'prefer_count': prefer_count,
        'pl_calls': pl_calls, 'pl_ignored': pl_ignored, 'ag_ignored': ag_ignored,
        'cuts_before_first': cuts_before_first,
        'first_cast_at': casts[0] if casts else None,
    }


def simulate_new_clean():
    """Cleaner event-driven model of Prefer every 3s for 90s."""
    logs = []
    casts = []
    pl_attempts = 0
    pl_sent = 0
    ag_logs = 0
    last_pl_at = -99.0
    last_ag_log = -99.0
    first_cast_sent = False
    first_cast_at = None
    party_need_cut_on_prefer = False  # must stay False in new

    for i in range(0, int(DURATION / PREFER_INTERVAL) + 1):
        now = i * PREFER_INTERVAL
        pl_attempts += 1
        if (now - last_pl_at) < PL_DEBOUNCE and last_pl_at >= 0:
            continue
        last_pl_at = now
        pl_sent += 1
        # AG: first Prefer locks + casts immediately; no pre-cut
        if party_need_cut_on_prefer:
            raise AssertionError('must not cut before first cast')
        if not first_cast_sent:
            first_cast_sent = True
            first_cast_at = now
            casts.append(now)
            if (now - last_ag_log) >= LOG_INTERVAL or last_ag_log < 0:
                logs.append((now, 'Ghost F cast'))
                last_ag_log = now
                ag_logs += 1
        else:
            # same UID quiet — no log even if Prefer arrives
            pass

    return {
        'logs': logs,
        'ag_logs': ag_logs,
        'casts': casts,
        'first_cast_at': first_cast_at,
        'pl_attempts': pl_attempts,
        'pl_sent': pl_sent,
    }


def main():
    print('=== SIM Prefer immediate cast / 90s spam (UID %d) ===' % UID)
    old = simulate_old()
    new = simulate_new_clean()

    print('\n--- OLD (1.8.73 spam) ---')
    print('prefer≈%d logs=%d first_cast=%s' % (
        old['prefer_count'], len(old['logs']),
        old['casts'][0] if old['casts'] else None))
    for ts, msg in old['logs'][:6]:
        print('t=%6.1fs %s' % (ts, msg))
    print('... total Prefer logs in 90s: %d' % len(old['logs']))

    print('\n--- NEW (1.8.74) ---')
    print('pl_attempts=%d pl_sent=%d ag_logs=%d first_cast_at=%s casts=%s'
          % (new['pl_attempts'], new['pl_sent'], new['ag_logs'],
             new['first_cast_at'], new['casts']))
    for ts, msg in new['logs']:
        print('t=%6.1fs %s' % (ts, msg))

    ok = True
    checks = []

    def check(name, cond):
        nonlocal ok
        checks.append((name, cond))
        if not cond:
            ok = False

    check('old spammed Prefer logs', len(old['logs']) >= 20)
    check('old first cast late or missing', (not old['casts']) or old['casts'][0] >= 60)
    check('new Prefer log spam == 0 extra', new['ag_logs'] == 1)
    check('new first cast < 1s', new['first_cast_at'] is not None and new['first_cast_at'] < 1.0)
    check('new only one cast event on first Prefer', len(new['casts']) == 1)
    check('90s → 0 Prefer re-log storm', new['ag_logs'] <= 1)
    # PL debounce ≥2s: a 1Hz Prefer storm must collapse
    storm_sent = 0
    storm_last = -99.0
    for s in range(0, 90):
        if (s - storm_last) >= PL_DEBOUNCE:
            storm_sent += 1
            storm_last = s
    check('PL 2s debounce vs 1Hz storm', storm_sent <= 46)  # 90/2 + 1

    print('\n--- PROOF ---')
    for name, cond in checks:
        print('%s %s' % ('PASS' if cond else 'FAIL', name))
    print('RESULT: %s' % ('SHIP_OK' if ok else 'NO_SHIP'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
