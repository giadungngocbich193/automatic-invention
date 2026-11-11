# -*- coding: utf-8 -*-
"""PartyLeader — PT theo chủ (phBot Stable).

Changelog:
- v1.0.1: Lấy tên mình = name + job_name (vd. ThienHau, AG_He). Phụ khớp tên
  và/hoặc nghề; start_trace luôn dùng tên NV (phần trước dấu phẩy).
- v1.0.0: Chat `ks` → phụ start_trace chủ; `ks off`/`dung` → stop_trace.
  Sync mục tiêu: B070 khi chủ đánh + broadcast `ks#UID` khi chủ chọn (0x7045).
  Phụ inject 0x7045 cùng UID. Không ALT.
"""

from __future__ import print_function

import json
import struct
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
VERSION = '1.0.1'
CONFIG_NAME = 'PartyLeader'

# Chat lệnh (không phân biệt hoa thường)
CMD_FOLLOW = ('ks',)
CMD_STOP = ('ks off', 'ksoff', 'ks dung', 'dung', 'stopks', 'notrace')

ROLE_FOLLOWER = 0
ROLE_LEADER = 1
ROLE_LABELS = (
    'Vai trò: Phụ (theo chủ)',
    'Vai trò: Chủ PT',
)

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'role': ROLE_FOLLOWER,
    'leader_name': '',
    'sync_target': True,
    'broadcast_select': True,
    'following': False,
    'last_uid': 0,
    'last_select_at': 0.0,
    'last_broadcast_uid': 0,
    'last_broadcast_at': 0.0,
}

QtBind.createLabel(gui, '%s v%s — PT theo chủ' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật plugin', 10, 32)
sync_box = QtBind.createCheckBox(gui, 'ui_sync', 'Đồng bộ mục tiêu (7045 / B070)', 140, 32)
broadcast_box = QtBind.createCheckBox(
    gui, 'ui_broadcast', 'Chủ: chat party ks#UID khi chọn (Target / ` )', 10, 56)

QtBind.createLabel(gui, 'Vai trò', 10, 88)
role_combo = QtBind.createCombobox(gui, 10, 106, 220, 22)
for label in ROLE_LABELS:
    QtBind.append(gui, role_combo, label)

QtBind.createLabel(gui, 'Tên chủ (name, job_name) — phụ điền đúng / Lấy tên mình', 250, 88)
leader_field = QtBind.createLineEdit(gui, '', 250, 106, 200, 22)
QtBind.createButton(gui, 'btn_self', 'Lấy tên mình', 460, 104)

QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 10, 144)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 140, 144)
QtBind.createButton(gui, 'btn_follow', 'Thử theo chủ (trace)', 280, 144)
QtBind.createButton(gui, 'btn_stop', 'Dừng theo', 460, 144)

status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 184)
QtBind.createLabel(
    gui,
    'Lệnh chat (party/all… từ chủ):  ks = phụ trace chủ  ·  ks off / dung = dừng trace.\n'
    'Chủ chọn địch → (tuỳ chọn) party ks#UID · hoặc khi chủ đánh (B070) phụ tự 7045 cùng UID.\n'
    'Cùng plugin mọi acc: phụ = Bật + ô chủ (name, job_name) · chủ = Lấy tên mình / chat ks.',
    10, 214,
)

# Defaults
QtBind.setChecked(gui, sync_box, True)
QtBind.setChecked(gui, broadcast_box, True)
QtBind.setText(gui, role_combo, ROLE_LABELS[ROLE_FOLLOWER])


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
    """Tên hiển thị cấu hình: 'Name, job_name' (tránh nhầm NV gần giống)."""
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
    """Tách ô Leader → (char_name, job_name, display).

    Chấp nhận: 'ThienHau, AG_He' | 'ThienHau' | chỉ job.
    """
    raw = ' '.join(str(text or '').strip().split())
    if not raw:
        return '', '', ''
    if ',' in raw:
        left, right = raw.split(',', 1)
        char_name = left.strip()
        job_name = right.strip()
    else:
        char_name = raw
        job_name = ''
    display = raw
    return char_name, job_name, display


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


def normalize_cmd(msg):
    return ' '.join(str(msg or '').strip().casefold().split())


def is_stop_cmd(norm):
    return norm in CMD_STOP


def is_follow_cmd(norm):
    return norm in CMD_FOLLOW


