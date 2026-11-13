# -*- coding: utf-8 -*-
"""Boss3Town — săn Boss định giờ tại 3 Thành cố định (phBot Stable).

Mỗi 30 phút (cấu hình được): chọn Thành (gần nhất / tay / lịch) →
bùa teleport CÁ NHÂN chỉ định (hoặc bùa về thành) → đi bộ tới XYZ Boss →
tự đánh. KHÔNG party/group teleport.

Changelog:
- v1.0.0: 3 Thành (name + region/x/y/z + đích TP tùy chọn), timer 30p,
  chọn nearest/manual/cycle/schedule, reverse_return(3) hoặc use_return_scroll,
  move_to + 7045 + start_bot. Không reverse_return party / group warp.
"""

from __future__ import print_function

import hashlib
import json
import math
import os
import struct
import tempfile
from datetime import datetime
from pathlib import Path
from threading import RLock
from time import monotonic

import QtBind
from phBot import (
    get_character_data,
    get_config_dir,
    get_monsters,
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

NAME = 'Boss3Town'
VERSION = '1.0.0'
CONFIG_NAME = 'Boss3Town'

# reverse_return type 3 = zone/map chỉ định (cá nhân). KHÔNG dùng type 2 (party).
REV_ZONE = 3

DEFAULT_INTERVAL_MIN = 30.0
DEFAULT_RADIUS = 50.0
DEFAULT_ARRIVE_M = 12.0
DEFAULT_DELAY_S = 8.0
DEFAULT_MOVE_NUDGE_S = 1.2
RETURN_WAIT_S = 45.0
SEARCH_TIMEOUT_S = 480.0
ATTACK_RESELECT_S = 4.0

# Chế độ chọn Thành
MODE_NEAREST = 0
MODE_TOWN1 = 1
MODE_TOWN2 = 2
MODE_TOWN3 = 3
MODE_CYCLE = 4

MODE_LABELS = (
    'Gần nhất trong 3',
    'Thành 1 (tay)',
    'Thành 2 (tay)',
    'Thành 3 (tay)',
    'Luân phiên 1→2→3',
)

# Timer: khoảng cách cố định / theo phút trong giờ
TIMER_INTERVAL = 0
TIMER_SCHEDULE = 1
TIMER_LABELS = (
    'Mỗi N phút (từ lần săn / bật)',
    'Theo phút trong giờ (vd 0,30)',
)

CMD_GO = (
    'san', 'di san', 'bosgo', 'bossgo', 'go', 'hunt', 'di boss',
)
CMD_STOP = (
    'dung', 'stop', 'bossoff', 'huy san', 'huy', 'stopboss',
)
CMD_NEAREST = ('gan', 'nearest', 'gan nhat')
CMD_T1 = ('thanh1', 'town1', 't1', 'thanh 1')
CMD_T2 = ('thanh2', 'town2', 't2', 'thanh 2')
CMD_T3 = ('thanh3', 'town3', 't3', 'thanh 3')

PLACEHOLDER_TOWNS = (
    {'name': 'Thành 1', 'region': 0, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'tp_dest': ''},
    {'name': 'Thành 2', 'region': 0, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'tp_dest': ''},
    {'name': 'Thành 3', 'region': 0, 'x': 0.0, 'y': 0.0, 'z': 0.0, 'tp_dest': ''},
)

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
_ui_applying = False
loaded_config_owner = None

state = {
    'enabled': False,
    'phase': 'idle',  # idle | teleport | wait | walking | search | attack
    'town_index': -1,
    'cycle_next': 0,
    'started_at': 0.0,
    'teleport_at': 0.0,
    'wait_until': 0.0,
    'last_nudge_at': 0.0,
    'search_at': 0.0,
    'attack_uid': 0,
    'last_attack_at': 0.0,
    'last_hunt_at': 0.0,
    'timer_armed_at': 0.0,
    'last_schedule_key': '',
    'last_status_at': 0.0,
}

# --- UI ---
QtBind.createLabel(gui, '%s v%s — Boss 3 Thành (timer · bùa cá nhân · đi bộ)' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật auto săn', 10, 28)

QtBind.createLabel(gui, 'Tên Boss (lọc get_monsters; để trống = quái gần XYZ)', 200, 28)
boss_names_field = QtBind.createLineEdit(gui, '', 200, 46, 340, 22)

# Town 1
QtBind.createLabel(gui, 'Thành 1 — tên', 10, 76)
t1_name = QtBind.createLineEdit(gui, PLACEHOLDER_TOWNS[0]['name'], 100, 74, 120, 22)
QtBind.createLabel(gui, 'region/x/y/z', 230, 76)
t1_region = QtBind.createLineEdit(gui, '0', 310, 74, 50, 22)
t1_x = QtBind.createLineEdit(gui, '0', 365, 74, 70, 22)
t1_y = QtBind.createLineEdit(gui, '0', 440, 74, 70, 22)
t1_z = QtBind.createLineEdit(gui, '0', 515, 74, 60, 22)
QtBind.createLabel(gui, 'TP dest (zone)', 10, 100)
t1_tp = QtBind.createLineEdit(gui, '', 100, 98, 200, 22)
QtBind.createButton(gui, 'btn_here1', 'Lấy XY hiện tại → T1', 320, 96)

# Town 2
QtBind.createLabel(gui, 'Thành 2 — tên', 10, 128)
t2_name = QtBind.createLineEdit(gui, PLACEHOLDER_TOWNS[1]['name'], 100, 126, 120, 22)
QtBind.createLabel(gui, 'region/x/y/z', 230, 128)
t2_region = QtBind.createLineEdit(gui, '0', 310, 126, 50, 22)
t2_x = QtBind.createLineEdit(gui, '0', 365, 126, 70, 22)
t2_y = QtBind.createLineEdit(gui, '0', 440, 126, 70, 22)
t2_z = QtBind.createLineEdit(gui, '0', 515, 126, 60, 22)
QtBind.createLabel(gui, 'TP dest (zone)', 10, 152)
t2_tp = QtBind.createLineEdit(gui, '', 100, 150, 200, 22)
QtBind.createButton(gui, 'btn_here2', 'Lấy XY hiện tại → T2', 320, 148)

# Town 3
QtBind.createLabel(gui, 'Thành 3 — tên', 10, 180)
t3_name = QtBind.createLineEdit(gui, PLACEHOLDER_TOWNS[2]['name'], 100, 178, 120, 22)
QtBind.createLabel(gui, 'region/x/y/z', 230, 180)
t3_region = QtBind.createLineEdit(gui, '0', 310, 178, 50, 22)
t3_x = QtBind.createLineEdit(gui, '0', 365, 178, 70, 22)
t3_y = QtBind.createLineEdit(gui, '0', 440, 178, 70, 22)
t3_z = QtBind.createLineEdit(gui, '0', 515, 178, 60, 22)
QtBind.createLabel(gui, 'TP dest (zone)', 10, 204)
t3_tp = QtBind.createLineEdit(gui, '', 100, 202, 200, 22)
QtBind.createButton(gui, 'btn_here3', 'Lấy XY hiện tại → T3', 320, 200)

# Timer / mode
QtBind.createLabel(gui, 'Chọn Thành', 10, 234)
mode_combo = QtBind.createCombobox(gui, 10, 252, 180, 22)
for _label in MODE_LABELS:
    QtBind.append(gui, mode_combo, _label)

QtBind.createLabel(gui, 'Kiểu timer', 200, 234)
timer_combo = QtBind.createCombobox(gui, 200, 252, 220, 22)
for _label in TIMER_LABELS:
    QtBind.append(gui, timer_combo, _label)

QtBind.createLabel(gui, 'N phút', 430, 234)
interval_field = QtBind.createLineEdit(gui, str(int(DEFAULT_INTERVAL_MIN)), 430, 252, 50, 22)
QtBind.createLabel(gui, 'phút giờ (0,30)', 490, 234)
schedule_field = QtBind.createLineEdit(gui, '0,30', 490, 252, 70, 22)

QtBind.createLabel(gui, 'Bán kính (m)', 10, 284)
radius_field = QtBind.createLineEdit(gui, str(int(DEFAULT_RADIUS)), 90, 282, 50, 22)
QtBind.createLabel(gui, 'Tới khi ≤ (m)', 150, 284)
arrive_field = QtBind.createLineEdit(gui, str(int(DEFAULT_ARRIVE_M)), 240, 282, 50, 22)
QtBind.createLabel(gui, 'Delay sau tele (s)', 300, 284)
delay_field = QtBind.createLineEdit(gui, str(int(DEFAULT_DELAY_S)), 410, 282, 50, 22)

QtBind.createButton(gui, 'btn_go', 'Săn ngay', 10, 316)
QtBind.createButton(gui, 'btn_stop', 'Dừng săn', 110, 316)
QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 220, 316)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 350, 316)

