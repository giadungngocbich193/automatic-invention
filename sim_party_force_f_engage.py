# -*- coding: utf-8 -*-
"""Sim: Phụ party prefer must force Target Enemy + Ghost F before cast.

User stall: “Phụ chưa đánh: Ghost chưa ở chế độ Chọn người → bấm F.”
Chủ ARM OK but Phụ never pressed F / Target Enemy.

SHIP_OK when AG 2.3.2 has party_sync_force_engage and select_uid uses it.
"""
from __future__ import print_function

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AG = (ROOT / 'AutoGhost.py').read_text(encoding='utf-8')


def fail(msg):
    print('SHIP_FAIL:', msg)
    sys.exit(1)


def ok(msg):
    print('OK:', msg)


m = re.search(r"VERSION = '([^']+)'", AG)
if not m or m.group(1) != '2.3.2':
    fail('VERSION want 2.3.2 got %r' % (m.group(1) if m else None))
ok('VERSION 2.3.2')

if 'def party_sync_force_engage' not in AG:
    fail('party_sync_force_engage missing')
ok('party_sync_force_engage defined')

body = AG[AG.find('def party_sync_force_engage'):]
body = body[:body.find('\ndef party_sync_arm_auto_pk')]
if 'Target Enemy' not in body and 'native_key' not in body:
    fail('Target Enemy path missing')
if "page_sent'] = False" not in body and "page_sent': False" not in body:
    fail('force page_sent=False (Ghost F) missing')
if 'prepare_pvp_page' not in body:
    fail('prepare_pvp_page after force F missing')
if 'Chọn người' not in body:
    fail('user-facing Chọn người status missing')
ok('force engage: Target Enemy + F + prepare')

sel = AG[AG.find('def party_sync_select_uid'):]
sel = sel[:sel.find('\ndef party_sync_clear_target')]
if 'party_sync_force_engage' not in sel:
    fail('select_uid does not call force_engage')
if 'request_pvp_page(page)\n' in sel and 'party_sync_force_engage' not in sel:
    fail('select_uid still bare request_pvp_page without force')
ok('select_uid uses force_engage')

arm = AG[AG.find('def party_sync_arm_auto_pk'):]
arm = arm[:arm.find('\ndef party_sync_stop_auto_pk')]
if 'party_sync_force_engage' not in arm:
    fail('arm_auto_pk missing force_engage fallback')
ok('arm path can force engage')

# Behavioral sketch: native Auto PK used to set page_sent=True (skip F).
# Force path must clear that.
print('\n=== sketch: party prefer engage ===')
steps = [
    'Chủ F1 → ksgo → Phụ arm Auto PK',
    'party_sync_select_uid(UID)',
    '1) Target Enemy key (Home/End/Insert…) → client player-select',
    '2) request_pvp_page + page_sent=False → prepare posts Ghost F',
    '3) pvp_armed → rotate_direct 7074',
]
for s in steps:
    print('-', s)

print('\nSHIP_OK')
sys.exit(0)
