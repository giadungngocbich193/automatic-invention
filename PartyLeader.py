# -*- coding: utf-8 -*-
"""PartyLeader — PT theo chủ (phBot Stable).

Changelog:
- v2.0.1: Leader F1/F2 debounce — không spam ksgo / “đã phát lệnh đánh” khi đã combat.
- v2.0: Leader F1/F2/3 → ksgo#F#UID arm Phụ; Prefer + soft-stop.
- v1.0.9: Trace AG_He luôn OK (Phụ role authoritative); AG≥1.8.69 prefer cast.
- v1.0.8: Trace job nick AG_He/*AG_He OK; soft-stop >10m (no inject/stop_bot DC);
  prefer party master name else job; giữ persist ticks 1.0.7. AG≥1.8.68.
- v1.0.7: Lưu/Tải đủ checkbox (Bật/sync/ks Auto PK/chat ks#/Chủ-Phụ/F/Leader);
  auto-load khi nạp plugin + auto-apply Bật từ file.
- v1.0.6: UI 10m; soft Trace; fix ensure override.
- v1.0.5: Follow 10m; grace; F4→stop+trace; CharName resolve.
- v1.0.4: Lấy tên chủ PT CharName + prefer UID no-7045. AG≥1.8.67.
- v1.0.3: Checkbox Chủ/Phụ. HARD Phụ UID chủ; >10m → trace; clear/hold.
- v1.0.2: `ks` → trace + Auto PK F.
- v1.0.1: Lấy tên mình = name + job_name.
- v1.0.0: Chat ks / sync B070 + ks#UID. Không ALT.
"""

from __future__ import print_function

import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from threading import RLock
from time import monotonic, sleep

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
VERSION = '2.0.1'
CONFIG_NAME = 'PartyLeader'

CMD_FOLLOW = ('ks',)
CMD_STOP = ('ks off', 'ksoff', 'ks dung', 'dung', 'stopks', 'notrace')
CMD_STOP_FIGHT = ('dungdanh', 'stopfight', 'ks hold', 'hold')
CMD_CLEAR_TARGET = ('ks clear', 'clear', 'cleartarget', 'bo target', 'bỏ target', 'ks#0')

ROLE_FOLLOWER = 0
ROLE_LEADER = 1
# Nhóm Ghost / Auto PK trên phụ (khớp AutoGhost PVP_EDIT_PAGES)
GHOST_PAGES = ('F1', 'F2', 'F3')
# Sau Bật plugin / ks / arm: chưa áp khoảng cách (tránh clear storm lúc enable Phụ).
FOLLOW_DISTANCE_GRACE = 12.0

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
    'follow_by_position': False,
    'armed_auto_pk': False,
    'fight_held': False,
    'last_uid': 0,
    'selected_uid': 0,
    'leader_combat_uid': 0,
    'last_combat_cmd_at': 0.0,
    'last_combat_cmd_key': '',
    'last_select_at': 0.0,
    'last_broadcast_uid': 0,
    'last_broadcast_at': 0.0,
    'last_clear_at': 0.0,
    'last_stop_fight_at': 0.0,
    'last_follow_nudge_at': 0.0,
    'follow_check_at': 0.0,
    'last_b070_uid': 0,
    'last_b070_at': 0.0,
    'last_inject_log_at': 0.0,
    'follow_grace_until': 0.0,
}

_ui_applying = False  # True while restore — skip checkbox side-effects

QtBind.createLabel(gui, '%s v%s — PT theo chủ' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật plugin', 10, 32)
sync_box = QtBind.createCheckBox(gui, 'ui_sync', 'Đồng bộ theo lệnh F1/F2', 140, 32)
arm_box = QtBind.createCheckBox(gui, 'ui_arm', 'F1/F2: bật AutoGhost Auto PK', 400, 32)
broadcast_box = QtBind.createCheckBox(
    gui, 'ui_broadcast', 'Chủ: chat party ks#UID khi chọn (Target / ` )', 10, 56)

QtBind.createLabel(gui, 'Vai trò', 10, 88)
role_leader_box = QtBind.createCheckBox(gui, 'ui_role_leader', 'Chủ', 10, 106)
role_follower_box = QtBind.createCheckBox(gui, 'ui_role_phu', 'Phụ', 70, 106)

QtBind.createLabel(gui, 'Nhóm Ghost F (phụ)', 150, 88)
page_combo = QtBind.createCombobox(gui, 150, 106, 70, 22)
for page in GHOST_PAGES:
    QtBind.append(gui, page_combo, page)

QtBind.createLabel(gui, 'Tên leader cần theo', 240, 88)
leader_field = QtBind.createLineEdit(gui, '', 240, 106, 160, 22)
QtBind.createButton(gui, 'btn_self', 'Lấy tên mình', 410, 104)
QtBind.createButton(gui, 'btn_party_master', 'Lấy tên chủ PT', 520, 104)

QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 10, 144)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 140, 144)
QtBind.createButton(gui, 'btn_follow', 'Thử theo chủ (trace)', 280, 144)
QtBind.createButton(gui, 'btn_stop', 'Dừng theo', 460, 144)

status_label = QtBind.createLabel(gui, 'Trạng thái: Phụ · chờ bật plugin', 10, 184)
follower_help = 'Theo lệnh F1/F2 và F4 của chủ.\nNhập tên leader hoặc bấm Lấy tên chủ PT.'
role_help_label = QtBind.createLabel(gui, follower_help, 10, 214)


def update_role_help(index):
    if index == ROLE_LEADER:
        message = 'Chọn mục tiêu để gửi UID cho tổ đội.\nF1/F2 bật hoặc dừng đánh. F4 dừng đánh.'
    else:
        message = follower_help
    QtBind.setText(gui, role_help_label, message)


