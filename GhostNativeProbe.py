# -*- coding: utf-8 -*-
"""GhostNativeProbe — thử Ghost qua NativeCut / client_7081 (đường AutoGhost thật).

Changelog:
- v1.0.0: Standalone probe. SAME path AutoGhost production Ghost uses:
  NativeCut (ctypes Read/WriteProcessMemory + GetTickCount thunk) → arm(2)
  for in-client 0x7081 queue. NOT inject_joymax (GhostSelfTest / AG inject
  path bị phBot Stable API=False trên True+False).
  UI: Bật, Gửi self UID, Gửi×2, optional Gửi target 7045.
  Log: C→S 0x7081 observed + S→C B074 02 00 vs từ chối.
  Độc lập — không import / không sửa AutoGhost.

Extracted from AutoGhost NativeCut + begin_native_cut / send_pvp_interrupt:
  session = NativeCut({pid, window, target})
  bridge.arm(1) → completed(4)  # verify tick hook
  bridge.arm(2)                # enqueue client 7081 for UID=target
  observe handle_silkroad 0x7081 pack('<I', uid)
  success = observed_request + B074 02 00 (+ bridge.completed(5) when available)
"""

from __future__ import print_function

import ctypes
import hashlib
import struct
import sys
from pathlib import PureWindowsPath
from threading import RLock
from time import monotonic
from ctypes import wintypes

import QtBind
import phBot as phbot_api
from phBot import get_character_data, log

NAME = 'GhostNativeProbe'
VERSION = '1.0.0'

# Verified Hùng Vương client builds — copied from AutoGhost NativeCut constants.
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

user32 = ctypes.WinDLL('user32') if sys.platform == 'win32' else None
if user32:
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'self_uid': 0,
    'target_uid': 0,
    'queue': [],
    'session': None,  # {'key': (pid, hwnd, uid), 'bridge': NativeCut, 'verified': bool}
    'pending_watch_until': 0.0,
    'last_send_uid': 0,
    'last_send_at': 0.0,
    'last_observed_7081': False,
    'last_b074': '',
    'active': None,  # in-flight job mirror for packet handlers
}

QtBind.createLabel(gui, '%s v%s — NativeCut / client_7081 (AG Ghost thật)' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật / Tắt', 10, 32)

self_uid_label = QtBind.createLabel(gui, 'Self UID: (chưa đọc)', 10, 60)
target_uid_label = QtBind.createLabel(gui, 'Target 7045 hiện tại: (chưa có)', 10, 82)
status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 104)
client_label = QtBind.createLabel(gui, 'Client: (chưa đọc)', 10, 126)

QtBind.createButton(gui, 'btn_refresh', 'Làm mới UID', 10, 154)
QtBind.createButton(gui, 'btn_send_self', 'Gửi self UID', 140, 154)
QtBind.createButton(gui, 'btn_send_x2', 'Gửi×2', 280, 154)
QtBind.createButton(gui, 'btn_send_target', 'Gửi target 7045', 380, 154)
QtBind.createButton(gui, 'btn_close', 'Tháo móc', 540, 154)

QtBind.createLabel(
    gui,
    'Đường gửi = AutoGhost NativeCut (ctypes/memory), KHÔNG inject_joymax. '
    'Xem log: observed C→S 0x7081 + B074 02 00 vs từ chối.',
    10, 192,
)


def _log(msg):
    log('[%s] %s' % (NAME, msg))