status_label = QtBind.createLabel(gui, 'Trạng thái: điền 3 tọa độ Boss (placeholder 0) → Lưu → Bật.', 10, 350)
help_label = QtBind.createLabel(
    gui,
    'TP: nếu có «TP dest» → reverse_return(3, zone) CÁ NHÂN; không thì use_return_scroll rồi đi bộ.\n'
    'KHÔNG party TP. Chat: san / dung / gan / thanh1|2|3 · Timer mặc định 30 phút.',
    10, 378,
)

TOWN_FIELDS = (
    (t1_name, t1_region, t1_x, t1_y, t1_z, t1_tp),
    (t2_name, t2_region, t2_x, t2_y, t2_z, t2_tp),
    (t3_name, t3_region, t3_x, t3_y, t3_z, t3_tp),
)


def _log(msg):
    log('[%s] %s' % (NAME, msg))


def set_status(msg, display=None):
    QtBind.setText(gui, status_label, 'Trạng thái: %s' % (display or msg))
    _log(msg)


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


def self_name():
    data = get_character_data() or {}
    for key in ('name', 'charname', 'char_name', 'character_name', 'CharName'):
        val = str(data.get(key) or '').strip()
        while val.startswith('*'):
            val = val[1:].strip()
        if val:
            return val
    return ''


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
        name = part.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        names.append(name)
    return names