QtBind.setChecked(gui, sync_box, True)
QtBind.setChecked(gui, broadcast_box, True)
QtBind.setChecked(gui, arm_box, True)
QtBind.setChecked(gui, role_follower_box, True)
QtBind.setChecked(gui, role_leader_box, False)
QtBind.setText(gui, page_combo, 'F2')


def _log(msg):
    log('[%s] %s' % (NAME, msg))


def set_status(msg, display=None):
    role = 'Chủ' if role_index() == ROLE_LEADER else 'Phụ'
    QtBind.setText(gui, status_label, 'Trạng thái: %s · %s' % (role, display or msg))
    _log(msg)


loaded_config_owner = None


def config_owner():
    character = get_character_data() or {}
    name = str(character.get('name') or '').strip()
    server = str(character.get('server') or '').strip()
    if not name or not server:
        return None
    return server.casefold(), name.casefold()


def config_path(owner=None):
    owner = owner or config_owner()
    if owner is None:
        raise ValueError('Vào game để đọc tên nhân vật và máy chủ.')
    key = json.dumps(owner, ensure_ascii=False).encode('utf-8')
    suffix = hashlib.sha256(key).hexdigest()[:24]
    return Path(get_config_dir()) / ('%s_%s.json' % (CONFIG_NAME, suffix))


def _strip_job_star(text):
    """Remove leading job-mode '*' from display names (*AG_BangChu → AG_BangChu)."""
    text = str(text or '').strip()
    while text.startswith('*'):
        text = text[1:].strip()
    return text


def self_name():
    data = get_character_data() or {}
    # Prefer real character name fields over job display.
    for key in ('name', 'charname', 'char_name', 'character_name', 'CharName'):
        val = _strip_job_star(data.get(key) or '')
        if val:
            return val
    return ''


def self_job_name():
    data = get_character_data() or {}
    for key in ('job_name', 'jobName', 'job'):
        val = str(data.get(key) or '').strip()
        if val:
            return val
    # Job-mode: character name field may be "*AG_He" while job_name empty.
    raw = str(data.get('name') or '').strip()
    if raw.startswith('*'):
        return raw
    return ''


def format_leader_display(char_name, job_name):
    """Normalize to `CharName, job_name` (accept job-mode *names)."""
    name = _strip_job_star(char_name)
    job = str(job_name or '').strip()
    if name and job:
        return '%s, %s' % (name, job)
    if name and not job:
        # Job-mode fallback: CharName, *CharName so trace gets real char name.
        return '%s, *%s' % (name, name)
    if job and not name:
        return '%s, %s' % (_strip_job_star(job), job if job.startswith('*') else '*%s' % job)
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
        return _strip_job_star(left), right.strip(), raw
    # Single token: treat as CharName (strip *); keep *form as job hint.
    token = raw.strip()
    if token.startswith('*'):
        return _strip_job_star(token), token, raw
    return token, '', raw


def require_full_leader(text, context='Leader'):
    """Validate/normalize to `CharName, job_name` (job-mode *names OK)."""
    char_name, job_name, _display = parse_leader_identity(text)
    full = format_leader_display(char_name, job_name)
    if full:
        return full
    raise ValueError('%s trống — cần CharName (job-mode *name OK).' % context)


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


def _member_player_id(member):
    if not isinstance(member, dict):
        return 0
    for key in ('player_id', 'unique_id', 'uid', 'id'):
        try:
            pid = int(member.get(key) or 0)
        except (TypeError, ValueError):
            pid = 0
        if pid > 0:
            return pid
    return 0


def _self_identity_tokens():
    tokens = set()
    for part in (self_name(), self_job_name(),
                 _strip_job_star(self_name()), _strip_job_star(self_job_name())):
        key = str(part or '').strip().casefold()
        if key:
            tokens.add(key)
            tokens.add(key.lstrip('*'))
    data = get_character_data() or {}
    for key in ('name', 'job_name', 'jobName', 'job', 'charname', 'CharName'):
        val = _strip_job_star(data.get(key) or '').casefold()
        if val:
            tokens.add(val)
    tokens.discard('')
    return tokens


def _is_self_identity(char_name, job_name=''):
    """True if CharName/job looks like the local character (job nick AG_He included)."""
    tokens = _self_identity_tokens()
    if not tokens:
        return False
    for part in (char_name, job_name, _strip_job_star(char_name), _strip_job_star(job_name)):
        key = str(part or '').strip().casefold().lstrip('*')
        if key and key in tokens:
            return True
    return False


def _is_self_member(member):
    """True if party member is the local character (avoid picking self as chủ)."""
    if not isinstance(member, dict):
        return False
    pid = _member_player_id(member)
    if pid and pid == self_player_id():
        return True
    m_char, m_job = '', ''
    try:
        m_char, m_job = _resolve_member_identity(member)
    except Exception:
        m_char = _strip_job_star(member.get('name') or '')
        m_job = str(member.get('job_name') or member.get('job') or '')
    if _is_self_identity(m_char, m_job):
        return True
    name = _strip_job_star(member.get('name') or '').casefold()
    if name and name in _self_identity_tokens():
        return True
    return False


