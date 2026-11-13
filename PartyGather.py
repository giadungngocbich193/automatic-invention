# -*- coding: utf-8 -*-
"""PartyGather — tụ họp PT bằng đi bộ / bùa cá nhân (phBot Stable).

KHÔNG dùng party teleport / group warp / 705A nhóm.
Chỉ: move_to + use_return_scroll (cá nhân) rồi đi bộ tới chỗ chủ.

Changelog:
- v1.0.0: Chủ phát gather#region#x#y#z; phụ đi bộ nếu gần cùng region,
  xa/khác region → bùa về thành cá nhân rồi move_to. Hủy: gatheroff.
"""

from __future__ import print_function

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from threading import RLock
from time import monotonic

import QtBind
from phBot import (
    get_character_data,
    get_config_dir,
    get_party,
    get_position,
    log,
    move_to,
)

try:
    from phBot import use_return_scroll as _use_return_scroll
except ImportError:
    _use_return_scroll = None

try:
    from phBot import stop_trace as _stop_trace
except ImportError:
    _stop_trace = None

try:
    from phBot import get_npcs as _get_npcs
except ImportError:
    _get_npcs = None

try:
    import phBotChat
except ImportError:
    phBotChat = None

NAME = 'PartyGather'
VERSION = '1.0.0'
CONFIG_NAME = 'PartyGather'

# Party chat protocol (ASCII, ổn định)
PROTO_GATHER = 'gather'
PROTO_CANCEL = 'gatheroff'

# Lệnh chat tiếng Việt / tắt (normalize, không dấu)
CMD_GATHER = (
    'gather', 'toi', 'toi cho tao', 'toi cho minh',
    'tu hop', 'tuhop', 'hop', 've cho tao', 've day',
)
CMD_CANCEL = (
    'gatheroff', 'dung', 'huy', 'huy tu', 'huy gather',
    'dung gather', 'stopgather', 'cancel gather', 'stop',
)

ROLE_FOLLOWER = 0
ROLE_LEADER = 1

# Cùng region và khoảng cách ≤ ngưỡng → chỉ đi bộ (không bùa)
DEFAULT_WALK_ONLY_M = 120.0
# Coi là đã tới khi còn trong bán kính này
DEFAULT_ARRIVE_M = 8.0
# Xa hơn ngưỡng → dùng bùa cá nhân trước
DEFAULT_MOVE_NUDGE_S = 1.2
RETURN_WAIT_S = 45.0
# Sau bùa: nếu vẫn khác region lâu → báo rõ (không party TP)
DIFF_REGION_GRACE_S = 25.0

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
lock = RLock()
_ui_applying = False
loaded_config_owner = None

state = {
    'enabled': False,
    'role': ROLE_FOLLOWER,
    'leader_name': '',
    'walk_only_m': DEFAULT_WALK_ONLY_M,
    'arrive_m': DEFAULT_ARRIVE_M,
    'phase': 'idle',  # idle | returning | walking
    'target': None,  # dict region/x/y/z
    'return_used': False,
    'return_at': 0.0,
    'walk_started_at': 0.0,
    'last_nudge_at': 0.0,
    'last_status_at': 0.0,
    'diff_region_since': 0.0,
}

QtBind.createLabel(gui, '%s v%s — Tụ họp PT (đi bộ / bùa cá nhân)' % (NAME, VERSION), 10, 8)
enabled_box = QtBind.createCheckBox(gui, 'ui_enabled', 'Bật plugin', 10, 32)

QtBind.createLabel(gui, 'Vai trò', 10, 60)
role_leader_box = QtBind.createCheckBox(gui, 'ui_role_leader', 'Chủ', 10, 78)
role_follower_box = QtBind.createCheckBox(gui, 'ui_role_phu', 'Phụ', 70, 78)

QtBind.createLabel(gui, 'Tên leader (phụ theo tên này)', 150, 60)
leader_field = QtBind.createLineEdit(gui, '', 150, 78, 180, 22)
QtBind.createButton(gui, 'btn_self', 'Lấy tên mình', 340, 76)
QtBind.createButton(gui, 'btn_party_master', 'Lấy tên chủ PT', 460, 76)

QtBind.createLabel(gui, 'Đi bộ nếu gần ≤ (m)', 10, 112)
walk_field = QtBind.createLineEdit(gui, str(int(DEFAULT_WALK_ONLY_M)), 160, 110, 60, 22)
QtBind.createLabel(gui, 'Đã tới khi ≤ (m)', 240, 112)
arrive_field = QtBind.createLineEdit(gui, str(int(DEFAULT_ARRIVE_M)), 360, 110, 60, 22)

