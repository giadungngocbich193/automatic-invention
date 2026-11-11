# -*- coding: utf-8 -*-
"""PartyLeader — PT theo chủ (phBot Stable).

Changelog:
- v1.0.2: `ks` → trace + bật AutoGhost Auto PK (nhóm F phụ chọn); `ks off`/`dung`
  dừng trace + tắt Auto PK nếu plugin này bật. Sync UID qua hook AutoGhost
  (tránh 7045=False bị Auto PK chặn) + fallback inject.
- v1.0.1: Lấy tên mình = name + job_name. Phụ khớp tên/nghề; trace dùng tên NV.
- v1.0.0: Chat ks / sync B070 + ks#UID. Không ALT.
"""

from __future__ import print_function

import json
import struct
import sys
from pathlib import Path
from threading import RLock
from time import monotonic

import QtBind
from phBot import (
    get_character_data,
    get_config_dir,
    get_locale,
    get_party,
    get_status,
    inject_joymax,
    log,
    start_bot,
    start_trace,
    stop_trace,
)

try:
    import phBotChat
except ImportError:
    phBotChat = None

NAME = 'PartyLeader'
VERSION = '1.0.2'
CONFIG_NAME = 'PartyLeader'

CMD_FOLLOW = ('ks',)
CMD_STOP = ('ks off', 'ksoff', 'ks dung', 'dung', 'stopks', 'notrace')

ROLE_FOLLOWER = 0
ROLE_LEADER = 1
ROLE_LABELS = (
    'Vai trò: Phụ (theo chủ)',
    'Vai trò: Chủ PT',
)
# Nhóm Ghost / Auto PK trên phụ (khớp AutoGhost PVP_EDIT_PAGES)
GHOST_PAGES = ('F1', 'F2', 'F3')

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'role': ROLE_FOLLOWER,
    'leader_name': '',
    'ghost_page': 'F2',
    'sync_target': True,
    'broadcast_select': True,
    'arm_auto_pk': True,
    'following': False,
    'armed_auto_pk': False,
    'last_uid': 0,
    'last_select_at': 0.0,
    'last_broadcast_uid': 0,
    'last_broadcast_at': 0.0,
}

QtBind.createLabel(gui, '%s v%s — PT theo chủ' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật plugin', 10, 32)
sync_box = QtBind.createCheckBox(gui, 'ui_sync', 'Đồng bộ mục tiêu (7045 / B070)', 140, 32)
arm_box = QtBind.createCheckBox(gui, 'ui_arm', 'ks: bật AutoGhost Auto PK', 400, 32)
broadcast_box = QtBind.createCheckBox(
    gui, 'ui_broadcast', 'Chủ: chat party ks#UID khi chọn (Target / ` )', 10, 56)

QtBind.createLabel(gui, 'Vai trò', 10, 88)
role_combo = QtBind.createCombobox(gui, 10, 106, 200, 22)
for label in ROLE_LABELS:
    QtBind.append(gui, role_combo, label)

QtBind.createLabel(gui, 'Nhóm Ghost F (phụ)', 220, 88)
page_combo = QtBind.createCombobox(gui, 220, 106, 70, 22)
for page in GHOST_PAGES:
    QtBind.append(gui, page_combo, page)

QtBind.createLabel(gui, 'Tên chủ (name, job_name)', 300, 88)
leader_field = QtBind.createLineEdit(gui, '', 300, 106, 180, 22)
QtBind.createButton(gui, 'btn_self', 'Lấy tên mình', 490, 104)

QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 10, 144)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 140, 144)
QtBind.createButton(gui, 'btn_follow', 'Thử theo chủ (trace)', 280, 144)
QtBind.createButton(gui, 'btn_stop', 'Dừng theo', 460, 144)

status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 184)
QtBind.createLabel(
    gui,
    'Lệnh từ chủ (party):  ks = phụ trace + bật Auto PK (nhóm F)  ·  ks off / dung = dừng.\n'
    'Chủ chọn/đánh → phụ chọn cùng UID (hook AutoGhost / 7045) rồi Ghost đánh.\n'
    'Phụ: Bật + tên chủ + chọn F1/F2/F3 + Lưu. Chủ: Lấy tên mình / chat ks.',
    10, 214,
)

