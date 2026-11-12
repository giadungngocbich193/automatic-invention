#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simulate the furious party Prefer→B074→soft-clear→Prefer loop.

Proves v1.8.72 / PL 1.0.11 stops the re-arm spam before ship.
"""
from __future__ import print_function

PARTY_PREFER_B074_BACKOFF = 1.5
UID = 752919
SKILL = 80031


def old_unreachable(reason):
    text = str(reason or '').casefold()
    return any(token in text for token in (
        'b074', 'từ chối đánh', 'ra vùng', 'vượt bán kính',
        'biến mất', 'không còn hợp lệ', 'đã chết', 'protected',
    ))


def new_unreachable(reason):
    text = str(reason or '').casefold()
    if 'b074' in text or 'từ chối đánh' in text:
        return False
    return any(token in text for token in (
        'ra vùng', 'vượt bán kính',
        'biến mất', 'không còn hợp lệ', 'đã chết', 'protected',
    ))


def simulate(mode, ticks=20, tick_dt=0.25):
    """mode: 'old' | 'new' — models the user log loop every ~2–3s."""
    log = []
    runtime = {
        'party_sync_uid': 0,
        'party_hold_fight': False,
        'party_b074_backoff_until': 0.0,
        'party_b074_uid': 0,
        'skill_retry_at': {},
        'armed': False,
        'paused': False,
        'target': 0,
    }
    pl = {
        'last_uid': 0,
        'last_select_at': -99.0,
        'refuse_uid': 0,
        'refuse_backoff_until': 0.0,
        'prefer_count': 0,
        'rearm_count': 0,
        'ignored_backoff': 0,
    }
    soft_clears = 0
    b074_retries = 0
    casts = 0
    now = 0.0

    def soft_clear(reason):
        nonlocal soft_clears
        soft_clears += 1
        runtime['party_sync_uid'] = 0
        runtime['armed'] = False
        runtime['paused'] = True
        runtime['target'] = 0
        log.append('t=%.2f soft-clear · %s' % (now, reason))

    def handle_b074():
        nonlocal b074_retries
        b074_retries += 1
        runtime['party_b074_backoff_until'] = now + PARTY_PREFER_B074_BACKOFF
        runtime['party_b074_uid'] = UID
        runtime['party_hold_fight'] = False
        runtime['party_sync_uid'] = UID
        runtime['skill_retry_at'][SKILL] = now + 0.75
        # keep armed / target
        log.append('t=%.2f B074 → retry next skill (giữ prefer UID %d · backoff %.1fs)'
                   % (now, UID, PARTY_PREFER_B074_BACKOFF))

    def prefer():
        pl['prefer_count'] += 1
        # PL local debounce 1.5s
        if UID == pl['last_uid'] and (now - pl['last_select_at']) < 1.5:
            log.append('t=%.2f Prefer ignored (PL 1.5s debounce)' % now)
            return 'debounce'
        # PL refuse backoff (new)
        if mode == 'new' and UID == pl['refuse_uid'] and now < pl['refuse_backoff_until']:
            pl['ignored_backoff'] += 1
            log.append('t=%.2f Prefer ignored (PL refuse backoff)' % now)
            return 'pl_backoff'
        # AG B074 backoff if already armed (new)
        if mode == 'new':
            if (runtime['armed'] and not runtime['paused']
                    and runtime['party_sync_uid'] == UID
                    and UID == runtime['party_b074_uid']
                    and now < runtime['party_b074_backoff_until']):
                pl['ignored_backoff'] += 1
                pl['refuse_uid'] = UID
                pl['refuse_backoff_until'] = runtime['party_b074_backoff_until']
                log.append('t=%.2f Prefer ignored (AG B074 re-arm debounce)' % now)
                return 'ag_backoff'
        # If cleared / not running → re-arm (the furious loop)
        if not runtime['armed'] or runtime['paused'] or runtime['party_sync_uid'] != UID:
            pl['rearm_count'] += 1
            runtime['armed'] = True
            runtime['paused'] = False
            runtime['party_sync_uid'] = UID
            runtime['target'] = UID
            pl['last_uid'] = UID
            pl['last_select_at'] = now
            log.append('t=%.2f Prefer+re-arm UID %d' % (now, UID))
            return 'rearm'
        # Already armed same UID
        runtime['party_sync_uid'] = UID
        runtime['target'] = UID
        pl['last_uid'] = UID
        pl['last_select_at'] = now
        log.append('t=%.2f Prefer UID %d (already armed)' % (now, UID))
        return 'prefer'

    def cast_and_b074():
        nonlocal casts
        if not (runtime['armed'] and runtime['party_sync_uid'] == UID and not runtime['paused']):
            return
        casts += 1
        log.append('t=%.2f cast skill %d on prefer UID %d' % (now, SKILL, UID))
        reason = 'server từ chối đánh (B074)'
        if mode == 'old':
            if old_unreachable(reason):
                soft_clear(reason)
            else:
                handle_b074()
        else:
            # new: never soft-clear on B074
            if new_unreachable(reason):
                soft_clear(reason)
            else:
                handle_b074()
                pl['refuse_uid'] = UID
                pl['refuse_backoff_until'] = runtime['party_b074_backoff_until']

    # Exact user loop: Prefer → cast → B074 → (old: clear) → Prefer again ~2–3s
    prefer()
    for i in range(ticks):
        now += tick_dt
        # cast shortly after arm if ready
        if runtime['armed'] and not runtime['paused'] and runtime['party_sync_uid'] == UID:
            # skill cooldown gate
            if runtime['skill_retry_at'].get(SKILL, 0) <= now:
                cast_and_b074()
        # PartyLeader Prefer spam every ~2.5s (furious log)
        if i > 0 and abs((now % 2.5) - 0) < tick_dt:
            prefer()

    return {
        'mode': mode,
        'soft_clears': soft_clears,
        'b074_retries': b074_retries,
        'casts': casts,
        'prefer_count': pl['prefer_count'],
        'rearm_count': pl['rearm_count'],
        'ignored_backoff': pl['ignored_backoff'],
        'final_prefer_uid': runtime['party_sync_uid'],
        'final_armed': runtime['armed'] and not runtime['paused'],
        'log': log,
    }


def main():
    print('=== SIM party Prefer↔B074 loop (UID %d skill %d) ===' % (UID, SKILL))
    old = simulate('old')
    new = simulate('new')
    print('\n--- OLD (buggy: soft-clear on B074) ---')
    for line in old['log']:
        print(line)
    print('summary old: soft_clears=%d rearm=%d casts=%d prefers=%d b074_retries=%d'
          % (old['soft_clears'], old['rearm_count'], old['casts'],
             old['prefer_count'], old['b074_retries']))

    print('\n--- NEW (v1.8.72: keep prefer + debounce) ---')
    for line in new['log']:
        print(line)
    print('summary new: soft_clears=%d rearm=%d casts=%d prefers=%d'
          ' b074_retries=%d ignored_backoff=%d final_prefer=%d armed=%s'
          % (new['soft_clears'], new['rearm_count'], new['casts'],
             new['prefer_count'], new['b074_retries'], new['ignored_backoff'],
             new['final_prefer_uid'], new['final_armed']))

    # Proof gates — must all pass to ship
    ok = True
    checks = []
    def check(name, cond):
        nonlocal ok
        checks.append((name, cond))
        if not cond:
            ok = False

    check('old reproduced soft-clear loop', old['soft_clears'] >= 2 and old['rearm_count'] >= 2)
    check('new soft_clears==0 on B074', new['soft_clears'] == 0)
    check('new keeps prefer UID', new['final_prefer_uid'] == UID and new['final_armed'])
    check('new uses B074 retry path', new['b074_retries'] >= 1)
    check('new Prefer re-arm not forever', new['rearm_count'] <= 1)
    check('new backoff ignores Prefer spam', new['ignored_backoff'] >= 1)
    # no soft-clear→rearm oscillation: rearm stays at initial arm only
    check('loop stopped (rearm << old)', new['rearm_count'] < old['rearm_count'])

    print('\n--- PROOF ---')
    for name, cond in checks:
        print('%s %s' % ('PASS' if cond else 'FAIL', name))
    print('RESULT: %s' % ('SHIP_OK' if ok else 'NO_SHIP'))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
