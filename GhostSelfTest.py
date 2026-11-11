# -*- coding: utf-8 -*-
"""GhostSelfTest — thử Ghost bản thân (7081 self UID) an toàn trên phBot Stable.

Changelog:
- v1.0.1: inject_joymax thử encrypted=True rồi fallback False; log cả hai API=
  kết quả. Gửi từ event_loop (giống AG KIỂM TRA GỬI) thay vì chỉ từ nút UI.
  Ghi chú: AutoGhost PvP Ghost thật dùng client_7081 (native), không phải inject;
  đường inject AG hiện tại = 0x7081 + pack('<I',uid) + encrypted=False.
- v1.0.0: UI Bật/Tắt; gửi 7081 self / 7081×2; hiện self UID; log C→S hex;
  handle_joymax log B074 (02 00 vs từ chối) + B081; tuỳ chọn 7081 target 7045 gần nhất.
  Độc lập — không import AutoGhost / PartyLeader.

Gói giống hiep.txt / AutoGhost begin_direct_exchange:
  inject_joymax(0x7081, struct.pack('<I', uid), encrypted)
"""

from __future__ import print_function

import struct
from threading import RLock
from time import monotonic

import QtBind
from phBot import get_character_data, inject_joymax, log

NAME = 'GhostSelfTest'
VERSION = '1.0.1'

# hiep.txt reference (Boss only — NOT self):
#   Client 0x7081 Data 13 13 5F 00  → UID 6230803 LE
# AutoGhost working inject (begin_direct_exchange / KIỂM TRA GỬI):
#   inject_joymax(0x7081, struct.pack('<I', target), False)  # True historically False on host
# AutoGhost production Ghost cut: transport=client_7081 (NativeCut), not inject_joymax.

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'self_uid': 0,
    'target_uid': 0,  # last outgoing 0x7045 select (no AutoGhost)
    'last_send_at': 0.0,
    'last_send_uid': 0,
    'last_send_hex': '',
    'last_encrypted': None,
    'pending_watch_until': 0.0,
    'queue': [],  # event_loop inject jobs (match AG probe context)
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
    'C→S 0x7081 = 4 byte LE UID (AG inject path). Thử encrypted=True rồi False; '
    'gửi từ event_loop. AG Ghost thật = client_7081 native. Xem log B074 02 00.',
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
        if not on:
            state['queue'] = []
    read_self_uid()
    show_target_uid()
    set_status('BẬT — sẵn sàng gửi 7081 (event_loop).' if on else 'TẮT.')


def btn_refresh():
    uid = read_self_uid()
    show_target_uid()
    set_status('Đã làm mới Self UID=%d.' % uid if uid else 'Chưa có player_id.')


def _pack_uid(uid):
    return struct.pack('<I', int(uid) & 0xffffffff)


def _api_ok(result):
    return result is not False


def inject_7081_ag_path(uid, label, seq=1):
    """Match AutoGhost inject bytes; try encrypted True then False; log both.

    AG production Ghost uses client_7081 (native). AG inject attempts use the
    same 4-byte LE UID packet; historically True returned False on host so AG
    settled on False — we still probe True first and fall back.
    """
    packet = _pack_uid(uid)
    hex_out = packet.hex(' ').upper()
    results = []
    chosen = None
    chosen_enc = None
    for encrypted in (True, False):
        try:
            result = inject_joymax(0x7081, packet, encrypted)
        except Exception as error:
            result = 'EXC:%s' % error
        results.append((encrypted, result))
        _log(
            'C→S 0x7081 [%s #%d] UID=%d | hex=%s | encrypted=%s | API=%r'
            % (label, seq, uid, hex_out, encrypted, result))
        if chosen is None and _api_ok(result):
            chosen = result
            chosen_enc = encrypted
            # Keep probing False for comparison log even if True accepted.
    summary = ' | '.join('enc=%s API=%r' % (enc, api) for enc, api in results)
    if chosen_enc is not None:
        _log('C→S 0x7081 [%s #%d] CHỌN encrypted=%s (AG-style packet) · %s'
             % (label, seq, chosen_enc, summary))
        return True, chosen_enc, hex_out, summary
    _log('C→S 0x7081 [%s #%d] CẢ HAI TỪ CHỐI · %s' % (label, seq, summary))
    return False, None, hex_out, summary


def queue_7081(uid, label, times=1):
    """Queue inject for event_loop (same context as AG KIỂM TRA GỬI)."""
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
    times = max(1, int(times))
    with lock:
        state['queue'].append({
            'uid': uid,
            'label': label,
            'times': times,
            'done': 0,
            'next_at': monotonic(),
            'ok_any': False,
            'last_summary': '',
            'hex': _pack_uid(uid).hex(' ').upper(),
        })
    set_status(
        'Đã xếp hàng 7081 %s ×%d UID=%d — gửi trên event_loop (True→False).'
        % (label, times, uid))
    return True


def _finish_job(job):
    uid = job['uid']
    with lock:
        state['last_send_at'] = monotonic()
        state['last_send_uid'] = uid
        state['last_send_hex'] = job.get('hex') or ''
        state['last_encrypted'] = job.get('chosen_enc')
        state['pending_watch_until'] = monotonic() + 3.0
    if job.get('ok_any'):
        set_status(
            'Đã gửi 7081 %s ×%d UID=%d · enc=%s · hex %s — chờ B074/B081.'
            % (job['label'], job['times'], uid,
               job.get('chosen_enc'), job.get('hex') or '?'))
    else:
        set_status(
            'phBot từ chối inject 7081 %s UID=%d (True+False đều API=False). %s'
            % (job['label'], uid, job.get('last_summary') or ''))


def event_loop():
    """Drain inject queue from phBot callback — mirrors AG transport probe."""
    if not plugin_enabled():
        return
    now = monotonic()
    with lock:
        if not state['queue']:
            return
        job = state['queue'][0]
    if now < float(job.get('next_at') or 0):
        return
    job['done'] = int(job.get('done') or 0) + 1
    ok, enc, hex_out, summary = inject_7081_ag_path(
        job['uid'], job['label'], seq=job['done'])
    job['hex'] = hex_out
    job['last_summary'] = summary
    if ok:
        job['ok_any'] = True
        job['chosen_enc'] = enc
    if job['done'] >= int(job.get('times') or 1):
        with lock:
            if state['queue'] and state['queue'][0] is job:
                state['queue'].pop(0)
        _finish_job(job)
    else:
        job['next_at'] = monotonic() + 0.01


def send_7081(uid, label, times=1):
    """UI entry: queue AG-style inject (True→False) onto event_loop."""
    return queue_7081(uid, label, times=times)


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
        last_enc = state.get('last_encrypted')
    # Always log B074 while enabled; highlight if shortly after our send.
    prefix = 'sau 7081' if watching else 'ngoài cửa sổ 3s'
    if opcode == 0xB074:
        note = _classify_b074(raw)
        _log('S→C 0xB074 [%s] %s | last C→S UID=%d enc=%s hex=%s'
             % (prefix, note, last_uid, last_enc, last_hex or '?'))
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
    set_status('Nạp %s v%s — bật rồi thử Gửi 7081 self (True→False / event_loop).'
               % (NAME, VERSION))
except Exception:
    pass
