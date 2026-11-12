# -*- coding: utf-8 -*-
"""GhostFarm — Ghost farm quái/NPC (standalone, NativeCut client_7081).

Changelog:
- v1.0.11: Overnight “có ghost đâu” harden — interrupt is ONLY NativeCut
  client_7081 self (arm(2)), never inject 7081. Event-loop fires cut at
  cut_at (Timer is nudge only; no silent Timer/active skip). Retarget self
  UID in thunk page before every arm(2). Log every B070 reject + every CUT
  SKIP. Every failed cycle LOUD `GHOST FAIL` (no 7081 / no B074 02 00) with
  phase/cut_fired/b070/bridge. Cancel before cast only if basic was dropped.
  NativeCut install fail stays on status every cycle. Windows host required.
- v1.0.10: Prefill Skill IDs from confirmed Auto PK F1 skill+Ngắt table
  (skip blank IDs; ignore blank-ID ms 850; no 81037):
  `80031=1;66007=5;54016=1;81019=5;7678=1;81016=7;7653=5`.
- v1.0.9: Fix “toàn đánh thường” farm — after 7045, phBot training / client
  basic `7074 01 01 01` stole combat while NativeCut prewarmed, so 7074 skill
  never got B070 and Ghost looked absent. While farming: DROP basic attacks,
  cancel action before skill cast, prewarm at Start. Also: close_session no
  longer clears active (Timer arm(2) race); cut_wait backup if Timer died;
  empty Skill IDs stop farm with loud status instead of silent basic-only.
- v1.0.8: Match AG PVP interrupt byte-for-byte timing — wait S→C B070 (cast
  landed / mid-animation) THEN Timer(cfg_ms) → arm(2). 1.0.7 cut at 7074+ms
  aborted cast before hit (no B070, “skill không đánh”). Keep prewarm before
  cast. Fallback: if no B070 within 800ms, cut as 7074+cfg_ms.
- v1.0.7: Prewarm then Timer from 7074 (too early — aborted cast before B070).
- v1.0.6: Real Ghost overlap — pre-warm NativeCut BEFORE cast; fire arm(2) at
  configured ms from 7074 send (prefer: wait B070 then +ms). Do NOT spend the
  delay installing/verifying the hook after the cast window (that cut after XP
  / finished cast → B074 02 00 without skill reset). Dead target still cuts.
- v1.0.5: Skill field `80031=1;66007=20;54016=0` = skillId=ms delay before
  NativeCut self. Per-skill Ghost timing. If monster dies after SELECT/cast,
  still wait ms then Ghost self (do not ValueError-skip interrupt). Soft-skip
  only when no living target at SELECT time.
- v1.0.4: Combat cycle — EVERY loop: (1) 7045 select living monster in radius
  FIRST (log), (2) cast attack skill 7074 on that UID (skill IDs UI),
  (3) NativeCut self interrupt while casting. Never Ghost without a living
  in-range target. Without targeting, Ghost is useless.
- v1.0.3: Target monster was NativeCut(monster UID) → C→S 7081 + B081 +
  “Không thấy mục tiêu” / no B074. Fix: inject 0x7045 select monster first,
  then NativeCut **self UID** (proven interrupt B074). Only Ghost when a
  living monster/NPC is in radius; Target also requires select. Prefer Self
  mode for farm interrupt.
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
from threading import RLock, Timer
from time import monotonic
from ctypes import wintypes

import QtBind
import phBot as phbot_api
from phBot import (
    get_character_data, get_monsters, get_npcs, get_position, get_skills,
    inject_joymax, log)

NAME = 'GhostFarm'
VERSION = '1.0.11'
SKILL_FIELD_EXAMPLE = '80031=1;66007=5;54016=1;81019=5;7678=1;81016=7;7653=5'

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
SELECT_WAIT_SEC = 0.25  # after 7045 before skill cast
DEFAULT_GHOST_DELAY_MS = 0  # used when skill has no =ms (bare id)
# AG schedules Timer on B070; if confirm never arrives, fall back after this.
B070_WAIT_SEC = 0.8
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
    'selected_uid': 0,  # last 7045 select (monster/NPC)
    'skill_index': 0,
    'queue': [],
    'session': None,  # {'key': (pid, hwnd, uid), 'bridge': NativeCut, 'verified': bool}
    'pending_watch_until': 0.0,
    'last_send_uid': 0,
    'last_send_at': 0.0,
    'last_observed_7081': False,
    'last_b074': '',
    'last_cast_skill': 0,
    'active': None,
    'next_scan_at': 0.0,
    'nearby_count': 0,
    'last_pick': '',
    'ok_count': 0,
    'fail_count': 0,
    'basic_drop_count': 0,
    'ghost_ok_count': 0,
    'ghost_fail_count': 0,
    'last_ghost_fail': '',
    'last_nativcut_error': '',
    'live_timers': set(),
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

QtBind.createLabel(gui, 'Skill IDs (F1)', 10, 98)
skill_field = QtBind.createLineEdit(gui, SKILL_FIELD_EXAMPLE, 110, 94, 450, 22)

self_uid_label = QtBind.createLabel(gui, 'Self UID: (chưa đọc)', 10, 126)
nearby_label = QtBind.createLabel(gui, 'Gần: 0 quái/NPC trong bán kính', 10, 148)
pick_label = QtBind.createLabel(gui, 'Mục tiêu Ghost: (chưa chọn)', 10, 170)
status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 192)
client_label = QtBind.createLabel(gui, 'Client: (chưa đọc)', 10, 214)
stats_label = QtBind.createLabel(gui, 'OK: 0 · Fail/timeout: 0', 10, 236)

QtBind.createLabel(
    gui,
    'v1.0.11: NativeCut self 7081 after B070+Timer (NOT inject). '
    'Log must show arm(2)+7081+B074 02 00. VD: 80031=1;66007=20.',
    10, 268,
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
        ghost_ok = int(state.get('ghost_ok_count') or 0)
        ghost_fail = int(state.get('ghost_fail_count') or 0)
    QtBind.setText(
        gui, stats_label,
        'OK: %d · Fail: %d · GhostOK: %d · GhostFAIL: %d'
        % (ok, fail, ghost_ok, ghost_fail))


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
    uid = 0
    for key in ('player_id', 'unique_id', 'uid'):
        try:
            value = int(character.get(key) or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            uid = value
            break
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


def read_skill_entries():
    """Parse Skill IDs field as [(skill_id, ghost_delay_ms), ...].

    Formats:
      80031=1;66007=5;54016=1;81019=5;7678=1;81016=7;7653=5
      80031=1,66007=5
      3048,3050          → delay DEFAULT_GHOST_DELAY_MS
    """
    raw = (QtBind.text(gui, skill_field) or '').strip()
    if not raw:
        return []
    for sep in (',', '|', ' '):
        raw = raw.replace(sep, ';')
    entries = []
    seen = set()
    for part in raw.split(';'):
        part = part.strip()
        if not part:
            continue
        delay_ms = DEFAULT_GHOST_DELAY_MS
        if '=' in part:
            left, right = part.split('=', 1)
            left = left.strip()
            right = right.strip()
            try:
                skill_id = int(left)
            except ValueError:
                continue
            try:
                delay_ms = int(float(right))
            except ValueError:
                delay_ms = DEFAULT_GHOST_DELAY_MS
        else:
            try:
                skill_id = int(part)
            except ValueError:
                continue
        if skill_id <= 0 or skill_id in seen:
            continue
        if delay_ms < 0:
            delay_ms = 0
        if delay_ms > 10000:
            delay_ms = 10000
        seen.add(skill_id)
        entries.append((skill_id, delay_ms))
    return entries


def read_skill_ids():
    """Skill id list only (compat for Start checks / status)."""
    return [skill_id for skill_id, _delay in read_skill_entries()]


def next_attack_skill():
    """Rotate skills; return (skill_id, ghost_delay_ms) or (0, 0)."""
    entries = read_skill_entries()
    if not entries:
        return 0, 0
    skills = {}
    try:
        skills = get_skills() or {}
    except Exception:
        skills = {}
    with lock:
        start = int(state.get('skill_index') or 0) % len(entries)
    for offset in range(len(entries)):
        skill_id, delay_ms = entries[(start + offset) % len(entries)]
        data = skills.get(skill_id) or skills.get(str(skill_id))
        if isinstance(data, dict) and data.get('can_cast') is False:
            continue
        with lock:
            state['skill_index'] = (start + offset + 1) % len(entries)
            state['last_cast_skill'] = skill_id
        return skill_id, delay_ms
    skill_id, delay_ms = entries[start]
    with lock:
        state['skill_index'] = (start + 1) % len(entries)
        state['last_cast_skill'] = skill_id
    return skill_id, delay_ms


def close_session(reason=None):
    """Close NativeCut bridge only.

    Do NOT clear state['active'] here — get_or_create_session calls this when
    (re)installing the hook, and wiping active races the B070 Timer so arm(2)
    is skipped (skills may cast, Ghost never fires; training fills with basic).
    """
    with lock:
        session = state.get('session')
        state['session'] = None
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


def _is_basic_attack_7074(raw):
    """Client / phBot training basic attack: 7074 len7 01 01 01 + UID."""
    raw = bytes(raw or b'')
    return len(raw) == 7 and raw[:3] == b'\x01\x01\x01'


def _cancel_current_action(reason='trước cast skill'):
    """Ask client to abort current swing/cast so 7074 skill is not queued behind basic."""
    try:
        api = inject_joymax(0x7074, b'\x02', False)
    except Exception as error:
        _log('7074 cancel (%s) exception: %s' % (reason, error))
        return False
    _log('C→S 0x7074 CANCEL action · %s · API=%r' % (reason, api))
    return api is not False


def _prewarm_self_at_start():
    """Kick NativeCut install/verify at Start so first select→cast is not delayed.

    Non-blocking: arm(1) here; select_wait / event_loop completes(4).
    """
    self_uid = read_self_uid()
    if not self_uid:
        return False
    try:
        session = get_or_create_session(self_uid)
        if session.get('verified'):
            _log('NativeCut PREWARM@Start already verified · self=%d' % self_uid)
            return True
        session['bridge'].arm(1)
        _log('NativeCut PREWARM@Start arm(1) · self=%d (verify trên event_loop)' % self_uid)
        return True
    except Exception as error:
        _log_traceback('PREWARM@Start TRACE', error)
        set_status(
            'NativeCut chưa sẵn sàng: %s — vẫn Start; cast chờ hook / xem log.'
            % error)
        return False


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


def _pick_monster_row(rows):
    """Prefer last 7045 selection if still in-range; else nearest living row."""
    if not rows:
        return None
    with lock:
        selected = int(state.get('selected_uid') or 0)
    if selected:
        for row in rows:
            if row['uid'] == selected:
                return row
    return rows[0]


def pick_farm_job(rows):
    """Build farm job only when a living monster/NPC is in range.

    EVERY cycle: 7045(monster) → 7074(skill, monster) → NativeCut(self).
    Never Ghost without a living in-range target.
    """
    if not rows:
        return None
    self_uid = read_self_uid()
    if not self_uid:
        return None
    monster = _pick_monster_row(rows)
    if monster is None:
        return None
    skill_id, delay_ms = next_attack_skill()
    if not skill_id:
        return None
    mode = current_mode()
    return {
        'ghost_uid': self_uid,
        'select_uid': int(monster['uid']),
        'need_select': True,  # always — no target at SELECT ⇒ soft-skip
        'skill_id': int(skill_id),
        'ghost_delay_ms': int(delay_ms),
        'label': monster['name'],
        'kind': monster['kind'],
        'monster_uid': int(monster['uid']),
        'monster_name': monster['name'],
        'mode': mode,
    }


def pick_ghost_target(rows):
    """UI helper: show combat target + interrupt self."""
    job = pick_farm_job(rows)
    if not job:
        return None
    return (
        job['ghost_uid'],
        '7045#%d→7074#%d=%dms→Ghost self' % (
            job['monster_uid'], job.get('skill_id') or 0,
            job.get('ghost_delay_ms') or 0),
        _safe_text(job.get('kind') or 'monster'),
    )


def ui_enabled(checked):
    on = bool(checked)
    with lock:
        active = state.get('active')
        state['enabled'] = on
        if not on:
            state['farming'] = False
            state['queue'] = []
            state['active'] = None
    if not on:
        _cancel_cut_timer(active)
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
        set_status('Plugin đang TẮT — tick Bật trước khi Start.')
        _log('START từ chối — plugin TẮT (chỉ Bật checkbox không đủ nếu chưa Start).')
        return
    if sys.platform != 'win32' or not user32:
        set_status(
            'GHOST BLOCKED — NativeCut chỉ chạy Windows phBot host (không Clientless).')
        _log(
            'START từ chối — platform=%s user32=%s. Interrupt = NativeCut '
            'client_7081, không inject_joymax(0x7081).'
            % (sys.platform, bool(user32)))
        return
    read_radius()
    current_mode()
    self_uid = read_self_uid()
    if not self_uid:
        set_status('Chưa có Self UID — vào game rồi Làm mới.')
        return
    entries = read_skill_entries()
    if not entries:
        set_status(
            'Thiếu Skill IDs — điền rồi Start. Ví dụ: %s'
            % SKILL_FIELD_EXAMPLE)
        _log(
            'START từ chối — Skill IDs trống. Không cast 7074 / không Ghost; '
            'nếu Training bật sẽ chỉ thấy đánh thường. Ví dụ: %s'
            % SKILL_FIELD_EXAMPLE)
        return
    show_client()
    client = get_client()
    if not (client.get('running') and client.get('pid') and client.get('window')):
        set_status(
            'GHOST BLOCKED — thiếu client PID/HWND (cần cửa sổ Silkroad, không Clientless).')
        _log('START từ chối — get_client() thiếu running/pid/window.')
        return
    with lock:
        active = state.get('active')
        state['farming'] = True
        state['next_scan_at'] = monotonic()
        state['queue'] = []
        state['active'] = None
        state['skill_index'] = 0
        state['last_ghost_fail'] = ''
        state['last_nativcut_error'] = ''
    _cancel_cut_timer(active)
    prewarm_ok = _prewarm_self_at_start()
    preview = ';'.join('%d=%d' % pair for pair in entries[:6])
    ag = ' · AutoGhost đang nạp (có thể conflict GetTickCount)' if _autoghost_hint() else ''
    set_status(
        'START · self=%d · %s · path=NativeCut arm(2) after B070 · prewarm=%s%s'
        % (self_uid, preview, 'OK' if prewarm_ok else 'PENDING/FAIL', ag))
    _log(
        'START farm · skills=%s · self=%d · interrupt=NativeCut client_7081 '
        'self (NOT inject) · expect log: B070 → arm(2) → C→S 7081 → B074 02 00 · '
        'tắt Training; unload AG Ghost nếu móc conflict.%s'
        % (preview, self_uid, ag))


def btn_stop():
    with lock:
        active = state.get('active')
        state['farming'] = False
        state['queue'] = []
        state['active'] = None
    _cancel_cut_timer(active)
    close_session('Stop farm')
    set_status('STOP farm — đã tháo móc.')


def _pack_uid(uid):
    return struct.pack('<I', int(uid) & 0xffffffff)


def queue_native(farm_job):
    """Queue combat: 7045(monster) → 7074(skill) → NativeCut(self). Never without target."""
    if not isinstance(farm_job, dict):
        set_status('Job farm không hợp lệ.')
        return False
    try:
        ghost_uid = int(farm_job.get('ghost_uid') or 0)
        select_uid = int(farm_job.get('select_uid') or farm_job.get('monster_uid') or 0)
        skill_id = int(farm_job.get('skill_id') or 0)
        delay_ms = int(farm_job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
    except (TypeError, ValueError):
        set_status('UID/skill không hợp lệ.')
        return False
    if not 0 < ghost_uid <= 0xffffffff:
        set_status('Self UID trống — không Ghost.')
        return False
    if not 0 < select_uid <= 0xffffffff:
        set_status('Không có quái mục tiêu — không Ghost.')
        return False
    if skill_id <= 0:
        set_status('Thiếu skill ID — không cast / không Ghost.')
        return False
    if delay_ms < 0:
        delay_ms = 0
    label = _safe_text(farm_job.get('label') or 'monster')
    kind = _safe_text(farm_job.get('kind') or '?')
    job = {
        'uid': ghost_uid,  # NativeCut / 7081 = self interrupt
        'select_uid': select_uid,
        'need_select': True,
        'monster_uid': select_uid,
        'skill_id': skill_id,
        'ghost_delay_ms': delay_ms,
        'label': label,
        'kind': kind,
        'mode': farm_job.get('mode') or current_mode(),
        'times': 1,
        'done': 0,
        'phase': 'select',  # always select living monster FIRST
        'verify_deadline': 0.0,
        'send_deadline': 0.0,
        'select_deadline': 0.0,
        'cast_at': 0.0,
        'cut_at': 0.0,
        'b070_deadline': 0.0,
        'select_sent': False,
        'select_observed': False,
        'cast_sent': False,
        'cast_api': None,
        'b070_seen': False,
        'b070_at': 0.0,
        'prewarm_started': False,
        'prewarm_ready': False,
        'prewarm_deadline': 0.0,
        'cut_fired_at': 0.0,
        'next_at': monotonic(),
        'observed': False,
        'bridge_done': False,
        'b074': '',
        'ok_any': False,
        'hex': _hex_bytes(_pack_uid(ghost_uid)),
        'error': '',
    }
    with lock:
        state['queue'] = [job]
        state['active'] = job
    show_pick(
        ghost_uid,
        '7045#%d→skill%d=%dms→Ghost self · %s'
        % (select_uid, skill_id, delay_ms, label),
        kind)
    set_status(
        'Xếp combat · target=%d · skill=%d · Ghost sau %dms · self=%d'
        % (select_uid, skill_id, delay_ms, ghost_uid))
    return True


def _soft_skip_job(job, note):
    """Drop current cycle without fail TRACE — used when SELECT has no target."""
    _cancel_cut_timer(job)
    with lock:
        if state['queue'] and state['queue'][0] is job:
            state['queue'].pop(0)
        if state.get('active') is job:
            state['active'] = None
        state['next_scan_at'] = monotonic() + NO_TARGET_RETRY_SEC
    set_status(note)
    _log('SOFT-SKIP: %s' % note)


def _prewarm_native(job, uid, now):
    """Install/verify NativeCut BEFORE cast so arm(2) can fire on the ms mark.

    Returns True when session verified and ready to arm(2) instantly.
    """
    session = get_or_create_session(uid)
    if session.get('verified'):
        job['prewarm_ready'] = True
        return True
    if not job.get('prewarm_started'):
        session['bridge'].arm(1)
        job['prewarm_started'] = True
        job['prewarm_deadline'] = now + 3.0
        _log('NativeCut PREWARM arm(1) verify UID=%d (trước cast)' % uid)
        return False
    if session['bridge'].completed(4):
        session['verified'] = True
        job['prewarm_ready'] = True
        _log('NativeCut PREWARM OK · UID=%d · sẵn sàng arm(2) overlapping cast' % uid)
        return True
    if now >= float(job.get('prewarm_deadline') or 0):
        with lock:
            state['last_nativcut_error'] = 'prewarm timeout 3s'
        raise ValueError(
            'prewarm NativeCut timeout — không arm(2)/7081 được. '
            'Cần Windows phBot + client Hùng Vương đã pin; nếu AutoGhost đang '
            'móc GetTickCount: tắt Ghost/PvP AG hoặc unload AG rồi Start lại.')
    return False


def _cancel_cut_timer(job):
    timer = job.pop('cut_timer', None) if isinstance(job, dict) else None
    if timer is not None:
        try:
            timer.cancel()
        except Exception:
            pass
        with lock:
            timers = state.get('live_timers')
            if isinstance(timers, set):
                timers.discard(timer)


def _retarget_bridge(session, uid):
    """Rewrite NativeCut page target UID before arm(2) (AG get_client_exchange spirit)."""
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
    _log('NativeCut retarget page UID %d → %d (trước arm(2))' % (old_target, new_target))


def _fire_native_cut(job, uid, now=None, reason='cut'):
    """AG/GhostNativeProbe cut: session ready → bridge.arm(2) only (NOT inject 7081)."""
    now = monotonic() if now is None else now
    with lock:
        active = state.get('active')
        if active is not None and active is not job:
            _log(
                'CUT SKIP · active is other job · phase=%s · reason=%s'
                % (job.get('phase'), reason))
            return False
        # Claim active so Timer/event_loop cannot race-skip arm(2).
        state['active'] = job
        if job.get('cut_fired'):
            return True
        if job.get('phase') not in ('cut_wait', 'arm', 'cut_now'):
            _log(
                'CUT SKIP · bad phase=%s · reason=%s · skill=%s'
                % (job.get('phase'), reason, job.get('skill_id')))
            return False
        job['phase'] = 'cut_now'
    try:
        # Refresh self UID — wrong UID ⇒ 7081 to dead target, no B074 02 00.
        live_uid = read_self_uid() or int(uid)
        if live_uid and live_uid != int(uid):
            _log('CUT self UID refresh %d → %d' % (int(uid), live_uid))
            uid = live_uid
            job['uid'] = uid
            job['hex'] = _hex_bytes(_pack_uid(uid))
        session = get_or_create_session(uid)
        if not session.get('verified'):
            if not _prewarm_native(job, uid, now):
                _log('CUT SKIP · NativeCut chưa verify · reason=%s · self=%d' % (reason, uid))
                with lock:
                    state['last_nativcut_error'] = 'prewarm chưa xong trước arm(2)'
                return False
            session = get_or_create_session(uid)
        _retarget_bridge(session, uid)
        # Exact AG send_pvp_interrupt body: arm(2) on verified NativeCut bridge.
        # This enqueues client_7081 — never inject_joymax(0x7081).
        job['observed'] = False
        job['bridge_done'] = False
        job['b074'] = ''
        session['bridge'].arm(2)
        job['cut_fired'] = True
        job['phase'] = 'wait'
        job['cut_fired_at'] = now
        job['send_deadline'] = now + 2.0
        job['next_at'] = now + 0.02
        cast_at = float(job.get('cast_at') or 0)
        b070_at = float(job.get('b070_at') or 0)
        delay_ms = int(job.get('ghost_delay_ms') or 0)
        since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
        since_b070 = int(round((now - b070_at) * 1000)) if b070_at else -1
        with lock:
            state['last_send_uid'] = uid
            state['last_send_at'] = now
            state['pending_watch_until'] = now + 3.0
            state['last_nativcut_error'] = ''
        _log(
            'NativeCut arm(2) CUT NOW · transport=client_7081 · NOT inject · '
            'reason=%s · self=%d · skill=%d · delay_cfg=%dms · since_B070=%dms · '
            'since_7074=%dms · hex=%s'
            % (reason, uid, int(job.get('skill_id') or 0), delay_ms, since_b070,
               since_7074, job.get('hex') or '?'))
        set_status(
            'Ghost CUT NativeCut arm(2) self=%d · since_B070=%dms (cfg=%dms) · skill=%d'
            % (uid, since_b070 if since_b070 >= 0 else delay_ms, delay_ms,
               int(job.get('skill_id') or 0)))
        return True
    except Exception as error:
        with lock:
            state['last_nativcut_error'] = '%s: %s' % (type(error).__name__, error)
        _log_traceback('CUT TRACE', error)
        set_status(
            'GHOST FAIL arm(2) · %s — NativeCut only (Windows + GetTickCount). '
            'Unload AutoGhost Ghost nếu conflict.'
            % error)
        return False


def _schedule_ag_cut_timer(job, uid, delay_ms, anchor='B070'):
    """After B070 (or fallback): schedule cut_at; event_loop is authoritative arm(2).

    Timer thread is a nudge only (AG parity). Overnight silent misses came from
    Timer firing while active/phase gates returned without logging.
    """
    _cancel_cut_timer(job)
    delay_s = max(0, int(delay_ms)) / 1000.0
    ticket = object()
    job['cut_ticket'] = ticket
    job['cut_anchor'] = anchor
    job['cut_uid'] = int(uid)
    job['phase'] = 'cut_wait'
    job['cut_at'] = monotonic() + delay_s
    job['cut_deadline'] = job['cut_at'] + 2.0

    def _timer_fire():
        with lock:
            if job.get('cut_ticket') is not ticket:
                _log('CUT TIMER skip · stale ticket · anchor=%s' % anchor)
                return
            if job.get('cut_fired'):
                return
            phase = job.get('phase')
            if phase not in ('cut_wait', 'cut_now'):
                _log(
                    'CUT TIMER skip · phase=%s · anchor=%s · self=%d'
                    % (phase, anchor, int(uid)))
                return
            job['phase'] = 'cut_now'
            state['active'] = job
        _fire_native_cut(job, uid, reason='%s+%dms-timer' % (anchor, int(delay_ms)))

    timer = Timer(delay_s, _timer_fire)
    timer.daemon = True
    job['cut_timer'] = timer
    with lock:
        timers = state.get('live_timers')
        if not isinstance(timers, set):
            timers = set()
            state['live_timers'] = timers
        timers.add(timer)
    timer.start()
    _log(
        'CUT due in %.3fs after %s · cfg=%dms · self=%d · skill=%d · '
        '(event_loop arm(2) at cut_at; Timer nudge only)'
        % (delay_s, anchor, int(delay_ms), uid, int(job.get('skill_id') or 0)))


def _fallback_cut_from_7074(job, uid, now):
    """No B070 within B070_WAIT_SEC — cut at 7074+cfg (remaining time)."""
    delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
    cast_at = float(job.get('cast_at') or now)
    elapsed = max(0.0, now - cast_at)
    remaining_s = max(0.0, (delay_ms / 1000.0) - elapsed)
    remaining_ms = int(round(remaining_s * 1000))
    with lock:
        basic_drops = int(state.get('basic_drop_count') or 0)
    _log(
        'B070 MISSING after %.0fms · skill=%d · API=%r · basic_drops=%d · '
        'fallback Timer(7074+%dms) remaining=%dms '
        '(nếu chỉ thấy đánh thường: check Skill IDs + DROP basic log + tắt Training)'
        % (B070_WAIT_SEC * 1000, int(job.get('skill_id') or 0),
           job.get('cast_api'), basic_drops, delay_ms, remaining_ms))
    job['b070_miss'] = True
    _schedule_ag_cut_timer(job, uid, remaining_ms, anchor='7074-fallback')


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
    _cancel_cut_timer(job)
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


def _record_ghost_fail(job, detail):
    with lock:
        state['ghost_fail_count'] = int(state.get('ghost_fail_count') or 0) + 1
        state['last_ghost_fail'] = detail
    set_stats()
    _log('GHOST FAIL · %s' % detail)
    set_status('GHOST FAIL · %s' % detail)


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
        with lock:
            state['ghost_ok_count'] = int(state.get('ghost_ok_count') or 0) + 1
            state['last_ghost_fail'] = ''
        set_stats()
        _finish_job(
            job,
            'OK GHOST NativeCut self · 7081=YES · B074 02 00 · skill=%d · self=%d'
            % (int(job.get('skill_id') or 0), int(job.get('uid') or 0)),
            ok=True)
        return

    with lock:
        nativ_err = state.get('last_nativcut_error') or ''
    detail = (
        'no Ghost this cycle · cut_fired=%s · observed_7081=%s · B074=%s · '
        'b070_seen=%s · b070_miss=%s · phase_end=%s · skill=%s · self=%s · '
        'bridge5=%s · nativcut=%s · tip=cần arm(2)→C→S 7081→B074 02 00 '
        '(NativeCut Windows; unload AG Ghost nếu conflict)'
        % (bool(job.get('cut_fired')), observed, b074,
           bool(job.get('b070_seen')), bool(job.get('b070_miss')),
           job.get('phase'), job.get('skill_id'), job.get('uid'),
           'done' if job.get('bridge_done') else 'no',
           nativ_err or job.get('error') or 'ok'))
    _record_ghost_fail(job, detail)
    if job.get('error'):
        _finish_job(
            job,
            'LỖI farm NativeCut %s UID=%d · %s'
            % (job['label'], job['uid'], job['error']),
            ok=False)
    else:
        _finish_job(
            job,
            'GHOST FAIL · 7081=%s · B074=%s · cut_fired=%s · self=%d'
            % (observed, b074, bool(job.get('cut_fired')), int(job.get('uid') or 0)),
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
        if phase == 'select':
            select_uid = int(job.get('select_uid') or job.get('monster_uid') or 0)
            if select_uid <= 0:
                _soft_skip_job(job, 'SELECT: không có UID quái — bỏ vòng (không Ghost).')
                return
            # Soft-skip ONLY here if target not alive in radius.
            rows = scan_nearby(read_radius())
            if not any(row['uid'] == select_uid for row in rows):
                _soft_skip_job(
                    job,
                    'SELECT: quái #%d không còn trong bán kính — bỏ vòng.'
                    % select_uid)
                return
            packet = _pack_uid(select_uid)
            try:
                api = inject_joymax(0x7045, packet, False)
            except Exception as error:
                raise RuntimeError('lỗi inject 7045: %s' % error)
            _log(
                'C→S 0x7045 SELECT FIRST · monster UID=%d · name=%s · hex=%s · API=%r'
                % (select_uid, _safe_text(job.get('label')), _hex_bytes(packet), api))
            if api is False:
                raise RuntimeError(
                    'phBot từ chối 7045 chọn UID=%d — không cast/Ghost.' % select_uid)
            with lock:
                state['selected_uid'] = select_uid
            job['select_sent'] = True
            job['select_observed'] = False
            job['phase'] = 'select_wait'
            job['select_deadline'] = now + SELECT_WAIT_SEC
            job['next_at'] = now + 0.05
            set_status('7045 đã chọn quái #%d — tiếp theo cast skill.' % select_uid)
            return

        if phase == 'select_wait':
            select_uid = int(job.get('select_uid') or 0)
            # Pre-warm NativeCut during select wait so cut is not late after cast.
            ready = _prewarm_native(job, uid, now)
            select_done = (
                job.get('select_observed')
                or now >= float(job.get('select_deadline') or 0))
            if select_done and ready:
                _log(
                    '7045 select UID=%d · observed=%s · prewarm=OK → cast 7074 '
                    'skill=%d delay=%dms (cut sẽ overlapping)'
                    % (select_uid, bool(job.get('select_observed')),
                       int(job.get('skill_id') or 0),
                       int(job.get('ghost_delay_ms') or 0)))
                job['phase'] = 'cast'
                job['next_at'] = now
                return
            if select_done and not ready:
                # Keep prewarming; do not cast until hook ready (real Ghost needs it).
                job['next_at'] = now + 0.05
                return
            job['next_at'] = now + 0.05
            return

        if phase == 'cast':
            select_uid = int(job.get('select_uid') or job.get('monster_uid') or 0)
            skill_id = int(job.get('skill_id') or 0)
            delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
            if skill_id <= 0:
                raise ValueError('thiếu skill — không cast/Ghost.')
            # Ensure hook still ready (should already be from select_wait).
            if not _prewarm_native(job, uid, now):
                job['next_at'] = now + 0.05
                return
            rows = scan_nearby(read_radius())
            alive = select_uid > 0 and any(row['uid'] == select_uid for row in rows)
            if not alive:
                _log(
                    'CAST: quái #%d đã chết/mất — bỏ 7074, cut self sau %dms (no B070)'
                    % (select_uid, delay_ms))
                job['cast_sent'] = True
                job['cast_api'] = 'skipped_dead_target'
                job['cast_at'] = now
                job['b070_deadline'] = now  # no cast → no B070; Timer(cfg) now
                _schedule_ag_cut_timer(job, uid, delay_ms, anchor='dead-skip')
                job['next_at'] = now + max(0.01, delay_ms / 1000.0)
                set_status(
                    'Quái #%d chết — Ghost self tại T+%dms' % (select_uid, delay_ms))
                return
            # Cancel only if Training basic was recently dropped — unconditional
            # cancel can abort the skill we are about to cast (no B070).
            with lock:
                basic_drops = int(state.get('basic_drop_count') or 0)
            if basic_drops > 0:
                _cancel_current_action(
                    'trước 7074 skill=%d target=%d (basic_drops=%d)'
                    % (skill_id, select_uid, basic_drops))
            packet = struct.pack('<BBIBI', 1, 4, skill_id, 1, select_uid)
            try:
                api = inject_joymax(0x7074, packet, False)
            except Exception as error:
                raise RuntimeError('lỗi inject 7074: %s' % error)
            job['cast_sent'] = True
            job['cast_api'] = api
            job['cast_at'] = now
            job['b070_seen'] = False
            job['b070_at'] = 0.0
            job['b070_deadline'] = now + B070_WAIT_SEC
            # AG: do NOT Timer yet — wait S→C B070 then Timer(cfg) → arm(2).
            job['phase'] = 'wait_b070'
            job['next_at'] = now + 0.02
            _log(
                'C→S 0x7074 CAST · skill=%d · target=%d · chờ B070 rồi Timer(+%dms) · '
                'hex=%s · API=%r'
                % (skill_id, select_uid, delay_ms, _hex_bytes(packet), api))
            if api is False:
                _log(
                    '7074 API=False skill=%d target=%d — vẫn chờ B070 / fallback 800ms'
                    % (skill_id, select_uid))
            set_status(
                'Cast skill %d → chờ B070 rồi Ghost +%dms (AG)'
                % (skill_id, delay_ms))
            return

        if phase == 'wait_b070':
            # Primary: handle_joymax schedules AG Timer on B070.
            if job.get('cut_fired') or job.get('cut_timer') is not None:
                return
            deadline = float(job.get('b070_deadline') or 0)
            if now >= deadline:
                _fallback_cut_from_7074(job, uid, now)
                job['next_at'] = now + 0.02
                return
            job['next_at'] = min(now + 0.02, deadline)
            return

        if phase == 'cut_wait':
            # Event-loop is authoritative: fire at cut_at (do not wait on Timer thread).
            if job.get('cut_fired'):
                return
            cut_at = float(job.get('cut_at') or 0)
            if cut_at and now < cut_at:
                job['next_at'] = min(now + 0.02, cut_at)
                return
            delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
            anchor = job.get('cut_anchor') or 'B070'
            cut_uid = int(job.get('cut_uid') or uid)
            if not _fire_native_cut(
                    job, cut_uid, now,
                    reason='%s+%dms-loop' % (anchor, delay_ms)):
                if now >= float(job.get('cut_deadline') or (now + 1)):
                    job['error'] = state.get('last_nativcut_error') or 'arm(2) không kịp'
                    with lock:
                        if state['queue'] and state['queue'][0] is job:
                            state['queue'].pop(0)
                    _advance_or_finish(job, ok_shot=False)
                    return
                job['next_at'] = now + 0.05
                return
            return

        if phase == 'cut_now':
            # Timer nudged phase; ensure arm(2) landed (idempotent).
            if not job.get('cut_fired'):
                delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
                anchor = job.get('cut_anchor') or 'B070'
                cut_uid = int(job.get('cut_uid') or uid)
                if not _fire_native_cut(
                        job, cut_uid, now,
                        reason='%s+%dms-now' % (anchor, delay_ms)):
                    if now >= float(job.get('cut_deadline') or (now + 1)):
                        job['error'] = state.get('last_nativcut_error') or 'arm(2) không kịp'
                        with lock:
                            if state['queue'] and state['queue'][0] is job:
                                state['queue'].pop(0)
                        _advance_or_finish(job, ok_shot=False)
                        return
                    job['next_at'] = now + 0.05
            return

        if phase == 'arm':
            # Legacy entry — treat as immediate cut.
            if not _fire_native_cut(job, uid, now, reason='arm'):
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
            state['ghost_fail_count'] = int(state.get('ghost_fail_count') or 0) + 1
            state['last_nativcut_error'] = job['error']
            state['last_ghost_fail'] = job['error']
            state['next_scan_at'] = monotonic() + backoff
        set_stats()
        tip = ''
        if _is_hook_conflict_error(error):
            tip = (
                ' · backoff %gs — GHOST BLOCKED: tắt Ghost/PvP AutoGhost hoặc '
                'unload AutoGhost (GetTickCount). NativeCut only, không inject 7081.'
                % HOOK_CONFLICT_BACKOFF_SEC)
        elif sys.platform != 'win32':
            tip = ' · NativeCut chỉ chạy trên Windows phBot host'
        set_status(
            'GHOST FAIL NativeCut %s UID=%d · %s%s'
            % (_safe_text(job.get('label')), uid, job['error'], tip))
        _log(
            'GHOST FAIL cycle · install/drive error · %s · cut_fired=%s · '
            'observed_7081=%s · B074=%s'
            % (job['error'], bool(job.get('cut_fired')),
               bool(job.get('observed')), job.get('b074') or '(none)'))
        return


def _farm_scan_tick(now):
    with lock:
        if state['queue'] or state.get('active'):
            return
        if now < float(state.get('next_scan_at') or 0):
            return
    if not read_skill_ids():
        with lock:
            state['farming'] = False
            state['queue'] = []
            state['active'] = None
            state['next_scan_at'] = now + NO_TARGET_RETRY_SEC
        set_status(
            'STOP — Skill IDs trống. Điền %s rồi Start lại '
            '(không để Training đánh thường thay GhostFarm).'
            % SKILL_FIELD_EXAMPLE)
        _log(
            'Farm STOP — Skill IDs trống giữa vòng. Không gửi 7074 skill / NativeCut.')
        return
    radius = read_radius()
    rows = scan_nearby(radius)
    show_nearby(rows)
    farm_job = pick_farm_job(rows)
    if not farm_job:
        with lock:
            state['next_scan_at'] = now + NO_TARGET_RETRY_SEC
        show_pick(0, '', '')
        reason = 'chưa thấy quái/NPC sống'
        if not read_self_uid():
            reason = 'chưa có Self UID'
        elif not read_skill_ids():
            reason = 'thiếu Skill IDs (F1)'
        set_status(
            'Farm chờ — %s trong %gm (không Ghost).' % (reason, radius))
        return
    queue_native(farm_job)


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
    """Observe C→S: 7045 select + NativeCut 7081; while farming DROP basic attacks."""
    raw = bytes(data or b'')

    # phBot Training / client auto-swing after 7045 steals the cast window.
    # Drop basic 7074 (01 01 01) so farm owns combat: skill → B070 → Ghost.
    if opcode == 0x7074 and farming_active() and _is_basic_attack_7074(raw):
        with lock:
            drops = int(state.get('basic_drop_count') or 0) + 1
            state['basic_drop_count'] = drops
        if drops <= 8 or drops % 25 == 0:
            _log(
                'DROP C→S 0x7074 basic (đánh thường) #%d — GhostFarm đang farm skill+Ghost'
                % drops)
        return False

    if opcode == 0x7045 and len(raw) >= 4:
        uid = struct.unpack_from('<I', raw, 0)[0]
        if uid:
            self_uid = read_self_uid()
            if not self_uid or uid != self_uid:
                with lock:
                    state['selected_uid'] = uid
                    job = state.get('active')
                    if (job is not None
                            and job.get('phase') in ('select', 'select_wait')
                            and int(job.get('select_uid') or 0) == uid):
                        job['select_observed'] = True
                if plugin_enabled():
                    _log('Quan sát C→S 0x7045 chọn UID=%d (monster select).' % uid)
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
            'C→S 0x7081 OBSERVED (NativeCut self) UID=%d hex=%s · transport=client_7081'
            % (uid, hex_out))
    elif watching:
        _log(
            'C→S 0x7081 (khác/đồng thời) UID=%d hex=%s · expect self=%d'
            % (uid, hex_out, expect))


def handle_joymax(opcode, data):
    """AG path: B070 confirms cast → Timer(cfg) → arm(2). Also watch B074 after cut."""
    if not plugin_enabled():
        return
    if opcode not in (0xB070, 0xB074, 0xB081, 0xB084, 0x3085):
        return
    try:
        raw = bytes(data or b'')
        with lock:
            watching = monotonic() <= float(state.get('pending_watch_until') or 0)
            last_uid = int(state.get('last_send_uid') or 0)
            job = state.get('active')

        if opcode == 0xB070 and job is not None:
            # AutoGhost gate: len>=19; skill,source @3; target @15; data[0]==1.
            # Then delay → NativeCut arm(2) self (client_7081), never inject 7081.
            phase = job.get('phase')
            if phase != 'wait_b070':
                return
            if job.get('cut_timer') is not None or job.get('cut_fired'):
                return
            if len(raw) < 19 or raw[0] != 1:
                if len(raw) >= 3:
                    _log(
                        'B070 IGNORE · phase=wait_b070 nhưng frame ngắn/không cast '
                        'len=%d b0=%s hex=%s'
                        % (len(raw), raw[0] if raw else '?', _hex_bytes(raw[:12])))
                return
            skill, source = struct.unpack_from('<II', raw, 3)
            target = struct.unpack_from('<I', raw, 15)[0]
            expect_skill = int(job.get('skill_id') or 0)
            expect_target = int(job.get('select_uid') or job.get('monster_uid') or 0)
            self_uid = int(job.get('uid') or state.get('self_uid') or 0)
            if not expect_skill or skill != expect_skill:
                _log(
                    'B070 REJECT skill · got=%d expect=%d · source=%s target=%d · '
                    'hex=%s (không hẹn Ghost — chờ đúng skill hoặc fallback 800ms)'
                    % (skill, expect_skill, source, target, _hex_bytes(raw[:19])))
                return
            if self_uid and source and source != self_uid:
                _log(
                    'B070 REJECT source · got=%d expect_self=%d · skill=%d target=%d'
                    % (source, self_uid, skill, target))
                return
            if self_uid and target == self_uid:
                _log(
                    'B070 REJECT self-target · skill=%d source=%d (buff/self — không Ghost farm)'
                    % (skill, source))
                return
            if expect_target and target and target != expect_target:
                # Still accept: monster UID can churn; skill+source already match.
                _log(
                    'B070 WARN target mismatch · got=%d expect=%d · vẫn hẹn Ghost '
                    '(skill=%d source=%d)'
                    % (target, expect_target, skill, source))
            now = monotonic()
            cast_at = float(job.get('cast_at') or 0)
            since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
            delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
            job['b070_seen'] = True
            job['b070_at'] = now
            _log(
                'S→C 0xB070 CAST CONFIRM · skill=%d · source=%s · target=%d · '
                'since_7074=%dms · hẹn NativeCut arm(2) sau +%dms (client_7081)'
                % (skill, source, target, since_7074, delay_ms))
            set_status(
                'B070 skill %d — NativeCut self sau %dms (không inject)'
                % (skill, delay_ms))
            _schedule_ag_cut_timer(job, int(job.get('uid') or self_uid), delay_ms,
                                   anchor='B070')
            return

        prefix = 'sau NativeCut' if watching else 'ngoài cửa sổ 3s'
        if opcode == 0xB074:
            note = _classify_b074(raw)
            _log('S→C 0xB074 [%s] %s | last UID=%d' % (prefix, note, last_uid))
            if job is not None and job.get('phase') == 'wait' and watching:
                job['b074'] = note
                if raw == b'\x02\x00':
                    set_status(
                        'B074 02 00 sau NativeCut UID=%d — NGẮT OK (overlap).'
                        % last_uid)
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
        'Nạp %s v%s — Ghost = NativeCut self 7081 after B070 (NOT inject). '
        'Bật+Skill+Start; log OK: arm(2)+7081+B074 02 00.'
        % (NAME, VERSION))
except Exception as error:
    try:
        _log_traceback('load TRACE', error)
    except Exception:
        pass