QtBind.setChecked(gui, sync_box, True)
QtBind.setChecked(gui, broadcast_box, True)
QtBind.setChecked(gui, arm_box, True)
QtBind.setText(gui, role_combo, ROLE_LABELS[ROLE_FOLLOWER])
QtBind.setText(gui, page_combo, 'F2')


def _log(msg):
    log('[%s] %s' % (NAME, msg))


def set_status(msg):
    QtBind.setText(gui, status_label, 'Trạng thái: ' + msg)
    _log(msg)


def config_path():
    return Path(get_config_dir()) / (CONFIG_NAME + '.json')


def self_name():
    data = get_character_data() or {}
    return str(data.get('name') or '').strip()


def self_job_name():
    data = get_character_data() or {}
    return str(data.get('job_name') or '').strip()


def self_display():
    name = self_name()
    job = self_job_name()
    if name and job:
        return '%s, %s' % (name, job)
    return name or job


def self_player_id():
    data = get_character_data() or {}
    try:
        return int(data.get('player_id') or 0)
    except (TypeError, ValueError):
        return 0


def parse_leader_identity(text):
    raw = ' '.join(str(text or '').strip().split())
    if not raw:
        return '', '', ''
    if ',' in raw:
        left, right = raw.split(',', 1)
        return left.strip(), right.strip(), raw
    return raw, '', raw


def identity_tokens(char_name, job_name, display):
    tokens = []
    for part in (display, char_name, job_name):
        key = str(part or '').strip().casefold()
        if key and key not in tokens:
            tokens.append(key)
    return tokens


def role_index():
    text = (QtBind.text(gui, role_combo) or '').strip()
    for i, label in enumerate(ROLE_LABELS):
        if label == text:
            return i
    return ROLE_FOLLOWER


def set_role(index):
    index = ROLE_LEADER if int(index) == ROLE_LEADER else ROLE_FOLLOWER
    QtBind.setText(gui, role_combo, ROLE_LABELS[index])


def ghost_page():
    page = (QtBind.text(gui, page_combo) or 'F2').strip().upper()
    return page if page in GHOST_PAGES else 'F2'


def set_ghost_page(page):
    page = str(page or 'F2').strip().upper()
    if page not in GHOST_PAGES:
        page = 'F2'
    QtBind.setText(gui, page_combo, page)


def normalize_cmd(msg):
    return ' '.join(str(msg or '').strip().casefold().split())


def is_stop_cmd(norm):
    return norm in CMD_STOP


def is_follow_cmd(norm):
    return norm in CMD_FOLLOW


def parse_ks_uid(msg):
    raw = str(msg or '').strip()
    low = raw.casefold()
    if low.startswith('ks#'):
        tail = raw[3:].strip()
        try:
            return int(tail.split()[0])
        except (ValueError, IndexError):
            return 0
    parts = low.split()
    if len(parts) >= 3 and parts[0] == 'ks' and parts[1] in ('t', 'uid', 'target'):
        try:
            return int(parts[2])
        except ValueError:
            return 0
    return 0


def configured_leader():
    name = (QtBind.text(gui, leader_field) or '').strip()
    if name:
        return name
    if role_index() == ROLE_LEADER:
        return self_display() or self_name()
    return ''


def configured_leader_char():
    char_name, _job, _display = parse_leader_identity(configured_leader())
    return char_name


def name_is_leader(player):
    if not player:
        return False
    leader = configured_leader()
    if not leader:
        return False
    char_name, job_name, display = parse_leader_identity(leader)
    needle = str(player).strip().casefold()
    if not needle:
        return False
    return needle in identity_tokens(char_name, job_name, display)


def i_am_leader():
    if role_index() == ROLE_LEADER:
        return True
    me = self_name()
    me_job = self_job_name()
    me_disp = self_display()
    if not me and not me_job:
        return False
    leader = configured_leader()
    if not leader:
        return False
    char_name, job_name, display = parse_leader_identity(leader)
    tokens = identity_tokens(char_name, job_name, display)
    for mine in (me_disp, me, me_job):
        key = str(mine or '').strip().casefold()
        if key and key in tokens:
            return True
    return False


def party_member_name(unique_id):
    try:
        uid = int(unique_id)
    except (TypeError, ValueError):
        return ''
    if uid and uid == self_player_id():
        return self_name()
    party = get_party()
    if not isinstance(party, dict):
        return ''
    for member in party.values():
        if not isinstance(member, dict):
            continue
        try:
            if int(member.get('player_id') or 0) == uid:
                return str(member.get('name') or '')
        except (TypeError, ValueError):
            continue
    return ''


