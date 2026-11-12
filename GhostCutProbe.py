# -*- coding: utf-8 -*-
"""GhostCutProbe — solo mid-cast Ghost probe (NativeCut client_7081).

Changelog:
- v1.0.1: Real compare — Cut Self NativeCut target=self UID; Cut Monster
  NativeCut target=monster/boss UID (arm page + 7081 with that UID). Was
  wrongly always self. Logs cut_uid clearly.
- v1.0.0: Manual Self / Monster|Boss cut tool. Cast skill → delay ms after
  7074 → NativeCut arm(2) (NOT inject 7081). Buttons: Cut Self |
  Cut Monster (selected/nearest). Boss+monster/NPC only — no Player cut.
  Log: UID, since_7074, 7081 observed, B074 MID-CUT vs FULL-CAST.
  Solo, no neighbor trade. Independent of AutoGhost / GhostFarm.

Path:
  NativeCut({pid, window, target=cut_uid}) → arm(1) verify → cast 7074 on
  monster → wait delay_ms → arm(2) client_7081 for cut_uid → observe 7081.
  cut_uid = self (Cut Self) | monster/boss (Cut Monster).
"""

from __future__ import print_function

import ctypes
import hashlib
import math
import struct
import sys
import traceback
from pathlib import PureWindowsPath
from threading import RLock
from time import monotonic
from ctypes import wintypes

import QtBind
import phBot as phbot_api
from phBot import (
    get_character_data, get_monsters, get_npcs, get_position, get_skills,
    inject_joymax, log)

NAME = 'GhostCutProbe'
VERSION = '1.0.1'

CLIENT_SHA256 = {
    'bd2aba5bb7ac74890f3a73795106339e556bd1499f019f4d637f0528fc3baa30',
    '5a67d0dd86436e1b1cde1fb8aa339b19286fcb8953c9437de1922fc60343d2de',
}
TICK_SLOT = 0xD801B8
CLIENT_SIGNATURES = {
    0x53CEA0: '668b442404568bf1b998cdee00c706e4',
    0x508FE0: '8b44240453558b6c241085ed8bd98944',
    0x8418D0: '6aff680e55d20064a10000000050b808',
    0x5097A0: '53578bf9c707e431d800e811caffff8b',
}

THUNK = bytes.fromhex(
    '9c60bb4443426164a1240000003b43040f85130100008b03'
    '83f801740983f8020f850301000089c2b903000000f00fb1'
    '0b0f85f200000083fa010f84db000000833d68ceee00000f'
    '84d6000000803d50cdee0000751a833dc0b01501000f84c0'
    '000000833d7ccdee00000f84b300000089e583e4f081ec20'
    '0200000fae442420fc31c089042489442404894424088944'
    '240c8944241089442414894424188944241c89e168817000'
    '00b8a0ce5300ffd0837c241000744bc644240c018b442410'
    '89442414c74424080000000089e18d53086a0452b8e08f50'
    '00ffd0c644240c008b44241089442414c744240400000000'
    '54b8d0188400ffd083c404bf05000000eb05bf0700000089'
    'e1b8a0975000ffd00fae4c242089ec893beb0ec703040000'
    '00eb06c70306000000619dff2544434262'
)

DEFAULT_DELAY_MS = 100  # ~120ms cast → cut mid-cast
DEFAULT_RADIUS = 50.0
SELECT_WAIT_SEC = 0.25
LOOP_GAP_SEC = 0.6

user32 = ctypes.WinDLL('user32') if sys.platform == 'win32' else None
if user32:
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'loop': False,
    'self_uid': 0,
    'selected_uid': 0,  # last 7045 if monster/boss (players ignored)
    'queue': [],
    'session': None,
    'pending_watch_until': 0.0,
    'last_send_uid': 0,
    'last_send_at': 0.0,
    'last_observed_7081': False,
    'last_b074': '',
    'last_verdict': '',
    'active': None,
    'ok_count': 0,
    'fail_count': 0,
    'mid_cut_count': 0,
    'full_cast_count': 0,
}

QtBind.createLabel(
    gui, '%s v%s — solo mid-cast Ghost (NativeCut)' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật / Tắt', 10, 32)
loop_box = QtBind.createCheckBox(gui, 'ui_loop', 'Loop cast→cut', 140, 32)

QtBind.createLabel(gui, 'Cast skill ID', 10, 62)
skill_field = QtBind.createLineEdit(gui, '', 110, 58, 100, 22)
QtBind.createLabel(gui, 'Delay ms after 7074', 230, 62)
delay_field = QtBind.createLineEdit(gui, str(DEFAULT_DELAY_MS), 370, 58, 70, 22)

QtBind.createButton(gui, 'btn_cut_self', 'Cut Self', 10, 96)
QtBind.createButton(gui, 'btn_cut_monster', 'Cut Monster', 140, 96)
QtBind.createButton(gui, 'btn_refresh', 'Làm mới', 300, 96)
QtBind.createButton(gui, 'btn_close', 'Tháo móc', 420, 96)

self_uid_label = QtBind.createLabel(gui, 'Self UID: (chưa đọc)', 10, 132)
monster_label = QtBind.createLabel(gui, 'Monster/Boss: (chưa có)', 10, 154)
client_label = QtBind.createLabel(gui, 'Client: (chưa đọc)', 10, 176)
status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 198)
stats_label = QtBind.createLabel(
    gui, 'MID-CUT: 0 · FULL-CAST: 0 · OK: 0 · Fail: 0', 10, 220)

