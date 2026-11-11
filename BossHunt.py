# -*- coding: utf-8 -*-
"""BossHunt — săn Unique Boss cho phBot Stable.

Changelog:
- v1.0.0: Nghe spawn Unique (handle_event t=0 + notice 0x300C), reverse/tele,
  set training + start_bot, chọn boss bằng 7045 (monster). Không ALT, không 7045 player.
"""

from __future__ import print_function

import json
import math
import struct
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
    reverse_return,
    set_training_position,
    set_training_radius,
    start_bot,
    stop_bot,
    use_return_scroll,
)

try:
    from phBot import set_training_area
except ImportError:
    set_training_area = None

NAME = 'BossHunt'
VERSION = '1.0.0'
CONFIG_NAME = 'BossHunt'

# phBot handle_event: t=0 Unique spawn/near (xChat / JellyDix).
EVENT_UNIQUE = 0
# reverse_return types (xControl)
REV_LAST_RETURN = 0
REV_LAST_DEATH = 1
REV_PLAYER = 2
REV_ZONE = 3

REVERSE_LABELS = (
    'Reverse: điểm Return cuối (mặc định)',
    'Reverse: điểm chết cuối',
    'Reverse: theo tên Zone',
    'Return Scroll (về thành)',
)

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
state = {
    'enabled': False,
    'phase': 'idle',  # idle | teleport | wait | search | attack
    'boss_query': '',
    'started_at': 0.0,
    'teleport_at': 0.0,
    'search_at': 0.0,
    'attack_uid': 0,
    'last_spawn': '',
}

# --- UI ---
QtBind.createLabel(gui, '%s v%s — săn Boss Unique' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật săn Boss', 10, 32)

QtBind.createLabel(gui, 'Tên Boss (cách nhau ; hoặc ,) — khớp một phần tên spawn', 10, 58)
boss_names_field = QtBind.createLineEdit(gui, '', 10, 76, 520, 22)

QtBind.createLabel(gui, 'Cách dịch chuyển', 10, 108)
reverse_combo = QtBind.createCombobox(gui, 10, 126, 280, 22)
for label in REVERSE_LABELS:
    QtBind.append(gui, reverse_combo, label)

QtBind.createLabel(gui, 'Tên Zone (chỉ khi Reverse Zone)', 300, 108)
zone_field = QtBind.createLineEdit(gui, '', 300, 126, 230, 22)

QtBind.createLabel(gui, 'Tọa độ săn Boss sau khi tele (region / x / y / z)', 10, 158)
region_field = QtBind.createLineEdit(gui, '0', 10, 176, 70, 22)
x_field = QtBind.createLineEdit(gui, '0', 90, 176, 90, 22)
y_field = QtBind.createLineEdit(gui, '0', 190, 176, 90, 22)
z_field = QtBind.createLineEdit(gui, '0', 290, 176, 90, 22)
QtBind.createButton(gui, 'btn_here', 'Lấy tọa độ hiện tại', 400, 174)

QtBind.createLabel(gui, 'Bán kính train (m)', 10, 208)
radius_field = QtBind.createLineEdit(gui, '50', 120, 206, 60, 22)
QtBind.createLabel(gui, 'Delay sau tele (giây)', 200, 208)
delay_field = QtBind.createLineEdit(gui, '8', 340, 206, 60, 22)

QtBind.createLabel(gui, 'Tên vùng train phBot (tuỳ chọn, nếu có trong list)', 10, 238)
area_field = QtBind.createLineEdit(gui, '', 10, 256, 280, 22)

QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 10, 290)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 140, 290)
QtBind.createButton(gui, 'btn_test', 'Thử săn ngay (tên ô trên)', 280, 290)

status_label = QtBind.createLabel(gui, 'Trạng thái: chờ bật.', 10, 330)
QtBind.createLabel(
    gui,
    'Gợi ý: Reverse mặc định = điểm Return Scroll cuối. Điểm săn = region/x/y gần Boss. '
    'Khi spawn khớp tên → tele → chờ delay → set train + start_bot + chọn Boss (7045).',
    10, 358,
)