QtBind.createButton(gui, 'btn_gather', 'Tới chỗ tao (gather)', 10, 148)
QtBind.createButton(gui, 'btn_cancel', 'Hủy tụ (dung)', 200, 148)
QtBind.createButton(gui, 'btn_save', 'Lưu cấu hình', 360, 148)
QtBind.createButton(gui, 'btn_load', 'Tải cấu hình', 490, 148)

status_label = QtBind.createLabel(gui, 'Trạng thái: Phụ · chờ bật plugin', 10, 188)
help_label = QtBind.createLabel(
    gui,
    'Chủ: bấm «Tới chỗ tao» hoặc party chat: toi / gather\n'
    'Phụ: tự đi bộ; xa hoặc khác map → bùa cá nhân rồi đi bộ. KHÔNG party TP.\n'
    'Hủy: dung / huy / gatheroff',
    10, 218,
)

QtBind.setChecked(gui, role_follower_box, True)
QtBind.setChecked(gui, role_leader_box, False)


def _log(msg):
    log('[%s] %s' % (NAME, msg))


def set_status(msg, display=None):
    role = 'Chủ' if role_index() == ROLE_LEADER else 'Phụ'
    QtBind.setText(gui, status_label, 'Trạng thái: %s · %s' % (role, display or msg))
    _log(msg)


def _strip_job_star(text):
    text = str(text or '').strip()
    while text.startswith('*'):
        text = text[1:].strip()
    return text


def _fold(text):
    """Chuẩn hóa lệnh: lower, bỏ dấu tiếng Việt cơ bản, gom khoảng trắng."""
    raw = str(text or '').strip().casefold()
    # Bỏ dấu thường gặp trong lệnh chat
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
    raw = raw.translate(table)
    return ' '.join(raw.split())


def self_name():
    data = get_character_data() or {}
    for key in ('name', 'charname', 'char_name', 'character_name', 'CharName'):
        val = _strip_job_star(data.get(key) or '')
        if val:
            return val
    return ''


def self_job_name():
    data = get_character_data() or {}
    for key in ('job_name', 'jobname', 'JobName'):
        val = _strip_job_star(data.get(key) or '')
        if val:
            return val
    return ''


def self_display():
    name, job = self_name(), self_job_name()
    if name and job and name.casefold() != job.casefold():
        return '%s, %s' % (name, job)
    return name or job or ''


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


def role_index():
    if QtBind.isChecked(gui, role_leader_box):
        return ROLE_LEADER
    return ROLE_FOLLOWER


def set_role(index):
    global _ui_applying
    _ui_applying = True
    try:
        QtBind.setChecked(gui, role_leader_box, index == ROLE_LEADER)
        QtBind.setChecked(gui, role_follower_box, index != ROLE_LEADER)
    finally:
        _ui_applying = False
    with lock:
        state['role'] = index


def i_am_leader():
    return QtBind.isChecked(gui, enabled_box) and role_index() == ROLE_LEADER


def configured_leader():
    return (QtBind.text(gui, leader_field) or '').strip()


def leader_tokens():
    raw = configured_leader()
    tokens = set()
    for part in raw.replace(',', ' ').split():
        t = _strip_job_star(part).casefold()
        if t:
            tokens.add(t)
    me = self_name().casefold()
    job = self_job_name().casefold()
    if role_index() == ROLE_LEADER:
        if me:
            tokens.add(me)
        if job:
            tokens.add(job)
    return tokens


def name_is_leader(player):
    needle = _strip_job_star(player).casefold()
    if not needle:
        return False
    tokens = leader_tokens()
    if needle in tokens:
        return True
    # Khớp một phần token (job nick)
    for tok in tokens:
        if tok and (tok in needle or needle in tok):
            return True
    return False


def party_master_name():
    party = get_party()
    if not isinstance(party, dict):
        raise ValueError('Chưa vào party.')
    for member in party.values():
        if not isinstance(member, dict):
            continue
        if member.get('player_id') == member.get('master_id') or member.get('masterLevel') or member.get('isMaster'):
            name = str(member.get('name') or '').strip()
            if name:
                return name
        # phBot thường đánh dấu master bằng level âm hoặc key riêng
        if member.get('master') or member.get('leader'):
            name = str(member.get('name') or '').strip()
            if name:
                return name
    # Fallback: member có partyNumber/order 0
    best = None
    for member in party.values():
        if not isinstance(member, dict):
            continue
        name = str(member.get('name') or '').strip()
        if not name:
            continue
        order = member.get('memberNumber', member.get('number', member.get('order')))
        try:
            order = int(order)
        except (TypeError, ValueError):
            order = 99
        if best is None or order < best[0]:
            best = (order, name)
    if best:
        return best[1]
    raise ValueError('Không đọc được chủ PT từ get_party().')