def _player_identity_from_near(player_id=0, hint_name=''):
    """Resolve CharName + job_name from get_players / character (not job-only)."""
    char_name, job = '', ''
    hint = _strip_job_star(hint_name).casefold()
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
                raw_name = str(player.get('name') or '').strip()
                pname = _strip_job_star(raw_name)
                match = (player_id and pid == player_id) or (
                    hint and pname.casefold() == hint)
                if not match and hint and raw_name.lstrip('*').casefold() == hint:
                    match = True
                if not match:
                    continue
                # Prefer dedicated char name fields over job display in `name`.
                for key in ('charname', 'char_name', 'character_name', 'CharName'):
                    val = _strip_job_star(player.get(key) or '')
                    if val:
                        char_name = val
                        break
                if not char_name:
                    # If name has no '*', treat as CharName; if '*', it's job display.
                    if raw_name.startswith('*'):
                        char_name = pname  # best guess without real char field
                    else:
                        char_name = pname
                job = str(player.get('job_name') or player.get('jobName')
                          or player.get('job') or '').strip()
                if not job and raw_name.startswith('*'):
                    job = raw_name
                if char_name:
                    return char_name, job
    if player_id and player_id == self_player_id():
        return self_name(), self_job_name()
    if hint and hint == self_name().casefold():
        return self_name(), self_job_name()
    return char_name, job


def _resolve_member_identity(member):
    """CharName (real) + job_name/* from party member + near list."""
    if not isinstance(member, dict):
        return '', ''
    player_id = _member_player_id(member)
    raw_name = str(member.get('name') or '').strip()
    # Dedicated char fields on party member if present.
    char_name = ''
    for key in ('charname', 'char_name', 'character_name', 'CharName'):
        val = _strip_job_star(member.get(key) or '')
        if val:
            char_name = val
            break
    job = str(member.get('job_name') or member.get('jobName')
              or member.get('job') or '').strip()
    if raw_name.startswith('*') and not job:
        job = raw_name
    if not char_name:
        if raw_name.startswith('*'):
            char_name = _strip_job_star(raw_name)
        else:
            char_name = raw_name
    near_char, near_job = _player_identity_from_near(player_id, char_name or raw_name)
    if near_char:
        # Prefer near CharName when party only had job display.
        if (not char_name) or (raw_name.startswith('*') and near_char.casefold() != _strip_job_star(raw_name).casefold()):
            char_name = near_char
        elif near_char and not raw_name.startswith('*'):
            char_name = near_char
        else:
            char_name = near_char or char_name
    if near_job and not job:
        job = near_job
    return _strip_job_star(char_name), job


def party_master_display():
    """Party master → prefer CharName, else job nick (AG_He / *AG_He OK)."""
    party = None
    deadline = monotonic() + 1.5
    while monotonic() < deadline:
        party = get_party()
        if isinstance(party, dict) and party:
            break
        sleep(0.05)
    if not isinstance(party, dict) or not party:
        raise ValueError('Chưa vào party / get_party trống — mở PT rồi thử lại.')
    members = [m for m in party.values() if isinstance(m, dict)]
    if not members:
        raise ValueError('Party không có thành viên đọc được.')
    master = None
    for member in members:
        if _member_is_party_master(member) and not _is_self_member(member):
            master = member
            break
    if master is None:
        for member in members:
            if _member_is_party_master(member):
                master = member
                break
    if master is None:
        # Fallback: first non-self by party key order.
        try:
            ordered = sorted(
                ((int(k) if str(k).isdigit() else 999, v) for k, v in party.items()
                 if isinstance(v, dict)),
                key=lambda item: item[0])
            for _k, member in ordered:
                if not _is_self_member(member):
                    master = member
                    break
            if master is None and ordered:
                master = ordered[0][1]
        except Exception:
            for member in members:
                if not _is_self_member(member):
                    master = member
                    break
            if master is None:
                master = members[0]
    if master is None:
        raise ValueError('Không xác định được chủ PT trong get_party.')
    if _is_self_member(master) and len(members) > 1:
        # Prefer any other member marked master / first other.
        alt = None
        for member in members:
            if _is_self_member(member):
                continue
            if _member_is_party_master(member) or alt is None:
                alt = member
                if _member_is_party_master(member):
                    break
        if alt is not None:
            master = alt
        else:
            raise ValueError(
                'Chỉ thấy chính mình trong party master — đứng gần chủ / mở PT rồi thử lại.')
    if _is_self_member(master):
        raise ValueError(
            'Lấy tên chủ PT ra chính mình — đứng gần chủ, mở PT, thử lại.')
    char_name, job = _resolve_member_identity(master)
    # Prefer distinct CharName; else job nick (chủ job AG_He is valid).
    job_bare = _strip_job_star(job)
    if char_name and job_bare and char_name.casefold() != job_bare.casefold():
        preferred_name, preferred_job = char_name, job
    elif char_name:
        preferred_name, preferred_job = char_name, job or ('*%s' % char_name)
    elif job_bare:
        preferred_name, preferred_job = job_bare, job if str(job).startswith('*') else ('*%s' % job_bare)
    else:
        raise ValueError(
            'Chủ PT thiếu name/job_name (name=%r job=%r). Đứng gần chủ hoặc mở PT rồi thử lại.'
            % (char_name, job))
    if preferred_job and not str(preferred_job).startswith('*') and preferred_name and (
            preferred_name.casefold() == _strip_job_star(preferred_job).casefold()):
        preferred_job = '*' + _strip_job_star(preferred_job)
    full = format_leader_display(preferred_name, preferred_job)
    if not full:
        raise ValueError(
            'Chủ PT thiếu name/job_name (name=%r job=%r). Đứng gần chủ hoặc mở PT rồi thử lại.'
            % (char_name, job))
    return full


def identity_tokens(char_name, job_name, display):
    tokens = []
    for part in (display, char_name, job_name,
                 _strip_job_star(char_name), _strip_job_star(job_name),
                 ('*' + _strip_job_star(job_name)) if job_name else ''):
        key = str(part or '').strip().casefold()
        if key and key not in tokens:
            tokens.append(key)
    return tokens


