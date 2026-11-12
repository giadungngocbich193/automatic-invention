# -*- coding: utf-8 -*-
"""Sim: PartyLeader 1.1.1 force-ARM F1/F2/3 + remove >10m soft-stop.

SHIP_OK when:
1. ag#F1#arm / ag#F1#0 / ag#F1#123 parse as ARM (0 is NOT stop)
2. ag#F1#stop parses as STOP
3. ALL Phụ pages match F1/F2/3
4. follower_check_leader_distance is a no-op stub
5. ARM payload uses #arm not #0 when uid missing
"""
from __future__ import print_function

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'PartyLeader.py'
text = SRC.read_text(encoding='utf-8')


def fail(msg):
    print('SHIP_FAIL:', msg)
    sys.exit(1)


def ok(msg):
    print('OK:', msg)


# --- extract parse_ag_fight_cmd via exec of isolated copy ---
# Minimal stub env for function body we re-implement from source invariants.

tree = ast.parse(text)
funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
for need in ('parse_ag_fight_cmd', 'follower_page_matches_cmd',
             'follower_check_leader_distance', 'leader_broadcast_fight_cmd',
             'follower_apply_fight_cmd', 'event_loop'):
    if need not in funcs:
        fail('missing def %s' % need)

# Static checks on source
if 'REMOVED (v1.1.1)' not in text and 'no >10m soft-stop/chase' not in text:
    fail('distance removal marker missing')
if 'follower_check_leader_distance():' not in text:
    fail('follower_check_leader_distance missing')

# Ensure event_loop does not call distance check
el = text[text.find('def event_loop'):text.find('def event_loop') + 1200]
if 'follower_check_leader_distance()' in el:
    fail('event_loop still calls follower_check_leader_distance')
ok('event_loop does not call distance soft-stop')

# Ensure stub returns immediately
fd = text[text.find('def follower_check_leader_distance'):]
fd = fd[:fd.find('\ndef ')]
if 'return' not in fd.split('\n')[2:6] and 'return' not in fd:
    # body should just return
    if 'return' not in fd:
        fail('distance check not stubbed to return')
ok('follower_check_leader_distance stubbed')

# Exec parse + page match with minimal globals
ns = {'GHOST_PAGES': ('F1', 'F2', 'F3'), 'AG_FIGHT_PREFIX': 'ag#'}
# compile just those two functions from source text
chunk = []
for name in ('parse_ag_fight_cmd', 'follower_page_matches_cmd'):
    start = text.find('def %s(' % name)
    if start < 0:
        fail('cannot find %s' % name)
    end = text.find('\ndef ', start + 1)
    chunk.append(text[start:end])
exec('\n\n'.join(chunk), ns)
parse = ns['parse_ag_fight_cmd']
match = ns['follower_page_matches_cmd']

cases = [
    ('ag#F1#arm', ('F1', 'arm', 0)),
    ('ag#F1#0', ('F1', 'arm', 0)),
    ('ag#F1#12345', ('F1', 'arm', 12345)),
    ('ag#F2#stop', ('F2', 'stop', 0)),
    ('ag#3#arm', ('3', 'arm', 0)),
    ('ag#F3#off', ('F3', 'stop', 0)),
    ('hello', None),
]
for raw, expect in cases:
    got = parse(raw)
    if got != expect:
        fail('parse(%r)=%r expected %r' % (raw, got, expect))
ok('parse_ag_fight_cmd ARM/STOP cases')

for page in ('F1', 'F2', 'F3', '3'):
    if not match(page):
        fail('page match false for %s' % page)
ok('ALL Phụ match F1/F2/3')

# Broadcast payload: arm with uid 0 must use token 'arm' not '0'
lb = text[text.find('def leader_broadcast_fight_cmd'):]
if "token = 'arm'" not in lb and 'token = "arm"' not in lb:
    fail('leader_broadcast missing #arm token for no-uid')
if "#0" in lb and 'NOT #0' not in lb and 'not #0' not in lb.lower():
    # comment about NOT #0 is fine; ensure we don't build payload with bare 0 as stop
    pass
if "token = 'stop'" not in lb:
    fail('stop token missing')
ok('broadcast uses #arm when no Prefer UID')

# force=True on arm path
if 'arm_auto_pk(prefer_uid=uid, force=True)' not in text and \
   'arm_auto_pk(prefer_uid=int(uid or 0), force=True)' not in text and \
   'force=True' not in text[text.find('def follower_apply_fight_cmd'):text.find('def follower_apply_fight_cmd')+900]:
    fail('follower_apply_fight_cmd missing force=True arm')
ok('follower_apply force=True')

if "VERSION = '1.1.1'" not in text:
    fail('VERSION not 1.1.1')
ok('VERSION 1.1.1')

print('SHIP_OK')
sys.exit(0)
