# -*- coding: utf-8 -*-
"""GhostFarm — Ghost farm quái/NPC (standalone, NativeCut client_7081).

Changelog:
- v1.0.14: Stop lying OK MID-CUT. Early 7081 + natural B074 ~cast-end looked
  like success (cut_cfg 1/7/50 → since_7074~14/61, B074 02 00) but **no visual
  Ghost**. Now: default cfg **100ms** mid-window; B074 must land soon after cut
  AND before full cast window; else **PACKET-FAKE FAIL**. Never claim Ghost from
  B074 02 00 alone. Optional **Weapon 7034** cut mode (probe A/B). Monster 7081
  ×2 remains default transport (solo; no inject 7081).
- v1.0.13: AOS-55 — lock mid-cut to GhostCutProbe A/B winner: after 7074+cfg_ms
  (~100), NativeCut **client_7081 → monster/boss UID ×2** (+15ms hiep). Self
  7081 flaky (MID-CUT then CAST-REFUSED); 7074\\x02 / move / ESC / sit = no real
  mid-cut — not used. Solo monster/boss only; never player neighbor; never
  inject_joymax(0x7081) when Stable refuses. Skill field prefill =
  `80031=1;66007=50;54016=1;81019=50;7678=1;81016=7;7653=50` (=5→50).
- v1.0.12: Ghost loop — cast → mid-cut at **7074+cfg_ms** (~100) → next skill.
  Cut UID = **Self OR Monster/Boss only** (never player / never trade).
  Modes: Monster 7081 (SroPlus, default) | Self. Optional arm(2)×2 ~15ms (hiep).
  Natural B074 before arm(2) = **FULL-CAST FAIL**; mid-cut 7081+B074 02 00 =
  **OK MID-CUT**. Loud `cut_cfg · since_7074 · cut_uid=self|monster`.
- v1.0.11: Overnight “có ghost đâu” harden — interrupt is ONLY NativeCut
  client_7081 self (arm(2)), never inject 7081. Event-loop fires cut at
  cut_at (Timer is nudge only; no silent Timer/active skip). Retarget self
  UID in thunk page before every arm(2). Log every B070 reject + every CUT
  SKIP. Every failed cycle LOUD `GHOST FAIL` (no 7081 / no B074 02 00) with
  phase/cut_fired/b070/bridge. Cancel before cast only if basic was dropped.
  NativeCut install fail stays on status every cycle. Windows host required.
- v1.0.10: Prefill Skill IDs from confirmed Auto PK F1 skill+Ngắt table
  (skip blank IDs; ignore blank-ID ms 850; no 81037). 1.0.12 bumps ms→100.
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
VERSION = '1.0.14'
# Mid-window cut: ~120ms cast → 7074+~100ms cancel. Solo monster/boss only.
# Tiny cfg (1/7/50) + B074 02 00 = PACKET-FAKE (natural end), not visual Ghost.
SKILL_FIELD_EXAMPLE = (
    '80031=100;66007=100;54016=100;81019=100;7678=100;81016=100;7653=100')

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

MODE_MONSTER = 'Monster/Boss 7081'
# Self kept in combo for layout only — A/B locked farm cut to monster UID (AOS-55).
MODE_SELF = 'Self (A/B fail)'
# Probe A/B: weapon swap also got B074 02 00 — try if 7081 is packet-only.
MODE_WEAPON = 'Weapon 7034'
MODE_LABELS = (MODE_MONSTER, MODE_WEAPON, MODE_SELF)

DEFAULT_RADIUS = 50.0
MAX_RADIUS = 200.0
SCAN_IDLE_SEC = 0.35
RESEND_GAP_SEC = 0.75
NO_TARGET_RETRY_SEC = 1.0
SELECT_WAIT_SEC = 0.25  # after 7045 before skill cast
# Farm mid-cut: cfg ms from 7074 send (not B070). Bare id → 100ms.
DEFAULT_GHOST_DELAY_MS = 100
# Typical farm skill animation / cast window (user: ~120ms).
CAST_WINDOW_HINT_MS = 120
# cfg below this → auto-bump to 100 (tiny cfg = PACKET-FAKE / no visual Ghost).
MIN_MIDCAST_WARN_MS = 80
# Tolerance when checking since_7074 ≈ cut_cfg.
CUT_MS_TOLERANCE = 45
# B074 after cut must be quick — late B074 ≈ natural cast end, not mid-cancel.
MAX_B074_AFTER_CUT_MS = 70
# Upper bound for B074 since 7074 (cut@100 + prompt B074 may land ~120–150).
MAX_B074_SINCE_7074_MS = 160
# After GetTickCount / install conflict — do not re-spam NativeCut every 0.75s.
HOOK_CONFLICT_BACKOFF_SEC = 8.0
# SroPlus/hiep often sends 7081×2 ~0–20ms; second arm(2) after this gap.
HIEP_DOUBLE_CUT_SEC = 0.015

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
    'mode': MODE_MONSTER,
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
QtBind.setText(gui, mode_combo, MODE_MONSTER)

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
    'v1.0.14: mid-window @~100ms · B074 soon after cut or PACKET-FAKE. '
    'No OK from B074 alone. Mode: 7081×2 | Weapon 7034.',
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
    # Legacy "Self" label → A/B-fail label; farm cut always monster (AOS-55).
    if text in ('Self', MODE_SELF):
        text = MODE_SELF
    if text not in MODE_LABELS:
        text = MODE_MONSTER
        QtBind.setText(gui, mode_combo, text)
    with lock:
        state['mode'] = text
    return text


def _is_weapon_mode(mode=None):
    return (mode or current_mode()) == MODE_WEAPON


def _bump_skill_ms_for_midcast(entries):
    """Raise tiny cfg into mid-window. Tiny ms + B074 02 00 = PACKET-FAKE."""
    bumped = []
    out = []
    for sid, ms in entries:
        ms = int(ms)
        if ms < MIN_MIDCAST_WARN_MS:
            bumped.append((sid, ms, DEFAULT_GHOST_DELAY_MS))
            ms = DEFAULT_GHOST_DELAY_MS
        out.append((sid, ms))
    if bumped:
        detail = ';'.join('%d:%d→%d' % (sid, old, new) for sid, old, new in bumped)
        _log(
            'CFG BUMP · skill ms < %dms → %dms (tiny cfg = PACKET-FAKE / no visual) · %s'
            % (MIN_MIDCAST_WARN_MS, DEFAULT_GHOST_DELAY_MS, detail))
        QtBind.setText(
            gui, skill_field,
            ';'.join('%d=%d' % pair for pair in out))
    return out


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
    entries = _bump_skill_ms_for_midcast(read_skill_entries())
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
    """One NativeCut bridge per client window; retarget UID before each arm(2).

    Farm rotates monster UIDs every cycle — do NOT reinstall per UID (that
    burns the mid-cast window). Key = (pid, hwnd) only.
    """
    client = get_client()
    if not client.get('running') or not client.get('window') or not client.get('pid'):
        raise ValueError('Cần client Silkroad đang chạy (có HWND); kiểm tra Clientless.')
    if sys.platform != 'win32' or not user32:
        raise RuntimeError('NativeCut chỉ chạy trên Windows phBot host.')
    key = (int(client['pid']), client['window'])
    with lock:
        session = state.get('session')
        if session is not None and session.get('key') == key:
            # Keep bridge; caller retargets to monster/self before arm(2).
            session['last_uid'] = int(uid)
            return session
    close_session('đổi client — tạo NativeCut mới')
    bridge = NativeCut({'pid': key[0], 'window': key[1], 'target': int(uid)})
    session = {
        'key': key,
        'bridge': bridge,
        'verified': False,
        'adopted': bool(getattr(bridge, 'adopted', False)),
        'last_uid': int(uid),
    }
    with lock:
        state['session'] = session
    _log(
        'NativeCut %s OK · PID=%d HWND=%s · seed_UID=%d (retarget mỗi cut)'
        % ('REUSE' if session['adopted'] else 'install',
           key[0], key[1], int(uid)))
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


def resolve_cut_uid(job, self_uid=None):
    """Ghost cut UID = current monster/boss only (AOS-55 locked A/B path).

    Never self primary, never a player, never neighbor trade. Self combo
    selection is ignored for the 7081 UID — still cuts monster/boss.
    """
    if self_uid is None:
        self_uid = read_self_uid()
    try:
        self_uid = int(self_uid or 0)
    except (TypeError, ValueError):
        self_uid = 0
    mode = (job or {}).get('mode') or current_mode()
    monster_uid = 0
    try:
        monster_uid = int(
            (job or {}).get('monster_uid')
            or (job or {}).get('select_uid')
            or 0)
    except (TypeError, ValueError):
        monster_uid = 0
    if mode == MODE_SELF or (job or {}).get('cut_target_kind') == 'self':
        _log(
            'CUT PATH LOCK · Self mode ignored — A/B winner is '
            '7081@monster ×2 (NativeCut client_7081)')
    if not 0 < monster_uid <= 0xffffffff:
        raise ValueError(
            'Monster/Boss UID trống — farm Ghost chỉ 7081@monster/boss.')
    if self_uid and monster_uid == self_uid:
        raise ValueError('Monster/Boss UID trùng Self — từ chối cut player-like.')
    return monster_uid, 'monster'


def pick_farm_job(rows):
    """Build farm job only when a living monster/NPC/boss is in range.

    EVERY cycle: 7045(monster/boss) → 7074(skill) → NativeCut 7081@monster ×2.
    Never cut self/player. Never trade/neighbor. Never inject 7081.
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
    monster_uid = int(monster['uid'])
    cut_kind = 'monster'
    cut_uid = monster_uid
    return {
        'ghost_uid': cut_uid,
        'select_uid': monster_uid,
        'need_select': True,  # always — no target at SELECT ⇒ soft-skip
        'skill_id': int(skill_id),
        'ghost_delay_ms': int(delay_ms),
        'label': monster['name'],
        'kind': monster['kind'],
        'monster_uid': monster_uid,
        'monster_name': monster['name'],
        'mode': mode,
        'cut_target_kind': cut_kind,
    }