def role_index():
    if QtBind.isChecked(gui, role_leader_box):
        return ROLE_LEADER
    return ROLE_FOLLOWER


def set_role(index):
    """Keep the role checkboxes mutually exclusive."""
    global _ui_applying
    index = ROLE_LEADER if int(index) == ROLE_LEADER else ROLE_FOLLOWER
    was = _ui_applying
    _ui_applying = True
    try:
        QtBind.setChecked(gui, role_leader_box, index == ROLE_LEADER)
        QtBind.setChecked(gui, role_follower_box, index == ROLE_FOLLOWER)
    finally:
        _ui_applying = was
    with lock:
        state['role'] = index
    update_role_help(index)
    if index == ROLE_FOLLOWER and not was:
        mark_follow_grace()


def ui_role_leader(checked):
    if _ui_applying:
        return
    if checked or not QtBind.isChecked(gui, role_follower_box):
        role = ROLE_LEADER if checked else ROLE_FOLLOWER
        set_role(role)
        set_status('Vai trò: %s' % ('Chủ' if role == ROLE_LEADER else 'Phụ'), 'Đã đổi vai trò')


def ui_role_phu(checked):
    if _ui_applying:
        return
    if checked or not QtBind.isChecked(gui, role_leader_box):
        role = ROLE_FOLLOWER if checked else ROLE_LEADER
        set_role(role)
        set_status('Vai trò: %s' % ('Chủ' if role == ROLE_LEADER else 'Phụ'), 'Đã đổi vai trò')


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
    """Left side of `CharName, job` after strip *."""
    char_name, job_name, _display = parse_leader_identity(configured_leader())
    return _strip_job_star(char_name)


def mark_follow_grace(seconds=None):
    seconds = FOLLOW_DISTANCE_GRACE if seconds is None else float(seconds)
    with lock:
        state['follow_grace_until'] = monotonic() + max(0.0, seconds)


def in_follow_grace():
    with lock:
        return monotonic() < float(state.get('follow_grace_until') or 0)


def resolve_trace_char_name():
    """Name for start_trace: prefer party CharName, else job nick (AG_He OK)."""
    raw = configured_leader()
    char_name, job_name, _display = parse_leader_identity(raw)
    char_name = _strip_job_star(char_name)
    job_bare = _strip_job_star(job_name)

    def _party_real_char(hint_char='', hint_job=''):
        party = get_party()
        if not isinstance(party, dict):
            return ''
        hint_c = _strip_job_star(hint_char).casefold()
        hint_j = _strip_job_star(hint_job).casefold()
        best = ''
        for member in party.values():
            if not isinstance(member, dict) or _is_self_member(member):
                continue
            m_char, m_job = _resolve_member_identity(member)
            m_char = _strip_job_star(m_char)
            m_job_bare = _strip_job_star(m_job)
            raw_m = str(member.get('name') or '').strip()
            tokens = {
                m_char.casefold(), m_job_bare.casefold(),
                raw_m.casefold(), _strip_job_star(raw_m).casefold(),
            }
            tokens.discard('')
            if hint_c or hint_j:
                if not ((hint_c and hint_c in tokens) or (hint_j and hint_j in tokens)):
                    continue
            # Prefer distinct CharName when party exposes both name + job.
            if m_char and m_job_bare and m_char.casefold() != m_job_bare.casefold():
                return m_char
            if m_char and not raw_m.startswith('*'):
                best = best or m_char
            elif m_char:
                best = best or m_char
        return best

    if char_name and job_bare and char_name.casefold() != job_bare.casefold():
        return char_name
    real = _party_real_char(char_name, job_bare or char_name)
    if real and job_bare and real.casefold() != job_bare.casefold():
        return real
    if real and char_name and real.casefold() != char_name.casefold() and not (
            job_bare and real.casefold() == job_bare.casefold()):
        return real
    # Job nick / same-as-job display is allowed (chủ job AG_He).
    if char_name:
        return char_name
    if job_bare:
        return job_bare
    raise ValueError('Chưa có tên chủ PT để trace.')


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
    # Phụ checkbox is authoritative — never treat job nick AG_He as "mình là chủ".
    if role_index() == ROLE_FOLLOWER:
        return False
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
    best = None
    best_key = None
    for module in list(sys.modules.values()):
        if getattr(module, 'NAME', None) != 'AutoGhost':
            continue
        parts = str(getattr(module, 'VERSION', '')).split('.')
        version = tuple(int(part) for part in parts) if all(part.isdecimal() for part in parts) else ()
        compatible = all(callable(getattr(module, hook, None)) for hook in (
            'party_sync_arm_auto_pk', 'party_sync_select_uid', 'party_sync_hold_fight'))
        key = compatible, version
        if best_key is None or key >= best_key:
            best, best_key = module, key
    return best


