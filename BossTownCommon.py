# -*- coding: utf-8 -*-
"""BossTownCommon — shared engine for BossTown1/2/3 drop-in plugins.

Library only (no QtBind tab). Load alongside BossTownN.py in Plugins.

Flow per town file:
1. Personal TP/scroll + walk to that file's start town XYZ (NO party TP).
2. On arrive → if Chủ PT: party chat ks#UID then ksgo#F#UID (PartyLeader/AutoGhost).
3. If no boss → cycle next town (1→2→3→1) with same personal TP + walk.

Attack command (exact):
  ks#<UID>          — lock target for party
  ksgo#F1#<UID>     — attack / ARM (default page F1; UI đổi được F1|F2|F3)
  dungdanh          — stop fight (chat / nút)
"""

from __future__ import print_function

import hashlib
import json
import math
import os
import struct
import sys
import tempfile
from pathlib import Path
from threading import RLock
from time import monotonic

import QtBind
from phBot import (
    get_character_data,
    get_config_dir,
    get_monsters,
    get_party,
    get_position,
    get_status,
    inject_joymax,
    log,
    move_to,
    set_training_position,
    set_training_radius,
    start_bot,
    stop_bot,
)

try:
    from phBot import reverse_return as _reverse_return
except ImportError:
    _reverse_return = None

try:
    from phBot import use_return_scroll as _use_return_scroll
except ImportError:
    _use_return_scroll = None

try:
    from phBot import stop_trace as _stop_trace
except ImportError:
    _stop_trace = None

try:
    import phBotChat
except ImportError:
    phBotChat = None

# reverse_return type 3 = zone cá nhân. KHÔNG type 2 (party).
REV_ZONE = 3

DEFAULT_RADIUS = 50.0
DEFAULT_ARRIVE_M = 12.0
DEFAULT_DELAY_S = 8.0
DEFAULT_MOVE_NUDGE_S = 1.2
DEFAULT_NO_BOSS_S = 60.0
DEFAULT_ATTACK_PAGE = 'F1'
RETURN_WAIT_S = 45.0
ATTACK_RESELECT_S = 4.0
KSGO_DEBOUNCE_S = 2.0

PLACEHOLDER_TOWNS = (
    {'name': 'Thành 1', 'region': 0, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'tp_dest': ''},
    {'name': 'Thành 2', 'region': 0, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'tp_dest': ''},
    {'name': 'Thành 3', 'region': 0, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'tp_dest': ''},
)

ATTACK_PAGES = ('F1', 'F2', 'F3')

CMD_GO = ('san', 'di san', 'bosgo', 'bossgo', 'go', 'hunt', 'di boss', 'bat dau')
CMD_STOP = ('dung', 'stop', 'bossoff', 'huy san', 'huy', 'stopboss')
CMD_STOP_FIGHT = ('dungdanh', 'stopfight', 'ks hold', 'hold')
CMD_NEXT = ('next', 'tiep', 'thanh ke', 'town next', 'nexttown')


def _fold(text):
    raw = str(text or '').strip().casefold()
    table = str.maketrans({
        'à': 'a', 'á': 'a', 'ả': 'a', 'ã': 'a', 'ạ': 'a',
        'ă': 'a', 'ằ': 'a', 'ắ': 'a', 'ẳ': 'a', 'ẵ': 'a', 'ặ': 'a',
        'â': 'a', 'ầ': 'a', 'ấ': 'a', 'ẩ': 'a', 'ẫ': 'a', 'ậ': 'a',
        'è': 'e', 'é': 'e', 'ẻ': 'e', 'ẽ': 'e', 'ẹ': 'e',
        'ê': 'e', 'ề': 'e', 'ế': 'e', 'ể': 'e', 'ễ': 'e', 'ệ': 'e',
        'ì': 'i', 'í': 'i', 'ỉ': 'i', 'ĩ': 'i', 'ị': 'i',
        'ò': 'o', 'ó': 'o', 'ỏ': 'o', 'õ': 'o', 'ọ': 'o',
        'ô': 'o', 'ồ': 'o', 'ố': 'o', 'ổ': 'o', 'ỗ': 'o', 'ộ': 'o',
        'ơ': 'o', 'ờ': 'o', 'ớ': 'o', 'ở': 'o', 'ỡ': 'o', 'ợ': 'o',
        'ù': 'u', 'ú': 'u', 'ủ': 'u', 'ũ': 'u', 'ụ': 'u',
        'ư': 'u', 'ừ': 'u', 'ứ': 'u', 'ử': 'u', 'ữ': 'u', 'ự': 'u',
        'ỳ': 'y', 'ý': 'y', 'ỷ': 'y', 'ỹ': 'y', 'ỵ': 'y',
        'đ': 'd',
    })
    return ' '.join(raw.translate(table).split())


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