def _log(msg):
    log('[%s] %s' % (NAME, msg))


def set_status(msg):
    QtBind.setText(gui, status_label, 'Trạng thái: ' + msg)
    _log(msg)


def config_path():
    return Path(get_config_dir()) / (CONFIG_NAME + '.json')


def reverse_mode_index():
    text = (QtBind.text(gui, reverse_combo) or '').strip()
    for i, label in enumerate(REVERSE_LABELS):
        if label == text:
            return i
    return 0


def set_reverse_mode(index):
    index = max(0, min(int(index), len(REVERSE_LABELS) - 1))
    QtBind.setText(gui, reverse_combo, REVERSE_LABELS[index])


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


def read_settings():
    names = parse_names(QtBind.text(gui, boss_names_field))
    if not names:
        raise ValueError('Nhập ít nhất một tên Boss.')
    try:
        region = int(float((QtBind.text(gui, region_field) or '0').strip()))
        x = float((QtBind.text(gui, x_field) or '0').strip().replace(',', '.'))
        y = float((QtBind.text(gui, y_field) or '0').strip().replace(',', '.'))
        z = float((QtBind.text(gui, z_field) or '0').strip().replace(',', '.'))
        radius = float((QtBind.text(gui, radius_field) or '50').strip().replace(',', '.'))
        delay = float((QtBind.text(gui, delay_field) or '8').strip().replace(',', '.'))
    except ValueError as error:
        raise ValueError('Tọa độ / bán kính / delay phải là số.') from error
    if not math.isfinite(radius) or radius < 5:
        raise ValueError('Bán kính train cần ≥ 5 m.')
    if not math.isfinite(delay) or delay < 0:
        raise ValueError('Delay sau tele không hợp lệ.')
    return {
        'enabled': QtBind.isChecked(gui, enabled_box),
        'boss_names': names,
        'reverse_mode': reverse_mode_index(),
        'zone_name': (QtBind.text(gui, zone_field) or '').strip(),
        'region': region,
        'x': x,
        'y': y,
        'z': z,
        'radius': min(radius, 200.0),
        'delay': min(delay, 120.0),
        'area_name': (QtBind.text(gui, area_field) or '').strip(),
    }


def apply_settings(data):
    QtBind.setChecked(gui, enabled_box, bool(data.get('enabled')))
    QtBind.setText(gui, boss_names_field, '; '.join(data.get('boss_names') or []))
    set_reverse_mode(data.get('reverse_mode', 0))
    QtBind.setText(gui, zone_field, str(data.get('zone_name') or ''))
    QtBind.setText(gui, region_field, str(int(data.get('region', 0) or 0)))
    QtBind.setText(gui, x_field, '%g' % float(data.get('x', 0) or 0))
    QtBind.setText(gui, y_field, '%g' % float(data.get('y', 0) or 0))
    QtBind.setText(gui, z_field, '%g' % float(data.get('z', 0) or 0))
    QtBind.setText(gui, radius_field, '%g' % float(data.get('radius', 50) or 50))
    QtBind.setText(gui, delay_field, '%g' % float(data.get('delay', 8) or 8))
    QtBind.setText(gui, area_field, str(data.get('area_name') or ''))
    with lock:
        state['enabled'] = bool(data.get('enabled'))


def btn_save():
    try:
        data = read_settings()
        path = config_path()
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        with lock:
            state['enabled'] = data['enabled']
        set_status('Đã lưu %s · Boss=%s' % (path.name, ', '.join(data['boss_names'])))
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
        set_status('Chưa có file cấu hình — bấm Lưu sau khi điền.')
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        set_status('Chưa tải: %s' % error)