def find_autoghost():
    for module in list(sys.modules.values()):
        try:
            if getattr(module, 'NAME', None) == 'AutoGhost':
                return module
        except Exception:
            continue
    return None


def arm_auto_pk(prefer_uid=0):
    """Bật AutoGhost Auto PK theo nhóm F đã lưu trên phụ."""
    if not QtBind.isChecked(gui, arm_box):
        return False
    ghost = find_autoghost()
    if ghost is None:
        set_status('Không thấy AutoGhost — chỉ trace/sync 7045.')
        return False
    page = ghost_page()
    hook = getattr(ghost, 'party_sync_arm_auto_pk', None)
    try:
        if callable(hook):
            ok = bool(hook(page=page, prefer_uid=int(prefer_uid or 0), source=NAME))
        else:
            # Fallback older AutoGhost: set page UI + request_auto_pk_arm
            field = getattr(ghost, 'auto_pk_page_field', None)
            gui_ref = getattr(ghost, 'gui', None)
            if field is not None and gui_ref is not None:
                QtBind.setText(gui_ref, field, page)
            arm = getattr(ghost, 'request_auto_pk_arm', None)
            if not callable(arm):
                set_status('AutoGhost thiếu request_auto_pk_arm.')
                return False
            arm()
            ok = bool(getattr(ghost, 'auto_pk_running', False))
    except Exception as error:
        set_status('Arm Auto PK lỗi: %s' % error)
        return False
    with lock:
        state['armed_auto_pk'] = bool(ok)
    set_status('Auto PK %s · nhóm %s · API=%r' % (
        'ON' if ok else 'FAIL', page, ok))
    return ok


def stop_auto_pk_if_ours(reason):
    with lock:
        armed = state['armed_auto_pk']
    if not armed and not QtBind.isChecked(gui, arm_box):
        return False
    ghost = find_autoghost()
    if ghost is None:
        with lock:
            state['armed_auto_pk'] = False
        return False
    hook = getattr(ghost, 'party_sync_stop_auto_pk', None)
    try:
        if callable(hook):
            hook(reason=reason, source=NAME)
        else:
            stop = getattr(ghost, 'stop_auto_pk', None)
            if callable(stop):
                stop(reason=reason)
    except Exception as error:
        set_status('Stop Auto PK lỗi: %s' % error)
        return False
    with lock:
        state['armed_auto_pk'] = False
    set_status('[%s] Đã tắt Auto PK.' % reason)
    return True


def inject_select(uid, reason):
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    with lock:
        now = monotonic()
        if uid == state['last_uid'] and (now - state['last_select_at']) < 0.35:
            return True
        state['last_uid'] = uid
        state['last_select_at'] = now

    # Ưu tiên hook AutoGhost (đánh dấu party_sync_uid → không bị chặn 7045).
    ghost = find_autoghost()
    if ghost is not None:
        select_hook = getattr(ghost, 'party_sync_select_uid', None)
        if callable(select_hook):
            try:
                ok = bool(select_hook(uid, source='%s:%s' % (NAME, reason)))
                set_status('Chọn UID=%d (%s) · AutoGhost hook=%r' % (uid, reason, ok))
                if ok:
                    try:
                        if not get_status():
                            start_bot()
                    except Exception:
                        pass
                    return True
            except Exception as error:
                _log('party_sync_select_uid: %s' % error)

    packet = struct.pack('<I', uid & 0xffffffff)
    ok = inject_joymax(0x7045, packet, False)
    if ok is False:
        ok = inject_joymax(0x7045, packet, True)
    set_status('Chọn UID=%d (%s) · 7045=%r' % (uid, reason, ok))
    try:
        if not get_status():
            start_bot()
    except Exception:
        pass
    # Nếu Auto PK đang chạy, vẫn giữ prefer_uid qua arm hook.
    if ok is False and ghost is not None and getattr(ghost, 'auto_pk_running', False):
        try:
            runtime = getattr(ghost, 'auto_pk_runtime', None)
            if isinstance(runtime, dict):
                runtime['party_sync_uid'] = uid
                runtime['requested'] = uid
                set_status('7045 từ chối · đã gắn prefer UID=%d cho Auto PK retry' % uid)
        except Exception:
            pass
    return ok is not False


