# -*- coding: utf-8 -*-
"""PartyLeader — PT theo chủ (phBot Stable).

Changelog:
- v1.0.3: Cần AutoGhost ≥1.8.62. Checkbox vai trò Chủ/Phụ (không combo).
  HARD Phụ: chỉ đánh UID chủ; chủ F4/dừng Ghost → phụ dừng đánh; chủ >5m →
  dừng đánh + trace; chủ bỏ target → phụ clear. Lấy tên chủ PT = CharName, job_name.
  ks→trace + arm F; 7045 sync; Auto PK + tracing OK (không stop_bot).
- v1.0.2: `ks` → trace + bật AutoGhost Auto PK (nhóm F); sync UID hook + fallback.
- v1.0.1: Lấy tên mình = name + job_name.
- v1.0.0: Chat ks / sync B070 + ks#UID. Không ALT.
"""

from __future__ import print_function

import json
import math
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
    get_position,
    inject_joymax,
    log,
    start_trace,
    stop_trace,
)

try:
    from phBot import get_players as _get_players
except ImportError:
    _get_players = None

try:
    import phBotChat
except ImportError:
    phBotChat = None

NAME = 'PartyLeader'
VERSION = '1.0.3'
CONFIG_NAME = 'PartyLeader'

CMD_FOLLOW = ('ks',)
CMD_STOP = ('ks off', 'ksoff', 'ks dung', 'dung', 'stopks', 'notrace')
CMD_STOP_FIGHT = ('dungdanh', 'stopfight', 'ks hold', 'hold')
CMD_CLEAR_TARGET = ('ks clear', 'clear', 'cleartarget', 'bo target', 'bỏ target', 'ks#0')

ROLE_FOLLOWER = 0
ROLE_LEADER = 1
# Nhóm Ghost / Auto PK trên phụ (khớp AutoGhost PVP_EDIT_PAGES)
GHOST_PAGES = ('F1', 'F2', 'F3')
# HARD: phụ dừng đánh + trace khi chủ xa hơn khoảng này (mét).
LEADER_FOLLOW_DISTANCE = 5.0

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
    'fight_held': False,
    'last_uid': 0,
    'last_select_at': 0.0,
    'last_broadcast_uid': 0,
    'last_broadcast_at': 0.0,
    'last_clear_at': 0.0,
    'last_stop_fight_at': 0.0,
    'last_follow_nudge_at': 0.0,
    'distance_check_at': 0.0,
}

QtBind.createLabel(gui, '%s v%s — PT theo chủ' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật plugin', 10, 32)
sync_box = QtBind.createCheckBox(gui, 'ui_sync', 'Đồng bộ mục tiêu (7045 / B070)', 140, 32)
arm_box = QtBind.createCheckBox(gui, 'ui_arm', 'ks: bật AutoGhost Auto PK', 400, 32)
broadcast_box = QtBind.createCheckBox(
    gui, 'ui_broadcast', 'Chủ: chat party ks#UID khi chọn (Target / ` )', 10, 56)

QtBind.createLabel(gui, 'Vai trò', 10, 88)
role_leader_box = QtBind.createCheckBox(gui, 'ui_role_leader', 'Chủ', 10, 106)
role_follower_box = QtBind.createCheckBox(gui, 'ui_role_phu', 'Phụ', 70, 106)

QtBind.createLabel(gui, 'Nhóm Ghost F (phụ)', 150, 88)
page_combo = QtBind.createCombobox(gui, 150, 106, 70, 22)
for page in GHOST_PAGES:
    QtBind.append(gui, page_combo, page)

QtBind.createLabel(gui, 'Chủ (name, job_name)', 240, 88)
leader_field = QtBind.createLineEdit(gui, '', 240, 106, 160, 22)
QtBind.createButton(gui, 'btn_self', 'Lấy tên mình', 410, 104)
QtBind.createButton(gui, 'btn_party_master', 'Lấy tên chủ PT', 520, 104)

QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 10, 144)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 140, 144)
QtBind.createButton(gui, 'btn_follow', 'Thử theo chủ (trace)', 280, 144)
QtBind.createButton(gui, 'btn_stop', 'Dừng theo', 460, 144)

status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 184)
QtBind.createLabel(
    gui,
    'ks = phụ trace + Auto PK · ks off = dừng. Chủ chọn/đánh → phụ cùng UID.\n'
    'HARD Phụ: chỉ UID chủ · chủ F4/dừng → phụ dừng đánh · chủ >5m → trace · chủ bỏ target → clear.\n'
    'Phụ: tick Phụ + Lấy tên chủ PT + F + Lưu. Chủ: tick Chủ + Lấy tên mình / chat ks.',
    10, 214,
)