QtBind.createLabel(
    gui,
    'v1.0.1: Cut Self → 7081 self UID; Cut Monster → 7081 monster/boss UID. '
    'NativeCut only (NOT inject 7081). Log: cut_uid · since_7074 · MID-CUT|FULL-CAST.',
    10, 250,
)


def _safe_text(value, fallback='?'):
    if value is None:
        return fallback
    try:
        text = str(value)
    except Exception:
        return fallback
    try:
        text = text.encode('utf-8', 'replace').decode('utf-8', 'replace')
    except Exception:
        return fallback
    text = text.replace('\x00', '').strip()
    return text or fallback


def _hex_bytes(data):
    raw = bytes(data or b'')
    try:
        return raw.hex(' ').upper()
    except TypeError:
        return ' '.join('%02X' % byte for byte in raw)


def _file_sha256(path):
    digest = getattr(hashlib, 'file_digest', None)
    with open(path, 'rb') as source:
        if digest is not None:
            return digest(source, 'sha256').hexdigest()
        hasher = hashlib.sha256()
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
        return hasher.hexdigest()


def _log(msg):
    text = _safe_text(msg, fallback='(empty log)')
    try:
        log('[%s] %s' % (NAME, text))
    except Exception:
        try:
            log('[%s] %s' % (NAME, text.encode('ascii', 'replace').decode('ascii')))
        except Exception:
            pass


def _log_traceback(prefix, error=None):
    detail = traceback.format_exc()
    if detail and detail.strip() != 'NoneType: None':
        for line in detail.strip().splitlines():
            _log('%s %s' % (prefix, line))
    elif error is not None:
        _log('%s %s: %s' % (prefix, type(error).__name__, error))


def set_status(msg):
    text = _safe_text(msg, fallback='(status)')
    try:
        QtBind.setText(gui, status_label, 'Trạng thái: ' + text)
    except Exception as error:
        _log('set_status QtBind lỗi: %s' % error)
    _log(text)


def set_stats():
    with lock:
        mid = int(state.get('mid_cut_count') or 0)
        full = int(state.get('full_cast_count') or 0)
        ok = int(state.get('ok_count') or 0)
        fail = int(state.get('fail_count') or 0)
        verdict = state.get('last_verdict') or ''
    text = 'MID-CUT: %d · FULL-CAST: %d · OK: %d · Fail: %d' % (mid, full, ok, fail)
    if verdict:
        text += ' · last=%s' % verdict
    try:
        QtBind.setText(gui, stats_label, text)
    except Exception:
        pass


def kernel_api():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    handle, pointer, size, dword, boolean = (
        wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
        wintypes.DWORD, wintypes.BOOL)
    entries = {
        'OpenProcess': (handle, dword, boolean, dword),
        'CloseHandle': (boolean, handle),
        'GetExitCodeProcess': (boolean, handle, ctypes.POINTER(dword)),
        'QueryFullProcessImageNameW': (
            boolean, handle, dword, wintypes.LPWSTR, ctypes.POINTER(dword)),
        'K32GetMappedFileNameW': (dword, handle, pointer, wintypes.LPWSTR, dword),
        'VirtualAllocEx': (pointer, handle, pointer, size, dword, dword),
        'VirtualFreeEx': (boolean, handle, pointer, size, dword),
        'VirtualProtectEx': (
            boolean, handle, pointer, size, dword, ctypes.POINTER(dword)),
        'FlushInstructionCache': (boolean, handle, pointer, size),
        'ReadProcessMemory': (
            boolean, handle, pointer, pointer, size, ctypes.POINTER(size)),
        'WriteProcessMemory': (
            boolean, handle, pointer, pointer, size, ctypes.POINTER(size)),
    }
    for name, (result, *args) in entries.items():
        function = getattr(api, name)
        function.restype, function.argtypes = result, args
    return api


