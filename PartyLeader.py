# -*- coding: utf-8 -*-
"""PartyLeader — PT theo chủ (phBot Stable).

Changelog:
- v1.0.12: Prefer same UID debounce ≥2.0s (stop 3s Prefer re-log storm).
- v1.0.11: Prefer backoff ≥1.5s after AG B074 refuse same UID (stop re-arm spam).
- v1.0.10: Trace AG_He/*AG_He hard-allow; >10m clear prefer+chase; persist
  restore on load/joined/deferred; label “tên Leader cần theo”; AG≥1.8.70.
- v1.0.9: Trace AG_He luôn OK (Phụ role authoritative); AG≥1.8.69 prefer cast.
- v1.0.8: soft-stop >10m (no inject/stop_bot DC); persist ticks 1.0.7.
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

import json
import math
import struct
import sys
from pathlib import Path
from threading import RLock, Timer
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
VERSION = '1.0.12'
CONFIG_NAME = 'PartyLeader'

CMD_FOLLOW = ('ks',)
CMD_STOP = ('ks off', 'ksoff', 'ks dung', 'dung', 'stopks', 'notrace')
CMD_STOP_FIGHT = ('dungdanh', 'stopfight', 'ks hold', 'hold')
CMD_CLEAR_TARGET = ('ks clear', 'clear', 'cleartarget', 'bo target', 'bỏ target', 'ks#0')

ROLE_FOLLOWER = 0
ROLE_LEADER = 1
# Nhóm Ghost / Auto PK trên phụ (khớp AutoGhost PVP_EDIT_PAGES)
GHOST_PAGES = ('F1', 'F2', 'F3')
# HARD: phụ dừng đánh + trace khi chủ xa hơn khoảng này (mét) — mặc định 10.
LEADER_FOLLOW_DISTANCE = 10.0
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
    'last_b070_uid': 0,
    'last_b070_at': 0.0,
    'last_inject_log_at': 0.0,
    'follow_grace_until': 0.0,
    'last_trace_fail_at': 0.0,
    'last_trace_fail_msg': '',
}

_ui_applying = False  # True while restore — skip checkbox side-effects
_persist_synced = False

QtBind.createLabel(gui, '%s v%s — PT theo Leader' % (NAME, VERSION), 10, 8)
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

QtBind.createLabel(gui, 'tên Leader cần theo', 240, 88)
leader_field = QtBind.createLineEdit(gui, '', 240, 106, 160, 22)
QtBind.createButton(gui, 'btn_self', 'Lấy tên mình', 410, 104)
QtBind.createButton(gui, 'btn_party_master', 'Lấy tên chủ PT', 520, 104)

QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 10, 144)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 140, 144)
QtBind.createButton(gui, 'btn_follow', 'Thử theo Leader (trace)', 280, 144)
QtBind.createButton(gui, 'btn_stop', 'Dừng theo', 460, 144)

status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 184)
QtBind.createLabel(
    gui,
    'ks = phụ trace + Auto PK · ks off = dừng. Leader chọn/đánh → phụ cùng UID.\n'
    'HARD Phụ: chỉ UID Leader · >10m soft-stop + Trace AG_He OK · Lưu/Tải giữ ticks.\n'
    'Phụ: tick Phụ + điền tên Leader cần theo / Lấy tên chủ PT + F + Lưu.',
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


def set_role(index, from_ui=False):
    """Checkbox Chủ/Phụ — exclusive. from_ui tránh đệ quy khi click."""
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
    if index == ROLE_FOLLOWER and not was:
        mark_follow_grace()


def ui_role_leader(checked):
    if _ui_applying:
        return
    if checked:
        set_role(ROLE_LEADER, from_ui=True)
        set_status('Vai trò: Chủ')
    elif not QtBind.isChecked(gui, role_follower_box):
        # Không cho bỏ cả hai — mặc định Phụ.
        set_role(ROLE_FOLLOWER, from_ui=True)


def ui_role_phu(checked):
    if _ui_applying:
        return
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
    if ok:
        mark_follow_grace()
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
    """Prefer AutoGhost direct UID + Ghost. Never 7045 inject storm."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return False
    if uid <= 0:
        return False
    with lock:
        now = monotonic()
        # Strong debounce — same Prefer UID at most once / 2.0s (stop 3s log storm).
        if uid == state['last_uid'] and (now - state['last_select_at']) < 2.0:
            return True
        # AG reported B074 refuse → back off Prefer spam for that UID.
        if (uid == int(state.get('refuse_uid') or 0)
                and now < float(state.get('refuse_backoff_until') or 0)):
            return True
        state['last_uid'] = uid
        state['last_select_at'] = now
        state['fight_held'] = False
        quiet = (now - state.get('last_inject_log_at', 0)) < 5.0
        if not quiet:
            state['last_inject_log_at'] = now

    ghost = find_autoghost()
    if ghost is not None:
        # Mirror AG B074 backoff so Prefer does not re-arm forever.
        try:
            runtime = getattr(ghost, 'auto_pk_runtime', None)
            if isinstance(runtime, dict):
                b074_until = float(runtime.get('party_b074_backoff_until') or 0)
                b074_uid = int(runtime.get('party_b074_uid') or 0)
                if uid == b074_uid and monotonic() < b074_until:
                    with lock:
                        state['refuse_uid'] = uid
                        state['refuse_backoff_until'] = b074_until
                    return True
        except Exception:
            pass
        select_hook = getattr(ghost, 'party_sync_select_uid', None)
        if callable(select_hook):
            try:
                ok = bool(select_hook(uid, source='%s:%s' % (NAME, reason)))
                # After select, if AG set B074 backoff — mirror it locally.
                try:
                    runtime = getattr(ghost, 'auto_pk_runtime', None)
                    if isinstance(runtime, dict):
                        b074_until = float(runtime.get('party_b074_backoff_until') or 0)
                        b074_uid = int(runtime.get('party_b074_uid') or 0)
                        if uid == b074_uid and monotonic() < b074_until:
                            with lock:
                                state['refuse_uid'] = uid
                                state['refuse_backoff_until'] = b074_until
                except Exception:
                    pass
                # F4 may have stopped Auto PK — re-arm then prefer again.
                # Never re-arm during B074 refuse backoff.
                if not ok:
                    if uid == int(state.get('refuse_uid') or 0) and monotonic() < float(
                            state.get('refuse_backoff_until') or 0):
                        return True
                    arm_ok = arm_auto_pk(prefer_uid=uid)
                    ok = bool(select_hook(uid, source='%s:%s:rearm' % (NAME, reason))) if arm_ok else False
                if not quiet:
                    set_status('Prefer UID=%d (%s) · AG hook=%r (no 7045)' % (uid, reason, ok))
                return bool(ok)
            except Exception as error:
                _log('party_sync_select_uid: %s' % error)
        # Fallback: re-arm + set prefer dict fields without 7045.
        try:
            runtime = getattr(ghost, 'auto_pk_runtime', None)
            if isinstance(runtime, dict):
                b074_until = float(runtime.get('party_b074_backoff_until') or 0)
                b074_uid = int(runtime.get('party_b074_uid') or 0)
                if uid == b074_uid and monotonic() < b074_until:
                    return True
            if not getattr(ghost, 'auto_pk_running', False):
                arm_auto_pk(prefer_uid=uid)
            runtime = getattr(ghost, 'auto_pk_runtime', None)
            if isinstance(runtime, dict):
                runtime['party_sync_uid'] = uid
                runtime['party_lock'] = True
                runtime['party_follow_mode'] = True
                runtime['party_hold_fight'] = False
                runtime['requested'] = uid
                if not quiet:
                    set_status('Prefer UID=%d gắn runtime (no 7045)' % uid)
                return True
        except Exception:
            pass
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
    mark_follow_grace()
    ok = safe_start_trace(leader_char, reason)
    with lock:
        state['following'] = bool(ok)
    set_status('[%s] Trace → %r (Leader=%r) · OK=%r' % (
        reason, leader_char, full, ok))
    arm_auto_pk(prefer_uid=0)
    mark_follow_grace()
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
        set_status('[%s] Chủ broadcast dungdanh → phụ stop + trace.' % reason)
        return True
    return False