def btn_here():
    position = get_position() or {}
    try:
        QtBind.setText(gui, region_field, str(int(position['region'])))
        QtBind.setText(gui, x_field, '%.2f' % float(position['x']))
        QtBind.setText(gui, y_field, '%.2f' % float(position['y']))
        QtBind.setText(gui, z_field, '%.2f' % float(position.get('z', 0)))
        set_status('Đã lấy tọa độ hiện tại.')
    except (KeyError, TypeError, ValueError) as error:
        set_status('Chưa lấy được tọa độ: %s' % error)


def ui_enabled(checked):
    with lock:
        state['enabled'] = bool(checked)
    set_status('Đã bật săn Boss.' if checked else 'Đã tắt săn Boss.')


def name_matches(query, text):
    if not query or not text:
        return False
    return query.casefold() in str(text).casefold()


def configured_match(spawn_text, settings):
    for name in settings['boss_names']:
        if name_matches(name, spawn_text):
            return name
    return None


def do_teleport(settings):
    mode = int(settings.get('reverse_mode', 0))
    if mode == 0:
        ok = reverse_return(REV_LAST_RETURN, '')
        set_status('Reverse → điểm Return cuối · API=%r' % ok)
        return bool(ok)
    if mode == 1:
        ok = reverse_return(REV_LAST_DEATH, '')
        set_status('Reverse → điểm chết cuối · API=%r' % ok)
        return bool(ok)
    if mode == 2:
        zone = settings.get('zone_name') or ''
        if not zone:
            set_status('Chọn Reverse Zone nhưng chưa nhập tên Zone.')
            return False
        ok = reverse_return(REV_ZONE, zone)
        set_status('Reverse → zone %r · API=%r' % (zone, ok))
        return bool(ok)
    # mode 3: return scroll to town
    ok = use_return_scroll()
    set_status('Return Scroll · API=%r' % ok)
    return bool(ok)


def begin_hunt(spawn_text, matched, settings, source):
    with lock:
        if state['phase'] not in ('idle',):
            set_status('Đang săn (phase=%s) · bỏ qua spawn mới: %s' % (state['phase'], spawn_text))
            return
        state.update(
            phase='teleport',
            boss_query=matched,
            started_at=monotonic(),
            teleport_at=0.0,
            search_at=0.0,
            attack_uid=0,
            last_spawn=spawn_text,
        )
    set_status('[%s] Thấy Unique %r → khớp %r · bắt đầu tele…' % (source, spawn_text, matched))
    try:
        if get_status():
            stop_bot()
    except Exception:
        pass
    if not do_teleport(settings):
        with lock:
            state['phase'] = 'idle'
        set_status('Tele thất bại — kiểm tra reverse scroll / zone.')
        return
    with lock:
        state['phase'] = 'wait'
        state['teleport_at'] = monotonic() + float(settings['delay'])


def btn_test():
    try:
        settings = read_settings()
    except ValueError as error:
        set_status(str(error))
        return
    name = settings['boss_names'][0]
    begin_hunt(name, name, settings, 'TEST')


def find_boss_uid(query, radius, anchor):
    monsters = get_monsters()
    if not isinstance(monsters, dict):
        return None, None
    best = None
    for raw_uid, mon in monsters.items():
        if not isinstance(mon, dict):
            continue
        label = mon.get('name') or mon.get('servername') or ''
        if not name_matches(query, label):
            continue
        try:
            uid = int(raw_uid)
            dx = float(mon['x']) - float(anchor['x'])
            dy = float(mon['y']) - float(anchor['y'])
            dist = math.hypot(dx, dy)
        except (TypeError, ValueError, KeyError):
            continue
        if dist > radius * 1.5:
            continue
        candidate = (dist, uid, label)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        return None, None
    return best[1], best[2]


def go_train_and_search(settings):
    area = settings.get('area_name') or ''
    if area and callable(set_training_area):
        try:
            if set_training_area(area):
                set_status('Đã chọn vùng train %r' % area)
        except Exception as error:
            _log('set_training_area: %s' % error)
    try:
        set_training_position(int(settings['region']), float(settings['x']),
                              float(settings['y']), float(settings['z']))
        set_training_radius(float(settings['radius']))
    except Exception as error:
        set_status('Lỗi set train: %s' % error)
        return False
    try:
        move_to(float(settings['x']), float(settings['y']), float(settings['z']))
    except Exception as error:
        _log('move_to: %s' % error)
    try:
        start_bot()
    except Exception as error:
        set_status('start_bot lỗi: %s' % error)
        return False
    set_status('Đã start_bot · đang tìm Boss %r…' % settings.get('boss_names', [''])[0])
    return True