class NativeCut:
    """Install GetTickCount thunk and arm client_7081 — never inject_joymax 7081."""

    def __init__(self, job):
        self.api = kernel_api()
        self.handle = self.api.OpenProcess(0x0438, False, job['pid'])
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.page = self.code = self.original = 0
        self.published = False
        try:
            self.install(job)
        except Exception:
            self.close()
            raise

    def read(self, address, count):
        data = ctypes.create_string_buffer(count)
        size = ctypes.c_size_t()
        if (not self.api.ReadProcessMemory(
                self.handle, address, data, count, ctypes.byref(size))
                or size.value != count):
            raise OSError('Không đọc được bộ nhớ client tại 0x%X.' % address)
        return data.raw

    def write(self, address, data):
        size = ctypes.c_size_t()
        buffer = ctypes.create_string_buffer(data)
        if (not self.api.WriteProcessMemory(
                self.handle, address, buffer, len(data), ctypes.byref(size))
                or size.value != len(data)):
            raise OSError('Không ghi được bộ nhớ client tại 0x%X.' % address)

    def protect(self, address, count, flags):
        old = wintypes.DWORD()
        if not self.api.VirtualProtectEx(
                self.handle, address, count, flags, ctypes.byref(old)):
            raise OSError('Không đổi được quyền trang tại 0x%X.' % address)
        return old.value

    def install(self, job):
        if not user32:
            raise RuntimeError('Cần Windows + user32 (phBot Stable host).')
        tid_pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(job['window'], ctypes.byref(tid_pid))
        if not tid or tid_pid.value != job['pid']:
            raise RuntimeError('HWND không thuộc PID client đã chọn.')
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        if not self.api.QueryFullProcessImageNameW(
                self.handle, 0, path, ctypes.byref(length)):
            raise OSError('Không đọc được đường dẫn client.')
        digest = _file_sha256(path.value)
        if digest not in CLIENT_SHA256:
            raise RuntimeError(
                'Client đang chạy khác bản Hùng Vương đã đối chiếu. SHA256=' + digest)
        for address, signature in CLIENT_SIGNATURES.items():
            expected = bytes.fromhex(signature)
            if self.read(address, len(expected)) != expected:
                raise RuntimeError(
                    'Mã client trong bộ nhớ khác bản đã đối chiếu tại 0x%X.' % address)
        self.original = struct.unpack('<I', self.read(TICK_SLOT, 4))[0]
        if not self.api.K32GetMappedFileNameW(
                self.handle, self.original, path, len(path)):
            raise RuntimeError('Không xác minh được đích GetTickCount.')
        if PureWindowsPath(path.value).name.casefold() not in (
                'kernel32.dll', 'kernelbase.dll'):
            raise RuntimeError(
                'GetTickCount đang qua một móc khác (unload AutoGhost Ghost?).')
        self.page = self.api.VirtualAllocEx(
            self.handle, None, 8192, 0x3000, 0x04) or 0
        if not self.page or self.page + 8191 > 0xffffffff:
            raise RuntimeError('Không cấp phát được vùng 32-bit cho lượt thử.')
        self.code = self.page + 4096
        thunk = (THUNK
                 .replace(b'DCBa', struct.pack('<I', self.page))
                 .replace(b'DCBb', struct.pack('<I', self.page + 12)))
        self.write(
            self.page,
            struct.pack('<IIII', 0, tid, job['target'], self.original))
        self.write(self.code, thunk)
        self.protect(self.code, 4096, 0x20)
        if not self.api.FlushInstructionCache(self.handle, self.code, len(thunk)):
            raise OSError('Không đồng bộ được mã thử với client.')
        if self.read(TICK_SLOT, 4) != struct.pack('<I', self.original):
            raise RuntimeError('GetTickCount vừa đổi trong khi chuẩn bị.')
        old = self.protect(TICK_SLOT, 4, 0x04)
        try:
            self.published = True
            self.write(TICK_SLOT, struct.pack('<I', self.code))
        finally:
            self.protect(TICK_SLOT, 4, old)

    def arm(self, value):
        self.write(self.page, struct.pack('<I', value))

    def completed(self, value):
        state_word = struct.unpack('<I', self.read(self.page, 4))[0]
        if state_word == 6:
            raise RuntimeError('Client chưa có đối tượng mạng hoặc hàng đợi gửi.')
        if state_word == 7:
            raise RuntimeError('Client không cấp được bộ đệm dựng gói 7081.')
        return state_word == value

    def close(self):
        if not self.handle:
            return
        try:
            exit_code = wintypes.DWORD()
            if (self.api.GetExitCodeProcess(self.handle, ctypes.byref(exit_code))
                    and exit_code.value != 259):
                return
            if self.published:
                try:
                    self.arm(0)
                finally:
                    current = self.read(TICK_SLOT, 4)
                    original = struct.pack('<I', self.original)
                    if current == struct.pack('<I', self.code):
                        old = self.protect(TICK_SLOT, 4, 0x04)
                        try:
                            self.write(TICK_SLOT, original)
                        finally:
                            self.protect(TICK_SLOT, 4, old)
                    if self.read(TICK_SLOT, 4) != original:
                        raise OSError(
                            'Con trỏ GetTickCount không trở về giá trị gốc.')
            elif self.page:
                self.api.VirtualFreeEx(self.handle, self.page, 0, 0x8000)
        finally:
            self.api.CloseHandle(self.handle)
            self.handle = None


def get_client():
    getter = getattr(phbot_api, 'get_client', None)
    if not getter:
        return {}
    try:
        return getter() or {}
    except Exception:
        return {}


def show_client():
    client = get_client()
    if client.get('running') and client.get('pid') and client.get('window'):
        QtBind.setText(
            gui, client_label,
            'Client: PID=%s HWND=%s (running)'
            % (client.get('pid'), client.get('window')))
    else:
        QtBind.setText(
            gui, client_label,
            'Client: thiếu PID/HWND — cần Silkroad cửa sổ (không Clientless).')


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


def _entity_alive(entity):
    if not entity:
        return False
    if entity.get('dead'):
        return False
    hp = entity.get('hp')
    if hp is None:
        return True
    try:
        return float(hp) > 0
    except (TypeError, ValueError):
        return True


def _player_uids():
    getter = getattr(phbot_api, 'get_players', None)
    if not getter:
        return set()
    try:
        players = getter() or {}
    except Exception:
        return set()
    out = set()
    for uid in players:
        try:
            out.add(int(uid))
        except (TypeError, ValueError):
            continue
    return out