def pick_ghost_target(rows):
    """UI helper: show combat target + interrupt UID (monster default)."""
    job = pick_farm_job(rows)
    if not job:
        return None
    kind = job.get('cut_target_kind') or 'monster'
    return (
        job['ghost_uid'],
        '7045#%d→7074#%d=%dms→7081@%s' % (
            job['monster_uid'], job.get('skill_id') or 0,
            job.get('ghost_delay_ms') or 0, kind),
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
    entries = _bump_skill_ms_for_midcast(read_skill_entries())
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
    mode = current_mode()
    prewarm_ok = True
    if not _is_weapon_mode(mode):
        prewarm_ok = _prewarm_self_at_start()
    preview = ';'.join('%d=%d' % pair for pair in entries[:6])
    ag = ' · AutoGhost đang nạp (có thể conflict GetTickCount)' if _autoghost_hint() else ''
    cut_desc = (
        'Weapon 0x7034 mid-cast'
        if _is_weapon_mode(mode) else
        'NativeCut client_7081 → monster ×2')
    set_status(
        'START · self=%d · mid-window ~%dms · %s · prewarm=%s%s'
        % (self_uid, DEFAULT_GHOST_DELAY_MS, cut_desc,
           'OK' if prewarm_ok else 'PENDING/FAIL', ag))
    _log(
        'START farm · skills=%s · self=%d · cut=%s · mode=%s · '
        'cut_anchor=7074+cut_cfg (~%dms mid-window) · '
        'SUCCESS only if B074 soon after cut AND before full cast · '
        'else PACKET-FAKE FAIL (B074 alone ≠ Ghost) · '
        'tắt Training; unload AG Ghost nếu móc conflict.%s'
        % (preview, self_uid, cut_desc, mode, DEFAULT_GHOST_DELAY_MS, ag))


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
    """Queue combat: 7045(monster/boss) → 7074 → NativeCut 7081@monster ×2."""
    if not isinstance(farm_job, dict):
        set_status('Job farm không hợp lệ.')
        return False
    try:
        select_uid = int(farm_job.get('select_uid') or farm_job.get('monster_uid') or 0)
        skill_id = int(farm_job.get('skill_id') or 0)
        delay_ms = int(farm_job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
    except (TypeError, ValueError):
        set_status('UID/skill không hợp lệ.')
        return False
    if not 0 < select_uid <= 0xffffffff:
        set_status('Không có quái/boss mục tiêu — không Ghost.')
        return False
    if skill_id <= 0:
        set_status('Thiếu skill ID — không cast / không Ghost.')
        return False
    if delay_ms < 0:
        delay_ms = DEFAULT_GHOST_DELAY_MS
    mode = farm_job.get('mode') or current_mode()
    draft = {
        'mode': mode,
        'cut_target_kind': 'monster',
        'monster_uid': select_uid,
        'select_uid': select_uid,
    }
    try:
        cut_uid, cut_kind = resolve_cut_uid(draft)
    except ValueError as error:
        set_status(str(error))
        return False
    label = _safe_text(farm_job.get('label') or 'monster')
    entity_kind = _safe_text(farm_job.get('kind') or '?')
    job = {
        'uid': cut_uid,  # NativeCut / 7081 = monster/boss UID only (AOS-55)
        'cut_uid': cut_uid,
        'cut_target_kind': cut_kind,
        'select_uid': select_uid,
        'need_select': True,
        'monster_uid': select_uid,
        'skill_id': skill_id,
        'ghost_delay_ms': delay_ms,
        'label': label,
        'kind': entity_kind,
        'mode': mode,
        'times': 1,
        'done': 0,
        'phase': 'select',  # always select living monster/boss FIRST
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
        'cut_fired': False,
        'cut_fired_at': 0.0,
        'cut_since_7074': -1,
        'cut_since_b070': -1,
        'b074_at': 0.0,
        'cut_transport': (
            'weapon_7034' if _is_weapon_mode(mode) else 'client_7081'),
        'natural_end_before_cut': False,
        'next_at': monotonic(),
        'observed': False,
        'bridge_done': False,
        'b074': '',
        'ok_any': False,
        'hex': _hex_bytes(_pack_uid(cut_uid)),
        'error': '',
    }
    with lock:
        state['queue'] = [job]
        state['active'] = job
    show_pick(
        cut_uid,
        '7045#%d→skill%d=%dms→7081@%s=%d · %s'
        % (select_uid, skill_id, delay_ms, cut_kind, cut_uid, label),
        entity_kind)
    set_status(
        'Xếp combat · mob/boss=%d · skill=%d · mid-cut %dms · 7081@%s=%d'
        % (select_uid, skill_id, delay_ms, cut_kind, cut_uid))
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


def _fire_weapon_swap(job):
    """C→S 0x7034 bag↔weapon mid-cast (Probe Weapon path)."""
    inv_fn = getattr(phbot_api, 'get_inventory', None)
    if not inv_fn:
        job['action_detail'] = 'phBot thiếu get_inventory'
        return False
    try:
        items = ((inv_fn() or {}).get('items') or [])
    except Exception as error:
        job['action_detail'] = 'get_inventory lỗi: %s' % error
        return False
    if len(items) < 14:
        job['action_detail'] = 'inventory quá ngắn (%d)' % len(items)
        return False
    item_fn = getattr(phbot_api, 'get_item', None)

    def _is_weapon_item(item):
        if not item or not item.get('model'):
            return False
        if not item_fn:
            return True
        try:
            data = item_fn(item['model']) or {}
        except Exception:
            return True
        return data.get('tid2') == 6

    bag_weapon = next(
        (i for i, item in enumerate(items)
         if i >= 13 and _is_weapon_item(item)),
        None)
    if bag_weapon is not None and bag_weapon <= 255:
        packet = struct.pack('<BBBH', 0, bag_weapon, 6, 0)
        detail = '7034 bag#%d→weapon(6)' % bag_weapon
    elif items[6]:
        empty = next(
            (i for i, item in enumerate(items) if i >= 13 and not item), None)
        if empty is None or empty > 255:
            job['action_detail'] = 'không có ô túi trống để cất vũ khí'
            return False
        packet = struct.pack('<BBBH', 0, 6, empty, 0)
        detail = '7034 weapon(6)→bag#%d' % empty
    else:
        job['action_detail'] = 'không có vũ khí túi/slot6 để 7034'
        return False
    try:
        api = inject_joymax(0x7034, packet, False)
    except Exception as error:
        job['action_detail'] = '7034 exception: %s' % error
        return False
    job['action_detail'] = '%s API=%r' % (detail, api)
    _log('C→S 0x7034 WEAPON mid-cut · %s' % job['action_detail'])
    return api is not False


def _mark_cut_timing(job, now):
    cast_at = float(job.get('cast_at') or 0)
    b070_at = float(job.get('b070_at') or 0)
    delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
    since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
    since_b070 = int(round((now - b070_at) * 1000)) if b070_at else -1
    job['cut_since_7074'] = since_7074
    job['cut_since_b070'] = since_b070
    job['cut_fired'] = True
    job['cut_fired_at'] = now
    job['phase'] = 'wait'
    job['send_deadline'] = now + 2.0
    job['next_at'] = now + 0.02
    job['b074'] = ''
    job['b074_at'] = 0.0
    return delay_ms, since_7074, since_b070


def _fire_native_cut(job, uid, now=None, reason='cut'):
    """Fire mid-cast cancel at cfg: NativeCut 7081×2 or Weapon 7034."""
    now = monotonic() if now is None else now
    with lock:
        active = state.get('active')
        if active is not None and active is not job:
            _log(
                'CUT SKIP · active is other job · phase=%s · reason=%s'
                % (job.get('phase'), reason))
            return False
        state['active'] = job
        if job.get('natural_end_before_cut'):
            _log(
                'CUT SKIP · natural B074 already ended cast · NOT mid-cut · reason=%s'
                % reason)
            return False
        if job.get('cut_fired'):
            return True
        if job.get('phase') not in ('cut_wait', 'arm', 'cut_now'):
            _log(
                'CUT SKIP · bad phase=%s · reason=%s · skill=%s'
                % (job.get('phase'), reason, job.get('skill_id')))
            return False
        job['phase'] = 'cut_now'
    try:
        cut_uid, kind = resolve_cut_uid(job)
        job['cut_uid'] = cut_uid
        job['cut_target_kind'] = kind
        job['uid'] = cut_uid
        job['hex'] = _hex_bytes(_pack_uid(cut_uid))
        mode = job.get('mode') or current_mode()
        delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)

        if _is_weapon_mode(mode):
            if not _fire_weapon_swap(job):
                with lock:
                    state['last_nativcut_error'] = job.get('action_detail') or '7034 fail'
                set_status('GHOST FAIL · Weapon 7034 · %s' % (job.get('action_detail') or '?'))
                return False
            job['observed'] = True  # action left client
            job['cut_transport'] = 'weapon_7034'
            job['bridge_done'] = True
            delay_ms, since_7074, since_b070 = _mark_cut_timing(job, now)
            with lock:
                state['last_send_uid'] = cut_uid
                state['last_send_at'] = now
                state['pending_watch_until'] = now + 3.0
                state['last_nativcut_error'] = ''
            _log(
                'CUT FIRE Weapon 7034 · mob/boss=%d · reason=%s · skill=%d · '
                'cut_cfg=%dms · since_7074=%dms · %s'
                % (cut_uid, reason, int(job.get('skill_id') or 0), delay_ms,
                   since_7074, job.get('action_detail') or ''))
            set_status(
                'CUT 7034 · cut_cfg=%dms · since_7074=%dms · skill=%d'
                % (delay_ms, since_7074, int(job.get('skill_id') or 0)))
            return True

        session = get_or_create_session(cut_uid)
        if not session.get('verified'):
            if not _prewarm_native(job, cut_uid, now):
                _log(
                    'CUT SKIP · NativeCut chưa verify · reason=%s · cut_uid=%d'
                    % (reason, cut_uid))
                with lock:
                    state['last_nativcut_error'] = 'prewarm chưa xong trước arm(2)'
                return False
            session = get_or_create_session(cut_uid)
        if job.get('natural_end_before_cut'):
            _log('CUT SKIP · natural end raced before arm(2)')
            return False
        _retarget_bridge(session, cut_uid)
        # client_7081 petition at monster UID (hiep) — never inject 7081.
        job['observed'] = False
        job['bridge_done'] = False
        job['cut_transport'] = 'client_7081'
        session['bridge'].arm(2)
        delay_ms, since_7074, since_b070 = _mark_cut_timing(job, now)
        with lock:
            state['last_send_uid'] = cut_uid
            state['last_send_at'] = now
            state['pending_watch_until'] = now + 3.0
            state['last_nativcut_error'] = ''
        _log(
            'CUT FIRE NativeCut arm(2) · 7081@%s=%d · transport=client_7081 · '
            'NOT inject · reason=%s · skill=%d · cut_cfg=%dms · since_7074=%dms · '
            'since_B070=%dms · hex=%s'
            % (kind, cut_uid, reason, int(job.get('skill_id') or 0), delay_ms,
               since_7074, since_b070, job.get('hex') or '?'))
        set_status(
            'CUT 7081@%s=%d ×2 · cut_cfg=%dms · since_7074=%dms · skill=%d'
            % (kind, cut_uid, delay_ms, since_7074, int(job.get('skill_id') or 0)))

        def _hiep_second():
            try:
                with lock:
                    if state.get('active') is not job or job.get('natural_end_before_cut'):
                        return
                _retarget_bridge(session, cut_uid)
                session['bridge'].arm(2)
                _log(
                    'NativeCut arm(2) ×2 hiep · cut_uid=%d · +%.0fms'
                    % (cut_uid, HIEP_DOUBLE_CUT_SEC * 1000))
            except Exception as error:
                _log('hiep ×2 arm(2) skip: %s' % error)

        timer2 = Timer(HIEP_DOUBLE_CUT_SEC, _hiep_second)
        timer2.daemon = True
        with lock:
            timers = state.get('live_timers')
            if not isinstance(timers, set):
                timers = set()
                state['live_timers'] = timers
            timers.add(timer2)
        timer2.start()
        return True
    except Exception as error:
        with lock:
            state['last_nativcut_error'] = '%s: %s' % (type(error).__name__, error)
        _log_traceback('CUT TRACE', error)
        set_status(
            'GHOST FAIL cut · %s — mid-window cancel (Windows). '
            'Unload AutoGhost Ghost nếu conflict.'
            % error)
        return False


def _schedule_ag_cut_timer(job, uid, delay_ms, anchor='7074'):
    """Schedule cut_at = now+cfg_ms (farm default anchor=7074). Event-loop fires arm(2)."""
    _cancel_cut_timer(job)
    delay_s = max(0, int(delay_ms)) / 1000.0
    try:
        cut_uid, cut_kind = resolve_cut_uid(job)
    except ValueError:
        cut_uid, cut_kind = int(uid), job.get('cut_target_kind') or 'monster'
    job['cut_uid'] = int(cut_uid)
    job['cut_target_kind'] = cut_kind
    job['uid'] = int(cut_uid)
    ticket = object()
    job['cut_ticket'] = ticket
    job['cut_anchor'] = anchor
    job['phase'] = 'cut_wait'
    job['cut_at'] = monotonic() + delay_s
    job['cut_deadline'] = job['cut_at'] + 2.0

    def _timer_fire():
        with lock:
            if job.get('cut_ticket') is not ticket:
                _log('CUT TIMER skip · stale ticket · anchor=%s' % anchor)
                return
            if job.get('cut_fired') or job.get('natural_end_before_cut'):
                return
            phase = job.get('phase')
            if phase not in ('cut_wait', 'cut_now'):
                _log(
                    'CUT TIMER skip · phase=%s · anchor=%s · cut_uid=%d'
                    % (phase, anchor, int(cut_uid)))
                return
            job['phase'] = 'cut_now'
            state['active'] = job
        _fire_native_cut(
            job, cut_uid, reason='%s+%dms-timer' % (anchor, int(delay_ms)))

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
        'CUT SCHEDULED · cut_cfg=%dms · anchor=%s · due in %.3fs · '
        '7081@%s=%d · skill=%d · window_hint=%dms · (event_loop arm(2) at cut_at)'
        % (int(delay_ms), anchor, delay_s, cut_kind, int(cut_uid),
           int(job.get('skill_id') or 0), CAST_WINDOW_HINT_MS))