def read_float_field(widget, default, lo, hi):
    try:
        val = float((QtBind.text(gui, widget) or '').strip().replace(',', '.'))
    except (TypeError, ValueError):
        val = default
    if not math.isfinite(val):
        val = default
    return max(lo, min(hi, val))


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
        return True  # thiếu region → không chặn đi bộ
    return ra == rb


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


def soft_stop_trace():
    if _stop_trace is None:
        return
    try:
        _stop_trace()
    except Exception:
        pass


def personal_return_scroll():
    """Chỉ bùa về thành CÁ NHÂN. Không party TP / group warp."""
    if _use_return_scroll is None:
        set_status('phBot thiếu use_return_scroll — chỉ đi bộ được.')
        return False
    try:
        ok = _use_return_scroll()
    except Exception as error:
        set_status('Bùa cá nhân lỗi: %s' % error)
        return False
    return ok is not False


def nearest_teleporter_npc(me, max_range=80.0):
    """NPC teleporter gần nhất (đi bộ tới điểm portal) — không inject party TP."""
    if _get_npcs is None or not me:
        return None
    try:
        npcs = _get_npcs() or {}
    except Exception:
        return None
    best = None
    for npc in npcs.values():
        if not isinstance(npc, dict):
            continue
        name = str(npc.get('name') or npc.get('servername') or '').casefold()
        # Heuristic: teleporter / cổng / portal
        if not any(k in name for k in ('teleport', 'portal', 'gate', 'cong', 'cổng', 'thuyen', 'ferry')):
            # Một số server chỉ có model type; bỏ qua nếu không có tên khớp
            if 'tele' not in name and 'warp' not in name:
                continue
        try:
            dist = math.hypot(float(npc['x']) - float(me['x']), float(npc['y']) - float(me['y']))
        except (KeyError, TypeError, ValueError):
            continue
        if dist > max_range:
            continue
        if best is None or dist < best[0]:
            best = (dist, {
                'x': float(npc['x']),
                'y': float(npc['y']),
                'z': float(npc.get('z') or me.get('z') or 0),
                'name': str(npc.get('name') or ''),
            })
    return best[1] if best else None


def clear_gather(reason=''):
    with lock:
        state['phase'] = 'idle'
        state['target'] = None
        state['return_used'] = False
        state['return_at'] = 0.0
        state['walk_started_at'] = 0.0
        state['diff_region_since'] = 0.0
    if reason:
        set_status('Đã hủy tụ · %s' % reason, 'Đã hủy')
    else:
        set_status('Đã hủy tụ.', 'Đã hủy')


def begin_gather(target, source='cmd'):
    """Phụ bắt đầu tụ về target {region,x,y,z}."""
    if not target:
        set_status('[%s] Thiếu tọa độ chủ.' % source)
        return
    soft_stop_trace()
    me = current_pos()
    walk_only = read_float_field(walk_field, DEFAULT_WALK_ONLY_M, 20.0, 2000.0)
    dist = distance_xy(me, target)
    can_walk_only = bool(me and same_region(me, target) and dist is not None and dist <= walk_only)

    with lock:
        state['target'] = dict(target)
        state['return_used'] = False
        state['return_at'] = 0.0
        state['diff_region_since'] = 0.0
        state['last_nudge_at'] = 0.0
        state['walk_started_at'] = monotonic()

    if can_walk_only:
        with lock:
            state['phase'] = 'walking'
        set_status(
            '[%s] Cùng map · %.0fm ≤ %.0fm → đi bộ tới chủ (%.0f, %.0f).'
            % (source, dist, walk_only, target['x'], target['y']),
            'Đang đi bộ')
        nudge_move(target, force=True)
        return

    # Xa hoặc khác region → bùa cá nhân (không party TP)
    with lock:
        state['phase'] = 'returning'
        state['return_used'] = True
        state['return_at'] = monotonic()
    reason = 'khác map' if (me and not same_region(me, target)) else 'xa %.0fm' % (dist or -1)
    set_status(
        '[%s] %s → bùa về thành CÁ NHÂN rồi đi bộ. (không party TP)'
        % (source, reason),
        'Đang bùa cá nhân')
    if not personal_return_scroll():
        # Không bùa được: thử đi bộ tới portal gần nhất rồi vẫn walk
        portal = nearest_teleporter_npc(me) if me else None
        if portal:
            with lock:
                state['phase'] = 'walking'
            set_status(
                'Không bùa được · đi bộ tới portal gần «%s» rồi tới chủ.'
                % (portal.get('name') or '?'),
                'Tới portal')
            nudge_move(portal, force=True)
        else:
            with lock:
                state['phase'] = 'walking'
            set_status(
                'Không bùa được · thử đi bộ thẳng tới chủ (không party TP).',
                'Đi bộ')
            nudge_move(target, force=True)