def do_follow(reason):
    if i_am_leader():
        set_status('[%s] Mình là chủ — không trace chính mình.' % reason)
        return False
    leader_char = configured_leader_char()
    if not leader_char:
        set_status('Chưa có tên chủ PT.')
        return False
    try:
        ok = start_trace(leader_char)
    except Exception as error:
        set_status('start_trace lỗi: %s' % error)
        return False
    with lock:
        state['following'] = bool(ok)
    set_status('[%s] Trace → %r (%s) · API=%r' % (
        reason, leader_char, configured_leader(), ok))
    # ks: bật Auto PK theo nhóm F trên phụ
    arm_auto_pk(prefer_uid=0)
    return bool(ok)


def do_stop_follow(reason):
    try:
        stop_trace()
    except Exception as error:
        set_status('stop_trace lỗi: %s' % error)
        return False
    with lock:
        state['following'] = False
    stop_auto_pk_if_ours(reason)
    set_status('[%s] Đã dừng trace (+ Auto PK nếu do plugin bật).' % reason)
    return True


def party_chat(msg):
    if phBotChat is None:
        set_status('Thiếu phBotChat — không gửi party được.')
        return False
    try:
        phBotChat.Party(str(msg))
        return True
    except Exception as error:
        set_status('Party chat lỗi: %s' % error)
        return False


def leader_broadcast_uid(uid):
    if not QtBind.isChecked(gui, broadcast_box):
        return
    if not i_am_leader():
        return
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return
    if uid <= 0:
        return
    with lock:
        now = monotonic()
        if uid == state['last_broadcast_uid'] and (now - state['last_broadcast_at']) < 0.6:
            return
        state['last_broadcast_uid'] = uid
        state['last_broadcast_at'] = now
    if party_chat('ks#%d' % uid):
        set_status('Chủ broadcast ks#%d (party)' % uid)


def read_settings():
    return {
        'enabled': QtBind.isChecked(gui, enabled_box),
        'role': role_index(),
        'leader_name': (QtBind.text(gui, leader_field) or '').strip(),
        'ghost_page': ghost_page(),
        'sync_target': QtBind.isChecked(gui, sync_box),
        'broadcast_select': QtBind.isChecked(gui, broadcast_box),
        'arm_auto_pk': QtBind.isChecked(gui, arm_box),
    }


def apply_settings(data):
    data = data or {}
    QtBind.setChecked(gui, enabled_box, bool(data.get('enabled')))
    set_role(data.get('role', ROLE_FOLLOWER))
    QtBind.setText(gui, leader_field, str(data.get('leader_name') or ''))
    set_ghost_page(data.get('ghost_page', 'F2'))
    QtBind.setChecked(gui, sync_box, bool(data.get('sync_target', True)))
    QtBind.setChecked(gui, broadcast_box, bool(data.get('broadcast_select', True)))
    QtBind.setChecked(gui, arm_box, bool(data.get('arm_auto_pk', True)))
    with lock:
        state['enabled'] = bool(data.get('enabled'))
        state['role'] = ROLE_LEADER if int(data.get('role', 0) or 0) == ROLE_LEADER else ROLE_FOLLOWER
        state['leader_name'] = str(data.get('leader_name') or '')
        state['ghost_page'] = ghost_page()
        state['sync_target'] = bool(data.get('sync_target', True))
        state['broadcast_select'] = bool(data.get('broadcast_select', True))
        state['arm_auto_pk'] = bool(data.get('arm_auto_pk', True))


def btn_save():
    try:
        data = read_settings()
        if data['role'] == ROLE_FOLLOWER and not data['leader_name']:
            raise ValueError('Phụ cần điền tên chủ (name, job_name).')
        if data['role'] == ROLE_LEADER and not data['leader_name']:
            me = self_display() or self_name()
            if me:
                data['leader_name'] = me
                QtBind.setText(gui, leader_field, me)
        path = config_path()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        apply_settings(data)
        set_status('Đã lưu %s · Leader=%r · F=%s' % (
            path.name, data['leader_name'], data['ghost_page']))
    except (OSError, ValueError, TypeError) as error:
        set_status('Chưa lưu: %s' % error)


def btn_load():
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('JSON không hợp lệ.')
        apply_settings(data)
        set_status('Đã tải %s' % path.name)
    except FileNotFoundError:
        set_status('Chưa có file — bấm Lưu sau khi điền.')
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        set_status('Chưa tải: %s' % error)