def scan_monsters(radius=DEFAULT_RADIUS):
    """Living monsters + NPCs (bosses often listed as NPC) in radius — never players."""
    position = get_position() or {}
    if not all(key in position for key in ('region', 'x', 'y')):
        return []
    try:
        px = float(position['x'])
        py = float(position['y'])
        region = position['region']
    except (TypeError, ValueError, KeyError):
        return []
    players = _player_uids()
    self_uid = read_self_uid()
    rows = []
    for kind, getter in (('monster', get_monsters), ('npc', get_npcs)):
        try:
            entities = getter() or {}
        except Exception:
            entities = {}
        for uid, entity in entities.items():
            try:
                uid = int(uid)
            except (TypeError, ValueError):
                continue
            if not uid or uid == self_uid or uid in players:
                continue
            if not _entity_alive(entity):
                continue
            if entity.get('region') is not None and entity.get('region') != region:
                continue
            try:
                ex = float(entity['x'])
                ey = float(entity['y'])
            except (KeyError, TypeError, ValueError):
                continue
            distance = math.hypot(ex - px, ey - py)
            if distance > radius:
                continue
            name = _safe_text(
                entity.get('name') or entity.get('servername') or uid, str(uid))
            rows.append({
                'uid': uid,
                'kind': kind,
                'name': name,
                'distance': distance,
            })
    rows.sort(key=lambda row: (row['distance'], row['uid']))
    return rows


def _is_player_uid(uid):
    uid = int(uid or 0)
    if not uid:
        return False
    if uid == read_self_uid():
        return False
    if uid in _player_uids():
        # Dual-listed opposing faction may appear in get_monsters — allow if also mob.
        for row in scan_monsters(DEFAULT_RADIUS):
            if row['uid'] == uid:
                return False
        return True
    return False


def show_monster_pick(rows=None):
    if rows is None:
        rows = scan_monsters()
    with lock:
        selected = int(state.get('selected_uid') or 0)
    pick = None
    if selected:
        for row in rows:
            if row['uid'] == selected:
                pick = row
                break
    if pick is None and rows:
        pick = rows[0]
    if pick:
        QtBind.setText(
            gui, monster_label,
            'Monster/Boss: #%d [%s] %s · %.1fm%s'
            % (pick['uid'], pick['kind'], pick['name'], pick['distance'],
               ' · selected' if selected == pick['uid'] else ' · nearest'))
    else:
        QtBind.setText(
            gui, monster_label,
            'Monster/Boss: (không có trong %.0fm — chọn quái/boss)' % DEFAULT_RADIUS)
    return pick


def pick_monster_row(rows):
    if not rows:
        return None
    with lock:
        selected = int(state.get('selected_uid') or 0)
    if selected:
        for row in rows:
            if row['uid'] == selected:
                return row
    return rows[0]


def read_skill_id():
    raw = (QtBind.text(gui, skill_field) or '').strip()
    if not raw:
        return 0
    try:
        return int(raw.split('=')[0].strip())
    except (TypeError, ValueError):
        return 0


def read_delay_ms():
    raw = (QtBind.text(gui, delay_field) or '').strip()
    if not raw:
        return DEFAULT_DELAY_MS
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        return DEFAULT_DELAY_MS
    return max(0, value)


def plugin_enabled():
    with lock:
        return bool(state['enabled'])


def loop_enabled():
    with lock:
        return bool(state['loop'])


def close_session(reason=None):
    with lock:
        session = state.get('session')
        state['session'] = None
    if session is None:
        return
    try:
        session['bridge'].close()
        _log('Tháo móc NativeCut%s.' % ((' · ' + reason) if reason else ''))
    except (OSError, ValueError) as error:
        _log('Chưa xác minh tháo móc — đóng client trước khi thử lại. %s' % error)


def get_or_create_session(uid):
    client = get_client()
    if not client.get('running') or not client.get('window') or not client.get('pid'):
        raise ValueError('Cần client Silkroad đang chạy (có HWND); kiểm tra Clientless.')
    if sys.platform != 'win32' or not user32:
        raise RuntimeError('NativeCut chỉ chạy trên Windows phBot host.')
    key = (int(client['pid']), client['window'], int(uid))
    with lock:
        session = state.get('session')
        if session is not None and session.get('key') == key:
            return session
    close_session('đổi UID/client — tạo NativeCut mới')
    bridge = NativeCut({'pid': key[0], 'window': key[1], 'target': key[2]})
    session = {'key': key, 'bridge': bridge, 'verified': False}
    with lock:
        state['session'] = session
    _log('NativeCut install OK · PID=%d HWND=%s UID=%d' % (key[0], key[1], key[2]))
    return session


def ui_enabled(checked):
    on = bool(checked)
    with lock:
        state['enabled'] = on
        if not on:
            state['queue'] = []
            state['active'] = None
    if not on:
        close_session('plugin tắt')
    read_self_uid()
    show_monster_pick()
    show_client()
    set_status(
        'BẬT — Cut Self=7081 self · Cut Monster=7081 monster/boss (NativeCut).'
        if on else 'TẮT — đã tháo móc.')


def ui_loop(checked):
    with lock:
        state['loop'] = bool(checked)
    set_status('Loop ON — cast→cut lặp.' if checked else 'Loop OFF — 1 phát mỗi nút.')


def btn_refresh():
    uid = read_self_uid()
    show_client()
    pick = show_monster_pick()
    set_status(
        'Làm mới · Self=%d · monster=%s · skill=%d · delay=%dms'
        % (uid, pick['uid'] if pick else 0, read_skill_id(), read_delay_ms()))