def set_status(msg):
    QtBind.setText(gui, status_label, 'Trạng thái: ' + msg)
    _log(msg)


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
    """Minimal AutoGhost NativeCut — install GetTickCount thunk, arm 7081 send."""

    def __init__(self, job):
        self.api = kernel_api()
        # QUERY_INFORMATION | VM_OPERATION | VM_READ | VM_WRITE
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
        with open(path.value, 'rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
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
            raise RuntimeError('GetTickCount đang qua một móc khác. Dừng thử.')
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
    show_target_uid()
    show_client()
    set_status(
        'BẬT — sẵn sàng NativeCut client_7081 (event_loop).'
        if on else 'TẮT — đã tháo móc.')


def btn_refresh():
    uid = read_self_uid()
    show_target_uid()
    show_client()
    set_status('Đã làm mới Self UID=%d.' % uid if uid else 'Chưa có player_id.')


def btn_close():
    close_session('nút Tháo móc')
    set_status('Đã tháo móc NativeCut.')


def _pack_uid(uid):
    return struct.pack('<I', int(uid) & 0xffffffff)


def queue_native(uid, label, times=1):
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
    job = {
        'uid': uid,
        'label': label,
        'times': times,
        'done': 0,
        'phase': 'ensure',  # ensure → verify → arm → wait → (repeat) → done
        'verify_deadline': 0.0,
        'send_deadline': 0.0,
        'next_at': monotonic(),
        'observed': False,
        'bridge_done': False,
        'b074': '',
        'ok_any': False,
        'hex': _pack_uid(uid).hex(' ').upper(),
        'error': '',
    }
    with lock:
        state['queue'].append(job)
    set_status(
        'Đã xếp hàng NativeCut %s ×%d UID=%d — arm(2) trên event_loop.'
        % (label, times, uid))
    return True


def btn_send_self():
    queue_native(read_self_uid(), 'self', times=1)


def btn_send_x2():
    # hiep first-ghost pattern: same UID twice ~10 ms apart (after each arm)
    queue_native(read_self_uid(), 'self×2', times=2)


def btn_send_target():
    with lock:
        uid = int(state.get('target_uid') or 0)
    if not uid:
        set_status('Chưa có target 7045 — chọn mục tiêu trong game trước.')
        return
    queue_native(uid, 'target', times=1)


def _classify_b074(data):
    raw = bytes(data or b'')
    if raw == b'\x02\x00':
        return '02 00 · NGẮT OK / cast end (Ghost signal)'
    if raw == b'\x02\x01':
        return '02 01 · kết thúc skill (biến thể)'
    if len(raw) >= 4 and raw[:4] == b'\x03\x00\x04\x40':
        return '03 00 04 40 · ActionRefusal (từ chối / OOR / busy)'
    if len(raw) >= 2 and raw[:2] == b'\x03\x00':
        return '%s · từ chối / fail (03 00…)' % raw[:8].hex(' ').upper()
    return '%s · (xem hex)' % (raw[:12].hex(' ').upper() if raw else '(trống)')


def _finish_job(job, note):
    with lock:
        state['last_send_at'] = monotonic()
        state['last_send_uid'] = int(job.get('uid') or 0)
        state['last_observed_7081'] = bool(job.get('observed'))
        state['last_b074'] = job.get('b074') or ''
        state['pending_watch_until'] = monotonic() + 3.0
        if state.get('active') is job:
            state['active'] = None
    set_status(note)


def _advance_or_finish(job, ok_shot):
    if ok_shot:
        job['ok_any'] = True
    job['done'] = int(job.get('done') or 0) + 1
    if job['done'] >= int(job.get('times') or 1):
        with lock:
            if state['queue'] and state['queue'][0] is job:
                state['queue'].pop(0)
        observed = 'YES' if job.get('observed') else 'NO'
        b074 = job.get('b074') or '(chưa thấy)'
        if job.get('ok_any') and job.get('observed') and (
                job.get('b074') or '').startswith('02 00'):
            _finish_job(
                job,
                'OK NativeCut %s UID=%d · observed 7081=%s · B074 %s'
                % (job['label'], job['uid'], observed, b074))
        elif job.get('error'):
            _finish_job(
                job,
                'LỖI NativeCut %s UID=%d · %s'
                % (job['label'], job['uid'], job['error']))
        else:
            _finish_job(
                job,
                'XONG NativeCut %s UID=%d · observed 7081=%s · B074 %s · bridge=%s'
                % (job['label'], job['uid'], observed, b074,
                   'done' if job.get('bridge_done') else 'pending/timeout'))
        # Keep session for optional next click; user can Tháo móc.
        return
    # Next shot on same UID — short gap like hiep ×2.
    job['phase'] = 'arm'
    job['observed'] = False
    job['bridge_done'] = False
    job['b074'] = ''
    job['next_at'] = monotonic() + 0.01
    job['send_deadline'] = 0.0


def event_loop():
    """Drive NativeCut verify/arm/wait from phBot callback (not UI thread)."""
    if not plugin_enabled():
        return
    now = monotonic()
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
                'NativeCut [%s #%d] arm(2) client_7081 UID=%d hex=%s · chờ observed+B074'
                % (job['label'], int(job.get('done') or 0) + 1, uid, job.get('hex') or '?'))
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
                _finish_job(job, 'LỖI bridge UID=%d · %s' % (uid, error))
                return

            # Success criteria mirrors AG client_exchange_confirmed spirit:
            # observed C→S 7081 + B074 02 00 (bridge state 5 is supporting).
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

    except (OSError, ValueError, RuntimeError, ctypes.WinError) as error:
        job['error'] = str(error)
        close_session(str(error))
        with lock:
            if state['queue'] and state['queue'][0] is job:
                state['queue'].pop(0)
            state['active'] = None
        set_status('LỖI NativeCut %s UID=%d · %s' % (job['label'], uid, error))
        return


def handle_silkroad(opcode, data):
    """Observe C→S: 7045 target + NativeCut-emitted 0x7081."""
    raw = bytes(data or b'')
    if opcode == 0x7045 and len(raw) >= 4:
        uid = struct.unpack_from('<I', raw, 0)[0]
        if uid:
            self_uid = read_self_uid()
            if not self_uid or uid != self_uid:
                with lock:
                    state['target_uid'] = uid
                show_target_uid()
                if plugin_enabled():
                    _log('Quan sát C→S 0x7045 chọn UID=%d (target so sánh).' % uid)
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
    hex_out = raw.hex(' ').upper()
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
    """Log S→C B074 / B081 after NativeCut arm."""
    if not plugin_enabled():
        return
    if opcode not in (0xB074, 0xB081, 0xB084, 0x3085):
        return
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
                    'B074 02 00 sau NativeCut UID=%d — có vẻ NGẮT OK.' % last_uid)
            elif raw[:2] == b'\x03\x00':
                set_status(
                    'B074 từ chối sau NativeCut UID=%d — %s' % (last_uid, note))
        return
    if opcode == 0xB081:
        _log('S→C 0xB081 [%s] hex=%s'
             % (prefix, raw[:16].hex(' ').upper() if raw else '(trống)'))
        return
    if opcode in (0xB084, 0x3085) and watching:
        _log('S→C 0x%04X [%s] hex=%s'
             % (opcode, prefix, raw[:16].hex(' ').upper() if raw else '(trống)'))


try:
    read_self_uid()
    show_target_uid()
    show_client()
    set_status(
        'Nạp %s v%s — bật rồi Gửi self UID (NativeCut / client_7081, không inject).'
        % (NAME, VERSION))
except Exception:
    pass