def arm_auto_pk(prefer_uid=0):
    """Bật AutoGhost Auto PK theo nhóm F đã lưu trên phụ (song song với trace)."""
    if not QtBind.isChecked(gui, arm_box):
        return False
    ghost = find_autoghost()
    if ghost is None:
        set_status('Chưa thấy AutoGhost đã nạp. Kiểm tra log tải plugin AutoGhost.py.')
        return False
    page = ghost_page()
    hook = getattr(ghost, 'party_sync_arm_auto_pk', None)
    if not callable(hook):
        version = getattr(ghost, 'VERSION', '?')
        now = monotonic()
        with lock:
            show = (state.get('missing_hook_version') != version
                    or now >= state.get('missing_hook_notice_at', 0))
            if show:
                state.update(missing_hook_version=version, missing_hook_notice_at=now + 10.0)
        if show:
            set_status('AutoGhost v%s thiếu hook bật Auto PK. Nạp cặp plugin cùng bản phát hành.' % version)
        return False
    try:
        ok = bool(hook(page=page, prefer_uid=int(prefer_uid or 0), source=NAME))
    except Exception as error:
        set_status('Arm Auto PK lỗi: %s' % error)
        return False
    with lock:
        state['armed_auto_pk'] = bool(ok)
    if ok:
        mark_follow_grace()
    if ok:
        set_status('Auto PK ON · nhóm %s' % page)
    else:
        field = getattr(ghost, 'auto_pk_status_label', None)
        ghost_gui = getattr(ghost, 'gui', None)
        detail = (QtBind.text(ghost_gui, field) or '').strip() if field is not None and ghost_gui is not None else ''
        set_status('AutoGhost v%s chưa bật nhóm %s · %s' %
                   (getattr(ghost, 'VERSION', '?'), page, detail or 'xem log AutoGhost'))
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
    """Prefer AutoGhost direct UID + Ghost. Never 7045 inject storm."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    ghost = find_autoghost()
    has_target = getattr(ghost, 'party_sync_has_target', None)
    if callable(has_target) and has_target(uid):
        with lock:
            state['last_uid'] = uid
            state['fight_held'] = False
        return True
    with lock:
        now = monotonic()
        # Strong debounce — B070 fires every cast; one prefer per UID/1.5s.
        if uid == state['last_uid'] and (now - state['last_select_at']) < 1.5:
            return True
        state['last_uid'] = uid
        state['last_select_at'] = now
        state['fight_held'] = False
        quiet = (now - state.get('last_inject_log_at', 0)) < 3.0
        if not quiet:
            state['last_inject_log_at'] = now

    if ghost is not None and not getattr(ghost, 'auto_pk_running', False):
        return False  # The arm failure is already reported.
    if ghost is not None:
        select_hook = getattr(ghost, 'party_sync_select_uid', None)
        if callable(select_hook):
            try:
                ok = bool(select_hook(uid, source='%s:%s' % (NAME, reason)))
                if not quiet:
                    set_status('Prefer UID=%d (%s) · AG hook=%r (no 7045)' % (uid, reason, ok))
                if not ok:
                    with lock:
                        if state['last_uid'] == uid:
                            state['last_uid'] = 0
                return ok
            except Exception as error:
                _log('party_sync_select_uid: %s' % error)
    if not quiet:
        set_status('Không AutoGhost hook · bỏ 7045 loop · UID=%d' % uid)
    return False


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
    try:
        leader_char = resolve_trace_char_name()
    except ValueError as error:
        set_status('[%s] %s' % (reason, error))
        return False
    ok = follower_ensure_trace(reason)
    return ok


def do_stop_follow(reason):
    try:
        stop_trace()
    except Exception as error:
        set_status('stop_trace lỗi: %s' % error)
        return False
    with lock:
        state['following'] = False
        state['follow_by_position'] = False
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
    if not i_am_leader():
        return
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return
    if uid <= 0:
        return
    with lock:
        state['selected_uid'] = uid
        if not QtBind.isChecked(gui, broadcast_box):
            return
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
        state['selected_uid'] = 0
        state['leader_combat_uid'] = 0
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
        set_status('[%s] Chủ broadcast dungdanh → phụ stop + trace.' % reason)
        return True
    return False


def leader_hotkeys_enabled():
    return QtBind.isChecked(gui, enabled_box) and i_am_leader()


def leader_has_selected_uid():
    return state['selected_uid'] if leader_hotkeys_enabled() else 0


def leader_combat_command_active():
    return bool(QtBind.isChecked(gui, enabled_box) and i_am_leader()
                and state['leader_combat_uid'])


def on_leader_ghost_start(page, uid):
    """Chủ F1/F2/3 → party chat ksgo. Debounce same page+UID (no spam)."""
    if (not QtBind.isChecked(gui, enabled_box) or not i_am_leader()
            or page not in GHOST_PAGES or not uid):
        return False
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return False
    page = str(page).upper()
    key = '%s#%d' % (page, uid)
    with lock:
        now = monotonic()
        if (state.get('leader_combat_uid') == uid
                and state.get('last_combat_cmd_key') == key
                and (now - float(state.get('last_combat_cmd_at') or 0)) < 2.0):
            return True  # already broadcast — silent
    if party_chat('ksgo#%s#%d' % (page, uid)):
        with lock:
            state['leader_combat_uid'] = uid
            state['last_combat_cmd_at'] = monotonic()
            state['last_combat_cmd_key'] = key
        set_status('Chủ phát lệnh đánh %s · UID %d' % (page, uid))
        return True
    return False


def on_leader_ghost_stop(reason=None):
    """Hook từ AutoGhost (F4 / pause Ghost) trên máy chủ."""
    with lock:
        state['leader_combat_uid'] = 0
        state['last_combat_cmd_key'] = ''
        state['last_combat_cmd_at'] = 0.0
    leader_broadcast_stop_fight(reason or 'Ghost dừng')


def _soft_hold_autoghost(reason):
    """Soft-stop Ghost/Auto PK cast — memory only, never inject/stop_bot."""
    ghost = find_autoghost()
    if ghost is None:
        return False
    hook = getattr(ghost, 'party_sync_hold_fight', None)
    if callable(hook):
        return bool(hook(reason=reason, source=NAME))
    clear = getattr(ghost, 'party_sync_clear_target', None)
    if callable(clear):
        return bool(clear(reason=reason, source=NAME))
    # Last resort: flag runtime only — do NOT pause_pvp(cancel_action) / inject.
    runtime = getattr(ghost, 'auto_pk_runtime', None)
    if isinstance(runtime, dict):
        runtime['party_hold_fight'] = True
        runtime['party_sync_uid'] = 0
        runtime['requested'] = 0
        return True
    return False


def follower_clear_target(reason):
    """HARD: phụ bỏ target Ghost/Auto PK (soft, no inject)."""
    cleared = False
    try:
        cleared = bool(_soft_hold_autoghost(reason))
    except Exception as error:
        set_status('Clear target lỗi: %s' % error)
        return False
    with lock:
        state['last_uid'] = 0
        state['fight_held'] = True
    set_status('[%s] Phụ soft-clear target (no inject).' % reason)
    return cleared


def follower_stop_fight(reason):
    """Soft-stop đánh ngay, giữ Auto PK armed — no inject / stop_bot (tránh DC)."""
    try:
        _soft_hold_autoghost(reason)
    except Exception as error:
        set_status('Stop fight lỗi: %s' % error)
        return False
    with lock:
        state['fight_held'] = True
        state['last_uid'] = 0
    set_status('[%s] Phụ đã yêu cầu bỏ đánh để theo leader.' % reason)
    return True


def follower_stop_and_follow(reason):
    """Chủ F4/dừng: soft-stop rồi ngay lập tức Trace (job nick OK)."""
    follower_stop_fight(reason)
    # Trace ngay — không chờ lượt đo khoảng cách; giữ Auto PK armed.
    mark_follow_grace(3.0)  # ngắn: tránh double-clear từ distance tick
    return follower_ensure_trace(reason)


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
        if math.isfinite(x) and math.isfinite(y) and (x or y):
            return {'x': x, 'y': y, 'name': name, 'region': member.get('region')}
    return None


def leader_distance(leader, me):
    if not leader:
        return None
    try:
        if (leader.get('region') not in (None, 0, '0') and me.get('region') is not None
                and int(leader['region']) != int(me['region'])):
            return None
        mx, my = float(me['x']), float(me['y'])
    except (KeyError, TypeError, ValueError):
        return None
    if not (math.isfinite(mx) and math.isfinite(my)):
        return None
    return math.hypot(leader['x'] - mx, leader['y'] - my)


def move_toward_leader():
    from phBot import move_to
    me = get_position() or {}
    leader = leader_xy_from_party()
    distance = leader_distance(leader, me)
    if distance is None:
        return False
    if distance == 0:
        return True
    return move_to(leader['x'], leader['y'], float(me.get('z') or 0)) is not False


def _name_is_configured_leader(name):
    needle = _strip_job_star(name).casefold()
    if not needle:
        return False
    char_name, job_name, display = parse_leader_identity(configured_leader())
    return needle in identity_tokens(char_name, job_name, display)


def safe_start_trace(char_name, reason=''):
    """start_trace with CharName or job nick (AG_He / *AG_He OK). Soft-fail."""
    name = _strip_job_star(char_name)
    if not name:
        set_status('[%s] Bỏ trace — tên trống.' % (reason or 'trace'))
        return False
    # Phụ / configured leader job nick: always allow start_trace('AG_He').
    # Only block accidental self-trace when role is Chủ and name is self.
    if (role_index() != ROLE_FOLLOWER
            and not _name_is_configured_leader(name)
            and _is_self_identity(name, name)):
        set_status(
            '[%s] Bỏ trace — %r là chính mình (không phải chủ đã lưu).'
            % (reason or 'trace', name))
        return False
    try:
        ok = start_trace(name)
    except Exception as error:
        set_status('[%s] start_trace lỗi: %s (name=%r) — giữ Auto PK, không DC retry.'
                   % (reason or 'trace', error, name))
        return False
    if ok is False:
        set_status('[%s] start_trace từ chối name=%r — giữ Auto PK (không spam).'
                   % (reason or 'trace', name))
        return False
    return True


def follower_ensure_trace(reason):
    tracing = False
    moved = False
    try:
        leader_char = resolve_trace_char_name()
        tracing = safe_start_trace(leader_char, reason)
        if tracing:
            set_status('[%s] Trace theo leader %s.' % (reason, leader_char))
        else:
            moved = move_toward_leader()
            if moved:
                set_status('[%s] Đang chạy theo tọa độ leader %s.' % (reason, leader_char))
    except (ImportError, KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        set_status('[%s] Chưa theo được leader: %s' % (reason, error))
    with lock:
        state['following'] = True
        state['follow_by_position'] = not tracing
        state['last_follow_nudge_at'] = monotonic()
    return tracing or moved


def read_settings():
    return {
        'plugin_version': VERSION,
        'enabled': QtBind.isChecked(gui, enabled_box),
        'role': role_index(),
        'leader_name': (QtBind.text(gui, leader_field) or '').strip(),
        'ghost_page': ghost_page(),
        'sync_target': QtBind.isChecked(gui, sync_box),
        'broadcast_select': QtBind.isChecked(gui, broadcast_box),
        'arm_auto_pk': QtBind.isChecked(gui, arm_box),
    }


def settings_summary(data):
    data = data or {}
    role = 'Chủ' if int(data.get('role', 0) or 0) == ROLE_LEADER else 'Phụ'
    return (
        'Bật=%s · Sync=%s · ksAutoPK=%s · chat ks#=%s · %s · F=%s · Leader=%r'
        % (
            'ON' if data.get('enabled') else 'OFF',
            'ON' if data.get('sync_target', True) else 'OFF',
            'ON' if data.get('arm_auto_pk', True) else 'OFF',
            'ON' if data.get('broadcast_select', True) else 'OFF',
            role,
            data.get('ghost_page') or 'F2',
            data.get('leader_name') or '',
        )
    )


def apply_settings(data):
    """Restore every persisted control; quiet so checkbox hooks do not fight restore."""
    global _ui_applying
    data = data or {}
    enabled = _truthy_flag(data.get('enabled', False))
    role = ROLE_LEADER if int(data.get('role', 0) or 0) == ROLE_LEADER else ROLE_FOLLOWER
    leader_name = str(data.get('leader_name') or '').strip()
    page = str(data.get('ghost_page') or 'F2').strip().upper()
    if page not in GHOST_PAGES:
        page = 'F2'
    sync_target = _truthy_flag(data.get('sync_target', True))
    broadcast_select = _truthy_flag(data.get('broadcast_select', True))
    arm_auto_pk = _truthy_flag(data.get('arm_auto_pk', True))
    _ui_applying = True
    try:
        QtBind.setChecked(gui, enabled_box, enabled)
        QtBind.setChecked(gui, role_leader_box, role == ROLE_LEADER)
        QtBind.setChecked(gui, role_follower_box, role == ROLE_FOLLOWER)
        QtBind.setText(gui, leader_field, leader_name)
        QtBind.setText(gui, page_combo, page)
        QtBind.setChecked(gui, sync_box, sync_target)
        QtBind.setChecked(gui, broadcast_box, broadcast_select)
        QtBind.setChecked(gui, arm_box, arm_auto_pk)
    finally:
        _ui_applying = False
    with lock:
        state['enabled'] = enabled
        state['role'] = role
        state['leader_name'] = leader_name
        state['ghost_page'] = page
        state['sync_target'] = sync_target
        state['broadcast_select'] = broadcast_select
        state['arm_auto_pk'] = arm_auto_pk
    update_role_help(role)
    if enabled:
        mark_follow_grace()


def btn_save():
    global loaded_config_owner
    try:
        owner = config_owner()
        path = config_path(owner)
        data = read_settings()
        if data['role'] == ROLE_LEADER and not data['leader_name']:
            me = self_display()
            if me:
                data['leader_name'] = me
                QtBind.setText(gui, leader_field, me)
                data = read_settings()
        if data.get('leader_name'):
            data['leader_name'] = require_full_leader(
                data.get('leader_name'), context='Chủ (Leader)')
            # Job nick chủ (AG_He / *AG_He) is valid — do not reject on Lưu.
            QtBind.setText(gui, leader_field, data['leader_name'])
        data['plugin_version'] = VERSION
        data['config_owner'] = list(owner)
        import os
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            staged = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2)
        try:
            os.replace(staged, path)
        finally:
            if staged.exists():
                staged.unlink()
        loaded_config_owner = owner
        apply_settings(data)
        set_status('Đã lưu %s · %s' % (path.name, settings_summary(data)), 'Đã lưu')
        _log('Lưu cấu hình: %s' % settings_summary(data))
    except (OSError, ValueError, TypeError) as error:
        set_status('Chưa lưu: %s' % error)


def load_settings(quiet=False):
    global loaded_config_owner
    owner = config_owner()
    if owner is None:
        if not quiet:
            set_status('Chờ phBot nhận diện nhân vật để nạp cấu hình.')
        return None
    loaded_config_owner = owner
    try:
        path = config_path(owner)
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('JSON không hợp lệ.')
        if data.get('config_owner') != list(owner):
            raise ValueError('Cấu hình không thuộc nhân vật hiện tại.')
        # Normalize legacy keys
        if 'sync_target' not in data and 'sync' in data:
            data['sync_target'] = data.get('sync')
        if 'arm_auto_pk' not in data and 'arm' in data:
            data['arm_auto_pk'] = data.get('arm')
        apply_settings(data)
        raw = str(data.get('leader_name') or '').strip()
        if raw:
            try:
                full = require_full_leader(raw, context='Leader đã lưu')
                if full != raw:
                    QtBind.setText(gui, leader_field, full)
                    data['leader_name'] = full
                    with lock:
                        state['leader_name'] = full
            except ValueError as error:
                if not quiet:
                    set_status('Đã tải %s · nhưng %s — bấm Lấy tên lại rồi Lưu.'
                               % (path.name, error))
                return data
        if not quiet:
            set_status('Đã tải %s · %s' % (path.name, settings_summary(data)), 'Đã tải')
            _log('Tải cấu hình: %s' % settings_summary(data))
        return data
    except FileNotFoundError:
        apply_settings({})
        if not quiet:
            set_status('Nhân vật này chưa có bản lưu riêng. Chọn Chủ/Phụ, bật plugin rồi bấm Lưu.')
        return None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        apply_settings({})
        if not quiet:
            set_status('Chưa tải: %s' % error)
        return None


def btn_load():
    load_settings(quiet=False)


def btn_self():
    name, job = self_name(), self_job_name()
    me = format_leader_display(name, job)
    if not me:
        set_status(
            'Chưa đọc được CharName (name=%r job=%r). Vào game rồi bấm lại.'
            % (name, job))
        return
    QtBind.setText(gui, leader_field, me)
    set_role(ROLE_LEADER)
    set_status('Đã điền tên mình %r · vai trò Chủ. Bấm Lưu cấu hình.' % me)


def btn_party_master():
    """Phụ: điền chủ PT = prefer name else job (AG_He OK)."""
    try:
        full = party_master_display()
    except ValueError as error:
        set_status('Lấy tên chủ PT: %s' % error)
        return
    char_name, job_name, _ = parse_leader_identity(full)
    # party_master_display already refused self-by-member; job nick AG_He is valid.
    QtBind.setText(gui, leader_field, full)
    set_role(ROLE_FOLLOWER)
    mark_follow_grace()
    set_status('Đã điền chủ PT %r · name=%r job=%r · Phụ. Bấm Lưu.'
               % (full, char_name, job_name))


def btn_follow():
    if not QtBind.isChecked(gui, enabled_box):
        set_status('Bật plugin trước.')
        return
    do_follow('UI')


def btn_stop():
    do_stop_follow('UI')


def ui_enabled(checked):
    if _ui_applying:
        with lock:
            state['enabled'] = bool(checked)
        return
    with lock:
        state['enabled'] = bool(checked)
    if checked:
        mark_follow_grace()
        set_status('Đã bật.' if role_index() == ROLE_LEADER else 'Đã bật · chờ lệnh từ leader.')
    else:
        set_status('Đã tắt.')


def ui_sync(checked):
    if _ui_applying:
        with lock:
            state['sync_target'] = bool(checked)
        return
    with lock:
        state['sync_target'] = bool(checked)


def ui_broadcast(checked):
    if _ui_applying:
        with lock:
            state['broadcast_select'] = bool(checked)
        return
    with lock:
        state['broadcast_select'] = bool(checked)


def ui_arm(checked):
    if _ui_applying:
        with lock:
            state['arm_auto_pk'] = bool(checked)
        return
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
    # HARD: chủ F4/dừng → phụ dừng cast + trace theo chủ ngay.
    if is_stop_fight_cmd(norm):
        if not i_am_leader():
            follower_stop_and_follow('chat dungdanh / F4')
        return
    # HARD: chủ clear target → phụ clear.
    if is_clear_target_cmd(norm):
        if not i_am_leader():
            follower_stop_and_follow('chủ bỏ mục tiêu')
        return

    command = text.split('#')
    if command[0].casefold() == 'ksgo':
        if (len(command) != 3 or command[1].upper() not in GHOST_PAGES
                or not command[2].isdigit() or i_am_leader()
                or not QtBind.isChecked(gui, sync_box)):
            return
        uid = int(command[2])
        if not 0 < uid <= 0xffffffff:
            return
        page = ghost_page()
        ghost = find_autoghost()
        if not (callable(getattr(ghost, 'party_sync_has_target', None))
                and ghost.party_sync_has_target(uid)
                and (getattr(ghost, 'auto_pk_runtime', None) or {}).get('page') == page):
            with lock:
                was_following = state['following']
            if was_following:
                try:
                    stop_trace()
                except (OSError, RuntimeError, ValueError) as error:
                    set_status('Chưa tạm dừng được trace: %s' % error)
                    return
            with lock:
                state['following'] = False
                state['follow_by_position'] = False
            if not arm_auto_pk(prefer_uid=uid):
                if was_following:
                    follower_ensure_trace('chưa bật được Ghost')
                return
        if inject_select(uid, 'lệnh %s của leader' % page):
            with lock:
                state['selected_uid'] = uid
        return

    uid = parse_ks_uid(text)
    if uid and QtBind.isChecked(gui, sync_box) and not i_am_leader():
        with lock:
            was_fighting_other = bool(state['last_uid'] and state['last_uid'] != uid)
            state['selected_uid'] = uid
        if was_fighting_other:
            follower_stop_and_follow('chủ chọn mục tiêu khác · chờ F1/F2')
        else:
            set_status('Đã ghi nhớ UID %d · chờ chủ bấm F1/F2.' % uid)
        return

    if is_stop_cmd(norm):
        if not i_am_leader():
            do_stop_follow('chat')
        return
    if is_follow_cmd(norm):
        if not i_am_leader():
            do_follow('chat ks')
        return


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
    """Resume following after AutoGhost releases the combat target."""
    owner = config_owner()
    if owner is not None and owner != loaded_config_owner:
        load_settings(quiet=False)
    if not QtBind.isChecked(gui, enabled_box):
        return
    if i_am_leader():
        return
    with lock:
        now = monotonic()
        if (now - state['follow_check_at']) < 0.45:
            return
        state['follow_check_at'] = now
    try:
        ghost = find_autoghost()
        runtime = getattr(ghost, 'auto_pk_runtime', None) or {}
        with lock:
            last_uid = state['last_uid']
            held = state['fight_held']
        if last_uid and not held and runtime.get('party_hold_fight'):
            follower_stop_and_follow('AutoGhost đã nhả mục tiêu')
            return
        with lock:
            follow_position = (state['following'] and state['follow_by_position']
                               and now - state['last_follow_nudge_at'] >= 1.0)
            if follow_position:
                state['last_follow_nudge_at'] = now
        if follow_position:
            move_toward_leader()

    except Exception as error:
        _log('follow check: %s' % error)


def joined_game():
    data = load_settings(quiet=False)
    if role_index() == ROLE_LEADER and not (QtBind.text(gui, leader_field) or '').strip():
        me = self_display() or self_name()
        if me:
            QtBind.setText(gui, leader_field, me)
    if data and data.get('enabled'):
        mark_follow_grace()
        _log('joined_game: đã auto-bật từ cấu hình đã lưu.')


def teleported():
    pass


# Auto-restore on plugin reload (before joined_game).
try:
    _boot = load_settings(quiet=True)
    if _boot is not None:
        set_status('Nạp v%s · restored %s' % (VERSION, settings_summary(_boot)), 'Đã tải')
    else:
        _log('Nạp v%s · chờ nhân vật hoặc bản lưu riêng.' % VERSION)
except Exception as _boot_error:
    _log('Nạp v%s · restore lỗi: %s' % (VERSION, _boot_error))

log('[%s] Đã nạp v%s. F1/F2/3 → ksgo (debounce) · Prefer Ghost cast · soft-stop. Cấu hình theo máy chủ + nhân vật.'
    % (NAME, VERSION))