def btn_close():
    with lock:
        state['queue'] = []
        state['active'] = None
    close_session('nút Tháo móc')
    set_status('Đã tháo móc NativeCut.')


def _pack_uid(uid):
    return struct.pack('<I', int(uid) & 0xffffffff)


def _classify_b074(data):
    raw = bytes(data or b'')
    if raw == b'\x02\x00':
        return '02 00 · NGẮT OK / cast end'
    if raw == b'\x02\x01':
        return '02 01 · kết thúc skill (biến thể)'
    if len(raw) >= 4 and raw[:4] == b'\x03\x00\x04\x40':
        return '03 00 04 40 · ActionRefusal'
    if len(raw) >= 2 and raw[:2] == b'\x03\x00':
        return '%s · từ chối / fail' % _hex_bytes(raw[:8])
    return '%s · (xem hex)' % (_hex_bytes(raw[:12]) if raw else '(trống)')


def _verdict_for_job(job):
    """MID-CUT = 7081 observed + B074 02 00 after cut; FULL-CAST = end without mid cut."""
    observed = bool(job.get('observed'))
    cut_fired = bool(job.get('cut_fired'))
    b074 = job.get('b074') or ''
    b074_ok = b074.startswith('02 00')
    full_cast_flag = bool(job.get('full_cast_seen'))
    if cut_fired and observed and b074_ok:
        return 'MID-CUT'
    if full_cast_flag and not (cut_fired and observed):
        return 'FULL-CAST'
    if b074_ok and not observed:
        return 'FULL-CAST'
    if cut_fired and observed and not b074_ok:
        return 'CUT-NO-B074'
    if cut_fired and not observed:
        return 'NO-7081'
    return 'FAIL'


def queue_cut(mode):
    """Queue cast→delay→NativeCut(cut_uid). mode self→self UID; monster→monster UID."""
    if not plugin_enabled():
        set_status('Plugin đang TẮT — bật trước khi Cut.')
        return False
    if sys.platform != 'win32' or not user32:
        set_status('NativeCut chỉ chạy Windows phBot host (không Clientless).')
        return False
    self_uid = read_self_uid()
    if not self_uid:
        set_status('Chưa có Self UID — vào game rồi Làm mới.')
        return False
    skill_id = read_skill_id()
    if skill_id <= 0:
        set_status('Điền Cast skill ID trước (số skill để 7074).')
        return False
    delay_ms = read_delay_ms()
    client = get_client()
    if not (client.get('running') and client.get('pid') and client.get('window')):
        set_status('Thiếu client PID/HWND — cần cửa sổ Silkroad.')
        return False

    rows = scan_monsters()
    monster = pick_monster_row(rows)
    if monster is None:
        set_status('Không có monster/boss trong bán kính — chọn quái rồi Cut.')
        return False
    if _is_player_uid(monster['uid']):
        set_status('Từ chối Player UID=%d — chỉ monster/boss.' % monster['uid'])
        return False

    monster_uid = int(monster['uid'])
    # Real compare: Cut Self → 7081 self; Cut Monster → 7081 monster/boss.
    if mode == 'monster':
        cut_uid = monster_uid
        cut_label = 'monster'
    else:
        cut_uid = self_uid
        cut_label = 'self'
        mode = 'self'

    show_monster_pick(rows)
    job = {
        'mode': mode,
        'uid': cut_uid,  # NativeCut / 7081 target (self OR monster)
        'self_uid': self_uid,
        'select_uid': monster_uid,
        'monster_uid': monster_uid,
        'monster_name': monster['name'],
        'kind': monster['kind'],
        'skill_id': skill_id,
        'ghost_delay_ms': delay_ms,
        'label': '%s cut_uid=%d cast→#%d' % (mode, cut_uid, monster_uid),
        'phase': 'select',
        'next_at': monotonic(),
        'verify_deadline': 0.0,
        'select_deadline': 0.0,
        'cast_at': 0.0,
        'cut_at': 0.0,
        'cut_fired': False,
        'cut_fired_at': 0.0,
        'send_deadline': 0.0,
        'prewarm_started': False,
        'prewarm_ready': False,
        'prewarm_deadline': 0.0,
        'observed': False,
        'bridge_done': False,
        'b074': '',
        'full_cast_seen': False,
        'hex': _hex_bytes(_pack_uid(cut_uid)),
        'error': '',
        'verdict': '',
    }
    with lock:
        state['queue'] = [job]
        state['active'] = job
    set_status(
        'Queued %s · NativeCut cut_uid=%d (%s) · cast monster=#%d · skill=%d · delay=%dms'
        % (mode, cut_uid, cut_label, monster_uid, skill_id, delay_ms))
    _log(
        'QUEUE %s · cut_uid=%d (%s) · self=%d · monster=%d [%s] %s · skill=%d · '
        'delay_after_7074=%dms · path=NativeCut client_7081 (NOT inject)'
        % (mode, cut_uid, cut_label, self_uid, monster_uid, monster['kind'],
           monster['name'], skill_id, delay_ms))
    return True


def btn_cut_self():
    queue_cut('self')


def btn_cut_monster():
    queue_cut('monster')