def parse_ks_uid(msg):
    """Parse 'ks#123' / 'ks# 123' / 'ks t 123' → uid or 0."""
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
    """Chuỗi ô Leader (có thể gồm name, job_name)."""
    name = (QtBind.text(gui, leader_field) or '').strip()
    if name:
        return name
    if role_index() == ROLE_LEADER:
        return self_display() or self_name()
    return ''


def configured_leader_char():
    """Tên NV dùng cho start_trace (không kèm job)."""
    char_name, _job, _display = parse_leader_identity(configured_leader())
    return char_name


def name_is_leader(player):
    """Khớp chat/party name với ô Leader: full / tên NV / job_name."""
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
    """UID → tên nếu là mình hoặc thành viên party."""
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
    packet = struct.pack('<I', uid & 0xffffffff)
    ok = inject_joymax(0x7045, packet, False)
    set_status('Chọn UID=%d (%s) · 7045=%r' % (uid, reason, ok))
    try:
        if not get_status():
            start_bot()
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
    return bool(ok)


def do_stop_follow(reason):
    try:
        stop_trace()
    except Exception as error:
        set_status('stop_trace lỗi: %s' % error)
        return False
    with lock:
        state['following'] = False
    set_status('[%s] Đã dừng trace.' % reason)
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
        'sync_target': QtBind.isChecked(gui, sync_box),
        'broadcast_select': QtBind.isChecked(gui, broadcast_box),
    }


def apply_settings(data):
    data = data or {}
    QtBind.setChecked(gui, enabled_box, bool(data.get('enabled')))
    set_role(data.get('role', ROLE_FOLLOWER))
    QtBind.setText(gui, leader_field, str(data.get('leader_name') or ''))
    QtBind.setChecked(gui, sync_box, bool(data.get('sync_target', True)))
    QtBind.setChecked(gui, broadcast_box, bool(data.get('broadcast_select', True)))
    with lock:
        state['enabled'] = bool(data.get('enabled'))
        state['role'] = ROLE_LEADER if int(data.get('role', 0) or 0) == ROLE_LEADER else ROLE_FOLLOWER
        state['leader_name'] = str(data.get('leader_name') or '')
        state['sync_target'] = bool(data.get('sync_target', True))
        state['broadcast_select'] = bool(data.get('broadcast_select', True))


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
        set_status('Đã lưu %s · Leader=%r' % (path.name, data['leader_name']))
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


def handle_chat(chat_type, player, msg):
    """ks / ks off từ chủ; ks#UID broadcast."""
    if not QtBind.isChecked(gui, enabled_box):
        return
    # Union chat đôi khi kèm "Guild: msg"
    if int(chat_type or 0) == 11 and msg and ': ' in str(msg):
        msg = str(msg).split(': ', 1)[1]
    text = str(msg or '').strip()
    if not text:
        return
    # Discord / webhook type 100: cho phép không cần tên khớp leader list
    from_leader = name_is_leader(player) or int(chat_type or 0) == 100
    if not from_leader:
        return

    uid = parse_ks_uid(text)
    if uid and QtBind.isChecked(gui, sync_box) and not i_am_leader():
        inject_select(uid, 'chat ks# từ chủ')
        return

    norm = normalize_cmd(text)
    if is_stop_cmd(norm):
        if not i_am_leader():
            do_stop_follow('chat')
        return
    if is_follow_cmd(norm):
        if not i_am_leader():
            # Trace đúng người gửi lệnh nếu trùng / hoặc tên cấu hình
            leader = configured_leader() or str(player or '').strip()
            if player and leader and str(player).casefold() != leader.casefold():
                # Chủ chat ks nhưng ô Leader khác — ưu tiên tên ô; vẫn trace ô
                pass
            do_follow('chat ks')
        return


def handle_joymax(opcode, data):
    """Server B070: chủ đánh → phụ chọn cùng target (xTargetSupport-style)."""
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
    if skill_type != 2:  # attack
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
        if locale in (18, 56):  # iSRO / TRSRO
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
        inject_select(target_uid, 'B070 chủ %s đánh' % attacker_name)
    return True


def handle_silkroad(opcode, data):
    """Chủ chọn target (0x7045 outgoing) → broadcast ks#UID cho phụ."""
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
    # refresh self id after tele
    pass


log('[%s] Đã nạp v%s. Phụ: Bật + tên chủ. Chủ: chat ks · chọn địch (ks#UID / B070).' % (NAME, VERSION))