QtBind.setChecked(gui, sync_box, True)
QtBind.setChecked(gui, broadcast_box, True)
QtBind.setChecked(gui, arm_box, True)
QtBind.setChecked(gui, role_follower_box, True)
QtBind.setChecked(gui, role_leader_box, False)
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


def format_leader_display(char_name, job_name):
    """Bắt buộc CharName, job_name — không nhận chỉ nghề / chỉ tên."""
    name = str(char_name or '').strip()
    job = str(job_name or '').strip()
    if name and job:
        return '%s, %s' % (name, job)
    return ''


def self_display():
    return format_leader_display(self_name(), self_job_name())


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


def require_full_leader(text, context='Leader'):
    """Validate/normalize to `CharName, job_name` or raise ValueError."""
    char_name, job_name, _display = parse_leader_identity(text)
    full = format_leader_display(char_name, job_name)
    if full:
        return full
    if char_name and not job_name:
        raise ValueError(
            '%s=%r chỉ có 1 phần — cần `CharName, job_name` (vd ThienHau, AG_He).'
            % (context, char_name))
    if job_name and not char_name:
        raise ValueError(
            '%s thiếu CharName — cần `CharName, job_name`.' % context)
    raise ValueError('%s trống — cần `CharName, job_name`.' % context)


def _truthy_flag(value):
    if value is True or value == 1:
        return True
    text = str(value or '').strip().casefold()
    return text in ('1', 'true', 'yes', 'leader', 'master', 'chu', 'chủ')


def _member_is_party_master(member):
    if not isinstance(member, dict):
        return False
    for key in ('leader', 'master', 'is_leader', 'isLeader', 'party_leader',
                'partyLeader', 'is_master', 'isMaster'):
        if key in member and _truthy_flag(member.get(key)):
            return True
    role = str(member.get('role') or member.get('type') or '').strip().casefold()
    return role in ('leader', 'master', 'chu', 'chủ', 'party leader')


def _lookup_job_name(char_name, player_id=0):
    job = ''
    # get_players near-list (job_name often only here).
    if callable(_get_players):
        try:
            players = _get_players() or {}
        except Exception:
            players = {}
        if isinstance(players, dict):
            for uid, player in players.items():
                if not isinstance(player, dict):
                    continue
                try:
                    pid = int(player.get('player_id') or uid or 0)
                except (TypeError, ValueError):
                    pid = 0
                pname = str(player.get('name') or '').strip()
                if (player_id and pid == player_id) or (
                        char_name and pname.casefold() == char_name.casefold()):
                    job = str(player.get('job_name') or player.get('jobName')
                              or player.get('job') or '').strip()
                    if job:
                        return job
    # Self character fallback.
    if player_id and player_id == self_player_id():
        return self_job_name()
    if char_name and char_name.casefold() == self_name().casefold():
        return self_job_name()
    return job


def party_master_display():
    """Party master → `CharName, job_name` từ get_party (+ get_players/character)."""
    party = get_party()
    if not isinstance(party, dict) or not party:
        raise ValueError('Chưa vào party / get_party trống.')
    members = [m for m in party.values() if isinstance(m, dict)]
    if not members:
        raise ValueError('Party không có thành viên đọc được.')
    master = None
    for member in members:
        if _member_is_party_master(member):
            master = member
            break
    if master is None:
        # Một số build: key 0 / partyNumber nhỏ nhất = chủ.
        try:
            ordered = sorted(
                ((int(k) if str(k).isdigit() else 999, v) for k, v in party.items()
                 if isinstance(v, dict)),
                key=lambda item: item[0])
            if ordered:
                master = ordered[0][1]
        except Exception:
            master = members[0]
    if master is None:
        raise ValueError('Không xác định được chủ PT trong get_party.')
    char_name = str(master.get('name') or '').strip()
    try:
        player_id = int(master.get('player_id') or 0)
    except (TypeError, ValueError):
        player_id = 0
    job = str(master.get('job_name') or master.get('jobName')
              or master.get('job') or '').strip()
    if not job:
        job = _lookup_job_name(char_name, player_id)
    full = format_leader_display(char_name, job)
    if not full:
        raise ValueError(
            'Chủ PT thiếu name/job_name (name=%r job=%r). Đứng gần chủ hoặc mở PT rồi thử lại.'
            % (char_name, job))
    return full


def identity_tokens(char_name, job_name, display):
    tokens = []
    for part in (display, char_name, job_name):
        key = str(part or '').strip().casefold()
        if key and key not in tokens:
            tokens.append(key)
    return tokens