def on_leader_ghost_stop(reason=None):
    """Hook từ AutoGhost (F4 / pause Ghost) trên máy chủ."""
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
    set_status('[%s] Phụ soft-stop đánh (no inject · chờ chủ).' % reason)
    return True


def follower_stop_and_follow(reason):
    """Chủ F4/dừng: soft-stop rồi ngay lập tức Trace (job nick OK)."""
    follower_stop_fight(reason)
    # Trace ngay — không chờ >10m tick; giữ Auto PK armed.
    mark_follow_grace(3.0)  # ngắn: tránh double-clear từ distance tick
    ok = follower_ensure_trace(reason)
    if ok:
        set_status('[%s] Đã soft-stop + Trace theo chủ.' % reason)
    return ok


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


def _name_is_configured_leader(name):
    needle = _strip_job_star(name).casefold()
    if not needle:
        return False
    char_name, job_name, display = parse_leader_identity(configured_leader())
    return needle in identity_tokens(char_name, job_name, display)


def safe_start_trace(char_name, reason=''):
    """start_trace with CharName or job nick AG_He/*AG_He. Soft-fail, no spam."""
    raw = str(char_name or '').strip()
    name = _strip_job_star(raw)
    if not name:
        set_status('[%s] Bỏ trace — tên trống.' % (reason or 'trace'))
        return False
    # Always allow configured Leader / Phụ job nick — never self-reject AG_He.
    candidates = []
    for c in (raw, name, '*' + name):
        c = str(c or '').strip()
        if c and c not in candidates:
            candidates.append(c)
    # Also try configured field variants.
    cfg = configured_leader()
    c_name, c_job, _ = parse_leader_identity(cfg)
    for c in (c_name, _strip_job_star(c_job), c_job,
              ('*' + _strip_job_star(c_job)) if c_job else ''):
        c = str(c or '').strip()
        if c and c not in candidates:
            candidates.append(c)
    last_error = None
    for candidate in candidates:
        try:
            ok = start_trace(candidate)
        except Exception as error:
            last_error = error
            continue
        if ok is False:
            continue
        return True
    # Debounce reject spam (distance tick every 2s).
    msg = ('start_trace từ chối %r (thử %s)%s'
           % (name, '/'.join(candidates),
              (': %s' % last_error) if last_error else ''))
    with lock:
        now = monotonic()
        prev = state.get('last_trace_fail_msg') or ''
        last_at = float(state.get('last_trace_fail_at') or 0)
        quiet = (msg == prev and (now - last_at) < 5.0)
        state['last_trace_fail_msg'] = msg
        state['last_trace_fail_at'] = now
    if not quiet:
        set_status('[%s] %s — giữ Auto PK, không spam.' % (reason or 'trace', msg))
    return False