def _prewarm_native(job, uid, now):
    session = get_or_create_session(uid)
    if session.get('verified'):
        job['prewarm_ready'] = True
        return True
    if not job.get('prewarm_started'):
        session['bridge'].arm(1)
        job['prewarm_started'] = True
        job['prewarm_deadline'] = now + 3.0
        _log('NativeCut PREWARM arm(1) · cut_uid=%d · mode=%s' % (uid, job.get('mode')))
        return False
    if session['bridge'].completed(4):
        session['verified'] = True
        job['prewarm_ready'] = True
        _log('NativeCut PREWARM OK · cut_uid=%d · mode=%s' % (uid, job.get('mode')))
        return True
    if now >= float(job.get('prewarm_deadline') or 0):
        raise ValueError(
            'prewarm NativeCut timeout — unload AutoGhost Ghost nếu GetTickCount conflict.')
    return False


def _retarget_bridge(session, uid):
    bridge = session.get('bridge')
    if bridge is None or not getattr(bridge, 'page', 0):
        return
    header = bridge.read(bridge.page, 16)
    state_w, tid, old_target, original = struct.unpack('<IIII', header)
    new_target = int(uid) & 0xffffffff
    if old_target == new_target:
        return
    bridge.write(
        bridge.page,
        struct.pack('<IIII', state_w, tid, new_target, original))
    _log('NativeCut retarget cut_uid %d → %d' % (old_target, new_target))


def _resolve_cut_uid(job):
    """Cut Self → live self UID; Cut Monster → monster/boss UID (never force self)."""
    mode = job.get('mode') or 'self'
    if mode == 'monster':
        cut_uid = int(job.get('monster_uid') or job.get('uid') or 0)
        if not cut_uid:
            raise ValueError('Cut Monster thiếu monster UID.')
        if _is_player_uid(cut_uid):
            raise ValueError('Cut Monster từ chối Player UID=%d.' % cut_uid)
        return cut_uid
    # mode self — refresh player_id in case of relog mid-probe
    live = read_self_uid()
    cut_uid = live or int(job.get('self_uid') or job.get('uid') or 0)
    if not cut_uid:
        raise ValueError('Cut Self thiếu self UID.')
    return cut_uid


def _fire_native_cut(job, uid, now):
    cut_uid = _resolve_cut_uid(job)
    if cut_uid != int(uid):
        _log(
            'CUT cut_uid resolve %d → %d · mode=%s'
            % (int(uid), cut_uid, job.get('mode')))
    uid = cut_uid
    job['uid'] = uid
    job['hex'] = _hex_bytes(_pack_uid(uid))
    session = get_or_create_session(uid)
    if not session.get('verified'):
        if not _prewarm_native(job, uid, now):
            return False
        session = get_or_create_session(uid)
    _retarget_bridge(session, uid)
    job['observed'] = False
    job['bridge_done'] = False
    # Keep any early FULL-CAST flag; mid-cut can still overwrite verdict later.
    session['bridge'].arm(2)
    job['cut_fired'] = True
    job['cut_fired_at'] = now
    job['phase'] = 'wait'
    job['send_deadline'] = now + 2.0
    job['next_at'] = now + 0.02
    cast_at = float(job.get('cast_at') or 0)
    since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
    with lock:
        state['last_send_uid'] = uid
        state['last_send_at'] = now
        state['pending_watch_until'] = now + 3.0
        state['active'] = job
    _log(
        'NativeCut arm(2) CUT NOW · transport=client_7081 · NOT inject · '
        'mode=%s · cut_uid=%d · self=%d · monster=%d · skill=%d · delay_cfg=%dms · '
        'since_7074=%dms · hex=%s'
        % (job.get('mode'), uid, int(job.get('self_uid') or 0),
           int(job.get('monster_uid') or 0), int(job.get('skill_id') or 0),
           int(job.get('ghost_delay_ms') or 0), since_7074, job.get('hex') or '?'))
    set_status(
        'CUT arm(2) cut_uid=%d (%s) · since_7074=%dms · monster=%d'
        % (uid, job.get('mode'), since_7074, int(job.get('monster_uid') or 0)))
    return True


def _finish_job(job, note):
    verdict = _verdict_for_job(job)
    job['verdict'] = verdict
    with lock:
        state['last_send_at'] = monotonic()
        state['last_send_uid'] = int(job.get('uid') or 0)
        state['last_observed_7081'] = bool(job.get('observed'))
        state['last_b074'] = job.get('b074') or ''
        state['last_verdict'] = verdict
        state['pending_watch_until'] = monotonic() + 2.0
        if state.get('active') is job:
            state['active'] = None
        if state['queue'] and state['queue'][0] is job:
            state['queue'].pop(0)
        if verdict == 'MID-CUT':
            state['mid_cut_count'] = int(state.get('mid_cut_count') or 0) + 1
            state['ok_count'] = int(state.get('ok_count') or 0) + 1
        elif verdict == 'FULL-CAST':
            state['full_cast_count'] = int(state.get('full_cast_count') or 0) + 1
            state['fail_count'] = int(state.get('fail_count') or 0) + 1
        else:
            state['fail_count'] = int(state.get('fail_count') or 0) + 1
        mode = job.get('mode')
        loop = bool(state.get('loop')) and bool(state.get('enabled'))
    set_stats()
    cast_at = float(job.get('cast_at') or 0)
    cut_at = float(job.get('cut_fired_at') or 0)
    since_7074 = int(round((cut_at - cast_at) * 1000)) if cast_at and cut_at else -1
    _log(
        'RESULT %s · verdict=%s · cut_uid=%d · self=%d · monster=%d · skill=%d · '
        'since_7074=%dms · 7081=%s · B074=%s · %s'
        % (job.get('mode'), verdict, int(job.get('uid') or 0),
           int(job.get('self_uid') or 0), int(job.get('monster_uid') or 0),
           int(job.get('skill_id') or 0), since_7074,
           'YES' if job.get('observed') else 'NO',
           job.get('b074') or '(none)', note))
    set_status(
        '%s · cut_uid=%d · 7081=%s · since_7074=%dms · B074=%s'
        % (verdict, int(job.get('uid') or 0),
           'YES' if job.get('observed') else 'NO', since_7074,
           job.get('b074') or '(none)'))
    if loop and mode in ('self', 'monster'):
        # Re-queue after a short gap so user can hold Loop for cast→cut→cast…
        def _requeue():
            pass
        with lock:
            state['_requeue_mode'] = mode
            state['_requeue_at'] = monotonic() + LOOP_GAP_SEC