def _classify_b074(data):
    raw = bytes(data or b'')
    if raw == b'\x02\x00':
        return '02 00 · cast end / Ghost abort'
    if raw == b'\x02\x01':
        return '02 01 · kết thúc skill (biến thể)'
    if len(raw) >= 4 and raw[:4] == b'\x03\x00\x04\x40':
        return '03 00 04 40 · ActionRefusal (từ chối / OOR / busy)'
    if len(raw) >= 2 and raw[:2] == b'\x03\x00':
        return '%s · từ chối / fail (03 00…)' % _hex_bytes(raw[:8])
    return '%s · (xem hex)' % (_hex_bytes(raw[:12]) if raw else '(trống)')


def _fail_natural_full_cast(job, note):
    """Cast finished before Ghost — user saw full skill, not mid-cut."""
    cfg = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
    cast_at = float(job.get('cast_at') or 0)
    since = int(round((monotonic() - cast_at) * 1000)) if cast_at else -1
    job['natural_end_before_cut'] = True
    job['b074'] = 'FULL-CAST natural · ' + note
    job['error'] = (
        'FULL-CAST · natural B074 before arm(2) · since_7074=%dms · cut_cfg=%dms · '
        'skill finished (đánh hết) — tăng cfg (~100) hoặc cast ngắn hơn window'
        % (since, cfg))
    _cancel_cut_timer(job)
    _log(
        'FULL-CAST FAIL · natural B074 BEFORE mid-cut · cut_cfg=%dms · '
        'since_7074=%dms · %s · tip=F1 ms 1–7 quá nhỏ cho skill ~%dms'
        % (cfg, since, note, CAST_WINDOW_HINT_MS))
    with lock:
        if state['queue'] and state['queue'][0] is job:
            state['queue'].pop(0)
    _advance_or_finish(job, ok_shot=False)


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