def follower_ensure_trace(reason):
    try:
        leader_char = resolve_trace_char_name()
    except ValueError as error:
        # Fallback: raw Leader field / AG_He job nick.
        leader_char = _strip_job_star(configured_leader()) or configured_leader()
        if not leader_char:
            set_status('[%s] %s' % (reason, error))
            return False
    ok = safe_start_trace(leader_char, reason)
    with lock:
        state['following'] = bool(ok)
    if ok:
        set_status('[%s] Trace → %r · OK' % (reason, leader_char))
    return bool(ok)


def follower_check_leader_distance():
    """HARD: Leader >10m → clear prefer + soft-stop + Trace/chase."""
    if i_am_leader() or not QtBind.isChecked(gui, enabled_box):
        return
    if in_follow_grace():
        return
    with lock:
        following = state['following'] or state['armed_auto_pk']
    if not following:
        return
    dist = distance_to_leader()
    if dist is None:
        return
    if dist <= LEADER_FOLLOW_DISTANCE:
        return
    with lock:
        now = monotonic()
        if (now - state['last_follow_nudge_at']) < 2.0:
            return
        state['last_follow_nudge_at'] = now
        state['last_uid'] = 0
        state['fight_held'] = True
    # Clear prefer UID + soft-stop attack, then chase Leader (AG_He OK).
    follower_stop_fight('Leader cách %.1fm (>%.0fm)' % (dist, LEADER_FOLLOW_DISTANCE))
    follower_ensure_trace('Leader xa %.1fm' % dist)


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
    enabled = bool(data.get('enabled'))
    role = ROLE_LEADER if int(data.get('role', 0) or 0) == ROLE_LEADER else ROLE_FOLLOWER
    leader_name = str(data.get('leader_name') or '').strip()
    page = str(data.get('ghost_page') or 'F2').strip().upper()
    if page not in GHOST_PAGES:
        page = 'F2'
    sync_target = bool(data.get('sync_target', True))
    broadcast_select = bool(data.get('broadcast_select', True))
    arm_auto_pk = bool(data.get('arm_auto_pk', True))
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
        # Re-assert after QtBind may async-flip exclusive role boxes.
        QtBind.setChecked(gui, role_leader_box, role == ROLE_LEADER)
        QtBind.setChecked(gui, role_follower_box, role == ROLE_FOLLOWER)
        QtBind.setChecked(gui, enabled_box, enabled)
        QtBind.setChecked(gui, sync_box, sync_target)
        QtBind.setChecked(gui, broadcast_box, broadcast_select)
        QtBind.setChecked(gui, arm_box, arm_auto_pk)
        QtBind.setText(gui, page_combo, page)
        QtBind.setText(gui, leader_field, leader_name)
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
    if enabled:
        mark_follow_grace()


