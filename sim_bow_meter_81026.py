# -*- coding: utf-8 -*-
"""Sim: F1 Đo ngắt ms accepts bow cast confirm (target=0) + late impact hit.

Also covers per-page approach ranges (F1=6 / F2=12) and no-cut basic-attack block.
"""
from __future__ import annotations

import struct


DAMAGE_METER_CAST_TIMEOUT_NS = 12_000_000_000
AUTO_PK_APPROACH_BY_PAGE = {'F1': 6.0, 'F2': 12.0, 'F3': 6.0}
AUTO_PK_APPROACH_RANGE = 6.0


def approach_range(page):
    return float(AUTO_PK_APPROACH_BY_PAGE.get(str(page), AUTO_PK_APPROACH_RANGE))


def move_stop_at(page, distance):
    stop_at = max(1.0, approach_range(page) - 0.5)
    if distance <= approach_range(page):
        return None  # ready to cast
    return (distance - stop_at) / distance if distance > stop_at else 0.0


def inline_first_damage(raw, target):
    if (len(raw) < 35 or raw[:3] != b'\x01\x02\x30'
            or raw[19:21] != b'\x01\x01' or raw[21] < 1
            or len(raw) < 22 + 13 * raw[21]
            or struct.unpack_from('<I', raw, 22)[0] != target
            or raw[26] not in (0, 1, 4, 5) or raw[27] not in (1, 2)):
        return None
    damage = int.from_bytes(raw[28:31], 'little')
    return damage if damage > 0 else None


def pack_b070(uid, source, action, target, with_hit=False, hit_target=None, damage=0):
    """B070: byte0=1, bytes1-2 type, then uid/source/action/target @3."""
    if with_hit:
        hit_uid = hit_target if hit_target is not None else target
        raw = bytearray(35)
        raw[0:3] = b'\x01\x02\x30'
        struct.pack_into('<IIII', raw, 3, uid, source, action, target)
        raw[19:21] = b'\x01\x01'
        raw[21] = 1
        struct.pack_into('<I', raw, 22, hit_uid)
        raw[26] = 1
        raw[27] = 1
        raw[28:31] = int(damage).to_bytes(3, 'little')
        return bytes(raw)
    return b'\x01\x02\x00' + struct.pack('<IIII', uid, source, action, target)


def observe(job, cast_timeout_ns, now, raw, logs):
    cast = job['cast']
    if not cast or now - cast['sent'] > cast_timeout_ns:
        return 'timeout_ignore'
    if len(raw) < 19 or raw[0] != 1:
        return 'short'
    uid, source, action, target = struct.unpack_from('<IIII', raw, 3)
    if uid != job['skill'] or source != job['source']:
        return 'mismatch_skill_source'
    expected = cast['target']
    if cast['ack'] is None:
        if target not in (0, expected):
            return 'reject_target'
        cast.update(ack=now, action=action)
        if target == 0:
            logs.append('confirm_zero_target')
    elif target not in (0, expected):
        return 'reject_target'
    damage = inline_first_damage(raw, expected)
    if damage is None:
        logs.append('wait_hit')
        return 'wait_hit'
    job['cast'] = None
    job['samples'].append((cast['ack'], now, damage))
    logs.append('hit_%d' % damage)
    return 'hit'


def old_observe_would_drop(job, now, raw):
    cast = job['cast']
    uid, source, action, target = struct.unpack_from('<IIII', raw, 3)
    if (uid, source, target) != (job['skill'], job['source'], cast['target']):
        return True
    if cast['ack'] is None:
        cast.update(ack=now, action=action)
        return False
    return cast['action'] != action


def blocks_basic_attack(natural_skills, armed, data, pvp_target):
    """v4.3 one-liner: drop 7074 01 01 01 while page has no-cut skills."""
    return bool(
        natural_skills and armed and len(data) == 7 and data[:3] == b'\x01\x01\x01'
        and struct.unpack_from('<I', data, 3)[0] == pvp_target)


def build_job(skill=81026, source=1001, target=2002, sent=0):
    return dict(
        skill=skill, source=source, samples=[],
        cast=dict(target=target, sent=sent, ack=None, action=None, repeated=False),
    )


def main():
    logs = []
    confirm = pack_b070(81026, 1001, action=11, target=0)
    impact = pack_b070(81026, 1001, action=99, target=2002,
                       with_hit=True, hit_target=2002, damage=1234)

    assert old_observe_would_drop(
        dict(skill=81026, source=1001,
             cast=dict(target=2002, sent=0, ack=None, action=None)),
        1_000_000, confirm), 'old meter rejects target=0 confirm'

    job = build_job()
    r1 = observe(job, DAMAGE_METER_CAST_TIMEOUT_NS, 50_000_000, confirm, logs)
    assert r1 == 'wait_hit' and job['cast']['ack'] == 50_000_000, r1
    assert 'confirm_zero_target' in logs

    job_old = build_job()
    observe(job_old, DAMAGE_METER_CAST_TIMEOUT_NS, 50_000_000, confirm, [])
    assert old_observe_would_drop(job_old, 400_000_000, impact)

    r2 = observe(job, DAMAGE_METER_CAST_TIMEOUT_NS, 400_000_000, impact, logs)
    assert r2 == 'hit' and job['samples'][0][2] == 1234, r2

    melee = pack_b070(1, 1001, action=5, target=2002, with_hit=True, damage=50)
    assert observe(build_job(skill=1), DAMAGE_METER_CAST_TIMEOUT_NS, 10_000_000, melee, []) == 'hit'

    # Approach: F2 must not stop at 4 m
    assert approach_range('F1') == 6.0 and approach_range('F2') == 12.0
    assert move_stop_at('F2', 20.0) is not None
    stop_frac = move_stop_at('F2', 20.0)
    stop_dist = 20.0 * (1.0 - stop_frac)
    assert abs(stop_dist - 11.5) < 0.01, stop_dist
    assert move_stop_at('F2', 10.0) is None  # already inside 12 m
    assert move_stop_at('F1', 10.0) is not None  # still outside 6 m

    basic = b'\x01\x01\x01' + struct.pack('<I', 2002)
    assert blocks_basic_attack({81026}, True, basic, 2002)
    assert not blocks_basic_attack(set(), True, basic, 2002)

    print('SHIP_OK bow_meter_81026 + approach_F1_6_F2_12 + block_basic_attack')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