def _cut_timing_verdict(job):
    """Honest cut score. B074 02 00 alone ≠ Ghost (user: no visual with tiny cfg).

    Real mid-window cancel needs:
      - cut fired near cut_cfg (mid cast, not 1–14ms)
      - B074 02 00 soon AFTER cut (not ~full cast later)
      - B074 since 7074 inside cast window (not natural end)
    Returns (ok_candidate, code, detail).
    """
    cfg = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
    cut_since = int(job.get('cut_since_7074') if job.get('cut_since_7074') is not None else -1)
    cast_at = float(job.get('cast_at') or 0)
    cut_at = float(job.get('cut_fired_at') or 0)
    b074_at = float(job.get('b074_at') or 0)
    b074 = job.get('b074') or ''
    b074_ok = b074.startswith('02 00')
    transport = job.get('cut_transport') or 'client_7081'
    if not job.get('cut_fired'):
        return False, 'NO-CUT', 'cut_fired=False'
    if not job.get('observed'):
        return False, 'NO-ACTION', 'no 7081/7034 observed'
    if not b074_ok:
        return False, 'NO-B074', 'B074=%s' % (b074 or '(none)')
    if cfg < MIN_MIDCAST_WARN_MS:
        return False, 'CFG-TOO-LOW', (
            'cut_cfg=%dms < %dms — tiny cfg makes natural B074 look like mid-cut'
            % (cfg, MIN_MIDCAST_WARN_MS))
    if cut_since >= 0 and cut_since < MIN_MIDCAST_WARN_MS:
        return False, 'CUT-TOO-EARLY', (
            'since_7074=%dms < %dms — cut before mid-window (visual full cast)'
            % (cut_since, MIN_MIDCAST_WARN_MS))
    if cut_since >= 0 and abs(cut_since - cfg) > CUT_MS_TOLERANCE:
        return False, 'CFG-IGNORED', (
            'cut_cfg=%dms but since_7074=%dms (drift>|%dms|) — cut ignored timing'
            % (cfg, cut_since, CUT_MS_TOLERANCE))
    if not b074_at or not cut_at:
        return False, 'NO-B074-TS', 'missing b074_at/cut_fired_at'
    b074_after_cut = int(round((b074_at - cut_at) * 1000))
    b074_since_7074 = int(round((b074_at - cast_at) * 1000)) if cast_at else -1
    if b074_after_cut < 0:
        return False, 'B074-BEFORE-CUT', 'b074 before cut_fired'
    if b074_after_cut > MAX_B074_AFTER_CUT_MS:
        return False, 'PACKET-FAKE', (
            'B074 %dms after cut (>%dms) · b074_since_7074=%dms — natural cast end '
            'after early/ignored cut, NOT visual Ghost · transport=%s'
            % (b074_after_cut, MAX_B074_AFTER_CUT_MS, b074_since_7074, transport))
    if b074_since_7074 >= 0 and b074_since_7074 > MAX_B074_SINCE_7074_MS:
        return False, 'PACKET-FAKE', (
            'b074_since_7074=%dms > %dms (~full cast) — packet OK but visual full cast'
            % (b074_since_7074, MAX_B074_SINCE_7074_MS))
    detail = (
        'cut_cfg=%dms · since_7074=%dms · b074_after_cut=%dms · '
        'b074_since_7074=%dms · transport=%s · VERIFY VISUAL (packet≠Ghost)'
        % (cfg, cut_since, b074_after_cut, b074_since_7074, transport))
    return True, 'CUT-TIMING-OK', detail


