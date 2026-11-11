# -*- coding: utf-8 -*-
"""GhostSelfTest — thử Ghost bản thân (7081 self UID) an toàn trên phBot Stable.

Changelog:
- v1.0.0: UI Bật/Tắt; gửi 7081 self / 7081×2; hiện self UID; log C→S hex;
  handle_joymax log B074 (02 00 vs từ chối) + B081; tuỳ chọn 7081 target 7045 gần nhất.
  Độc lập — không import AutoGhost / PartyLeader.

Gói giống hiep.txt: inject_joymax(0x7081, struct.pack('<I', uid), False)
  — hiep dùng Boss UID; plugin này thử cùng format với player_id (bản thân).
"""

from __future__ import print_function

import struct
from threading import RLock
from time import monotonic, sleep

import QtBind
from phBot import get_character_data, inject_joymax, log

NAME = 'GhostSelfTest'
VERSION = '1.0.0'

# hiep.txt reference (Boss only — NOT self):
#   Client 0x7081 Data 13 13 5F 00  → UID 6230803 LE
# Self experiment uses the SAME 4-byte LE layout with get_character_data()['player_id'].

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'self_uid': 0,
    'target_uid': 0,  # last outgoing 0x7045 select (no AutoGhost)
    'last_send_at': 0.0,
    'last_send_uid': 0,
    'last_send_hex': '',
    'pending_watch_until': 0.0,
}

QtBind.createLabel(gui, '%s v%s — thử Ghost bản thân' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật / Tắt', 10, 32)

self_uid_label = QtBind.createLabel(gui, 'Self UID: (chưa đọc)', 10, 60)
target_uid_label = QtBind.createLabel(gui, 'Target 7045 hiện tại: (chưa có)', 10, 82)
status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 104)

QtBind.createButton(gui, 'btn_refresh', 'Làm mới UID', 10, 132)
QtBind.createButton(gui, 'btn_send_self', 'Gửi 7081 self', 140, 132)
QtBind.createButton(gui, 'btn_send_x2', 'Gửi 7081×2', 280, 132)
QtBind.createButton(gui, 'btn_send_target', '7081 target hiện tại', 420, 132)

QtBind.createLabel(
    gui,
    'C→S 0x7081 = 4 byte LE UID (giống hiep Boss, nhưng self = player_id). '
    'Xem log B074 02 00 = ngắt OK / khác = từ chối hoặc không cắt. '
    'Không sửa AutoGhost.',
    10, 170,
)


def _log(msg):
    log('[%s] %s' % (NAME, msg))


def set_status(msg):
    QtBind.setText(gui, status_label, 'Trạng thái: ' + msg)
    _log(msg)


def read_self_uid():
    character = get_character_data() or {}
    try:
        uid = int(character.get('player_id') or 0)
    except (TypeError, ValueError):
        uid = 0
    with lock:
        state['self_uid'] = uid
    name = character.get('name') or '?'
    if uid:
        QtBind.setText(gui, self_uid_label, 'Self UID: %d (%s)' % (uid, name))
    else:
        QtBind.setText(gui, self_uid_label, 'Self UID: (chưa đọc — vào game)')
    return uid


def show_target_uid():
    with lock:
        uid = int(state.get('target_uid') or 0)
    if uid:
        QtBind.setText(gui, target_uid_label, 'Target 7045 hiện tại: %d' % uid)
    else:
        QtBind.setText(
            gui, target_uid_label,
            'Target 7045 hiện tại: (chưa có — click chọn mục tiêu trong game)')


def plugin_enabled():
    with lock:
        return bool(state['enabled'])


def ui_enabled(checked):
    on = bool(checked)
    with lock:
        state['enabled'] = on
    read_self_uid()
    show_target_uid()
    set_status('BẬT — sẵn sàng gửi 7081.' if on else 'TẮT.')


def btn_refresh():
    uid = read_self_uid()
    show_target_uid()
    set_status('Đã làm mới Self UID=%d.' % uid if uid else 'Chưa có player_id.')


def _pack_uid(uid):
    return struct.pack('<I', int(uid) & 0xffffffff)