def nudge_move(dest, force=False):
    if not dest:
        return False
    now = monotonic()
    with lock:
        if not force and (now - state['last_nudge_at']) < DEFAULT_MOVE_NUDGE_S:
            return False
        state['last_nudge_at'] = now
    try:
        z = float(dest.get('z') or 0)
        ok = move_to(float(dest['x']), float(dest['y']), z)
    except Exception as error:
        set_status('move_to lỗi: %s' % error)
        return False
    return ok is not False


def leader_broadcast_gather():
    if not i_am_leader():
        set_status('Chỉ Chủ mới phát lệnh tụ.')
        return False
    me = current_pos()
    if not me:
        set_status('Chưa đọc được vị trí mình.')
        return False
    msg = '%s#%d#%.2f#%.2f#%.2f' % (
        PROTO_GATHER, int(me['region']), me['x'], me['y'], me['z'])
    if party_chat(msg):
        set_status(
            'Đã phát tụ → region=%d (%.0f, %.0f, %.0f)'
            % (me['region'], me['x'], me['y'], me['z']),
            'Đã phát gather')
        return True
    return False


def leader_broadcast_cancel():
    if not i_am_leader():
        # Phụ vẫn được hủy local
        clear_gather('local')
        return True
    ok = party_chat(PROTO_CANCEL)
    clear_gather('chủ hủy')
    if ok:
        set_status('Đã phát hủy tụ (gatheroff).', 'Đã hủy')
    return ok


def parse_gather_msg(text):
    """Trả về ('gather', target_dict) | ('cancel', None) | None."""
    raw = str(text or '').strip()
    if not raw:
        return None
    # Protocol có tọa độ
    if '#' in raw:
        parts = raw.split('#')
        head = parts[0].strip().casefold()
        if head == PROTO_CANCEL or _fold(head) in CMD_CANCEL:
            return 'cancel', None
        if head == PROTO_GATHER or _fold(head) in ('toi', 'gather', 'tu hop', 'tuhop'):
            if len(parts) >= 5:
                try:
                    target = {
                        'region': int(float(parts[1])),
                        'x': float(parts[2]),
                        'y': float(parts[3]),
                        'z': float(parts[4]),
                    }
                    return 'gather', target
                except (TypeError, ValueError):
                    return None
            return 'gather', None  # thiếu tọa độ — phụ lấy từ party
    norm = _fold(raw)
    if norm in CMD_CANCEL:
        return 'cancel', None
    if norm in CMD_GATHER:
        return 'gather', None
    return None


