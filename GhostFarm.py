# -*- coding: utf-8 -*-
"""GhostFarm — Ghost farm quái/NPC (standalone, NativeCut client_7081).

Changelog:
- v1.0.2: When AutoGhost already owns GetTickCount, reuse/adopt its NativeCut
  thunk (same THUNK layout) instead of failing “Không xác minh được đích
  GetTickCount”. close() on adopted hook only arms(0)+CloseHandle (does NOT
  restore tick — AG still owns it). Hook-conflict errors back off 8s + clear
  status telling user to unload AG Ghost if adopt fails.
- v1.0.1: Fix event_loop Exception spam after Start (Self + Target monster).
  Root: except (…, ctypes.WinError) — WinError is not a catchable class; any
  NativeCut error became a second uncaught TypeError every tick. Wrap
  event_loop + _drive_native_queue like GhostNativeProbe intent; catch
  Exception; log full traceback to phBot log; sanitize monster names for
  log/UI (mojibake “Th­¬ng…”); safe hex; hashlib.sha256 fallback.
- v1.0.0: Standalone farm plugin. SAME NativeCut / client_7081 path proven in
  GhostNativeProbe (self UID → C→S 0x7081 + B074 02 00). Scans get_monsters /
  get_npcs within radius (default 50 m). Modes: Self (Ghost self UID when
  nearby) / Target monster (Ghost nearest living monster|NPC UID).
  UI: Bật, bán kính, chế độ, Start / Stop, Tháo móc.
  Độc lập — không import / không sửa AutoGhost / PartyLeader.

NativeCut extract (GhostNativeProbe / AutoGhost):
  session = NativeCut({pid, window, target})
  bridge.arm(1) → completed(4)  # verify tick hook
  bridge.arm(2)                # enqueue client 7081 for UID=target
  observe handle_silkroad 0x7081 pack('<I', uid)
  success = observed_request + B074 02 00
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
from phBot import get_character_data, get_monsters, get_npcs, get_position, log

NAME = 'GhostFarm'
VERSION = '1.0.2'

# Verified Hùng Vương client builds — copied from GhostNativeProbe / AutoGhost.
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

# x86 thunk. Marker DCBa = state pointer; DCBb = original GetTickCount slot.
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

MODE_SELF = 'Self'
MODE_TARGET = 'Target monster'
MODE_LABELS = (MODE_SELF, MODE_TARGET)

DEFAULT_RADIUS = 50.0
MAX_RADIUS = 200.0
SCAN_IDLE_SEC = 0.35
RESEND_GAP_SEC = 0.75
NO_TARGET_RETRY_SEC = 1.0
# After GetTickCount / install conflict — do not re-spam NativeCut every 0.75s.
HOOK_CONFLICT_BACKOFF_SEC = 8.0

user32 = ctypes.WinDLL('user32') if sys.platform == 'win32' else None
if user32:
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'farming': False,
    'radius': DEFAULT_RADIUS,
    'mode': MODE_SELF,
    'self_uid': 0,
    'selected_uid': 0,  # last 7045 click (monster/NPC preferred)
    'queue': [],
    'session': None,  # {'key': (pid, hwnd, uid), 'bridge': NativeCut, 'verified': bool}
    'pending_watch_until': 0.0,
    'last_send_uid': 0,
    'last_send_at': 0.0,
    'last_observed_7081': False,
    'last_b074': '',
    'active': None,
    'next_scan_at': 0.0,
    'nearby_count': 0,
    'last_pick': '',
    'ok_count': 0,
    'fail_count': 0,
}

QtBind.createLabel(gui, '%s v%s — Ghost farm quái/NPC (NativeCut)' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật / Tắt', 10, 32)

QtBind.createLabel(gui, 'Bán kính (m)', 140, 34)
radius_field = QtBind.createLineEdit(gui, str(int(DEFAULT_RADIUS)), 230, 30, 60, 22)

QtBind.createLabel(gui, 'Chế độ Ghost', 310, 34)
mode_combo = QtBind.createCombobox(gui, 400, 30, 160, 22)
for label in MODE_LABELS:
    QtBind.append(gui, mode_combo, label)
QtBind.setText(gui, mode_combo, MODE_SELF)

QtBind.createButton(gui, 'btn_start', 'Start farm', 10, 66)
QtBind.createButton(gui, 'btn_stop', 'Stop farm', 140, 66)
QtBind.createButton(gui, 'btn_refresh', 'Làm mới', 280, 66)
QtBind.createButton(gui, 'btn_close', 'Tháo móc', 400, 66)

self_uid_label = QtBind.createLabel(gui, 'Self UID: (chưa đọc)', 10, 104)
nearby_label = QtBind.createLabel(gui, 'Gần: 0 quái/NPC trong bán kính', 10, 126)
pick_label = QtBind.createLabel(gui, 'Mục tiêu Ghost: (chưa chọn)', 10, 148)
status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 170)
client_label = QtBind.createLabel(gui, 'Client: (chưa đọc)', 10, 192)
stats_label = QtBind.createLabel(gui, 'OK: 0 · Fail/timeout: 0', 10, 214)

QtBind.createLabel(
    gui,
    'Self = NativeCut self UID khi có quái/NPC trong bán kính. '
    'Target monster = UID quái/NPC gần nhất (ưu tiên 7045). '
    'v1.0.2: nếu AutoGhost đang giữ GetTickCount → GhostFarm reuse móc đó; '
    'nếu không reuse được → tắt Ghost/PvP AG hoặc unload AutoGhost.',
    10, 246,
)


def _safe_text(value, fallback='?'):
    """Normalize entity/UI names so mojibake / surrogates cannot crash log/Qt."""
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
    # Strip NULs / lone surrogates that break some phBot consoles.
    text = text.replace('\x00', '').strip()
    return text or fallback


def _hex_bytes(data):
    raw = bytes(data or b'')
    try:
        return raw.hex(' ').upper()
    except TypeError:
        return ' '.join('%02X' % byte for byte in raw)


def _file_sha256(path):
    """SHA256 of client EXE — hashlib.file_digest needs 3.11+; fallback for Stable."""
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
        ok = int(state.get('ok_count') or 0)
        fail = int(state.get('fail_count') or 0)
    QtBind.setText(gui, stats_label, 'OK: %d · Fail/timeout: %d' % (ok, fail))


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


def _autoghost_hint():
    """Best-effort: AutoGhost loaded in this phBot process?"""
    for name in list(sys.modules):
        low = str(name).casefold()
        if 'autoghost' in low:
            return True
    return False


def _hook_conflict_message(detail):
    ag = ' (AutoGhost đang nạp)' if _autoghost_hint() else ''
    return (
        '%s%s. GhostFarm sẽ thử reuse móc NativeCut nếu cùng THUNK; '
        'nếu vẫn lỗi: tắt Ghost/PvP AutoGhost hoặc unload AutoGhost rồi Start lại.'
        % (detail, ag))


def _is_hook_conflict_error(error):
    text = str(error or '').casefold()
    keys = (
        'gettickcount', 'móc', 'nativecut', 'tick', 'thunk',
        'không xác minh', 'đích gettickcount', 'qua một móc')
    return any(key in text for key in keys)


class NativeCut:
    """Minimal AutoGhost / GhostNativeProbe NativeCut — install or reuse GetTickCount thunk."""

    def __init__(self, job):
        self.api = kernel_api()
        # QUERY_INFORMATION | VM_OPERATION | VM_READ | VM_WRITE
        self.handle = self.api.OpenProcess(0x0438, False, job['pid'])
        if not self.handle:
            err = ctypes.get_last_error()
            raise OSError('OpenProcess thất bại (Win32=%s).' % err)
        self.page = self.code = self.original = 0
        self.published = False
        self.adopted = False  # True = reused AG/prior thunk; must NOT restore tick on close
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

    def _mapped_module(self, address, path_buf):
        """Return casefolded mapped module file name, or None if unmapped (thunk page)."""
        if not self.api.K32GetMappedFileNameW(
                self.handle, address, path_buf, len(path_buf)):
            return None
        try:
            return PureWindowsPath(path_buf.value).name.casefold()
        except Exception:
            return None

    def _expected_thunk(self, page):
        return (THUNK
                .replace(b'DCBa', struct.pack('<I', page))
                .replace(b'DCBb', struct.pack('<I', page + 12)))

    def _try_adopt_existing(self, job, code, tid, path_buf):
        """Reuse AutoGhost / prior NativeCut thunk when TICK_SLOT already points at it."""
        if not code or code < 4096:
            return False
        page = (code - 4096) & 0xffffffff
        try:
            header = self.read(page, 16)
        except OSError:
            return False
        _state, _old_tid, _old_target, original = struct.unpack('<IIII', header)
        mapped = self._mapped_module(original, path_buf)
        if mapped not in ('kernel32.dll', 'kernelbase.dll'):
            return False
        expected = self._expected_thunk(page)
        try:
            actual = self.read(code, len(expected))
        except OSError:
            return False
        if actual != expected:
            return False
        # Shared live hook — retarget UID, keep original GetTickCount pointer.
        self.page = page
        self.code = code
        self.original = original
        self.published = True
        self.adopted = True
        self.write(
            self.page,
            struct.pack('<IIII', 0, tid, int(job['target']) & 0xffffffff, original))
        _log(
            'NativeCut REUSE móc có sẵn · page=0x%X code=0x%X · UID=%d%s'
            % (page, code, job['target'],
               ' · AutoGhost đang nạp' if _autoghost_hint() else ''))
        return True

    def _install_fresh(self, job, tid, original):
        self.original = original
        self.adopted = False
        self.page = self.api.VirtualAllocEx(
            self.handle, None, 8192, 0x3000, 0x04) or 0
        if not self.page or self.page + 8191 > 0xffffffff:
            raise RuntimeError('Không cấp phát được vùng 32-bit cho lượt thử.')
        self.code = self.page + 4096
        thunk = self._expected_thunk(self.page)
        self.write(
            self.page,
            struct.pack('<IIII', 0, tid, int(job['target']) & 0xffffffff, original))
        self.write(self.code, thunk)
        self.protect(self.code, 4096, 0x20)
        if not self.api.FlushInstructionCache(self.handle, self.code, len(thunk)):
            raise OSError('Không đồng bộ được mã thử với client.')
        if self.read(TICK_SLOT, 4) != struct.pack('<I', original):
            raise RuntimeError(
                _hook_conflict_message(
                    'GetTickCount vừa đổi trong khi chuẩn bị (plugin khác đang móc)'))
        old = self.protect(TICK_SLOT, 4, 0x04)
        try:
            self.published = True
            self.write(TICK_SLOT, struct.pack('<I', self.code))
        finally:
            self.protect(TICK_SLOT, 4, old)

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

        current = struct.unpack('<I', self.read(TICK_SLOT, 4))[0]
        mapped = self._mapped_module(current, path)
        if mapped in ('kernel32.dll', 'kernelbase.dll'):
            self._install_fresh(job, tid, current)
            return
        # Slot already redirected (AutoGhost NativeCut / leftover Farm) — try reuse.
        if self._try_adopt_existing(job, current, tid, path):
            return
        if mapped is None:
            raise RuntimeError(
                _hook_conflict_message(
                    'Không xác minh được đích GetTickCount — slot đang trỏ vùng không-map '
                    '(thường = AutoGhost NativeCut) nhưng không khớp THUNK GhostFarm'))
        raise RuntimeError(
            _hook_conflict_message(
                'GetTickCount đang qua móc khác (%s)' % mapped))

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
            if self.adopted:
                # Foreign/shared hook (usually AutoGhost) — disarm only; never restore tick.
                try:
                    if self.page:
                        self.arm(0)
                except Exception as error:
                    _log('NativeCut adopt close disarm: %s' % error)
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
            'Client: PID=%s HWND=%s (running)' % (client.get('pid'), client.get('window')))
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


def plugin_enabled():
    with lock:
        return bool(state['enabled'])


def farming_active():
    with lock:
        return bool(state['enabled']) and bool(state['farming'])


def current_mode():
    text = (QtBind.text(gui, mode_combo) or '').strip()
    if text not in MODE_LABELS:
        text = MODE_SELF
        QtBind.setText(gui, mode_combo, text)
    with lock:
        state['mode'] = text
    return text


def read_radius():
    raw = (QtBind.text(gui, radius_field) or '').strip().replace(',', '.')
    try:
        radius = float(raw) if raw else DEFAULT_RADIUS
    except ValueError:
        radius = DEFAULT_RADIUS
    if not math.isfinite(radius) or radius < 1:
        radius = DEFAULT_RADIUS
    radius = min(radius, MAX_RADIUS)
    QtBind.setText(gui, radius_field, '%g' % radius)
    with lock:
        state['radius'] = radius
    return radius


def close_session(reason=None):
    with lock:
        session = state.get('session')
        state['session'] = None
        state['active'] = None
    if session is None:
        return
    try:
        session['bridge'].close()
        if reason:
            _log('Tháo móc NativeCut: %s' % reason)
        else:
            _log('Tháo móc NativeCut.')
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
    session = {
        'key': key,
        'bridge': bridge,
        'verified': False,
        'adopted': bool(getattr(bridge, 'adopted', False)),
    }
    with lock:
        state['session'] = session
    _log(
        'NativeCut %s OK · PID=%d HWND=%s UID=%d'
        % ('REUSE' if session['adopted'] else 'install',
           key[0], key[1], key[2]))
    return session


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


def scan_nearby(radius):
    """Return living monsters + NPCs inside radius (same region), sorted by distance."""
    position = get_position() or {}
    if not all(key in position for key in ('region', 'x', 'y')):
        return []
    try:
        px = float(position['x'])
        py = float(position['y'])
        region = position['region']
    except (TypeError, ValueError, KeyError):
        return []

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
            if not uid or not _entity_alive(entity):
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


def show_nearby(rows):
    count = len(rows)
    with lock:
        state['nearby_count'] = count
    try:
        if not rows:
            QtBind.setText(
                gui, nearby_label,
                'Gần: 0 quái/NPC trong bán kính %g m' % read_radius())
            return
        head = rows[0]
        QtBind.setText(
            gui, nearby_label,
            'Gần: %d · gần nhất %s #%d (%s) %.1fm'
            % (count, _safe_text(head['kind']), head['uid'],
               _safe_text(head['name']), head['distance']))
    except Exception as error:
        _log_traceback('show_nearby TRACE', error)


def show_pick(uid, label, kind=''):
    try:
        if uid:
            text = 'Mục tiêu Ghost: UID=%d' % uid
            if kind:
                text += ' [%s]' % _safe_text(kind)
            if label:
                text += ' · %s' % _safe_text(label)
            QtBind.setText(gui, pick_label, text)
            with lock:
                state['last_pick'] = text
        else:
            QtBind.setText(gui, pick_label, 'Mục tiêu Ghost: (chưa chọn)')
            with lock:
                state['last_pick'] = ''
    except Exception as error:
        _log_traceback('show_pick TRACE', error)


def pick_ghost_target(rows):
    """Choose NativeCut UID from scan + mode. Returns (uid, label, kind) or None."""
    mode = current_mode()
    if not rows:
        return None
    if mode == MODE_SELF:
        uid = read_self_uid()
        if not uid:
            return None
        return uid, 'self', 'self'

    with lock:
        selected = int(state.get('selected_uid') or 0)
    if selected:
        for row in rows:
            if row['uid'] == selected:
                return selected, row['name'], row['kind']
    nearest = rows[0]
    return nearest['uid'], nearest['name'], nearest['kind']


def ui_enabled(checked):
    on = bool(checked)
    with lock:
        state['enabled'] = on
        if not on:
            state['farming'] = False
            state['queue'] = []
            state['active'] = None
    if not on:
        close_session('plugin tắt')
    read_self_uid()
    read_radius()
    current_mode()
    show_client()
    show_nearby(scan_nearby(read_radius()) if on else [])
    set_status(
        'BẬT — chỉnh bán kính/chế độ rồi Start farm.'
        if on else 'TẮT — đã Stop + tháo móc.')


def btn_refresh():
    uid = read_self_uid()
    radius = read_radius()
    mode = current_mode()
    show_client()
    rows = scan_nearby(radius)
    show_nearby(rows)
    pick = pick_ghost_target(rows) if rows else None
    if pick:
        show_pick(pick[0], pick[1], pick[2])
    else:
        show_pick(0, '', '')
    set_status(
        'Làm mới · Self=%d · mode=%s · gần=%d · r=%gm'
        % (uid, mode, len(rows), radius))


def btn_close():
    close_session('nút Tháo móc')
    set_status('Đã tháo móc NativeCut.')


def btn_start():
    if not plugin_enabled():
        set_status('Plugin đang TẮT — bật trước khi Start.')
        return
    read_radius()
    current_mode()
    self_uid = read_self_uid()
    if current_mode() == MODE_SELF and not self_uid:
        set_status('Chưa có Self UID — vào game rồi Làm mới.')
        return
    show_client()
    with lock:
        state['farming'] = True
        state['next_scan_at'] = monotonic()
        state['queue'] = []
        state['active'] = None
    set_status(
        'START farm · mode=%s · bán kính %gm — NativeCut client_7081'
        % (current_mode(), read_radius()))


def btn_stop():
    with lock:
        state['farming'] = False
        state['queue'] = []
        state['active'] = None
    close_session('Stop farm')
    set_status('STOP farm — đã tháo móc.')


def _pack_uid(uid):
    return struct.pack('<I', int(uid) & 0xffffffff)


def queue_native(uid, label, kind='?'):
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        set_status('UID không hợp lệ.')
        return False
    if not 0 < uid <= 0xffffffff:
        set_status('UID trống / không hợp lệ.')
        return False
    job = {
        'uid': uid,
        'label': label,
        'kind': kind,
        'times': 1,
        'done': 0,
        'phase': 'ensure',
        'verify_deadline': 0.0,
        'send_deadline': 0.0,
        'next_at': monotonic(),
        'observed': False,
        'bridge_done': False,
        'b074': '',
        'ok_any': False,
        'hex': _hex_bytes(_pack_uid(uid)),
        'error': '',
    }
    with lock:
        state['queue'] = [job]
        state['active'] = job
    show_pick(uid, label, kind)
    set_status(
        'Xếp NativeCut %s UID=%d [%s] · arm(2) event_loop'
        % (_safe_text(label), uid, _safe_text(kind)))
    return True


def _classify_b074(data):
    raw = bytes(data or b'')
    if raw == b'\x02\x00':
        return '02 00 · NGẮT OK / cast end (Ghost signal)'
    if raw == b'\x02\x01':
        return '02 01 · kết thúc skill (biến thể)'
    if len(raw) >= 4 and raw[:4] == b'\x03\x00\x04\x40':
        return '03 00 04 40 · ActionRefusal (từ chối / OOR / busy)'
    if len(raw) >= 2 and raw[:2] == b'\x03\x00':
        return '%s · từ chối / fail (03 00…)' % _hex_bytes(raw[:8])
    return '%s · (xem hex)' % (_hex_bytes(raw[:12]) if raw else '(trống)')


def _finish_job(job, note, ok=False):
    with lock:
        state['last_send_at'] = monotonic()
        state['last_send_uid'] = int(job.get('uid') or 0)
        state['last_observed_7081'] = bool(job.get('observed'))
        state['last_b074'] = job.get('b074') or ''
        state['pending_watch_until'] = monotonic() + 3.0
        if state.get('active') is job:
            state['active'] = None
        if ok:
            state['ok_count'] = int(state.get('ok_count') or 0) + 1
        else:
            state['fail_count'] = int(state.get('fail_count') or 0) + 1
        state['next_scan_at'] = monotonic() + RESEND_GAP_SEC
    set_stats()
    set_status(note)


def _advance_or_finish(job, ok_shot):
    if ok_shot:
        job['ok_any'] = True
    job['done'] = int(job.get('done') or 0) + 1
    with lock:
        if state['queue'] and state['queue'][0] is job:
            state['queue'].pop(0)
    observed = 'YES' if job.get('observed') else 'NO'
    b074 = job.get('b074') or '(chưa thấy)'
    ok = bool(
        job.get('ok_any') and job.get('observed')
        and (job.get('b074') or '').startswith('02 00'))
    if ok:
        _finish_job(
            job,
            'OK farm NativeCut %s UID=%d · observed 7081=%s · B074 %s'
            % (job['label'], job['uid'], observed, b074),
            ok=True)
    elif job.get('error'):
        _finish_job(
            job,
            'LỖI farm NativeCut %s UID=%d · %s'
            % (job['label'], job['uid'], job['error']),
            ok=False)
    else:
        _finish_job(
            job,
            'XONG farm NativeCut %s UID=%d · observed 7081=%s · B074 %s · bridge=%s'
            % (job['label'], job['uid'], observed, b074,
               'done' if job.get('bridge_done') else 'pending/timeout'),
            ok=False)


def _drive_native_queue(now):
    with lock:
        if not state['queue']:
            return
        job = state['queue'][0]
        state['active'] = job
    if now < float(job.get('next_at') or 0):
        return

    phase = job.get('phase') or 'ensure'
    uid = int(job['uid'])

    try:
        if phase == 'ensure':
            session = get_or_create_session(uid)
            if session['verified']:
                job['phase'] = 'arm'
                job['next_at'] = now
                return
            session['bridge'].arm(1)
            job['phase'] = 'verify'
            job['verify_deadline'] = now + 3.0
            job['next_at'] = now + 0.05
            _log('NativeCut [%s] arm(1) verify UID=%d' % (job['label'], uid))
            return

        if phase == 'verify':
            session = get_or_create_session(uid)
            if session['bridge'].completed(4):
                session['verified'] = True
                job['phase'] = 'arm'
                job['next_at'] = now
                _log('NativeCut [%s] verified tick hook UID=%d' % (job['label'], uid))
                return
            if now >= float(job.get('verify_deadline') or 0):
                raise ValueError('không nhận được nhịp luồng của cửa sổ game (verify timeout).')
            job['next_at'] = now + 0.05
            return

        if phase == 'arm':
            session = get_or_create_session(uid)
            if not session['verified']:
                job['phase'] = 'ensure'
                job['next_at'] = now
                return
            job['observed'] = False
            job['bridge_done'] = False
            job['b074'] = ''
            session['bridge'].arm(2)
            job['phase'] = 'wait'
            job['send_deadline'] = now + 2.0
            job['next_at'] = now + 0.02
            with lock:
                state['last_send_uid'] = uid
                state['last_send_at'] = now
                state['pending_watch_until'] = now + 3.0
            _log(
                'NativeCut [%s] arm(2) client_7081 UID=%d hex=%s · chờ observed+B074'
                % (job['label'], uid, job.get('hex') or '?'))
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
                with lock:
                    if state['queue'] and state['queue'][0] is job:
                        state['queue'].pop(0)
                _finish_job(job, 'LỖI bridge UID=%d · %s' % (uid, error), ok=False)
                return

            if job.get('observed') and (job.get('b074') or '').startswith('02 00'):
                _log(
                    'NativeCut [%s] SUCCESS UID=%d · observed 7081 + B074 02 00 · bridge5=%s'
                    % (job['label'], uid, job.get('bridge_done')))
                _advance_or_finish(job, ok_shot=True)
                return

            if now >= float(job.get('send_deadline') or 0):
                _log(
                    'NativeCut [%s] TIMEOUT 2s UID=%d · observed=%s · B074=%s · bridge5=%s'
                    % (job['label'], uid, job.get('observed'),
                       job.get('b074') or '(none)', job.get('bridge_done')))
                _advance_or_finish(job, ok_shot=False)
                return
            job['next_at'] = now + 0.05
            return

    except Exception as error:
        # NOTE: never except ctypes.WinError — it is a factory fn, not a class;
        # catching it raised TypeError and spammed “Python: Exception occurred”.
        job['error'] = '%s: %s' % (type(error).__name__, error)
        _log_traceback('NativeCut drive TRACE', error)
        close_session(str(error))
        backoff = (HOOK_CONFLICT_BACKOFF_SEC
                   if _is_hook_conflict_error(error) else RESEND_GAP_SEC)
        with lock:
            if state['queue'] and state['queue'][0] is job:
                state['queue'].pop(0)
            state['active'] = None
            state['fail_count'] = int(state.get('fail_count') or 0) + 1
            state['next_scan_at'] = monotonic() + backoff
        set_stats()
        tip = ''
        if _is_hook_conflict_error(error):
            tip = ' · backoff %gs — tắt Ghost AG hoặc unload AutoGhost nếu lặp lại' % (
                HOOK_CONFLICT_BACKOFF_SEC)
        set_status(
            'LỖI NativeCut %s UID=%d · %s%s'
            % (_safe_text(job.get('label')), uid, job['error'], tip))
        return


def _farm_scan_tick(now):
    with lock:
        if state['queue'] or state.get('active'):
            return
        if now < float(state.get('next_scan_at') or 0):
            return
    radius = read_radius()
    rows = scan_nearby(radius)
    show_nearby(rows)
    pick = pick_ghost_target(rows)
    if not pick:
        with lock:
            state['next_scan_at'] = now + NO_TARGET_RETRY_SEC
        show_pick(0, '', '')
        set_status(
            'Farm đang chạy — chưa thấy quái/NPC trong %gm (mode=%s).'
            % (radius, current_mode()))
        return
    uid, label, kind = pick
    queue_native(uid, _safe_text(label), _safe_text(kind))


def event_loop():
    """Drive farm scan + NativeCut verify/arm/wait from phBot callback."""
    if not plugin_enabled():
        return
    try:
        now = monotonic()
        if farming_active():
            with lock:
                busy = bool(state['queue']) or state.get('active') is not None
            if busy:
                _drive_native_queue(now)
            else:
                _farm_scan_tick(now)
            return
        # Not farming: still advance any leftover single job (none expected after Stop).
        with lock:
            has_queue = bool(state['queue'])
        if has_queue:
            _drive_native_queue(now)
    except Exception as error:
        _log_traceback('event_loop TRACE', error)
        with lock:
            state['queue'] = []
            state['active'] = None
            state['fail_count'] = int(state.get('fail_count') or 0) + 1
            state['next_scan_at'] = monotonic() + RESEND_GAP_SEC
        try:
            close_session('event_loop exception')
        except Exception:
            pass
        try:
            set_stats()
            set_status('LỖI event_loop · %s: %s — xem log TRACE' % (
                type(error).__name__, error))
        except Exception:
            pass


def handle_silkroad(opcode, data):
    """Observe C→S: 7045 target + NativeCut-emitted 0x7081."""
    raw = bytes(data or b'')
    if opcode == 0x7045 and len(raw) >= 4:
        uid = struct.unpack_from('<I', raw, 0)[0]
        if uid:
            self_uid = read_self_uid()
            if not self_uid or uid != self_uid:
                with lock:
                    state['selected_uid'] = uid
                if plugin_enabled():
                    _log('Quan sát C→S 0x7045 chọn UID=%d (ưu tiên Target monster).' % uid)
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
    if expect and uid == expect and job is not None and job.get('phase') == 'wait':
        job['observed'] = True
        _log(
            'C→S 0x7081 OBSERVED (NativeCut) UID=%d hex=%s · transport=client_7081'
            % (uid, hex_out))
    elif watching:
        _log(
            'C→S 0x7081 (khác/đồng thời) UID=%d hex=%s · expect=%d'
            % (uid, hex_out, expect))


def handle_joymax(opcode, data):
    """Log S→C B074 after NativeCut arm."""
    if not plugin_enabled():
        return
    if opcode not in (0xB074, 0xB081, 0xB084, 0x3085):
        return
    try:
        raw = bytes(data or b'')
        with lock:
            watching = monotonic() <= float(state.get('pending_watch_until') or 0)
            last_uid = int(state.get('last_send_uid') or 0)
            job = state.get('active')
        prefix = 'sau NativeCut' if watching else 'ngoài cửa sổ 3s'
        if opcode == 0xB074:
            note = _classify_b074(raw)
            _log('S→C 0xB074 [%s] %s | last UID=%d' % (prefix, note, last_uid))
            if job is not None and job.get('phase') == 'wait' and watching:
                job['b074'] = note
                if raw == b'\x02\x00':
                    set_status(
                        'B074 02 00 sau NativeCut UID=%d — NGẮT OK.' % last_uid)
                elif raw[:2] == b'\x03\x00':
                    set_status(
                        'B074 từ chối sau NativeCut UID=%d — %s'
                        % (last_uid, note))
            return
        if opcode == 0xB081:
            _log('S→C 0xB081 [%s] hex=%s'
                 % (prefix, _hex_bytes(raw[:16]) if raw else '(trống)'))
            return
        if opcode in (0xB084, 0x3085) and watching:
            _log('S→C 0x%04X [%s] hex=%s'
                 % (opcode, prefix, _hex_bytes(raw[:16]) if raw else '(trống)'))
    except Exception as error:
        _log_traceback('handle_joymax TRACE', error)


try:
    read_self_uid()
    read_radius()
    current_mode()
    show_client()
    set_stats()
    set_status(
        'Nạp %s v%s — bật → chọn Self/Target → Start farm (NativeCut, không inject).'
        % (NAME, VERSION))
except Exception as error:
    try:
        _log_traceback('load TRACE', error)
    except Exception:
        pass