def _advance_or_finish(job, ok_shot):
    if ok_shot:
        job['ok_any'] = True
    job['done'] = int(job.get('done') or 0) + 1
    with lock:
        if state['queue'] and state['queue'][0] is job:
            state['queue'].pop(0)
    observed = 'YES' if job.get('observed') else 'NO'
    b074 = job.get('b074') or '(chưa thấy)'
    cfg = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
    since_7074 = int(job.get('cut_since_7074') if job.get('cut_since_7074') is not None else -1)
    natural = bool(job.get('natural_end_before_cut'))
    cut_kind = job.get('cut_target_kind') or 'monster'
    cut_uid = int(job.get('cut_uid') or job.get('uid') or 0)
    transport = job.get('cut_transport') or 'client_7081'

    # Never OK from B074 02 00 alone — require mid-window timing gates.
    if (job.get('ok_any') and job.get('cut_fired') and job.get('observed')
            and (job.get('b074') or '').startswith('02 00') and not natural):
        ok_cand, code, detail = _cut_timing_verdict(job)
        if ok_cand:
            with lock:
                state['ghost_ok_count'] = int(state.get('ghost_ok_count') or 0) + 1
                state['last_ghost_fail'] = ''
            set_stats()
            _finish_job(
                job,
                'CUT TIMING OK @%s=%d · %s · skill=%d · VERIFY VISUAL'
                % (cut_kind, cut_uid, detail, int(job.get('skill_id') or 0)),
                ok=True)
            _log(
                'CUT TIMING OK · %s · skill=%d · %s=%d · NOT claiming Ghost from '
                'B074 alone — user must see cast abort'
                % (detail, int(job.get('skill_id') or 0), transport, cut_uid))
            return
        _record_ghost_fail(job, '%s · %s' % (code, detail))
        _finish_job(
            job,
            '%s FAIL · %s · skill=%d · cut_cfg=%dms · since_7074=%dms'
            % (code, detail, int(job.get('skill_id') or 0), cfg, since_7074),
            ok=False)
        _log(
            'PACKET-FAKE / timing FAIL · code=%s · %s · skill=%d · '
            'B074 02 00 alone is NOT Ghost'
            % (code, detail, int(job.get('skill_id') or 0)))
        return

    with lock:
        nativ_err = state.get('last_nativcut_error') or ''
    if natural:
        detail = (
            'FULL-CAST (đánh hết skill) · natural B074 before cut · '
            'cut_cfg=%dms · skill=%s · tip=dùng ~100ms cho skill ~%dms'
            % (cfg, job.get('skill_id'), CAST_WINDOW_HINT_MS))
    else:
        detail = (
            'no mid-window cut · cut_fired=%s · action=%s · B074=%s · '
            'cut_cfg=%dms · since_7074=%dms · b070=%s · phase=%s · skill=%s · '
            'err=%s · tip=cut@7074+~100 → B074 within %dms of cut'
            % (bool(job.get('cut_fired')), observed, b074, cfg, since_7074,
               bool(job.get('b070_seen')), job.get('phase'), job.get('skill_id'),
               nativ_err or job.get('error') or 'ok', MAX_B074_AFTER_CUT_MS))
    _record_ghost_fail(job, detail)
    if job.get('error'):
        _finish_job(
            job,
            'LỖI farm cut %s UID=%d · %s'
            % (job['label'], job['uid'], job['error']),
            ok=False)
    elif natural:
        _finish_job(
            job,
            'FULL-CAST FAIL · đánh hết · cut_cfg=%dms · skill=%d · tăng ms (~100)'
            % (cfg, int(job.get('skill_id') or 0)),
            ok=False)
    else:
        _finish_job(
            job,
            'GHOST FAIL · action=%s · B074=%s · cut_fired=%s · cut_cfg=%dms · @%s=%d'
            % (observed, b074, bool(job.get('cut_fired')), cfg, cut_kind, cut_uid),
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
                try:
                    cut_uid, cut_kind = resolve_cut_uid(job)
                except ValueError as error:
                    _soft_skip_job(job, 'CAST dead: %s' % error)
                    return
                _log(
                    'CAST: quái/boss #%d đã chết/mất — bỏ 7074, mid-cut @%s=%d '
                    'sau cut_cfg=%dms'
                    % (select_uid, cut_kind, cut_uid, delay_ms))
                job['cast_sent'] = True
                job['cast_api'] = 'skipped_dead_target'
                job['cast_at'] = now
                _schedule_ag_cut_timer(job, cut_uid, delay_ms, anchor='7074-dead')
                job['next_at'] = now + max(0.01, delay_ms / 1000.0)
                set_status(
                    'Quái #%d chết — mid-cut @%s=%d tại 7074+%dms'
                    % (select_uid, cut_kind, cut_uid, delay_ms))
                return
            # Cancel only if Training basic was recently dropped — unconditional
            # cancel can abort the skill we are about to cast.
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
            job['natural_end_before_cut'] = False
            # Farm mid-cut: cfg ms from 7074. Cut UID = monster/boss ×2 only.
            try:
                cut_uid, cut_kind = resolve_cut_uid(job)
            except ValueError as error:
                raise RuntimeError(str(error))
            _schedule_ag_cut_timer(job, cut_uid, delay_ms, anchor='7074')
            job['next_at'] = now + 0.02
            warn = ''
            if delay_ms < MIN_MIDCAST_WARN_MS:
                warn = (
                    ' · WARN cut_cfg=%dms < %dms — dễ FULL-CAST (đánh hết); '
                    'dùng ~100 cho skill ~%dms'
                    % (delay_ms, MIN_MIDCAST_WARN_MS, CAST_WINDOW_HINT_MS))
            _log(
                'C→S 0x7074 CAST · skill=%d · mob/boss=%d · mid-cut NativeCut '
                '@%s=%d at 7074+cut_cfg=%dms (NOT player/trade/inject) · '
                'hex=%s · API=%r%s'
                % (skill_id, select_uid, cut_kind, cut_uid, delay_ms,
                   _hex_bytes(packet), api, warn))
            if api is False:
                _log(
                    '7074 API=False skill=%d target=%d — vẫn hẹn mid-cut 7074+%dms'
                    % (skill_id, select_uid, delay_ms))
            set_status(
                'Cast skill %d → mid-cut 7074+%dms @%s=%d%s'
                % (skill_id, delay_ms, cut_kind, cut_uid,
                   ' · cfg thấp!' if warn else ''))
            return

        if phase == 'cut_wait':
            # Event-loop fires at cut_at (= cast_at + cut_cfg).
            if job.get('cut_fired'):
                return
            if job.get('natural_end_before_cut'):
                return
            cut_at = float(job.get('cut_at') or 0)
            if cut_at and now < cut_at:
                job['next_at'] = min(now + 0.02, cut_at)
                return
            delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
            anchor = job.get('cut_anchor') or '7074'
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
            if job.get('natural_end_before_cut'):
                return
            if not job.get('cut_fired'):
                delay_ms = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
                anchor = job.get('cut_anchor') or '7074'
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
            if not _is_weapon_mode(job.get('mode')):
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
                    'CUT [%s] packet B074 02 00 UID=%d · transport=%s · '
                    'scoring timing (B074 alone ≠ Ghost)'
                    % (job['label'], uid, job.get('cut_transport') or '?'))
                _advance_or_finish(job, ok_shot=True)
                return

            if now >= float(job.get('send_deadline') or 0):
                _log(
                    'CUT [%s] TIMEOUT 2s UID=%d · observed=%s · B074=%s · transport=%s'
                    % (job['label'], uid, job.get('observed'),
                       job.get('b074') or '(none)', job.get('cut_transport') or '?'))
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
    cut_kind = (job or {}).get('cut_target_kind') or '?'
    if expect and uid == expect and job is not None and job.get('phase') == 'wait':
        job['observed'] = True
        _log(
            'C→S 0x7081 OBSERVED (NativeCut @%s) UID=%d hex=%s · transport=client_7081'
            % (cut_kind, uid, hex_out))
    elif watching:
        _log(
            'C→S 0x7081 (khác/đồng thời) UID=%d hex=%s · expect @%s=%d'
            % (uid, hex_out, cut_kind, expect))