def btn_save():
    try:
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
        path = config_path()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        apply_settings(data)
        set_status('Đã lưu %s · %s' % (path.name, settings_summary(data)))
        _log('Lưu cấu hình: %s' % settings_summary(data))
    except (OSError, ValueError, TypeError) as error:
        set_status('Chưa lưu: %s' % error)


def load_settings(quiet=False):
    """Load PartyLeader.json and apply all checkboxes / fields / enable."""
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('JSON không hợp lệ.')
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
            set_status('Đã tải %s · %s' % (path.name, settings_summary(data)))
            _log('Tải cấu hình: %s' % settings_summary(data))
        return data
    except FileNotFoundError:
        if not quiet:
            set_status('Chưa có file — tick cấu hình rồi bấm Lưu.')
        return None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
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
        set_status('Đã bật · grace %.0fs trước luật >%.0fm.' % (
            FOLLOW_DISTANCE_GRACE, LEADER_FOLLOW_DISTANCE))
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
            now = monotonic()
            # Debounce B070 spam (mỗi cast của chủ).
            if (target_uid == state.get('last_b070_uid')
                    and (now - state.get('last_b070_at', 0)) < 1.2):
                return True
            state['last_b070_uid'] = target_uid
            state['last_b070_at'] = now
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


def _ensure_persist_ui():
    """Re-apply saved ticks if UI drifted after plugin reload."""
    global _persist_synced, _ui_applying
    path = config_path()
    if not path.is_file():
        _persist_synced = True
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    want = {
        'enabled': bool(data.get('enabled')),
        'sync': bool(data.get('sync_target', data.get('sync', True))),
        'arm': bool(data.get('arm_auto_pk', data.get('arm', True))),
        'broadcast': bool(data.get('broadcast_select', True)),
        'role': ROLE_LEADER if int(data.get('role', 0) or 0) == ROLE_LEADER else ROLE_FOLLOWER,
        'page': str(data.get('ghost_page') or 'F2').strip().upper(),
        'leader': str(data.get('leader_name') or '').strip(),
    }
    if want['page'] not in GHOST_PAGES:
        want['page'] = 'F2'
    cur_enabled = QtBind.isChecked(gui, enabled_box)
    cur_sync = QtBind.isChecked(gui, sync_box)
    cur_arm = QtBind.isChecked(gui, arm_box)
    cur_broadcast = QtBind.isChecked(gui, broadcast_box)
    cur_role = role_index()
    cur_page = (QtBind.text(gui, page_combo) or '').strip().upper()
    cur_leader = (QtBind.text(gui, leader_field) or '').strip()
    mismatched = (
        cur_enabled != want['enabled']
        or cur_sync != want['sync']
        or cur_arm != want['arm']
        or cur_broadcast != want['broadcast']
        or cur_role != want['role']
        or cur_page != want['page']
        or cur_leader != want['leader']
    )
    if mismatched:
        apply_settings({
            'enabled': want['enabled'],
            'sync_target': want['sync'],
            'arm_auto_pk': want['arm'],
            'broadcast_select': want['broadcast'],
            'role': want['role'],
            'ghost_page': want['page'],
            'leader_name': want['leader'],
        })
        _log('persist re-sync UI ← %s' % settings_summary({
            'enabled': want['enabled'],
            'sync_target': want['sync'],
            'arm_auto_pk': want['arm'],
            'broadcast_select': want['broadcast'],
            'role': want['role'],
            'ghost_page': want['page'],
            'leader_name': want['leader'],
        }))
    _persist_synced = True
    return data