def leader_xy_from_party():
    """Fallback: tọa độ chủ từ get_party theo tên đã lưu."""
    tokens = leader_tokens()
    if not tokens:
        return None
    party = get_party()
    if not isinstance(party, dict):
        return None
    for member in party.values():
        if not isinstance(member, dict):
            continue
        name = _strip_job_star(member.get('name') or '').casefold()
        if not name or name not in tokens:
            continue
        try:
            return {
                'region': int(member.get('region') or 0),
                'x': float(member['x']),
                'y': float(member['y']),
                'z': float(member.get('z') or 0),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return None


def handle_gather_command(kind, target, source):
    if kind == 'cancel':
        clear_gather(source)
        return
    if kind != 'gather':
        return
    if i_am_leader():
        # Chủ gõ toi/gather → broadcast vị trí hiện tại
        leader_broadcast_gather()
        return
    # Phụ
    if target is None:
        target = leader_xy_from_party()
        if not target:
            set_status('[%s] Phụ chưa có tọa độ chủ — nhập tên leader / chờ gather#region#x#y#z.'
                       % source)
            return
    begin_gather(target, source=source)


# --- UI ---

def ui_enabled(checked):
    if _ui_applying:
        with lock:
            state['enabled'] = bool(checked)
        return
    with lock:
        state['enabled'] = bool(checked)
    if not checked:
        clear_gather('tắt plugin')
    set_status('Đã bật.' if checked else 'Đã tắt.')


def ui_role_leader(checked):
    if _ui_applying:
        return
    if checked:
        set_role(ROLE_LEADER)
        me = self_display() or self_name()
        if me and not configured_leader():
            QtBind.setText(gui, leader_field, me)
        set_status('Vai trò Chủ.')
    elif not QtBind.isChecked(gui, role_follower_box):
        set_role(ROLE_FOLLOWER)


def ui_role_phu(checked):
    if _ui_applying:
        return
    if checked:
        set_role(ROLE_FOLLOWER)
        set_status('Vai trò Phụ.')
    elif not QtBind.isChecked(gui, role_leader_box):
        set_role(ROLE_LEADER)


def btn_self():
    me = self_display() or self_name()
    if not me:
        set_status('Chưa đọc được tên. Vào game rồi bấm lại.')
        return
    QtBind.setText(gui, leader_field, me)
    set_role(ROLE_LEADER)
    set_status('Đã điền tên mình %r · Chủ. Bấm Lưu.' % me)


def btn_party_master():
    try:
        name = party_master_name()
    except ValueError as error:
        set_status(str(error))
        return
    QtBind.setText(gui, leader_field, name)
    set_role(ROLE_FOLLOWER)
    set_status('Đã điền chủ PT %r · Phụ. Bấm Lưu.' % name)


def btn_gather():
    if not QtBind.isChecked(gui, enabled_box):
        set_status('Bật plugin trước.')
        return
    if i_am_leader():
        leader_broadcast_gather()
    else:
        # Phụ tự tụ về vị trí chủ party (không cần chat)
        target = leader_xy_from_party()
        if not target:
            set_status('Phụ: chưa thấy tọa độ chủ trong party.')
            return
        begin_gather(target, source='UI phụ')


def btn_cancel():
    if i_am_leader():
        leader_broadcast_cancel()
    else:
        clear_gather('UI')


def read_settings():
    return {
        'plugin_version': VERSION,
        'enabled': QtBind.isChecked(gui, enabled_box),
        'role': role_index(),
        'leader_name': configured_leader(),
        'walk_only_m': read_float_field(walk_field, DEFAULT_WALK_ONLY_M, 20.0, 2000.0),
        'arrive_m': read_float_field(arrive_field, DEFAULT_ARRIVE_M, 3.0, 50.0),
    }


def apply_settings(data):
    global _ui_applying
    data = data or {}
    enabled = bool(data.get('enabled'))
    role = ROLE_LEADER if int(data.get('role', 0) or 0) == ROLE_LEADER else ROLE_FOLLOWER
    leader_name = str(data.get('leader_name') or '').strip()
    walk_only = float(data.get('walk_only_m') or DEFAULT_WALK_ONLY_M)
    arrive = float(data.get('arrive_m') or DEFAULT_ARRIVE_M)
    _ui_applying = True
    try:
        QtBind.setChecked(gui, enabled_box, enabled)
        QtBind.setChecked(gui, role_leader_box, role == ROLE_LEADER)
        QtBind.setChecked(gui, role_follower_box, role == ROLE_FOLLOWER)
        QtBind.setText(gui, leader_field, leader_name)
        QtBind.setText(gui, walk_field, str(int(walk_only)))
        QtBind.setText(gui, arrive_field, str(int(arrive)))
    finally:
        _ui_applying = False
    with lock:
        state['enabled'] = enabled
        state['role'] = role
        state['leader_name'] = leader_name
        state['walk_only_m'] = walk_only
        state['arrive_m'] = arrive


def btn_save():
    global loaded_config_owner
    try:
        owner = config_owner()
        path = config_path(owner)
        data = read_settings()
        if data['role'] == ROLE_LEADER and not data['leader_name']:
            me = self_display() or self_name()
            if me:
                data['leader_name'] = me
                QtBind.setText(gui, leader_field, me)
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
        set_status('Đã lưu %s' % path.name, 'Đã lưu')
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
            set_status('Chưa có bản lưu. Chọn Chủ/Phụ rồi Lưu.')
        return None
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        apply_settings({})
        if not quiet:
            set_status('Chưa tải: %s' % error)
        return None


def btn_load():
    load_settings(quiet=False)


# --- phBot hooks ---

def handle_chat(chat_type, player, msg):
    if not QtBind.isChecked(gui, enabled_box):
        return
    if int(chat_type or 0) == 11 and msg and ': ' in str(msg):
        msg = str(msg).split(': ', 1)[1]
    text = str(msg or '').strip()
    if not text:
        return
    parsed = parse_gather_msg(text)
    if not parsed:
        return
    kind, target = parsed
    # Chỉ nhận lệnh từ leader (hoặc chính chủ gõ)
    from_leader = name_is_leader(player) or i_am_leader() or int(chat_type or 0) == 100
    # Party chat type thường = 4; vẫn yêu cầu tên khớp trừ khi là protocol gather# từ party
    if not from_leader:
        # Cho phép protocol gather#... nếu người gửi khớp token leader
        if not name_is_leader(player):
            return
    handle_gather_command(kind, target, source='chat')


def event_loop():
    global loaded_config_owner
    owner = config_owner()
    if owner is not None and owner != loaded_config_owner:
        load_settings(quiet=False)
    if not QtBind.isChecked(gui, enabled_box):
        return
    with lock:
        phase = state['phase']
        target = dict(state['target']) if state['target'] else None
        return_at = state['return_at']
        return_used = state['return_used']
    if phase == 'idle' or not target:
        return

    me = current_pos()
    arrive_m = read_float_field(arrive_field, DEFAULT_ARRIVE_M, 3.0, 50.0)
    now = monotonic()

    if phase == 'returning':
        # Chờ teleported(); nếu quá hạn vẫn chuyển sang đi bộ
        if now - return_at >= RETURN_WAIT_S:
            with lock:
                state['phase'] = 'walking'
                state['walk_started_at'] = now
            set_status('Hết chờ bùa · chuyển đi bộ tới chủ.', 'Đi bộ')
            nudge_move(target, force=True)
        return

    # walking
    if not me:
        return
    dist = distance_xy(me, target)
    if dist is not None and same_region(me, target) and dist <= arrive_m:
        clear_gather()
        set_status('Đã tới chỗ chủ (%.1fm).' % dist, 'Đã tới')
        return

    if not same_region(me, target):
        with lock:
            if state['diff_region_since'] <= 0:
                state['diff_region_since'] = now
            since = state['diff_region_since']
        if return_used and (now - since) >= DIFF_REGION_GRACE_S:
            # Sau bùa cá nhân vẫn khác region lâu — không party TP
            with lock:
                last_st = state['last_status_at']
                spam = (now - last_st) > 5
                if spam:
                    state['last_status_at'] = now
            if spam:
                set_status(
                    'khác map — không dịch chuyển nhóm (chỉ bùa cá nhân + đi bộ). '
                    'region mình=%s chủ=%s' % (me.get('region'), target.get('region')),
                    'Khác map')
            # Thử đi tới portal gần (đi bộ), không inject group warp
            portal = nearest_teleporter_npc(me)
            if portal:
                nudge_move(portal)
            return
    else:
        with lock:
            state['diff_region_since'] = 0.0

    nudge_move(target)


def teleported():
    """Sau bùa cá nhân → chuyển sang đi bộ tới chỗ chủ."""
    with lock:
        if state['phase'] != 'returning' or not state['target']:
            return
        target = dict(state['target'])
        state['phase'] = 'walking'
        state['walk_started_at'] = monotonic()
        state['last_nudge_at'] = 0.0
        state['diff_region_since'] = 0.0
    set_status('Đã về thành (bùa cá nhân) · đi bộ tới chủ.', 'Đi bộ')
    nudge_move(target, force=True)


def joined_game():
    data = load_settings(quiet=False)
    if role_index() == ROLE_LEADER and not configured_leader():
        me = self_display() or self_name()
        if me:
            QtBind.setText(gui, leader_field, me)
    if data and data.get('enabled'):
        _log('joined_game: auto-bật từ cấu hình.')


try:
    _boot = load_settings(quiet=True)
    if _boot is not None:
        set_status('Nạp v%s · đã restore cấu hình' % VERSION, 'Đã tải')
except Exception as _boot_error:
    _log('Nạp v%s · restore lỗi: %s' % (VERSION, _boot_error))

log('[%s] Đã nạp v%s. Chủ: toi/gather · Phụ: đi bộ hoặc bùa cá nhân · Hủy: dung/gatheroff. KHÔNG party TP.'
    % (NAME, VERSION))