def parse_schedule(text):
    mins = []
    seen = set()
    for part in str(text or '').replace(';', ',').split(','):
        part = part.strip()
        if not part:
            continue
        try:
            m = int(float(part))
        except (TypeError, ValueError):
            continue
        if 0 <= m <= 59 and m not in seen:
            seen.add(m)
            mins.append(m)
    return sorted(mins) or [0, 30]


def combo_index(combo, labels, default=0):
    text = (QtBind.text(gui, combo) or '').strip()
    for i, label in enumerate(labels):
        if label == text:
            return i
    return default


def set_combo(combo, labels, index):
    index = max(0, min(int(index), len(labels) - 1))
    QtBind.setText(gui, combo, labels[index])


def read_town(index):
    name_w, reg_w, x_w, y_w, z_w, tp_w = TOWN_FIELDS[index]
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
    name_w, reg_w, x_w, y_w, z_w, tp_w = TOWN_FIELDS[index]
    QtBind.setText(gui, name_w, str(data.get('name') or ('Thành %d' % (index + 1))))
    QtBind.setText(gui, reg_w, str(int(data.get('region', 0) or 0)))
    QtBind.setText(gui, x_w, '%g' % float(data.get('x', 0) or 0))
    QtBind.setText(gui, y_w, '%g' % float(data.get('y', 0) or 0))
    QtBind.setText(gui, z_w, '%g' % float(data.get('z', 0) or 0))
    QtBind.setText(gui, tp_w, str(data.get('tp_dest') or ''))


def town_configured(town):
    """Placeholder (0,0,0) region 0 = chưa điền — vẫn cho lưu nhưng cảnh báo khi săn."""
    try:
        if int(town.get('region') or 0) != 0:
            return True
        if abs(float(town.get('x') or 0)) > 0.01 or abs(float(town.get('y') or 0)) > 0.01:
            return True
    except (TypeError, ValueError):
        return False
    return False