def send_7081(uid, label, times=1):
    if not plugin_enabled():
        set_status('Plugin đang TẮT — bật trước khi gửi.')
        return False
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        set_status('UID không hợp lệ.')
        return False
    if not 0 < uid <= 0xffffffff:
        set_status('UID trống / không hợp lệ.')
        return False

    packet = _pack_uid(uid)
    hex_out = packet.hex(' ').upper()
    ok_all = True
    for i in range(max(1, int(times))):
        try:
            result = inject_joymax(0x7081, packet, False)
        except Exception as error:
            set_status('Lỗi inject 7081: %s' % error)
            return False
        api_ok = result is not False
        ok_all = ok_all and api_ok
        _log(
            'C→S 0x7081 [%s #%d] UID=%d | hex=%s | encrypted=False | API=%r'
            % (label, i + 1, uid, hex_out, result))
        if times > 1 and i + 1 < times:
            sleep(0.01)
    with lock:
        state['last_send_at'] = monotonic()
        state['last_send_uid'] = uid
        state['last_send_hex'] = hex_out
        state['pending_watch_until'] = monotonic() + 3.0
    if ok_all:
        set_status(
            'Đã gửi 7081 %s ×%d UID=%d · hex %s — chờ B074/B081.'
            % (label, times, uid, hex_out))
    else:
        set_status(
            'phBot từ chối inject 7081 %s UID=%d (API=False).' % (label, uid))
    return ok_all


def btn_send_self():
    uid = read_self_uid()
    send_7081(uid, 'self', times=1)


def btn_send_x2():
    uid = read_self_uid()
    # hiep first-ghost pattern: 7081×2 same UID ~0–20 ms apart
    send_7081(uid, 'self×2', times=2)


def btn_send_target():
    with lock:
        uid = int(state.get('target_uid') or 0)
    if not uid:
        set_status('Chưa có target 7045 — chọn mục tiêu trong game trước.')
        return
    send_7081(uid, 'target', times=1)


def _classify_b074(data):
    raw = bytes(data or b'')
    if raw == b'\x02\x00':
        return '02 00 · NGẮT OK / cast end (thường = Ghost thành công)'
    if raw == b'\x02\x01':
        return '02 01 · kết thúc skill (biến thể)'
    if len(raw) >= 4 and raw[:4] == b'\x03\x00\x04\x40':
        return '03 00 04 40 · ActionRefusal (từ chối / OOR / busy)'
    if len(raw) >= 2 and raw[:2] == b'\x03\x00':
        return '%s · từ chối / fail (03 00…)' % raw[:8].hex(' ').upper()
    return '%s · (xem hex)' % (raw[:12].hex(' ').upper() if raw else '(trống)')


def handle_joymax(opcode, data):
    """Log S→C replies liên quan Ghost / trao đổi."""
    if not plugin_enabled():
        return
    if opcode not in (0xB074, 0xB081, 0xB084, 0x3085):
        return
    raw = bytes(data or b'')
    with lock:
        watching = monotonic() <= float(state.get('pending_watch_until') or 0)
        last_uid = int(state.get('last_send_uid') or 0)
        last_hex = state.get('last_send_hex') or ''
    # Always log B074 while enabled; highlight if shortly after our send.
    prefix = 'sau 7081' if watching else 'ngoài cửa sổ 3s'
    if opcode == 0xB074:
        note = _classify_b074(raw)
        _log('S→C 0xB074 [%s] %s | last C→S UID=%d hex=%s'
             % (prefix, note, last_uid, last_hex or '?'))
        if watching and raw == b'\x02\x00':
            set_status('B074 02 00 sau 7081 UID=%d — có vẻ NGẮT OK.' % last_uid)
        elif watching and raw[:2] == b'\x03\x00':
            set_status('B074 từ chối sau 7081 UID=%d — %s' % (last_uid, note))
        return
    if opcode == 0xB081:
        _log('S→C 0xB081 [%s] hex=%s | (reply trao đổi / trade)'
             % (prefix, raw[:16].hex(' ').upper() if raw else '(trống)'))
        return
    if opcode in (0xB084, 0x3085) and watching:
        _log('S→C 0x%04X [%s] hex=%s'
             % (opcode, prefix, raw[:16].hex(' ').upper() if raw else '(trống)'))


def handle_silkroad(opcode, data):
    """Nhớ UID chọn mục tiêu (7045) để nút so sánh — không phụ thuộc AutoGhost."""
    if opcode != 0x7045:
        return
    raw = bytes(data or b'')
    if len(raw) < 4:
        return
    uid = struct.unpack_from('<I', raw, 0)[0]
    if not uid:
        return
    self_uid = read_self_uid()
    if self_uid and uid == self_uid:
        return
    with lock:
        state['target_uid'] = uid
    show_target_uid()
    if plugin_enabled():
        _log('Quan sát C→S 0x7045 chọn UID=%d (target so sánh).' % uid)


# phBot may call these on load
try:
    read_self_uid()
    show_target_uid()
    set_status('Nạp %s v%s — bật rồi thử Gửi 7081 self.' % (NAME, VERSION))
except Exception:
    pass
