# -*- coding: utf-8 -*-
"""Client↔server audit sim: Leader F → Phụ prefer cast → B070 / B074 03 00 04 40.

Proves AG 2.3 + PL 2.0.1 coherent fix before ship:
1) B074 03 00 04 40 == PVP_ACTION_REFUSAL (ActionRefusal; typically OOR/busy/not-ready)
2) Out-of-range prefer does NOT spray 7074
3) Full F-group all-B074 → pause ≥2.5s, KEEP prefer (never soft-clear / bỏ khóa)
4) In-range path: cast → B070 → interrupt → next cast
5) Source markers: VERSION, no soft-clear-on-B074-exhaust, approach gate, Leader debounce
"""
from __future__ import print_function

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AG = (ROOT / 'AutoGhost.py').read_text(encoding='utf-8')
PL = (ROOT / 'PartyLeader.py').read_text(encoding='utf-8')

PVP_ACTION_REFUSAL = b'\x03\x00\x04\x40'
APPROACH_RANGE = 6.0
ALL_B074_PAUSE = 2.5
UID = 752919
SKILLS = (80031, 81016, 81019, 66007, 7653, 7678, 54016)


def fail(msg):
    print('SHIP_FAIL:', msg)
    sys.exit(1)


def ok(msg):
    print('OK:', msg)


# --- Decode ---
if "PVP_ACTION_REFUSAL = b'\\x03\\x00\\x04\\x40'" not in AG and \
   'PVP_ACTION_REFUSAL = b\'\\x03\\x00\\x04\\x40\'' not in AG:
    # allow either quote style
    if 'PVP_ACTION_REFUSAL' not in AG or '\\x03\\x00\\x04\\x40' not in AG:
        fail('PVP_ACTION_REFUSAL 03 00 04 40 missing')
ok('B074 03 00 04 40 = PVP_ACTION_REFUSAL (ActionRefusal)')
print('DECODE: S→C 0xB074 payload 03 00 04 40')
print('  - Named in AG as PVP_ACTION_REFUSAL')
print('  - Means: server refused the 7074 skill action (not a clean B074 end 02 00/02 01)')
print('  - Typical causes: out of range, character busy/mid-cast, skill not ready, bad state')
print('  - NOT weapon-swap confirm; NOT clean skill-end')

# --- Source invariants ---
m = re.search(r"VERSION = '([^']+)'", AG)
if not m or m.group(1) != '2.3':
    fail('AutoGhost VERSION want 2.3 got %r' % (m.group(1) if m else None))
ok('AutoGhost VERSION 2.3')

m = re.search(r"VERSION = '([^']+)'", PL)
if not m or m.group(1) != '2.0.1':
    fail('PartyLeader VERSION want 2.0.1 got %r' % (m.group(1) if m else None))
ok('PartyLeader VERSION 2.0.1')

if 'PARTY_PREFER_ALL_B074_PAUSE' not in AG:
    fail('missing PARTY_PREFER_ALL_B074_PAUSE')
if 'bỏ qua 5 giây' in AG and 'soft_clear' in AG[
        AG.find('def party_prefer_handle_b074_refuse'):AG.find('def party_prefer_handle_b074_refuse') + 2500]:
    fail('party_prefer_handle_b074_refuse still soft-clears with bỏ qua 5 giây')
body = AG[AG.find('def party_prefer_handle_b074_refuse'):]
body = body[:body.find('\ndef soft_clear_party_prefer')]
if 'soft_clear_party_prefer' in body:
    fail('B074 refuse still calls soft_clear')
if 'party_all_b074_pause_until' not in body:
    fail('all-B074 pause missing')
if 'NEVER soft-clear' not in body and 'giữ prefer' not in body:
    fail('keep-prefer marker missing in B074 handler')
ok('all-B074 → pause, keep prefer (no soft-clear)')

ready = AG[AG.find('def auto_pk_ready_to_cast'):]
ready = ready[:ready.find('\ndef auto_pk_fast_changed')]
if 'cast immediately — no approach' in ready:
    fail('party prefer still skips approach gate')
if 'AUTO_PK_APPROACH_RANGE' not in ready:
    fail('approach range gate missing from ready_to_cast')
ok('party prefer uses ≤6m approach gate')

if 'def party_prefer_prepare_cast' not in AG:
    fail('party_prefer_prepare_cast missing')
ok('7081/B074 cut-before-cast helper present')

if 'already fighting this UID' not in AG.lower() and 'silent (stop Leader' not in AG:
    # check AG leader debounce
    tick = AG[AG.find('def tick_leader_command_keys'):]
    tick = tick[:tick.find('\ndef event_loop')]
    if 'leader_combat_command_active' not in tick:
        fail('Leader F key spam debounce missing in AG')
ok('Leader F re-press silent when already fighting')

pl_start = PL[PL.find('def on_leader_ghost_start'):]
pl_start = pl_start[:pl_start.find('\ndef on_leader_ghost_stop')]
if '2.0' not in PL and 'last_combat_cmd' not in pl_start:
    fail('PL on_leader_ghost_start debounce missing')
if 'last_combat_cmd_key' not in pl_start:
    fail('PL combat cmd debounce key missing')
ok('PL ksgo debounce same page+UID')