def event_loop():
    """Phụ: Leader >10m → dừng đánh + trace. First ticks re-sync persist UI."""
    global _persist_synced
    if not _persist_synced:
        try:
            _ensure_persist_ui()
        except Exception as error:
            _persist_synced = True
            _log('persist sync: %s' % error)
    # Prefer state.enabled if UI checkbox failed to restore.
    enabled = QtBind.isChecked(gui, enabled_box)
    with lock:
        if state.get('enabled') and not enabled:
            enabled = True
    if not enabled:
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
    global _persist_synced
    _persist_synced = False
    data = load_settings(quiet=False)
    _ensure_persist_ui()
    if role_index() == ROLE_LEADER and not (QtBind.text(gui, leader_field) or '').strip():
        me = self_display() or self_name()
        if me:
            QtBind.setText(gui, leader_field, me)
    if data and data.get('enabled'):
        mark_follow_grace()
        _log('joined_game: đã auto-bật từ cấu hình đã lưu.')


def plugin_load():
    """phBot hook alias — restore ticks on plugin reload."""
    global _persist_synced
    _persist_synced = False
    data = load_settings(quiet=False)
    _ensure_persist_ui()
    return data


def teleported():
    pass


def _deferred_persist_restore():
    try:
        _ensure_persist_ui()
    except Exception as error:
        _log('deferred persist: %s' % error)


# Auto-restore on plugin reload (before joined_game) + deferred re-assert.
try:
    _boot = load_settings(quiet=True)
    if _boot is not None:
        _log('Nạp v%s · restored %s · file=%s'
             % (VERSION, settings_summary(_boot), config_path()))
    else:
        _log('Nạp v%s · chưa có PartyLeader.json — tick rồi Lưu.' % VERSION)
except Exception as _boot_error:
    _log('Nạp v%s · restore lỗi: %s' % (VERSION, _boot_error))

for _delay in (0.5, 1.5, 3.0):
    try:
        _t = Timer(_delay, _deferred_persist_restore)
        _t.daemon = True
        _t.start()
    except Exception:
        pass

log('[%s] Đã nạp v%s. Persist ticks · Trace AG_He · >10m chase · AG≥1.8.70.'
    % (NAME, VERSION))