def role_index():
    if QtBind.isChecked(gui, role_leader_box):
        return ROLE_LEADER
    return ROLE_FOLLOWER


def set_role(index, from_ui=False):
    """Checkbox Chủ/Phụ — exclusive. from_ui tránh đệ quy khi click."""
    index = ROLE_LEADER if int(index) == ROLE_LEADER else ROLE_FOLLOWER
    QtBind.setChecked(gui, role_leader_box, index == ROLE_LEADER)
    QtBind.setChecked(gui, role_follower_box, index == ROLE_FOLLOWER)
    with lock:
        state['role'] = index


def ui_role_leader(checked):
    if checked:
        set_role(ROLE_LEADER, from_ui=True)
        set_status('Vai trò: Chủ')
    elif not QtBind.isChecked(gui, role_follower_box):
        # Không cho bỏ cả hai — mặc định Phụ.
        set_role(ROLE_FOLLOWER, from_ui=True)


def ui_role_phu(checked):
    if checked:
        set_role(ROLE_FOLLOWER, from_ui=True)
        set_status('Vai trò: Phụ')
    elif not QtBind.isChecked(gui, role_leader_box):
        set_role(ROLE_LEADER, from_ui=True)


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


def is_stop_fight_cmd(norm):
    return norm in CMD_STOP_FIGHT


def is_clear_target_cmd(norm):
    return norm in CMD_CLEAR_TARGET


def parse_ks_uid(msg):
    raw = str(msg or '').strip()
    low = raw.casefold()
    if low.startswith('ks#'):
        tail = raw[3:].strip()
        if not tail or tail.split()[0] in ('0', 'clear', 'none'):
            return 0
        try:
            return int(tail.split()[0])
        except (ValueError, IndexError):
            return None  # invalid
    parts = low.split()
    if len(parts) >= 3 and parts[0] == 'ks' and parts[1] in ('t', 'uid', 'target'):
        try:
            return int(parts[2])
        except ValueError:
            return None
    return None


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
    """Bật AutoGhost Auto PK theo nhóm F đã lưu trên phụ (song song với trace)."""
    if not QtBind.isChecked(gui, arm_box):
        return False
    ghost = find_autoghost()
    if ghost is None:
        set_status('Không thấy AutoGhost — chỉ trace/sync 7045.')
        return False
    # Không stop_bot: đang ks/trace thì get_status truthy — AutoGhost 1.8.62+ cho phép.
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
    # Giữ trace; không start_bot / stop_bot.
    ghost = find_autoghost()
    if ghost is not None:
        select_hook = getattr(ghost, 'party_sync_select_uid', None)
        if callable(select_hook):
            try:
                ok = bool(select_hook(uid, source='%s:%s' % (NAME, reason)))
                set_status('Chọn UID=%d (%s) · AutoGhost hook=%r' % (uid, reason, ok))
                if ok:
                    return True
            except Exception as error:
                _log('party_sync_select_uid: %s' % error)

    packet = struct.pack('<I', uid & 0xffffffff)
    ok = inject_joymax(0x7045, packet, False)
    if ok is False:
        ok = inject_joymax(0x7045, packet, True)
    set_status('Chọn UID=%d (%s) · 7045=%r' % (uid, reason, ok))
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
    try:
        full = require_full_leader(configured_leader(), context='Chủ')
        QtBind.setText(gui, leader_field, full)
    except ValueError as error:
        set_status('[%s] %s' % (reason, error))
        return False
    leader_char = configured_leader_char()
    if not leader_char:
        set_status('Chưa có CharName chủ PT.')
        return False
    try:
        ok = start_trace(leader_char)
    except Exception as error:
        set_status('start_trace lỗi: %s' % error)
        return False
    with lock:
        state['following'] = bool(ok)
    set_status('[%s] Trace → CharName=%r (Leader=%r) · API=%r' % (
        reason, leader_char, full, ok))
    # ks: arm Auto PK song song trace — chủ đánh → phụ 7045 + Ghost cùng UID.
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
        state['fight_held'] = False
    if party_chat('ks#%d' % uid):
        set_status('Chủ broadcast ks#%d (party)' % uid)


def leader_broadcast_clear_target(reason='bỏ target'):
    """Chủ clear/unlock → phụ clear cùng lúc."""
    if not QtBind.isChecked(gui, enabled_box):
        return False
    if not i_am_leader():
        return False
    with lock:
        now = monotonic()
        if (now - state['last_clear_at']) < 0.35:
            return False
        state['last_clear_at'] = now
        state['last_broadcast_uid'] = 0
    if party_chat('ks#0'):
        set_status('[%s] Chủ broadcast clear target (ks#0).' % reason)
        return True
    return False