def _drive_queue(now):
    with lock:
        requeue_at = float(state.get('_requeue_at') or 0)
        requeue_mode = state.get('_requeue_mode')
        if requeue_at and now >= requeue_at and not state['queue']:
            state['_requeue_at'] = 0.0
            mode = requeue_mode
            state['_requeue_mode'] = None
        else:
            mode = None
    if mode and loop_enabled() and plugin_enabled():
        queue_cut(mode)

    with lock:
        if not state['queue']:
            return
        job = state['queue'][0]
        state['active'] = job
    if now < float(job.get('next_at') or 0):
        return

    phase = job.get('phase') or 'select'
    uid = int(job['uid'])

    try:
        if phase == 'select':
            select_uid = int(job.get('select_uid') or 0)
            if select_uid <= 0 or _is_player_uid(select_uid):
                job['error'] = 'select UID không phải monster/boss'
                _finish_job(job, job['error'])
                return
            rows = scan_monsters()
            if not any(row['uid'] == select_uid for row in rows):
                job['error'] = 'monster #%d không còn trong bán kính' % select_uid
                _finish_job(job, job['error'])
                return
            packet = _pack_uid(select_uid)
            try:
                api = inject_joymax(0x7045, packet, False)
            except Exception as error:
                raise RuntimeError('lỗi inject 7045: %s' % error)
            _log(
                'C→S 0x7045 SELECT · monster=%d · %s · API=%r'
                % (select_uid, _safe_text(job.get('monster_name')), api))
            if api is False:
                raise RuntimeError('phBot từ chối 7045 UID=%d' % select_uid)
            with lock:
                state['selected_uid'] = select_uid
            job['phase'] = 'select_wait'
            job['select_deadline'] = now + SELECT_WAIT_SEC
            job['next_at'] = now + 0.05
            return

        if phase == 'select_wait':
            ready = _prewarm_native(job, uid, now)
            select_done = now >= float(job.get('select_deadline') or 0)
            if select_done and ready:
                job['phase'] = 'cast'
                job['next_at'] = now
                return
            job['next_at'] = now + 0.05
            return

        if phase == 'cast':
            if not _prewarm_native(job, uid, now):
                job['next_at'] = now + 0.05
                return
            select_uid = int(job.get('select_uid') or 0)
            skill_id = int(job.get('skill_id') or 0)
            delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_DELAY_MS)
            # Confirm skill known (warn only).
            try:
                skills = get_skills() or {}
            except Exception:
                skills = {}
            if skills and skill_id not in skills and str(skill_id) not in skills:
                _log('WARN skill %d không thấy trong get_skills() — vẫn cast' % skill_id)
            packet = struct.pack('<BBIBI', 1, 4, skill_id, 1, select_uid)
            try:
                api = inject_joymax(0x7074, packet, False)
            except Exception as error:
                raise RuntimeError('lỗi inject 7074: %s' % error)
            job['cast_at'] = now
            job['cut_at'] = now + (delay_ms / 1000.0)
            job['phase'] = 'cut_wait'
            job['next_at'] = now + 0.02
            _log(
                'C→S 0x7074 CAST · skill=%d · target_monster=%d · '
                'cut_due_after=%dms · hex=%s · API=%r'
                % (skill_id, select_uid, delay_ms, _hex_bytes(packet), api))
            if api is False:
                _log('7074 API=False — vẫn hẹn cut theo delay (client có thể vẫn cast)')
            set_status(
                'Cast skill %d → NativeCut cut_uid=%d (%s) sau %dms'
                % (skill_id, uid, job.get('mode'), delay_ms))
            return

        if phase == 'cut_wait':
            if job.get('cut_fired'):
                return
            cut_at = float(job.get('cut_at') or 0)
            if cut_at and now < cut_at:
                job['next_at'] = min(now + 0.02, cut_at)
                return
            if not _fire_native_cut(job, uid, now):
                job['next_at'] = now + 0.05
            return

        if phase == 'wait':
            session = get_or_create_session(uid)
            try:
                if session['bridge'].completed(5):
                    job['bridge_done'] = True
                    session['verified'] = True
            except RuntimeError as error:
                job['error'] = str(error)
                close_session(str(error))
                _finish_job(job, 'bridge error: %s' % error)
                return

            if job.get('observed') and (job.get('b074') or '').startswith('02 00'):
                _finish_job(job, 'observed 7081 + B074 02 00')
                return

            if now >= float(job.get('send_deadline') or 0):
                _finish_job(
                    job,
                    'timeout 2s · observed=%s · B074=%s · bridge5=%s'
                    % (job.get('observed'), job.get('b074') or '(none)',
                       job.get('bridge_done')))
                return
            job['next_at'] = now + 0.05
            return

    except Exception as error:
        job['error'] = '%s: %s' % (type(error).__name__, error)
        _log_traceback('drive TRACE', error)
        try:
            close_session(str(error))
        except Exception:
            pass
        _finish_job(job, job['error'])