def handle_joymax(opcode, data):
    """B070 = cast confirm (log). Mid-cut scheduled from 7074+cfg.

    B074 before cut = FULL-CAST FAIL.
    B074 after cut scored by mid-window timing — B074 alone ≠ Ghost.
    """
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
            phase = job.get('phase')
            # Cut already scheduled from 7074; B070 is confirmation only.
            if phase not in ('cut_wait', 'cut_now', 'wait'):
                return
            if len(raw) < 19 or raw[0] != 1:
                return
            skill, source = struct.unpack_from('<II', raw, 3)
            target = struct.unpack_from('<I', raw, 15)[0]
            expect_skill = int(job.get('skill_id') or 0)
            # Always compare to own character UID — job.uid may be monster cut target.
            self_uid = read_self_uid() or int(state.get('self_uid') or 0)
            if not expect_skill or skill != expect_skill:
                return
            if self_uid and source and source != self_uid:
                return
            if self_uid and target == self_uid:
                return  # not a monster/boss cast
            now = monotonic()
            cast_at = float(job.get('cast_at') or 0)
            since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
            cfg = int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS)
            job['b070_seen'] = True
            job['b070_at'] = now
            remaining = -1
            cut_at = float(job.get('cut_at') or 0)
            if cut_at and not job.get('cut_fired'):
                remaining = max(0, int(round((cut_at - now) * 1000)))
            cut_kind = job.get('cut_target_kind') or '?'
            cut_uid = int(job.get('cut_uid') or job.get('uid') or 0)
            _log(
                'S→C 0xB070 CAST CONFIRM · skill=%d · source=%s · mob/boss=%d · '
                'since_7074=%dms · cut_cfg=%dms · mid-cut remaining≈%sms · '
                'cut@%s=%d · anchor=7074'
                % (skill, source, target, since_7074, cfg,
                   remaining if remaining >= 0 else '?', cut_kind, cut_uid))
            if since_7074 >= CAST_WINDOW_HINT_MS and not job.get('cut_fired'):
                _log(
                    'B070 LATE · since_7074=%dms ≥ window_hint=%dms — cast may '
                    'already be ending; if natural B074 before cut → FULL-CAST'
                    % (since_7074, CAST_WINDOW_HINT_MS))
            return

        prefix = 'sau cut' if watching else 'ngoài cửa sổ'
        if opcode == 0xB074:
            note = _classify_b074(raw)
            now = monotonic()
            _log('S→C 0xB074 [%s] %s | last UID=%d' % (prefix, note, last_uid))
            if job is None:
                return
            phase = job.get('phase')
            # Natural cast end BEFORE cut → skill finished full (đánh hết).
            if (not job.get('cut_fired')
                    and phase in ('cut_wait', 'cut_now', 'cast')
                    and len(raw) >= 2 and raw[:2] in (b'\x02\x00', b'\x02\x01')):
                _fail_natural_full_cast(job, note)
                return
            if job.get('phase') == 'wait' and (watching or job.get('cut_fired')):
                job['b074'] = note
                if not job.get('b074_at'):
                    job['b074_at'] = now
                cast_at = float(job.get('cast_at') or 0)
                cut_at = float(job.get('cut_fired_at') or 0)
                since_cut = int(round((now - cut_at) * 1000)) if cut_at else -1
                since_7074 = int(round((now - cast_at) * 1000)) if cast_at else -1
                if raw == b'\x02\x00':
                    set_status(
                        'B074 02 00 · %dms after cut · since_7074=%dms · scoring…'
                        % (since_cut, since_7074))
                    _log(
                        'B074 02 00 TIMING · after_cut=%dms · since_7074=%dms · '
                        'cut_cfg=%dms · (need after_cut≤%dms AND since_7074≤%dms)'
                        % (since_cut, since_7074,
                           int(job.get('ghost_delay_ms') or DEFAULT_GHOST_DELAY_MS),
                           MAX_B074_AFTER_CUT_MS, MAX_B074_SINCE_7074_MS))
                elif raw[:2] == b'\x03\x00':
                    set_status(
                        'B074 từ chối sau cut UID=%d — %s'
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
        'Nạp %s v%s — mid-window ~100ms · PACKET-FAKE if B074 late · '
        'B074 alone ≠ Ghost. Modes: 7081×2 | Weapon 7034.'
        % (NAME, VERSION))
except Exception as error:
    try:
        _log_traceback('load TRACE', error)
    except Exception:
        pass