def leader_broadcast_stop_fight(reason='F4/dừng Ghost'):
    """Chủ dừng đánh (F4 / stop Ghost) → phụ dừng cast ngay."""
    if not QtBind.isChecked(gui, enabled_box):
        return False
    if not i_am_leader():
        return False
    with lock:
        now = monotonic()
        if (now - state['last_stop_fight_at']) < 0.35:
            return False
        state['last_stop_fight_at'] = now
    if party_chat('dungdanh'):
        set_status('[%s] Chủ broadcast dungdanh → phụ dừng đánh.' % reason)
        return True
    return False


def on_leader_ghost_stop(reason=None):
    """Hook từ AutoGhost (F4 / pause Ghost) trên máy chủ."""
    leader_broadcast_stop_fight(reason or 'Ghost dừng')


def follower_clear_target(reason):
    """HARD: phụ bỏ target Ghost/Auto PK ngay."""
    ghost = find_autoghost()
    cleared = False
    if ghost is not None:
        hook = getattr(ghost, 'party_sync_clear_target', None)
        try:
            if callable(hook):
                cleared = bool(hook(reason=reason, source=NAME))
            else:
                # Fallback: pause clear_target
                pause = getattr(ghost, 'pause_pvp', None)
                if callable(pause):
                    pause(reason, clear_target=True, cancel_action=True, notify=False)
                    cleared = True
        except Exception as error:
            set_status('Clear target lỗi: %s' % error)
            return False
    with lock:
        state['last_uid'] = 0
        state['fight_held'] = True
    set_status('[%s] Phụ đã clear target.' % reason)
    return cleared


def follower_stop_fight(reason):
    """HARD: phụ dừng đánh ngay, giữ trace / Auto PK armed để chờ UID mới."""
    ghost = find_autoghost()
    if ghost is not None:
        hook = getattr(ghost, 'party_sync_hold_fight', None)
        try:
            if callable(hook):
                hook(reason=reason, source=NAME)
            else:
                clear = getattr(ghost, 'party_sync_clear_target', None)
                if callable(clear):
                    clear(reason=reason, source=NAME)
                else:
                    pause = getattr(ghost, 'pause_pvp', None)
                    if callable(pause):
                        pause(reason, clear_target=True, cancel_action=True, notify=False)
        except Exception as error:
            set_status('Stop fight lỗi: %s' % error)
            return False
    with lock:
        state['fight_held'] = True
        state['last_uid'] = 0
    set_status('[%s] Phụ dừng đánh (chờ chủ).' % reason)
    return True


def leader_xy_from_party():
    """Tọa độ chủ từ get_party (name khớp Leader field)."""
    char_name, job_name, display = parse_leader_identity(configured_leader())
    tokens = identity_tokens(char_name, job_name, display)
    if not tokens:
        return None
    party = get_party()
    if not isinstance(party, dict):
        return None
    for member in party.values():
        if not isinstance(member, dict):
            continue
        name = str(member.get('name') or '').strip()
        if not name or name.casefold() not in tokens:
            # cũng khớp job_name nếu party chỉ có char name
            if name.casefold() != char_name.casefold():
                continue
        try:
            x = float(member.get('x'))
            y = float(member.get('y'))
        except (TypeError, ValueError):
            continue
        if math.isfinite(x) and math.isfinite(y):
            return {'x': x, 'y': y, 'name': name}
    return None


def distance_to_leader():
    me = get_position() or {}
    try:
        mx = float(me.get('x'))
        my = float(me.get('y'))
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(mx) and math.isfinite(my)):
        return None
    leader = leader_xy_from_party()
    if not leader:
        return None
    return math.hypot(leader['x'] - mx, leader['y'] - my)


def follower_ensure_trace(reason):
    leader_char = configured_leader_char()
    if not leader_char:
        return False
    try:
        ok = start_trace(leader_char)
    except Exception as error:
        set_status('[%s] start_trace lỗi: %s' % (reason, error))
        return False
    with lock:
        state['following'] = bool(ok)
    set_status('[%s] Trace → %r · API=%r' % (reason, leader_char, ok))
    return bool(ok)