def read_settings():
    towns = [read_town(i) for i in range(3)]
    return {
        'plugin_version': VERSION,
        'enabled': QtBind.isChecked(gui, enabled_box),
        'boss_names': parse_names(QtBind.text(gui, boss_names_field)),
        'towns': towns,
        'select_mode': combo_index(mode_combo, MODE_LABELS, MODE_NEAREST),
        'timer_mode': combo_index(timer_combo, TIMER_LABELS, TIMER_INTERVAL),
        'interval_min': read_float(interval_field, DEFAULT_INTERVAL_MIN, 1.0, 24 * 60.0),
        'schedule_mins': parse_schedule(QtBind.text(gui, schedule_field)),
        'radius': read_float(radius_field, DEFAULT_RADIUS, 5.0, 200.0),
        'arrive_m': read_float(arrive_field, DEFAULT_ARRIVE_M, 3.0, 80.0),
        'delay_s': read_float(delay_field, DEFAULT_DELAY_S, 0.0, 120.0),
    }


def apply_settings(data):
    global _ui_applying
    data = data or {}
    towns = data.get('towns') or list(PLACEHOLDER_TOWNS)
    while len(towns) < 3:
        towns.append(dict(PLACEHOLDER_TOWNS[len(towns)]))
    _ui_applying = True
    try:
        QtBind.setChecked(gui, enabled_box, bool(data.get('enabled')))
        QtBind.setText(gui, boss_names_field, '; '.join(data.get('boss_names') or []))
        for i in range(3):
            write_town(i, towns[i])
        set_combo(mode_combo, MODE_LABELS, data.get('select_mode', MODE_NEAREST))
        set_combo(timer_combo, TIMER_LABELS, data.get('timer_mode', TIMER_INTERVAL))
        QtBind.setText(gui, interval_field, '%g' % float(data.get('interval_min', DEFAULT_INTERVAL_MIN) or DEFAULT_INTERVAL_MIN))
        mins = data.get('schedule_mins') or [0, 30]
        QtBind.setText(gui, schedule_field, ','.join(str(int(m)) for m in mins))
        QtBind.setText(gui, radius_field, '%g' % float(data.get('radius', DEFAULT_RADIUS) or DEFAULT_RADIUS))
        QtBind.setText(gui, arrive_field, '%g' % float(data.get('arrive_m', DEFAULT_ARRIVE_M) or DEFAULT_ARRIVE_M))
        QtBind.setText(gui, delay_field, '%g' % float(data.get('delay_s', DEFAULT_DELAY_S) or DEFAULT_DELAY_S))
    finally:
        _ui_applying = False
    with lock:
        state['enabled'] = bool(data.get('enabled'))
        if state['enabled'] and state['timer_armed_at'] <= 0:
            state['timer_armed_at'] = monotonic()


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


def personal_teleport(town):
    """Bùa CÁ NHÂN tới Thành. Ưu tiên reverse_return(3, dest). Không party TP."""
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
        set_status('Thiếu TP dest và thiếu use_return_scroll — điền TP dest hoặc mang bùa về thành.')
        return False
    try:
        ok = _use_return_scroll()
    except Exception as error:
        set_status('use_return_scroll lỗi: %s' % error)
        return False
    set_status('Bùa về thành CÁ NHÂN · API=%r (không party TP)' % ok, 'Đang tele')
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


def pick_town_index(settings, force_mode=None):
    mode = force_mode if force_mode is not None else int(settings.get('select_mode', MODE_NEAREST))
    towns = settings['towns']
    if mode in (MODE_TOWN1, MODE_TOWN2, MODE_TOWN3):
        idx = mode - 1
        if not town_configured(towns[idx]):
            set_status('Thành %d chưa có tọa độ (placeholder). Điền XYZ rồi Lưu.' % (idx + 1))
            return -1
        return idx
    if mode == MODE_CYCLE:
        with lock:
            start = state['cycle_next'] % 3
        for offset in range(3):
            idx = (start + offset) % 3
            if town_configured(towns[idx]):
                with lock:
                    state['cycle_next'] = (idx + 1) % 3
                return idx
        set_status('Chưa có Thành nào có tọa độ — điền XYZ placeholder.')
        return -1

    # nearest
    me = current_pos()
    best = None
    for i, town in enumerate(towns):
        if not town_configured(town):
            continue
        if me is None:
            # Không đọc được vị trí → lấy Thành đầu tiên đã điền
            return i
        dist = distance_xy(me, town)
        if dist is None:
            continue
        # Ưu tiên cùng region nếu có
        same = 0 if same_region(me, town) else 1
        cand = (same, dist, i)
        if best is None or cand < best:
            best = cand
    if best is None:
        set_status('Chưa có Thành nào có tọa độ — điền 3 XYZ Boss rồi Lưu.')
        return -1
    return best[2]