def event_loop():
    if not plugin_enabled():
        return
    try:
        _drive_queue(monotonic())
    except Exception as error:
        _log_traceback('event_loop TRACE', error)


def handle_silkroad(opcode, data):
    raw = bytes(data or b'')
    if opcode == 0x7045 and len(raw) >= 4:
        uid = struct.unpack_from('<I', raw, 0)[0]
        if not uid:
            return
        self_uid = read_self_uid()
        if self_uid and uid == self_uid:
            return
        if _is_player_uid(uid):
            _log('IGNORE 7045 Player UID=%d (GhostCutProbe = monster/boss only)' % uid)
            return
        # Accept if in monsters/npcs, or unknown non-player (boss may be sparse).
        rows = scan_monsters()
        known = any(row['uid'] == uid for row in rows)
        with lock:
            state['selected_uid'] = uid
        show_monster_pick(rows)
        if plugin_enabled():
            _log(
                'Quan sát C→S 0x7045 monster/boss UID=%d%s'
                % (uid, '' if known else ' (chưa trong scan — vẫn ghi selected)'))
        return

    if opcode != 0x7081 or len(raw) != 4:
        return
    if not plugin_enabled():
        return
    uid = struct.unpack_from('<I', raw, 0)[0]
    with lock:
        job = state.get('active')
        watching = monotonic() <= float(state.get('pending_watch_until') or 0)
        expect = int((job or {}).get('uid') or state.get('last_send_uid') or 0)
    hex_out = _hex_bytes(raw)
    cast_at = float((job or {}).get('cast_at') or 0)
    since_7074 = int(round((monotonic() - cast_at) * 1000)) if cast_at else -1
    if expect and uid == expect and job is not None and job.get('phase') == 'wait':
        job['observed'] = True
        _log(
            'C→S 0x7081 OBSERVED · UID=%d · since_7074=%dms · hex=%s · '
            'transport=client_7081'
            % (uid, since_7074, hex_out))
    elif watching:
        _log(
            'C→S 0x7081 (khác) UID=%d · expect=%d · since_7074=%dms · hex=%s'
            % (uid, expect, since_7074, hex_out))


def handle_joymax(opcode, data):
    if not plugin_enabled():
        return
    if opcode not in (0xB074, 0xB070, 0xB081):
        return
    raw = bytes(data or b'')
    now = monotonic()
    with lock:
        watching = now <= float(state.get('pending_watch_until') or 0)
        job = state.get('active')
        last_uid = int(state.get('last_send_uid') or 0)

    if opcode == 0xB070 and job is not None:
        # Log only — cut timing is delay after 7074 (probe default 100ms).
        cast_at = float(job.get('cast_at') or 0)
        since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
        _log(
            'S→C 0xB070 · since_7074=%dms · hex=%s · (cut vẫn theo delay sau 7074)'
            % (since_7074, _hex_bytes(raw[:16])))
        return

    if opcode == 0xB074:
        note = _classify_b074(raw)
        cast_at = float((job or {}).get('cast_at') or 0)
        since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
        cut_fired = bool((job or {}).get('cut_fired'))
        observed = bool((job or {}).get('observed'))
        if job is not None and job.get('phase') in ('cut_wait', 'wait', 'cast'):
            job['b074'] = note
            # Natural cast end before/without successful mid-cut observation.
            if raw in (b'\x02\x00', b'\x02\x01') and not (cut_fired and observed):
                if not cut_fired or job.get('phase') == 'cut_wait':
                    job['full_cast_seen'] = True
        tag = 'MID-CUT?' if (cut_fired and observed) else (
            'FULL-CAST?' if job and job.get('full_cast_seen') else 'B074')
        _log(
            'S→C 0xB074 [%s] %s · self=%d · since_7074=%dms · cut_fired=%s · 7081=%s'
            % (tag, note, last_uid, since_7074, cut_fired,
               'YES' if observed else 'NO'))
        if watching or (job and job.get('phase') == 'wait'):
            if raw == b'\x02\x00' and cut_fired and observed:
                set_status(
                    'MID-CUT B074 02 00 · self=%d · since_7074=%dms'
                    % (last_uid, since_7074))
            elif raw == b'\x02\x00' and job and job.get('full_cast_seen'):
                set_status(
                    'FULL-CAST B074 02 00 · self=%d · since_7074=%dms (no mid 7081)'
                    % (last_uid, since_7074))
        return

    if opcode == 0xB081 and (watching or job):
        _log('S→C 0xB081 hex=%s' % (_hex_bytes(raw[:16]) if raw else '(trống)'))


try:
    read_self_uid()
    show_monster_pick()
    show_client()
    set_stats()
    set_status(
        'Nạp %s v%s — Cut Self=7081 self · Cut Monster=7081 monster · delay default %dms.'
        % (NAME, VERSION, DEFAULT_DELAY_MS))
except Exception:
    pass