def follower_check_leader_distance():
    """HARD: chủ >5m → phụ dừng đánh + start_trace."""
    if i_am_leader() or not QtBind.isChecked(gui, enabled_box):
        return
    with lock:
        following = state['following'] or state['armed_auto_pk']
    if not following and not QtBind.isChecked(gui, arm_box):
        return
    dist = distance_to_leader()
    if dist is None:
        return
    if dist <= LEADER_FOLLOW_DISTANCE:
        return
    with lock:
        now = monotonic()
        if (now - state['last_follow_nudge_at']) < 1.0:
            return
        state['last_follow_nudge_at'] = now
    follower_stop_fight('chủ cách %.1fm (>%.0fm)' % (dist, LEADER_FOLLOW_DISTANCE))
    follower_ensure_trace('chủ xa %.1fm' % dist)


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
        if data['role'] == ROLE_LEADER and not data['leader_name']:
            me = self_display()
            if me:
                data['leader_name'] = me
                QtBind.setText(gui, leader_field, me)
        data['leader_name'] = require_full_leader(
            data.get('leader_name'), context='Chủ (Leader)')
        QtBind.setText(gui, leader_field, data['leader_name'])
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
        raw = str(data.get('leader_name') or '').strip()
        if raw:
            try:
                full = require_full_leader(raw, context='Leader đã lưu')
                if full != raw:
                    QtBind.setText(gui, leader_field, full)
                set_status('Đã tải %s · Leader=%r' % (path.name, full))
            except ValueError as error:
                set_status('Đã tải %s · nhưng %s — bấm Lấy tên lại rồi Lưu.'
                           % (path.name, error))
        else:
            set_status('Đã tải %s' % path.name)
    except FileNotFoundError:
        set_status('Chưa có file — bấm Lưu sau khi điền.')
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        set_status('Chưa tải: %s' % error)


def btn_self():
    me = self_display()
    if not me:
        name, job = self_name(), self_job_name()
        set_status(
            'Chưa đủ name+job_name (name=%r job=%r). Vào game rồi bấm lại.'
            % (name, job))
        return
    QtBind.setText(gui, leader_field, me)
    set_role(ROLE_LEADER)
    set_status('Đã điền tên mình %r · vai trò Chủ. Bấm Lưu cấu hình.' % me)


def btn_party_master():
    """Phụ: điền chủ PT = CharName, job_name từ party."""
    try:
        full = party_master_display()
    except ValueError as error:
        set_status('Lấy tên chủ PT: %s' % error)
        return
    QtBind.setText(gui, leader_field, full)
    set_role(ROLE_FOLLOWER)
    set_status('Đã điền chủ PT %r · vai trò Phụ. Bấm Lưu cấu hình.' % full)


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

    norm = normalize_cmd(text)
    # HARD: chủ dừng đánh → phụ dừng cast ngay (giữ trace).
    if is_stop_fight_cmd(norm):
        if not i_am_leader():
            follower_stop_fight('chat dungdanh')
        return
    # HARD: chủ clear target → phụ clear.
    if is_clear_target_cmd(norm):
        if not i_am_leader():
            follower_clear_target('chat clear')
        return

    uid = parse_ks_uid(text)
    if uid == 0 and text.casefold().startswith('ks#'):
        if not i_am_leader():
            follower_clear_target('chat ks#0')
        return
    if uid and QtBind.isChecked(gui, sync_box) and not i_am_leader():
        with lock:
            state['fight_held'] = False
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
        with lock:
            state['fight_held'] = False
        if QtBind.isChecked(gui, arm_box):
            with lock:
                armed = state['armed_auto_pk']
            if not armed:
                arm_auto_pk(prefer_uid=target_uid)
        inject_select(target_uid, 'B070 chủ %s đánh' % attacker_name)
    return True


def handle_silkroad(opcode, data):
    if not QtBind.isChecked(gui, enabled_box):
        return True
    if not i_am_leader():
        return True
    # Chủ bỏ target (7046 hoặc 7045 UID=0) → phụ clear.
    if opcode == 0x7046:
        leader_broadcast_clear_target('7046')
        return True
    if opcode != 0x7045 or not data:
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
    else:
        leader_broadcast_clear_target('7045 UID=0')
    return True


def event_loop():
    """Phụ: chủ >5m → dừng đánh + trace."""
    if not QtBind.isChecked(gui, enabled_box):
        return
    if i_am_leader():
        return
    with lock:
        now = monotonic()
        if (now - state['distance_check_at']) < 0.45:
            return
        state['distance_check_at'] = now
    try:
        follower_check_leader_distance()
    except Exception as error:
        _log('distance check: %s' % error)


def joined_game():
    btn_load()
    if role_index() == ROLE_LEADER and not (QtBind.text(gui, leader_field) or '').strip():
        me = self_display() or self_name()
        if me:
            QtBind.setText(gui, leader_field, me)


def teleported():
    pass


log('[%s] Đã nạp v%s. Tick Chủ/Phụ + Lấy tên chủ PT. ks→trace+Auto PK (AG≥1.8.66).'
    % (NAME, VERSION))