def begin_hunt(settings, force_mode=None, source='UI'):
    with lock:
        if state['phase'] not in ('idle',):
            set_status('Đang săn (phase=%s) · bỏ qua lệnh mới.' % state['phase'])
            return False
    idx = pick_town_index(settings, force_mode=force_mode)
    if idx < 0:
        return False
    town = settings['towns'][idx]
    soft_stop()
    with lock:
        state.update(
            phase='teleport',
            town_index=idx,
            started_at=monotonic(),
            teleport_at=monotonic(),
            wait_until=0.0,
            search_at=0.0,
            attack_uid=0,
            last_nudge_at=0.0,
        )
    set_status(
        '[%s] → %s · region=%s (%.0f, %.0f) · tele cá nhân…'
        % (source, town['name'], town['region'], town['x'], town['y']),
        'Tele → %s' % town['name'])
    if not personal_teleport(town):
        # Không tele được: nếu cùng map thì đi bộ thẳng
        me = current_pos()
        if me and same_region(me, town):
            with lock:
                state['phase'] = 'walking'
            set_status('Tele thất bại · cùng map → đi bộ tới Boss.', 'Đi bộ')
            nudge_move(town, force=True)
            return True
        with lock:
            state['phase'] = 'idle'
            state['town_index'] = -1
        set_status('Tele thất bại — kiểm tra TP dest / bùa cá nhân. (không party TP)')
        return False
    with lock:
        state['phase'] = 'wait'
        state['wait_until'] = monotonic() + float(settings.get('delay_s', DEFAULT_DELAY_S))
    return True


def clear_hunt(reason=''):
    with lock:
        state['phase'] = 'idle'
        state['town_index'] = -1
        state['attack_uid'] = 0
        state['wait_until'] = 0.0
    soft_stop()
    if reason:
        set_status('Đã dừng săn · %s' % reason, 'Đã dừng')
    else:
        set_status('Đã dừng săn.', 'Đã dừng')