def btn_self():
    me = self_display() or self_name()
    if not me:
        set_status('Chưa vào game / chưa đọc được name+job_name.')
        return
    QtBind.setText(gui, leader_field, me)
    set_role(ROLE_LEADER)
    set_status('Đã điền tên mình %r (name + job_name) · vai trò Chủ.' % me)


def btn_follow():
    if not QtBind.isChecked(gui, enabled_box):
        set_status('Bật plugin trước.')
        return
    do_follow('UI')


def btn_stop():
    do_stop_follow('UI')


def ui_enabled(checked):
    with lock:
        state['enabled'] = bool(checked)
    set_status('Đã bật.' if checked else 'Đã tắt.')


def ui_sync(checked):
    with lock:
        state['sync_target'] = bool(checked)


def ui_broadcast(checked):
    with lock:
        state['broadcast_select'] = bool(checked)


def ui_arm(checked):
    with lock:
        state['arm_auto_pk'] = bool(checked)


def handle_chat(chat_type, player, msg):
    if not QtBind.isChecked(gui, enabled_box):
        return
    if int(chat_type or 0) == 11 and msg and ': ' in str(msg):
        msg = str(msg).split(': ', 1)[1]
    text = str(msg or '').strip()
    if not text:
        return
    from_leader = name_is_leader(player) or int(chat_type or 0) == 100
    if not from_leader:
        return

    uid = parse_ks_uid(text)
    if uid and QtBind.isChecked(gui, sync_box) and not i_am_leader():
        # Đảm bảo Auto PK đang chạy khi nhận target
        if QtBind.isChecked(gui, arm_box):
            with lock:
                armed = state['armed_auto_pk']
            if not armed:
                arm_auto_pk(prefer_uid=uid)
            else:
                inject_select(uid, 'chat ks# từ chủ')
                return
        inject_select(uid, 'chat ks# từ chủ')
        return

    norm = normalize_cmd(text)
    if is_stop_cmd(norm):
        if not i_am_leader():
            do_stop_follow('chat')
        return
    if is_follow_cmd(norm):
        if not i_am_leader():
            do_follow('chat ks')
        return


def handle_joymax(opcode, data):
    if opcode != 0xB070 or not data:
        return True
    if not QtBind.isChecked(gui, enabled_box):
        return True
    if not QtBind.isChecked(gui, sync_box):
        return True
    if i_am_leader():
        return True
    try:
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
    except Exception:
        return True
    if len(raw) < 15 or raw[0] != 1:
        return True
    skill_type = raw[1]
    if skill_type != 2:
        return True
    index = 7
    try:
        attacker_uid = struct.unpack_from('<I', raw, index)[0]
        index += 8
        locale = 0
        try:
            locale = int(get_locale() or 0)
        except Exception:
            locale = 0
        if locale in (18, 56):
            index += 4
        if len(raw) < index + 4:
            return True
        target_uid = struct.unpack_from('<I', raw, index)[0]
    except Exception:
        return True
    attacker_name = party_member_name(attacker_uid)
    if not attacker_name or not name_is_leader(attacker_name):
        return True
    if target_uid:
        if QtBind.isChecked(gui, arm_box):
            with lock:
                armed = state['armed_auto_pk']
            if not armed:
                arm_auto_pk(prefer_uid=target_uid)
        inject_select(target_uid, 'B070 chủ %s đánh' % attacker_name)
    return True


def handle_silkroad(opcode, data):
    if opcode != 0x7045 or not data:
        return True
    if not QtBind.isChecked(gui, enabled_box):
        return True
    if not i_am_leader():
        return True
    if not QtBind.isChecked(gui, broadcast_box):
        return True
    try:
        raw = data if isinstance(data, (bytes, bytearray)) else bytes(data)
    except Exception:
        return True
    if len(raw) < 4:
        return True
    uid = struct.unpack_from('<I', raw, 0)[0]
    if uid:
        leader_broadcast_uid(uid)
    return True


def joined_game():
    btn_load()
    if role_index() == ROLE_LEADER and not (QtBind.text(gui, leader_field) or '').strip():
        me = self_display() or self_name()
        if me:
            QtBind.setText(gui, leader_field, me)


def teleported():
    pass


log('[%s] Đã nạp v%s. Phụ: tên chủ + nhóm F + Bật. Chủ: chat ks → phụ Auto PK.' % (NAME, VERSION))