def boot(module_name, start_town, name='BossTown', version='1.0.0'):
    """Install GUI + hooks onto the calling plugin module (BossTown1/2/3)."""
    mod = sys.modules[module_name]
    start_town = int(start_town) % 3
    config_name = name

    gui = QtBind.init(module_name, '%s v%s' % (name, version))
    lock = RLock()
    ui_applying = {'v': False}
    loaded_config_owner = {'v': None}

    state = {
        'enabled': False,
        'phase': 'idle',  # idle | teleport | wait | walking | search | attack
        'town_index': -1,
        'started_at': 0.0,
        'teleport_at': 0.0,
        'wait_until': 0.0,
        'last_nudge_at': 0.0,
        'search_at': 0.0,
        'attack_uid': 0,
        'last_attack_at': 0.0,
        'last_ksgo_at': 0.0,
        'last_ksgo_key': '',
        'last_status_at': 0.0,
        'is_leader': True,
    }

    QtBind.createLabel(
        gui,
        '%s v%s — bắt đầu Thành %d · PT attack · không Boss → vòng 1→2→3'
        % (name, version, start_town + 1),
        10, 8)
    enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật săn', 10, 28)
    leader_box = QtBind.createCheckBox(
        gui, 'ui_leader', 'Chủ PT (gửi ksgo)', 110, 28)
    QtBind.setChecked(gui, leader_box, True)

    QtBind.createLabel(gui, 'Tên Boss (;). Trống = quái gần XYZ', 280, 28)
    boss_names_field = QtBind.createLineEdit(gui, '', 280, 46, 280, 22)

    QtBind.createLabel(gui, 'Lệnh đánh PT', 10, 52)
    page_combo = QtBind.createCombobox(gui, 100, 50, 70, 22)
    for _p in ATTACK_PAGES:
        QtBind.append(gui, page_combo, _p)
    QtBind.setText(gui, page_combo, DEFAULT_ATTACK_PAGE)

    # --- 3 towns (cần đủ XYZ để cycle) ---
    town_widgets = []
    y0 = 78
    for i in range(3):
        yy = y0 + i * 52
        tag = 'T%d' % (i + 1)
        mark = ' ★START' if i == start_town else ''
        QtBind.createLabel(gui, 'Thành %d — tên%s' % (i + 1, mark), 10, yy)
        name_w = QtBind.createLineEdit(gui, PLACEHOLDER_TOWNS[i]['name'], 130, yy - 2, 110, 22)
        QtBind.createLabel(gui, 'r/x/y/z', 250, yy)
        reg_w = QtBind.createLineEdit(gui, '0', 300, yy - 2, 45, 22)
        x_w = QtBind.createLineEdit(gui, '0', 350, yy - 2, 65, 22)
        y_w = QtBind.createLineEdit(gui, '0', 420, yy - 2, 65, 22)
        z_w = QtBind.createLineEdit(gui, '0', 490, yy - 2, 55, 22)
        QtBind.createLabel(gui, 'TP dest (zone)', 10, yy + 24)
        tp_w = QtBind.createLineEdit(gui, '', 110, yy + 22, 180, 22)
        # Button callbacks set below after helpers exist
        town_widgets.append((name_w, reg_w, x_w, y_w, z_w, tp_w, tag))

    btn_here1 = QtBind.createButton(gui, 'btn_here1', 'Lấy XY → T1', 310, 100)
    btn_here2 = QtBind.createButton(gui, 'btn_here2', 'Lấy XY → T2', 310, 152)
    btn_here3 = QtBind.createButton(gui, 'btn_here3', 'Lấy XY → T3', 310, 204)

    QtBind.createLabel(gui, 'Bán kính', 10, 244)
    radius_field = QtBind.createLineEdit(gui, str(int(DEFAULT_RADIUS)), 70, 242, 45, 22)
    QtBind.createLabel(gui, 'Tới ≤m', 125, 244)
    arrive_field = QtBind.createLineEdit(gui, str(int(DEFAULT_ARRIVE_M)), 175, 242, 45, 22)
    QtBind.createLabel(gui, 'Delay tele s', 230, 244)
    delay_field = QtBind.createLineEdit(gui, str(int(DEFAULT_DELAY_S)), 310, 242, 45, 22)
    QtBind.createLabel(gui, 'Không Boss → next (s)', 370, 244)
    noboss_field = QtBind.createLineEdit(gui, str(int(DEFAULT_NO_BOSS_S)), 510, 242, 50, 22)

    QtBind.createButton(gui, 'btn_go', 'Săn ngay (START)', 10, 276)
    QtBind.createButton(gui, 'btn_next', 'Town kế', 150, 276)
    QtBind.createButton(gui, 'btn_stop', 'Dừng', 250, 276)
    QtBind.createButton(gui, 'btn_save', 'Lưu', 340, 276)
    QtBind.createButton(gui, 'btn_load', 'Tải', 420, 276)

    status_label = QtBind.createLabel(
        gui,
        'Trạng thái: điền XYZ 3 Thành (Lấy XY) → Lưu → Bật. Placeholder 0,0,0.',
        10, 310)
    help_label = QtBind.createLabel(
        gui,
        'Chủ: tới Boss → ks#UID + ksgo#%s#UID (PartyLeader/AutoGhost Phụ nghe).\n'
        'Không Boss trong N giây → tele cá nhân + đi bộ Thành kế (1→2→3→1). KHÔNG party TP.\n'
        'Chat: san / dung / next / dungdanh · Load BossTownCommon.py + file Thành này.'
        % DEFAULT_ATTACK_PAGE,
        10, 338)

    # silence unused widget refs (buttons bound by name string)
    _ = (btn_here1, btn_here2, btn_here3, help_label)

    def _log(msg):
        log('[%s] %s' % (name, msg))

    def set_status(msg, display=None):
        QtBind.setText(gui, status_label, 'Trạng thái: %s' % (display or msg))
        _log(msg)

    def self_name():
        data = get_character_data() or {}
        for key in ('name', 'charname', 'char_name', 'character_name', 'CharName'):
            val = str(data.get(key) or '').strip()
            while val.startswith('*'):
                val = val[1:].strip()
            if val:
                return val
        return ''

    def self_player_id():
        data = get_character_data() or {}
        try:
            return int(data.get('player_id') or 0)
        except (TypeError, ValueError):
            return 0

    def config_owner():
        character = get_character_data() or {}
        char = str(character.get('name') or '').strip()
        server = str(character.get('server') or '').strip()
        if not char or not server:
            return None
        return server.casefold(), char.casefold()

    def config_path(owner=None):
        owner = owner or config_owner()
        if owner is None:
            raise ValueError('Vào game để đọc tên nhân vật và máy chủ.')
        key = json.dumps(owner, ensure_ascii=False).encode('utf-8')
        suffix = hashlib.sha256(key).hexdigest()[:24]
        return Path(get_config_dir()) / ('%s_%s.json' % (config_name, suffix))

    def read_float(widget, default, lo, hi):
        try:
            val = float((QtBind.text(gui, widget) or '').strip().replace(',', '.'))
        except (TypeError, ValueError):
            val = default
        if not math.isfinite(val):
            val = default
        return max(lo, min(hi, val))

    def read_int(widget, default):
        try:
            return int(float((QtBind.text(gui, widget) or '').strip().replace(',', '.')))
        except (TypeError, ValueError):
            return default

    def parse_names(text):
        raw = (text or '').replace(';', ',').replace('|', ',')
        names = []
        seen = set()
        for part in raw.split(','):
            n = part.strip()
            if not n:
                continue
            key = n.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(n)
        return names

    def attack_page():
        text = (QtBind.text(gui, page_combo) or DEFAULT_ATTACK_PAGE).strip().upper()
        if text not in ATTACK_PAGES:
            return DEFAULT_ATTACK_PAGE
        return text

    def read_town(index):
        name_w, reg_w, x_w, y_w, z_w, tp_w, _tag = town_widgets[index]
        return {
            'name': (QtBind.text(gui, name_w) or ('Thành %d' % (index + 1))).strip(),
            'region': read_int(reg_w, 0),
            'x': read_float(x_w, 0.0, -999999.0, 999999.0),
            'y': read_float(y_w, 0.0, -999999.0, 999999.0),
            'z': read_float(z_w, 0.0, -999999.0, 999999.0),
            'tp_dest': (QtBind.text(gui, tp_w) or '').strip(),
        }

    def write_town(index, data):
        data = data or {}
        name_w, reg_w, x_w, y_w, z_w, tp_w, _tag = town_widgets[index]
        QtBind.setText(gui, name_w, str(data.get('name') or ('Thành %d' % (index + 1))))
        QtBind.setText(gui, reg_w, str(int(data.get('region', 0) or 0)))
        QtBind.setText(gui, x_w, '%g' % float(data.get('x', 0) or 0))
        QtBind.setText(gui, y_w, '%g' % float(data.get('y', 0) or 0))
        QtBind.setText(gui, z_w, '%g' % float(data.get('z', 0) or 0))
        QtBind.setText(gui, tp_w, str(data.get('tp_dest') or ''))

    def town_configured(town):
        try:
            if int(town.get('region') or 0) != 0:
                return True
            if abs(float(town.get('x') or 0)) > 0.01 or abs(float(town.get('y') or 0)) > 0.01:
                return True
        except (TypeError, ValueError):
            return False
        return False

    def read_settings():
        return {
            'plugin_version': version,
            'start_town': start_town,
            'enabled': QtBind.isChecked(gui, enabled_box),
            'is_leader': QtBind.isChecked(gui, leader_box),
            'boss_names': parse_names(QtBind.text(gui, boss_names_field)),
            'attack_page': attack_page(),
            'towns': [read_town(i) for i in range(3)],
            'radius': read_float(radius_field, DEFAULT_RADIUS, 5.0, 200.0),
            'arrive_m': read_float(arrive_field, DEFAULT_ARRIVE_M, 3.0, 80.0),
            'delay_s': read_float(delay_field, DEFAULT_DELAY_S, 0.0, 120.0),
            'no_boss_s': read_float(noboss_field, DEFAULT_NO_BOSS_S, 10.0, 600.0),
        }

    def apply_settings(data):
        data = data or {}
        towns = data.get('towns') or list(PLACEHOLDER_TOWNS)
        while len(towns) < 3:
            towns.append(dict(PLACEHOLDER_TOWNS[len(towns)]))
        ui_applying['v'] = True
        try:
            QtBind.setChecked(gui, enabled_box, bool(data.get('enabled')))
            QtBind.setChecked(gui, leader_box, bool(data.get('is_leader', True)))
            QtBind.setText(gui, boss_names_field, '; '.join(data.get('boss_names') or []))
            page = str(data.get('attack_page') or DEFAULT_ATTACK_PAGE).upper()
            if page not in ATTACK_PAGES:
                page = DEFAULT_ATTACK_PAGE
            QtBind.setText(gui, page_combo, page)
            for i in range(3):
                write_town(i, towns[i])
            QtBind.setText(gui, radius_field, '%g' % float(data.get('radius', DEFAULT_RADIUS) or DEFAULT_RADIUS))
            QtBind.setText(gui, arrive_field, '%g' % float(data.get('arrive_m', DEFAULT_ARRIVE_M) or DEFAULT_ARRIVE_M))
            QtBind.setText(gui, delay_field, '%g' % float(data.get('delay_s', DEFAULT_DELAY_S) or DEFAULT_DELAY_S))
            QtBind.setText(gui, noboss_field, '%g' % float(data.get('no_boss_s', DEFAULT_NO_BOSS_S) or DEFAULT_NO_BOSS_S))
        finally:
            ui_applying['v'] = False
        with lock:
            state['enabled'] = bool(data.get('enabled'))
            state['is_leader'] = bool(data.get('is_leader', True))

    def current_pos():
        me = get_position() or {}
        try:
            return {
                'region': int(me.get('region') or 0),
                'x': float(me['x']),
                'y': float(me['y']),
                'z': float(me.get('z') or 0),
            }
        except (KeyError, TypeError, ValueError):
            return None

    def distance_xy(a, b):
        if not a or not b:
            return None
        try:
            return math.hypot(float(a['x']) - float(b['x']), float(a['y']) - float(b['y']))
        except (KeyError, TypeError, ValueError):
            return None

    def same_region(a, b):
        if not a or not b:
            return False
        try:
            ra, rb = int(a.get('region') or 0), int(b.get('region') or 0)
        except (TypeError, ValueError):
            return False
        if ra == 0 or rb == 0:
            return True
        return ra == rb

    def soft_stop():
        if _stop_trace is not None:
            try:
                _stop_trace()
            except Exception:
                pass
        try:
            if get_status():
                stop_bot()
        except Exception:
            pass

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

    def detect_party_leader():
        """True if checkbox Chủ OR get_party marks self as master."""
        if QtBind.isChecked(gui, leader_box):
            return True
        me = self_name().casefold()
        me_id = self_player_id()
        party = get_party()
        if not isinstance(party, dict) or not party:
            return False
        for member in party.values():
            if not isinstance(member, dict) or not _member_is_party_master(member):
                continue
            mname = str(member.get('name') or '').strip()
            while mname.startswith('*'):
                mname = mname[1:].strip()
            try:
                mid = int(member.get('player_id') or 0)
            except (TypeError, ValueError):
                mid = 0
            if me and mname and mname.casefold() == me:
                return True
            if me_id and mid and me_id == mid:
                return True
        return False

    def personal_teleport(town):
        dest = (town.get('tp_dest') or '').strip()
        if dest:
            if _reverse_return is None:
                set_status('phBot thiếu reverse_return — không tele được.')
                return False
            try:
                ok = _reverse_return(REV_ZONE, dest)
            except Exception as error:
                set_status('reverse_return(3) lỗi: %s' % error)
                return False
            set_status('Bùa chỉ định zone %r · API=%r (không party TP)' % (dest, ok), 'Đang tele')
            return ok is not False
        if _use_return_scroll is None:
            set_status('Thiếu TP dest và thiếu use_return_scroll.')
            return False
        try:
            ok = _use_return_scroll()
        except Exception as error:
            set_status('use_return_scroll lỗi: %s' % error)
            return False
        set_status('Bùa về thành CÁ NHÂN · API=%r' % ok, 'Đang tele')
        return ok is not False

    def nudge_move(dest, force=False):
        if not dest:
            return False
        now = monotonic()
        with lock:
            if not force and (now - state['last_nudge_at']) < DEFAULT_MOVE_NUDGE_S:
                return False
            state['last_nudge_at'] = now
        try:
            ok = move_to(float(dest['x']), float(dest['y']), float(dest.get('z') or 0))
        except Exception as error:
            set_status('move_to lỗi: %s' % error)
            return False
        return ok is not False

    def next_configured_index(from_index, settings):
        towns = settings['towns']
        for offset in range(1, 4):
            idx = (int(from_index) + offset) % 3
            if town_configured(towns[idx]):
                return idx
        return -1

    def begin_hunt(settings, town_index=None, source='UI'):
        with lock:
            if state['phase'] not in ('idle',):
                # Allow forced next from search timeout via clear first
                pass
        if town_index is None:
            town_index = start_town
        town_index = int(town_index) % 3
        town = settings['towns'][town_index]
        if not town_configured(town):
            alt = next_configured_index(town_index - 1, settings)
            if alt < 0:
                set_status('Chưa có Thành nào có XYZ — Lấy XY / sửa placeholder.')
                return False
            town_index = alt
            town = settings['towns'][town_index]
            set_status('Thành START chưa có XY · nhảy T%d' % (town_index + 1))

        soft_stop()
        with lock:
            state.update(
                phase='teleport',
                town_index=town_index,
                started_at=monotonic(),
                teleport_at=monotonic(),
                wait_until=0.0,
                search_at=0.0,
                attack_uid=0,
                last_nudge_at=0.0,
                last_ksgo_key='',
                is_leader=detect_party_leader(),
            )
        set_status(
            '[%s] → %s (T%d) · region=%s (%.0f, %.0f) · tele cá nhân…'
            % (source, town['name'], town_index + 1, town['region'], town['x'], town['y']),
            'Tele → T%d' % (town_index + 1))
        if not personal_teleport(town):
            me = current_pos()
            if me and same_region(me, town):
                with lock:
                    state['phase'] = 'walking'
                set_status('Tele thất bại · cùng map → đi bộ.', 'Đi bộ')
                nudge_move(town, force=True)
                return True
            with lock:
                state['phase'] = 'idle'
                state['town_index'] = -1
            set_status('Tele thất bại — kiểm tra TP dest / bùa (không party TP).')
            return False
        with lock:
            state['phase'] = 'wait'
            state['wait_until'] = monotonic() + float(settings.get('delay_s', DEFAULT_DELAY_S))
        return True

    def go_next_town(settings, reason='không Boss'):
        with lock:
            cur = state['town_index']
            if cur < 0:
                cur = start_town
        nxt = next_configured_index(cur, settings)
        if nxt < 0:
            clear_hunt('không còn Thành có XY')
            return False
        with lock:
            state['phase'] = 'idle'
            state['attack_uid'] = 0
        soft_stop()
        set_status('%s · chuyển T%d → T%d' % (reason, cur + 1, nxt + 1), 'Town kế')
        return begin_hunt(settings, town_index=nxt, source='cycle')

    def clear_hunt(reason=''):
        with lock:
            state['phase'] = 'idle'
            state['town_index'] = -1
            state['attack_uid'] = 0
            state['wait_until'] = 0.0
        soft_stop()
        if reason:
            set_status('Đã dừng · %s' % reason, 'Đã dừng')
        else:
            set_status('Đã dừng săn.', 'Đã dừng')

    def go_train(town, radius):
        try:
            set_training_position(
                int(town['region']), float(town['x']),
                float(town['y']), float(town.get('z') or 0))
            set_training_radius(float(radius))
        except Exception as error:
            _log('set train: %s' % error)
        nudge_move(town, force=True)
        try:
            start_bot()
        except Exception as error:
            _log('start_bot: %s' % error)
            return False
        return True

    def name_matches(query, text):
        if not query or not text:
            return False
        return query.casefold() in str(text).casefold()

    def find_boss(settings, town, me):
        monsters = get_monsters()
        if not isinstance(monsters, dict):
            return None, None
        names = settings.get('boss_names') or []
        radius = float(settings.get('radius', DEFAULT_RADIUS))
        best = None
        for raw_uid, mon in monsters.items():
            if not isinstance(mon, dict):
                continue
            label = mon.get('name') or mon.get('servername') or ''
            if names and not any(name_matches(n, label) for n in names):
                continue
            try:
                uid = int(raw_uid)
                dx = float(mon['x']) - float(me['x'])
                dy = float(mon['y']) - float(me['y'])
                dist = math.hypot(dx, dy)
            except (TypeError, ValueError, KeyError):
                continue
            if dist > radius * 1.5:
                continue
            to_anchor = distance_xy(mon, town)
            score = (dist if to_anchor is None else to_anchor, dist, uid, label)
            if best is None or score < best:
                best = score
        if best is None:
            return None, None
        return best[2], best[3]

    def select_local(uid, label):
        packet = struct.pack('<I', int(uid) & 0xffffffff)
        accepted = inject_joymax(0x7045, packet, False)
        try:
            start_bot()
        except Exception:
            pass
        return accepted is not False

    def leader_issue_attack(uid, label, page):
        """PartyLeader-compatible: ks#UID then ksgo#F#UID."""
        try:
            uid = int(uid)
        except (TypeError, ValueError):
            return False
        page = str(page or DEFAULT_ATTACK_PAGE).upper()
        if page not in ATTACK_PAGES:
            page = DEFAULT_ATTACK_PAGE
        key = '%s#%d' % (page, uid)
        now = monotonic()
        with lock:
            if (state.get('last_ksgo_key') == key
                    and (now - float(state.get('last_ksgo_at') or 0)) < KSGO_DEBOUNCE_S):
                select_local(uid, label)
                return True
        party_chat('ks#%d' % uid)
        ok = party_chat('ksgo#%s#%d' % (page, uid))
        with lock:
            state['last_ksgo_key'] = key
            state['last_ksgo_at'] = now
        select_local(uid, label)
        if ok:
            set_status(
                'Chủ phát ks#%d + ksgo#%s#%d · %s' % (uid, page, uid, label or 'Boss'),
                'PT đánh')
        else:
            set_status('7045 local UID=%d · (party chat thất bại)' % uid, 'Đánh local')
        return True

    def stop_party_fight(reason='dungdanh'):
        if detect_party_leader():
            party_chat('dungdanh')
        clear_hunt(reason)

    # --- UI ---
    def ui_enabled(checked):
        if ui_applying['v']:
            with lock:
                state['enabled'] = bool(checked)
            return
        with lock:
            state['enabled'] = bool(checked)
            if not checked:
                state['phase'] = 'idle'
        if checked:
            set_status('Đã bật · bấm Săn ngay hoặc chat san.', 'Đã bật')
        else:
            clear_hunt('tắt')

    def ui_leader(checked):
        with lock:
            state['is_leader'] = bool(checked)

    def _fill_here(index):
        me = current_pos()
        if not me:
            set_status('Chưa đọc được vị trí. Vào game rồi bấm lại.')
            return
        name_w, reg_w, x_w, y_w, z_w, _tp, _tag = town_widgets[index]
        QtBind.setText(gui, reg_w, str(int(me['region'])))
        QtBind.setText(gui, x_w, '%.2f' % me['x'])
        QtBind.setText(gui, y_w, '%.2f' % me['y'])
        QtBind.setText(gui, z_w, '%.2f' % me['z'])
        set_status('Đã ghi XY → Thành %d (%.0f, %.0f).' % (index + 1, me['x'], me['y']))

    def btn_here1():
        _fill_here(0)

    def btn_here2():
        _fill_here(1)

    def btn_here3():
        _fill_here(2)

    def btn_go():
        if not QtBind.isChecked(gui, enabled_box):
            QtBind.setChecked(gui, enabled_box, True)
            with lock:
                state['enabled'] = True
        try:
            settings = read_settings()
        except (ValueError, TypeError) as error:
            set_status(str(error))
            return
        with lock:
            state['phase'] = 'idle'
        begin_hunt(settings, town_index=start_town, source='UI')

    def btn_next():
        try:
            settings = read_settings()
        except (ValueError, TypeError) as error:
            set_status(str(error))
            return
        go_next_town(settings, reason='UI town kế')

    def btn_stop():
        clear_hunt('UI')

    def btn_save():
        try:
            owner = config_owner()
            path = config_path(owner)
            data = read_settings()
            data['plugin_version'] = version
            data['config_owner'] = list(owner)
            with tempfile.NamedTemporaryFile(
                    mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
                staged = Path(stream.name)
                json.dump(data, stream, ensure_ascii=False, indent=2)
            try:
                os.replace(staged, path)
            finally:
                if staged.exists():
                    staged.unlink()
            loaded_config_owner['v'] = owner
            apply_settings(data)
            filled = sum(1 for t in data['towns'] if town_configured(t))
            set_status('Đã lưu %s · %d/3 Thành có XY' % (path.name, filled), 'Đã lưu')
        except (OSError, ValueError, TypeError) as error:
            set_status('Chưa lưu: %s' % error)

    def load_settings(quiet=False):
        owner = config_owner()
        if owner is None:
            if not quiet:
                set_status('Chờ nhận diện nhân vật để nạp cấu hình.')
            return None
        loaded_config_owner['v'] = owner
        try:
            path = config_path(owner)
            data = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('JSON không hợp lệ.')
            if data.get('config_owner') != list(owner):
                raise ValueError('Cấu hình không thuộc nhân vật hiện tại.')
            apply_settings(data)
            if not quiet:
                set_status('Đã tải %s' % path.name, 'Đã tải')
            return data
        except FileNotFoundError:
            apply_settings({'is_leader': True})
            if not quiet:
                set_status('Chưa có bản lưu. Lấy XY 3 Thành → Lưu.')
            return None
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            apply_settings({'is_leader': True})
            if not quiet:
                set_status('Chưa tải: %s' % error)
            return None

    def btn_load():
        load_settings(quiet=False)

    def parse_chat_cmd(text):
        norm = _fold(text)
        if not norm:
            return None
        if norm in CMD_STOP_FIGHT:
            return 'stopfight', None
        if norm in CMD_STOP:
            return 'stop', None
        if norm in CMD_NEXT:
            return 'next', None
        if norm in CMD_GO:
            return 'go', None
        return None

    def handle_chat(chat_type, player, msg):
        if not QtBind.isChecked(gui, enabled_box):
            return
        ctype = int(chat_type or 0)
        if ctype == 11 and msg and ': ' in str(msg):
            msg = str(msg).split(': ', 1)[1]
        text = str(msg or '').strip()
        parsed = parse_chat_cmd(text)
        if not parsed:
            return
        me = self_name().casefold()
        sender = str(player or '').strip()
        while sender.startswith('*'):
            sender = sender[1:].strip()
        # Lệnh điều khiển: từ chính mình. dungdanh từ Chủ cũng OK nếu mình là phụ chạy script.
        kind, _extra = parsed
        if kind != 'stopfight':
            if me and sender and sender.casefold() != me:
                return
        try:
            settings = read_settings()
        except (ValueError, TypeError) as error:
            set_status(str(error))
            return
        if kind == 'stop':
            clear_hunt('chat')
            return
        if kind == 'stopfight':
            stop_party_fight('chat dungdanh')
            return
        if kind == 'next':
            go_next_town(settings, reason='chat next')
            return
        with lock:
            state['phase'] = 'idle'
        begin_hunt(settings, town_index=start_town, source='chat')

    def tick():
        try:
            settings = read_settings()
        except (ValueError, TypeError):
            return
        now = monotonic()
        with lock:
            enabled = state['enabled']
            phase = state['phase']
            idx = state['town_index']
            wait_until = state['wait_until']
            attack_uid = state['attack_uid']
            started_at = state['started_at']
            teleport_at = state['teleport_at']
            search_at = state['search_at']
            last_attack_at = state['last_attack_at']

        if not enabled or phase == 'idle':
            return
        if idx < 0 or idx > 2:
            return
        town = settings['towns'][idx]
        no_boss_s = float(settings.get('no_boss_s', DEFAULT_NO_BOSS_S))
        page = settings.get('attack_page') or DEFAULT_ATTACK_PAGE

        if phase == 'wait':
            if now < wait_until:
                return
            with lock:
                state['phase'] = 'walking'
                state['last_nudge_at'] = 0.0
            set_status('Hết delay tele · đi bộ tới %s.' % town['name'], 'Đi bộ')
            nudge_move(town, force=True)
            return

        if phase == 'teleport':
            if now - teleport_at >= RETURN_WAIT_S:
                with lock:
                    state['phase'] = 'walking'
                set_status('Hết chờ tele · chuyển đi bộ.', 'Đi bộ')
                nudge_move(town, force=True)
            return

        me = current_pos()
        if phase == 'walking':
            if not me:
                return
            arrive = float(settings.get('arrive_m', DEFAULT_ARRIVE_M))
            dist = distance_xy(me, town)
            if dist is not None and same_region(me, town) and dist <= arrive:
                with lock:
                    state['phase'] = 'search'
                    state['search_at'] = now
                    state['is_leader'] = detect_party_leader()
                set_status('Đã tới XYZ (%.1fm) · tìm Boss…' % dist, 'Tìm Boss')
                go_train(town, settings.get('radius', DEFAULT_RADIUS))
                return
            if not same_region(me, town):
                with lock:
                    spam = (now - state['last_status_at']) > 6
                    if spam:
                        state['last_status_at'] = now
                if spam:
                    set_status(
                        'khác map sau tele — không party TP. region=%s đích=%s'
                        % (me.get('region'), town.get('region')),
                        'Khác map')
                return
            nudge_move(town)
            if now - started_at > max(no_boss_s * 3, 180.0):
                go_next_town(settings, reason='timeout đi bộ')
            return

        if phase == 'search':
            if not me:
                return
            uid, label = find_boss(settings, town, me)
            if uid:
                is_lead = detect_party_leader()
                if is_lead:
                    leader_issue_attack(uid, label, page)
                else:
                    select_local(uid, label or 'Boss')
                    set_status('Phụ: chọn Boss local UID=%d (chờ ksgo từ Chủ)' % uid, 'Chờ Chủ')
                with lock:
                    state['phase'] = 'attack'
                    state['attack_uid'] = uid
                    state['last_attack_at'] = now
                return
            if now - search_at > 8.0:
                with lock:
                    state['search_at'] = now
                go_train(town, settings.get('radius', DEFAULT_RADIUS))
            if now - started_at > no_boss_s:
                go_next_town(settings, reason='không Boss tại T%d' % (idx + 1))
            return

        if phase == 'attack':
            monsters = get_monsters() or {}
            alive = attack_uid in monsters or str(attack_uid) in monsters
            if not alive:
                # Boss chết → ở lại điểm, chuyển search ngắn; nếu không spawn lại → next
                with lock:
                    state['phase'] = 'search'
                    state['search_at'] = now
                    state['started_at'] = now  # reset no-boss window
                    state['attack_uid'] = 0
                set_status('Boss biến · chờ lại / hết giờ → town kế.', 'Tìm lại')
                return
            try:
                if not get_status():
                    start_bot()
            except Exception:
                pass
            if now - last_attack_at >= ATTACK_RESELECT_S:
                with lock:
                    state['last_attack_at'] = now
                if detect_party_leader():
                    leader_issue_attack(attack_uid, 'Boss', page)
                else:
                    select_local(attack_uid, 'Boss')

    def teleported():
        with lock:
            if state['phase'] not in ('wait', 'teleport'):
                return
            idx = state['town_index']
            delay_left = max(0.0, state['wait_until'] - monotonic())
        if idx < 0:
            return
        if delay_left > 0.5:
            set_status('Đã tele (cá nhân) · chờ thêm %.0fs.' % delay_left, 'Chờ delay')
            return
        try:
            settings = read_settings()
            town = settings['towns'][idx]
        except (ValueError, TypeError, IndexError):
            return
        with lock:
            state['phase'] = 'walking'
            state['last_nudge_at'] = 0.0
        set_status('Đã tele · đi bộ tới %s.' % town['name'], 'Đi bộ')
        nudge_move(town, force=True)

    def event_loop():
        owner = config_owner()
        if owner is not None and owner != loaded_config_owner['v']:
            load_settings(quiet=False)
        try:
            tick()
        except Exception as error:
            _log('event_loop: %s' % error)

    def joined_game():
        data = load_settings(quiet=False)
        if data and data.get('enabled'):
            _log('joined_game: cấu hình đã bật — bấm Săn ngay / chat san.')

    # Export hooks + button handlers onto plugin module
    for key, val in (
        ('gui', gui),
        ('NAME', name),
        ('VERSION', version),
        ('ui_enabled', ui_enabled),
        ('ui_leader', ui_leader),
        ('btn_here1', btn_here1),
        ('btn_here2', btn_here2),
        ('btn_here3', btn_here3),
        ('btn_go', btn_go),
        ('btn_next', btn_next),
        ('btn_stop', btn_stop),
        ('btn_save', btn_save),
        ('btn_load', btn_load),
        ('handle_chat', handle_chat),
        ('event_loop', event_loop),
        ('teleported', teleported),
        ('joined_game', joined_game),
    ):
        setattr(mod, key, val)

    try:
        boot_data = load_settings(quiet=True)
        if boot_data is not None:
            set_status('Nạp v%s · restore OK · START=T%d' % (version, start_town + 1), 'Đã tải')
    except Exception as boot_error:
        _log('Nạp v%s · restore lỗi: %s' % (version, boot_error))

    log('[%s] Đã nạp v%s · START Thành %d. Cần BossTownCommon.py. '
        'Chủ: ks# + ksgo#%s#UID. Không Boss → town kế. KHÔNG party TP.'
        % (name, version, start_town + 1, DEFAULT_ATTACK_PAGE))
    return mod