def go_train(town, radius):
    try:
        set_training_position(int(town['region']), float(town['x']),
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
        if names:
            if not any(name_matches(n, label) for n in names):
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
        # Ưu tiên gần XYZ Boss đã cấu hình
        to_anchor = distance_xy(mon, town)
        score = (dist if to_anchor is None else to_anchor, dist, uid, label)
        if best is None or score < best:
            best = score
    if best is None:
        return None, None
    return best[2], best[3]


def select_and_attack(uid, label):
    packet = struct.pack('<I', int(uid) & 0xffffffff)
    accepted = inject_joymax(0x7045, packet, False)
    set_status('Chọn Boss %s UID=%d · 7045=%r' % (label, uid, accepted), 'Đang đánh')
    try:
        start_bot()
    except Exception:
        pass
    return accepted is not False


def timer_should_fire(settings, now):
    with lock:
        if state['phase'] != 'idle':
            return False
        if not state['enabled']:
            return False
        last_hunt = state['last_hunt_at']
        armed = state['timer_armed_at']
        last_key = state['last_schedule_key']

    timer_mode = int(settings.get('timer_mode', TIMER_INTERVAL))
    if timer_mode == TIMER_SCHEDULE:
        mins = settings.get('schedule_mins') or [0, 30]
        wall = datetime.now()
        if wall.minute not in mins:
            return False
        if wall.second > 8:
            return False
        key = '%04d-%02d-%02d-%02d-%02d' % (wall.year, wall.month, wall.day, wall.hour, wall.minute)
        if key == last_key:
            return False
        # Tránh bắn ngay lúc vừa bật trong cùng phút
        if armed > 0 and (now - armed) < 3.0:
            return False
        with lock:
            state['last_schedule_key'] = key
        return True

    interval_s = float(settings.get('interval_min', DEFAULT_INTERVAL_MIN)) * 60.0
    base = last_hunt if last_hunt > 0 else armed
    if base <= 0:
        return False
    return (now - base) >= interval_s


# --- UI handlers ---

def ui_enabled(checked):
    if _ui_applying:
        with lock:
            state['enabled'] = bool(checked)
        return
    with lock:
        state['enabled'] = bool(checked)
        if checked:
            state['timer_armed_at'] = monotonic()
            if state['last_hunt_at'] <= 0:
                state['last_hunt_at'] = 0.0
        else:
            state['phase'] = 'idle'
    if checked:
        set_status('Đã bật auto · chờ timer / bấm Săn ngay.', 'Đã bật')
    else:
        clear_hunt('tắt plugin')


def _fill_here(index):
    me = current_pos()
    if not me:
        set_status('Chưa đọc được vị trí. Vào game rồi bấm lại.')
        return
    name_w, reg_w, x_w, y_w, z_w, _tp = TOWN_FIELDS[index]
    QtBind.setText(gui, reg_w, str(int(me['region'])))
    QtBind.setText(gui, x_w, '%.2f' % me['x'])
    QtBind.setText(gui, y_w, '%.2f' % me['y'])
    QtBind.setText(gui, z_w, '%.2f' % me['z'])
    cur_name = (QtBind.text(gui, name_w) or '').strip()
    if not cur_name or cur_name.startswith('Thành '):
        QtBind.setText(gui, name_w, 'Thành %d' % (index + 1))
    set_status('Đã ghi XY hiện tại → Thành %d (%.0f, %.0f).' % (index + 1, me['x'], me['y']))


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
            state['timer_armed_at'] = monotonic()
    try:
        settings = read_settings()
    except (ValueError, TypeError) as error:
        set_status(str(error))
        return
    begin_hunt(settings, source='UI')


def btn_stop():
    clear_hunt('UI')


def btn_save():
    global loaded_config_owner
    try:
        owner = config_owner()
        path = config_path(owner)
        data = read_settings()
        data['plugin_version'] = VERSION
        data['config_owner'] = list(owner)
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
        filled = sum(1 for t in data['towns'] if town_configured(t))
        set_status('Đã lưu %s · %d/3 Thành có XY · timer=%g phút' % (
            path.name, filled, data['interval_min']), 'Đã lưu')
    except (OSError, ValueError, TypeError) as error:
        set_status('Chưa lưu: %s' % error)


def load_settings(quiet=False):
    global loaded_config_owner
    owner = config_owner()
    if owner is None:
        if not quiet:
            set_status('Chờ nhận diện nhân vật để nạp cấu hình.')
        return None
    loaded_config_owner = owner
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
        apply_settings({})
        if not quiet:
            set_status('Chưa có bản lưu. Điền 3 XYZ → Lưu.')
        return None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        apply_settings({})
        if not quiet:
            set_status('Chưa tải: %s' % error)
        return None


def btn_load():
    load_settings(quiet=False)


def parse_chat_cmd(text):
    norm = _fold(text)
    if not norm:
        return None
    if norm in CMD_STOP:
        return 'stop', None
    if norm in CMD_GO:
        return 'go', None
    if norm in CMD_NEAREST:
        return 'go', MODE_NEAREST
    if norm in CMD_T1:
        return 'go', MODE_TOWN1
    if norm in CMD_T2:
        return 'go', MODE_TOWN2
    if norm in CMD_T3:
        return 'go', MODE_TOWN3
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
    # Chỉ nhận lệnh từ chính mình (tránh người khác chat «san»)
    me = self_name().casefold()
    sender = str(player or '').strip()
    while sender.startswith('*'):
        sender = sender[1:].strip()
    if me and sender and sender.casefold() != me:
        return
    kind, force_mode = parsed
    if kind == 'stop':
        clear_hunt('chat')
        return
    try:
        settings = read_settings()
    except (ValueError, TypeError) as error:
        set_status(str(error))
        return
    begin_hunt(settings, force_mode=force_mode, source='chat')


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

    if not enabled:
        return

    if phase == 'idle':
        if timer_should_fire(settings, now):
            begin_hunt(settings, source='timer')
        return

    if idx < 0 or idx > 2:
        return
    town = settings['towns'][idx]

    if phase == 'wait':
        if now < wait_until:
            return
        with lock:
            state['phase'] = 'walking'
            state['last_nudge_at'] = 0.0
        set_status('Hết delay tele · đi bộ tới Boss %s.' % town['name'], 'Đi bộ')
        nudge_move(town, force=True)
        return

    if phase == 'teleport':
        # Chờ teleported() hook; timeout → walking
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
            set_status('Đã tới XYZ Boss (%.1fm) · tìm mục tiêu…' % dist, 'Tìm Boss')
            go_train(town, settings.get('radius', DEFAULT_RADIUS))
            return
        # Khác region lâu sau tele → vẫn chỉ đi bộ, không party TP
        if not same_region(me, town):
            with lock:
                spam = (now - state['last_status_at']) > 6
                if spam:
                    state['last_status_at'] = now
            if spam:
                set_status(
                    'khác map sau tele — không party TP. region=%s đích=%s · chờ về đúng map / portal.'
                    % (me.get('region'), town.get('region')),
                    'Khác map')
            return
        nudge_move(town)
        if now - started_at > SEARCH_TIMEOUT_S:
            clear_hunt('timeout đi bộ')
        return

    if phase == 'search':
        if not me:
            return
        uid, label = find_boss(settings, town, me)
        if uid:
            if select_and_attack(uid, label or (settings.get('boss_names') or ['Boss'])[0]):
                with lock:
                    state['phase'] = 'attack'
                    state['attack_uid'] = uid
                    state['last_attack_at'] = now
            return
        if now - search_at > 10.0:
            with lock:
                state['search_at'] = now
            go_train(town, settings.get('radius', DEFAULT_RADIUS))
        if now - started_at > SEARCH_TIMEOUT_S:
            with lock:
                state['last_hunt_at'] = now
            clear_hunt('hết giờ tìm Boss')
        return

    if phase == 'attack':
        monsters = get_monsters() or {}
        alive = attack_uid in monsters or str(attack_uid) in monsters
        if not alive:
            with lock:
                state['last_hunt_at'] = now
            clear_hunt('Boss chết / biến')
            set_status('Boss xong · chờ timer tiếp theo.', 'Chờ timer')
            return
        try:
            if not get_status():
                start_bot()
        except Exception:
            pass
        if now - last_attack_at >= ATTACK_RESELECT_S:
            with lock:
                state['last_attack_at'] = now
            select_and_attack(attack_uid, 'Boss')


def teleported():
    with lock:
        if state['phase'] not in ('wait', 'teleport'):
            return
        idx = state['town_index']
        delay_left = max(0.0, state['wait_until'] - monotonic())
    if idx < 0:
        return
    # Giữ delay ngắn nếu teleported sớm hơn delay cấu hình
    if delay_left > 0.5:
        set_status('Đã tele (bùa cá nhân) · chờ thêm %.0fs rồi đi bộ.' % delay_left, 'Chờ delay')
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
    global loaded_config_owner
    owner = config_owner()
    if owner is not None and owner != loaded_config_owner:
        load_settings(quiet=False)
    try:
        tick()
    except Exception as error:
        _log('event_loop: %s' % error)


def joined_game():
    data = load_settings(quiet=False)
    if data and data.get('enabled'):
        with lock:
            state['timer_armed_at'] = monotonic()
        _log('joined_game: auto-bật từ cấu hình · chờ timer.')


# Boot
set_combo(mode_combo, MODE_LABELS, MODE_NEAREST)
set_combo(timer_combo, TIMER_LABELS, TIMER_INTERVAL)
try:
    _boot = load_settings(quiet=True)
    if _boot is not None:
        set_status('Nạp v%s · đã restore cấu hình' % VERSION, 'Đã tải')
except Exception as _boot_error:
    _log('Nạp v%s · restore lỗi: %s' % (VERSION, _boot_error))

log('[%s] Đã nạp v%s. Điền 3 XYZ Boss → Lưu → Bật. Chat: san/dung/gan/thanh1|2|3. KHÔNG party TP.'
    % (NAME, VERSION))