def select_and_attack(uid, label):
    packet = struct.pack('<I', int(uid) & 0xffffffff)
    accepted = inject_joymax(0x7045, packet, False)
    set_status('Chọn Boss %s UID=%d · 7045=%r · start_bot' % (label, uid, accepted))
    try:
        start_bot()
    except Exception:
        pass
    return accepted is not False


def tick():
    with lock:
        if not state['enabled'] or state['phase'] == 'idle':
            return
        phase = state['phase']
        query = state['boss_query']
        teleport_at = state['teleport_at']
        attack_uid = state['attack_uid']
    try:
        settings = read_settings()
    except ValueError:
        return
    now = monotonic()
    if phase == 'wait':
        if now < teleport_at:
            return
        if go_train_and_search(settings):
            with lock:
                state['phase'] = 'search'
                state['search_at'] = now
        else:
            with lock:
                state['phase'] = 'idle'
        return
    if phase == 'search':
        position = get_position() or {}
        if 'x' not in position:
            return
        uid, label = find_boss_uid(query, settings['radius'], position)
        if uid:
            if select_and_attack(uid, label or query):
                with lock:
                    state['phase'] = 'attack'
                    state['attack_uid'] = uid
            return
        # Re-push train / move occasionally
        if now - state.get('search_at', now) > 12.0:
            with lock:
                state['search_at'] = now
            go_train_and_search(settings)
        # Timeout 8 minutes
        if now - state.get('started_at', now) > 480:
            with lock:
                state['phase'] = 'idle'
            set_status('Hết giờ tìm Boss · về idle.')
        return
    if phase == 'attack':
        monsters = get_monsters() or {}
        alive = attack_uid in monsters or str(attack_uid) in monsters
        if not alive:
            with lock:
                state['phase'] = 'idle'
                state['attack_uid'] = 0
            set_status('Boss hết / ra xa · săn xong.')
            return
        # Keep bot running
        try:
            if not get_status():
                start_bot()
        except Exception:
            pass


def handle_event(t, data):
    if int(t) != EVENT_UNIQUE:
        return
    text = str(data or '').strip()
    if not text:
        return
    with lock:
        enabled = state['enabled']
    if not enabled:
        return
    try:
        settings = read_settings()
    except ValueError:
        return
    matched = configured_match(text, settings)
    if not matched:
        _log('Unique spawn bỏ qua (không khớp list): %r' % text)
        return
    begin_hunt(text, matched, settings, 'EVENT_UNIQUE')


def handle_joymax(opcode, data):
    # Backup: server notice often carries unique text (0x300C on many privates).
    if opcode != 0x300C or not data:
        return True
    with lock:
        enabled = state['enabled']
    if not enabled:
        return True
    try:
        text = data.decode('utf-16le', errors='ignore')
    except Exception:
        return True
    text = ' '.join(text.replace('\x00', ' ').split())
    if not text:
        return True
    try:
        settings = read_settings()
    except ValueError:
        return True
    matched = configured_match(text, settings)
    if matched and any(k in text.casefold() for k in ('appear', 'spawn', 'xuất hiện', 'unique', 'boss')):
        begin_hunt(text, matched, settings, 'NOTICE')
    return True


def event_loop():
    try:
        tick()
    except Exception as error:
        _log('event_loop: %s' % error)


def joined_game():
    btn_load()


# Load defaults into combo
set_reverse_mode(0)
log('[%s] Đã nạp thành công v%s. Điền tên Boss → Lấy tọa độ → Lưu → Bật săn Boss.' % (NAME, VERSION))
