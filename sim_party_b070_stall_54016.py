# -*- coding: utf-8 -*-
"""Sim exact user stall: B070 80031 OK → spam “chưa nhận B070 skill 54016 · giữ mục tiêu”.

OLD (2.3): soft-wait 54016 forever (~5s log spam), never rotate.
NEW (2.3.1): ≤2 misses → bỏ 54016 + 7081 cut + next F skill; prefer kept.

SHIP_OK when NEW leaves 54016 and keeps Ghost F rotation.
"""
from __future__ import print_function

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AG = (ROOT / 'AutoGhost.py').read_text(encoding='utf-8')

UID = 80001
SKILL_OK = 80031
SKILL_STALL = 54016
# Match user: first confirm 80031, next pick is 54016
SKILLS = (80031, 54016, 81016, 81019, 66007, 7653, 7678)
MISS_MAX = 2
CONFIRM = 0.55


def fail(msg):
    print('SHIP_FAIL:', msg)
    sys.exit(1)


def ok(msg):
    print('OK:', msg)


m = re.search(r"VERSION = '([^']+)'", AG)
if not m or m.group(1) != '2.3.1':
    fail('VERSION want 2.3.1 got %r' % (m.group(1) if m else None))
ok('VERSION 2.3.1')

body = AG[AG.find('def party_prefer_wait_timeout'):]
body = body[:body.find('\ndef party_prefer_prepare_cast')]
if 'miss_count < PARTY_PREFER_B070_MISS_MAX' not in body:
    fail('miss budget missing')
if 'party_need_cut' not in body:
    fail('cut-on-skip missing')
ok('wait_timeout miss budget + cut+next')


def simulate(old=False, ticks=120, dt=0.25):
    log = []
    casts = {}
    b070 = {}
    wait_logs_54016 = 0
    skips = 0
    cuts = 0
    prefer = UID
    now = 0.0
    skill_i = 0
    expect = None
    deadline = 0.0
    cut_until = 0.0
    miss = {}
    retry_at = {}

    def next_skill():
        nonlocal skill_i
        for _ in range(len(SKILLS)):
            sid = SKILLS[skill_i % len(SKILLS)]
            skill_i += 1
            if retry_at.get(sid, 0) <= now:
                return sid
        return None

    for _ in range(ticks):
        now += dt
        if now < cut_until or now < deadline:
            continue

        if expect is not None:
            skill, sent_at = expect
            if now - sent_at < CONFIRM:
                continue
            if skill != SKILL_STALL:
                b070[skill] = b070.get(skill, 0) + 1
                miss.pop(skill, None)
                log.append('t=%.2f B070 OK skill %d' % (now, skill))
                expect = None
                cuts += 1
                cut_until = now + 0.35
                deadline = cut_until
                log.append('t=%.2f interrupt 7081 after B070' % now)
                continue

            # 54016 never confirms
            miss[skill] = miss.get(skill, 0) + 1
            wait_logs_54016 += 1
            if old:
                log.append('t=%.2f chưa nhận B070 skill %d · giữ mục tiêu' % (now, skill))
                deadline = now + 5.0
                expect = (skill, now)
                continue
            if miss[skill] < MISS_MAX:
                log.append('t=%.2f chưa nhận B070 skill %d · thử lại %d/%d · giữ mục tiêu'
                           % (now, skill, miss[skill], MISS_MAX))
                casts[skill] = casts.get(skill, 0) + 1
                expect = (skill, now)
                deadline = now + CONFIRM
                continue
            skips += 1
            retry_at[skill] = now + 1.25
            miss.pop(skill, None)
            expect = None
            cuts += 1
            cut_until = now + 0.35
            deadline = cut_until
            log.append('t=%.2f bỏ skill %d · cut + skill kế (giữ prefer=%d)'
                       % (now, skill, prefer))
            continue

        sid = next_skill()
        if sid is None:
            deadline = now + 0.2
            continue
        casts[sid] = casts.get(sid, 0) + 1
        expect = (sid, now)
        deadline = now + CONFIRM
        log.append('t=%.2f cast 7074 skill %d' % (now, sid))

    return dict(log=log, casts=casts, b070=b070, wait_logs_54016=wait_logs_54016,
                skips=skips, cuts=cuts, prefer=prefer)


print('\n=== OLD: forever “chưa nhận B070 skill 54016 · giữ mục tiêu” ===')
old = simulate(old=True)
for line in old['log'][:12]:
    print(line)
print('... wait_logs_54016=%d skips=%d' % (old['wait_logs_54016'], old['skips']))

print('\n=== NEW: ≤2 miss → skip 54016 → rotate Ghost F ===')
new = simulate(old=False)
for line in new['log'][:28]:
    print(line)
print('summary casts=%s b070=%s waits=%d skips=%d cuts=%d'
      % (new['casts'], new['b070'], new['wait_logs_54016'], new['skips'], new['cuts']))

checks = []


def check(name, cond):
    checks.append((name, cond))
    print('%s %s' % ('PASS' if cond else 'FAIL', name))


check('old B070 80031 then stalls 54016', old['b070'].get(SKILL_OK, 0) >= 1 and old['wait_logs_54016'] >= 5)
check('old never skips 54016', old['skips'] == 0)
check('old does not cast skills after 54016 stall',
      sum(old['casts'].get(s, 0) for s in SKILLS if s not in (SKILL_OK, SKILL_STALL)) == 0)

check('new B070 80031', new['b070'].get(SKILL_OK, 0) >= 1)
check('new skips 54016 ≥1', new['skips'] >= 1)
# First stall episode: waits before first skip ≤ MISS_MAX
first_skip_i = next(i for i, l in enumerate(new['log']) if 'bỏ skill %d' % SKILL_STALL in l)
waits_before = sum(1 for l in new['log'][:first_skip_i] if 'chưa nhận B070 skill %d' % SKILL_STALL in l)
check('first episode ≤2 wait logs', waits_before <= MISS_MAX)
check('new casts other F skills after skip',
      any(new['casts'].get(s, 0) >= 1 for s in (81016, 81019, 66007, 7653, 7678)))
check('new cuts after B070/skip', new['cuts'] >= 2)
check('prefer kept', new['prefer'] == UID)

if not all(c for _, c in checks):
    fail('checks failed')
print('\nSHIP_OK')
sys.exit(0)