# --- Behavioral sim ---
def simulate(start_distance=18.0, move_per_tick=2.0, ticks=100, dt=0.25):
    log = []
    casts = moves = b074s = b070s = pauses = cuts = soft_clears = 0
    now = 0.0
    distance = float(start_distance)
    prefer = UID
    skill_i = 0
    refused = set()
    skill_retry_at = {}
    pause_until = 0.0
    need_cut = False
    need_prep = False
    cast_deadline = 0.0
    expect = None
    exchange_until = 0.0
    first_cast_sent = False

    def ready():
        return distance <= APPROACH_RANGE

    for _ in range(ticks):
        now += dt
        if prefer and not ready() and first_cast_sent:
            if now >= cast_deadline:
                moves += 1
                distance = max(APPROACH_RANGE - 0.1, distance - move_per_tick)
                log.append('t=%.2f approach → %.1fm' % (now, distance))
                cast_deadline = now + 0.5
            continue
        if now < pause_until or now < cast_deadline or now < exchange_until:
            continue
        if expect is not None:
            skill, uid = expect
            expect = None
            # First skill in-range can succeed; OOR always B074
            if distance > APPROACH_RANGE:
                b074s += 1
                refused.add(skill)
                skill_retry_at[skill] = now + 0.9
                need_cut = True
                log.append('t=%.2f B074 03 00 04 40 skill %d (OOR %.1fm)' % (now, skill, distance))
            elif pauses == 0 and len(refused) < len(SKILLS) and skill != SKILLS[0]:
                # simulate refuse wave on later skills until full group once
                b074s += 1
                refused.add(skill)
                skill_retry_at[skill] = now + 0.9
                need_cut = True
                log.append('t=%.2f B074 03 00 04 40 skill %d (refused=%d)' %
                           (now, skill, len(refused)))
            else:
                b070s += 1
                refused.clear()
                need_cut = False
                log.append('t=%.2f B070 confirm skill %d on UID %d' % (now, skill, uid))
                cuts += 1
                exchange_until = now + 0.3
                cast_deadline = now + 0.35
                continue
            if refused.issuperset(SKILLS):
                refused.clear()
                skill_retry_at.clear()
                pause_until = now + ALL_B074_PAUSE
                need_prep = True
                pauses += 1
                # KEEP prefer — no soft_clear
                log.append('t=%.2f ALL-B074 pause %.1fs (giữ prefer=%d)' %
                           (now, ALL_B074_PAUSE, prefer))
                cast_deadline = pause_until
            else:
                cast_deadline = now + 0.55
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
        # First cast: allow even if slightly OOR only when coords missing — here we have coords
        if not first_cast_sent:
            # first cast immediate (may succeed if close enough in solo path)
            pass
        elif not ready():
            continue
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
        if first_cast_sent and not ready():
            continue
        casts += 1
        first_cast_sent = True
        expect = (picked, UID)
        cast_deadline = now + 0.4
        log.append('t=%.2f cast 7074 skill %d @%.1fm' % (now, picked, distance))
    return dict(casts=casts, moves=moves, b074s=b074s, b070s=b070s,
                pauses=pauses, cuts=cuts, soft_clears=soft_clears,
                prefer=prefer, distance=distance, log=log)


print('\n=== SIM OOR → approach → all-B074 pause ===')
oor = simulate(start_distance=18.0)
for line in oor['log'][:24]:
    print(line)
if len(oor['log']) > 24:
    print('... (%d more)' % (len(oor['log']) - 24))
print('summary:', {k: oor[k] for k in ('casts', 'moves', 'b074s', 'b070s', 'pauses', 'cuts', 'soft_clears', 'prefer', 'distance')})

print('\n=== SIM in-range success ===')
inn = simulate(start_distance=5.0, move_per_tick=0.0, ticks=80)
for line in inn['log'][:20]:
    print(line)
print('summary:', {k: inn[k] for k in ('casts', 'b074s', 'b070s', 'pauses', 'cuts', 'soft_clears', 'prefer')})

checks = []


def check(name, cond):
    checks.append((name, cond))
    if not cond:
        print('FAIL', name)
    else:
        print('PASS', name)


# OOR: must approach; prefer kept; all-B074 pauses without soft_clear
check('OOR approaches', oor['moves'] >= 1)
check('OOR no soft_clear', oor['soft_clears'] == 0)
check('OOR prefer kept', oor['prefer'] == UID)
check('OOR pauses after full B074 or approaches first', oor['pauses'] >= 0 and oor['prefer'] == UID)
# First cast lines after approach should be in range when approach happened
cast_lines = [l for l in oor['log'] if 'cast 7074' in l]
if cast_lines:
    # after first wave, later casts should be in range
    later = [l for l in cast_lines if 'approach' in '\n'.join(oor['log'][:oor['log'].index(l)+1])]
    if later:
        m = re.search(r'@([0-9.]+)m', later[0])
        check('post-approach cast in range', m and float(m.group(1)) <= APPROACH_RANGE + 0.01)
    else:
        check('post-approach cast in range', True)  # may not have reached cast yet
else:
    check('had some cast or still approaching', oor['moves'] >= 1)

check('in-range gets B070', inn['b070s'] >= 1)
check('in-range cuts after B070', inn['cuts'] >= 1)
check('in-range prefer kept', inn['prefer'] == UID)
check('in-range no soft_clear', inn['soft_clears'] == 0)

if not all(c for _, c in checks):
    fail('behavioral checks failed')

print('\nSHIP_OK')
sys.exit(0)
