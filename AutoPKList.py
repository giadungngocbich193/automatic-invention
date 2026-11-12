# -*- coding: utf-8 -*-
"""AutoPKList — một tab vận hành 6 chế độ Auto PK (phBot Stable / QtBind).

Không thay thế AutoGhost / AutoKS / PartyLeader / GhostFarm.
Tab này: panel điều khiển + giải thích cơ chế + trạng thái live / cần plugin khác.
Combat Ghost / KS / phát target vẫn chạy ở plugin gốc khi đã nạp.

Changelog:
- v1.1.0: Panel đủ 6 mode (swap view), shared scan, JSON config, probe plugin stack.
- v1.0.0: prototype chỉ xem/quét (docs/uploads).
"""
from __future__ import print_function

import hashlib
import json
import math
import sys
from pathlib import Path

import QtBind
import phBot as bot
from phBot import get_config_dir, log

NAME = 'AutoPKList'
VERSION = '1.1.0'
CONFIG_NAME = 'AutoPKList'

MODE_ANCHOR = '1. Đánh theo tọa độ'
MODE_LEADER = '2. Đánh theo Leader / Follow KS'
MODE_PUBLISH = '3. Phát target Leader'
MODE_DEFEND = '4. Tím / Đỏ / Job đối địch'
MODE_EXCHANGE = '5. Trao đổi và Ghost Boss nền'
MODE_COMMANDS = '6. Lệnh tham chiếu SroPlus / ChatControl'
MODES = (
    MODE_ANCHOR, MODE_LEADER, MODE_PUBLISH,
    MODE_DEFEND, MODE_EXCHANGE, MODE_COMMANDS,
)

# View keys match MODES order.
VIEW_BY_MODE = {
    MODE_ANCHOR: 'm1',
    MODE_LEADER: 'm2',
    MODE_PUBLISH: 'm3',
    MODE_DEFEND: 'm4',
    MODE_EXCHANGE: 'm5',
    MODE_COMMANDS: 'm6',
}

STATUS_LIVE = 'LIVE trong tab này'
STATUS_NEEDS = 'CẦN plugin khác để combat thật'
STATUS_REF = 'Tham chiếu (không inject)'

FLOW = {
    MODE_ANCHOR: (
        'CƠ CHẾ: đứng điểm chờ → quét người trong bán kính → khóa địch → Ghost F → hết đuổi → về điểm chờ.',
        'Ai làm: 1 acc solo (hoặc phụ sau khi đã có target).',
        'F / gói: Target Enemy (7045) · Ghost F1–F3 · NativeCut 7081 sau B070 · F4/X dừng.',
        'Ưu tiên: nếu Mode 2/3 đang Follow/Leader target → target Leader thắng local Auto PK.',
        'TRẠNG THÁI: quét/tọa độ/F LIVE tại tab · combat Auto PK = CẦN AutoGhost (tab Auto PK / ghep-2.6).',
    ),
    MODE_LEADER: (
        'CƠ CHẾ: Phụ bật Follow KS · nhận !aks / ksgo từ Chủ · trace Chủ · Ghost cùng UID.',
        'Ai làm: Chủ phát lệnh · Phụ nhận + Ghost.',
        'F / lệnh: Chủ F3=!aks go · F4=clear · F1/F2/3 arm PvP Chủ · party !aks target/go/hit/clear.',
        'Song song: PartyLeader Phụ + sync F + arm AutoGhost Auto PK.',
        'TRẠNG THÁI: cấu hình/quét LIVE · phiên KS thật = CẦN AutoKS (ghep-2.6 Bật Auto KS) hoặc PartyLeader Phụ.',
    ),
    MODE_PUBLISH: (
        'CƠ CHẾ: Chủ chọn địch → chat party ks#UID → Phụ khóa UID (đợi B045) → Chủ F1/F2 → ksgo → Phụ Ghost Prefer.',
        'Ai làm: Chủ = PartyLeader vai trò Chủ · Phụ = PartyLeader Phụ + AutoGhost.',
        'F / chat: ks#UID · ksgo#F#UID · dungdanh / F4 · ks#0 clear.',
        'Prefer: áp sát ≤6m trước cast · B074 03 00 04 40 = OOR.',
        'TRẠNG THÁI: checklist/lệnh LIVE · phát target thật = CẦN PartyLeader ≥2.0.1 + AutoGhost ≥2.3.1.',
    ),
    MODE_DEFEND: (
        'CƠ CHẾ: filter địch đỏ/tím/job · bỏ Party/Guild · không đánh vàng/xanh/trắng soft.',
        'Ai làm: acc đang canh (thường cùng Mode 1 Auto PK).',
        'Quét tab này: hiện cờ API thô (pvp/pk/job_…) — cờ thô ≠ quyết định combat.',
        'Combat filter thật nằm trong AutoGhost Auto PK (Target Enemy + skip Party/Guild).',
        'TRẠNG THÁI: quét cờ LIVE · filter combat = CẦN AutoGhost.',
    ),
    MODE_EXCHANGE: (
        'CƠ CHẾ Ghost: 7074 cast → chờ S→C B070 → Timer(ms) → NativeCut self 7081 → kỳ vọng B074 02 00.',
        'CẤM: cut 0ms từ 7074 (abort cast / Ghost fail). Cut self only sau B070.',
        'PvP: AutoGhost tab PvP dãy ID=ms · Boss/farm: GhostFarm / Probe.',
        'Đo ms: ghep-2.6 strip Đo ngắt ms · ghi cut vào F1.',
        'TRẠNG THÁI: quy tắc + checklist LIVE · cut thật = CẦN AutoGhost / GhostFarm / GhostNativeProbe.',
    ),
    MODE_COMMANDS: (
        'CƠ CHẾ: bảng map lệnh SroPlus/ChatControl → stack Project hiện tại.',
        'Không gửi chat / không inject từ tab này.',
        'Set k/kk ≈ Bật/Dừng Auto PK · Set f/ff ≈ AutoKS / PartyLeader.',
        'F5 pause Ghost (SroPlus) ≈ bấm lại F1–F3 / Dừng Ghost.',
        'TRẠNG THÁI: ' + STATUS_REF + ' — luôn dùng được trong tab.',
    ),
}

COMMAND_ROWS = (
    'Set k / Set kk (ChatControl Auto PK) → AutoGhost Bật Auto PK / Dừng canh',
    'Set f / Set ff (Follow KS) → AutoKS Bật Auto KS hoặc PartyLeader Bật plugin + sync',
    'F5 pause Ghost (SroPlus) → F1–F3 bấm lại / Dừng Ghost (AutoGhost)',
    'F6/F7 pause Leader (SroPlus) → Chủ F4 / party dungdanh (PartyLeader)',
    'F3 Chủ (AutoKS) → !aks go <UID> · Phụ Ghost',
    'F4 Chủ (AutoKS/PL) → clear / dừng Phụ',
    'F1/F2/3 Chủ → arm / ksgo#F#UID (tuỳ plugin)',
    'party ks#UID → Phụ khóa target · ks#0 / ks clear → clear',
    'party ksgo#F#UID → Phụ ARM + Prefer Ghost',
    'Boss ESC 7005/7006 (SroPlus) → KHÔNG dùng cho Ghost PvP Project (dùng 7081 NativeCut)',
    '7081 = Exchange/Ghost self · B070 = confirm skill · B074 02 00 = ngắt OK',
    'B074 03 00 04 40 = từ chối (OOR/busy) · Prefer cần ≤6m',
    '0ms cut ngay 7074 = SAI · Timer(ms) sau B070 rồi mới cut',
)

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
ui_views = {}
_ui_view = 'm1'
anchor = None
loaded_owner = None


def widget(view, kind, *args):
    handle = getattr(QtBind, kind)(gui, *args)
    offset = -4 if kind in ('createLineEdit', 'createCombobox', 'createList') else -2
    if offset == -2:
        x, y = args[-2:]
    else:
        x, y = args[offset:offset + 2]
    ui_views.setdefault(view, []).append((handle, x, y))
    return handle


def show_view(view):
    global _ui_view
    _ui_view = view
    for name, controls in ui_views.items():
        visible = name == view
        for handle, x, y in controls:
            QtBind.move(gui, handle, x if visible else -10000, y)


def _log(message):
    log('[%s] %s' % (NAME, message))


def set_status(message):
    QtBind.setText(gui, status_field, message)


def render_list(lines):
    QtBind.clear(gui, list_field)
    for line in lines:
        QtBind.append(gui, list_field, line)


def records(api_name):
    getter = getattr(bot, api_name, None)
    if not callable(getter):
        return {}
    value = getter()
    return value if isinstance(value, dict) else {}


def find_plugin(name):
    best = None
    for module in list(sys.modules.values()):
        if getattr(module, 'NAME', None) != name:
            continue
        best = module
    return best


def plugin_status_line(name, detail_ok, detail_miss):
    module = find_plugin(name)
    if module is None:
        return '• %s: CHƯA nạp — %s' % (name, detail_miss)
    version = getattr(module, 'VERSION', '?')
    return '• %s v%s: đã nạp — %s' % (name, version, detail_ok)


def stack_status_lines(mode):
    lines = ['— Trạng thái stack (probe sys.modules) —']
    if mode == MODE_ANCHOR:
        lines.append(plugin_status_line(
            'AutoGhost', 'có thể Bật Auto PK trên tab AutoGhost',
            'combat tọa độ chưa chạy được'))
        lines.append('• Tab này: LIVE quét / điểm chờ / bán kính / nhóm F (config).')
    elif mode == MODE_LEADER:
        lines.append(plugin_status_line(
            'AutoGhost', 'engine Ghost cho Phụ/Chủ',
            'Follow KS không Ghost được'))
        # AutoKS may live inside ghep as NAME AutoKS via exec — also check module attr
        aks = find_plugin('AutoKS')
        if aks is None:
            ghost = find_plugin('AutoGhost')
            # ghep embeds AutoKS; detect by AutoKS helpers if present
            if ghost is not None and (
                    callable(getattr(ghost, 'prepare_ks_pvp', None))
                    or 'AutoKS' in str(getattr(ghost, 'VERSION', ''))
                    or hasattr(ghost, 'view_auto_ks')):
                lines.append('• AutoKS: có dấu hiệu ghep trong AutoGhost — mở strip AutoKS, Bật Auto KS.')
            else:
                lines.append('• AutoKS: CHƯA thấy — cần ghep-2.6 (strip AutoKS) hoặc bản có AutoKS.')
        else:
            lines.append('• AutoKS v%s: đã nạp — session = Bật Auto KS (không tick tab).' %
                         getattr(aks, 'VERSION', '?'))
        lines.append(plugin_status_line(
            'PartyLeader', 'Phụ sync/arm thay hoặc song song AutoKS',
            'thiếu Follow thay thế qua PL'))
        lines.append('• Tab này: LIVE chọn Leader / vai trò / checklist — không tự bật KS.')
    elif mode == MODE_PUBLISH:
        lines.append(plugin_status_line(
            'PartyLeader', 'Chủ chat ks# / ksgo',
            'không phát target được'))
        lines.append(plugin_status_line(
            'AutoGhost', 'Phụ Prefer + Ghost',
            'Phụ không arm/prefer được'))
        lines.append('• Tab này: LIVE checklist + bảng lệnh — không gửi party chat hộ.')
    elif mode == MODE_DEFEND:
        lines.append(plugin_status_line(
            'AutoGhost', 'filter địch + Auto PK',
            'chỉ còn quét cờ thô tại tab này'))
        lines.append('• Tab này: LIVE Quét người + lọc hiển thị cờ.')
    elif mode == MODE_EXCHANGE:
        lines.append(plugin_status_line(
            'AutoGhost', 'Ghost PvP / Đo ms / Boss path',
            'không cut PvP được từ tab này'))
        lines.append(plugin_status_line(
            'GhostFarm', 'farm Ghost overlapping',
            'farm nền cần nạp GhostFarm'))
        lines.append('• Tab này: LIVE quy tắc B070→Timer→7081 + checklist — không NativeCut.')
    else:
        lines.append('• Không phụ thuộc plugin combat — bảng lệnh luôn LIVE.')
    return lines


# ---- shared header / tools (always visible) ----
QtBind.createLabel(gui, 'AUTO PK · Vận hành (%s v%s)' % (NAME, VERSION), 10, 8)
QtBind.createLabel(gui, 'Chế độ', 10, 34)
mode_field = QtBind.createCombobox(gui, 62, 30, 300, 22)
for mode in MODES:
    QtBind.append(gui, mode_field, mode)
QtBind.setText(gui, mode_field, MODE_ANCHOR)
QtBind.createButton(gui, 'open_mode_panel', 'Mở panel', 372, 29)
QtBind.createButton(gui, 'show_flow', 'Cơ chế', 462, 29)
QtBind.createButton(gui, 'refresh_stack', 'Probe stack', 540, 29)
QtBind.createButton(gui, 'save_config', 'Lưu', 640, 29)
QtBind.createButton(gui, 'load_config', 'Tải', 690, 29)

QtBind.createLabel(gui, 'Leader', 10, 60)
leader_field = QtBind.createCombobox(gui, 62, 56, 170, 22)
QtBind.createButton(gui, 'scan_party', 'Quét Party', 242, 55)
QtBind.createLabel(gui, 'Quét m', 340, 60)
scan_field = QtBind.createLineEdit(gui, '60', 390, 56, 40, 21)
QtBind.createLabel(gui, 'Đánh m', 440, 60)
attack_field = QtBind.createLineEdit(gui, '40', 492, 56, 40, 21)
QtBind.createLabel(gui, 'Nhóm', 542, 60)
page_field = QtBind.createCombobox(gui, 582, 56, 56, 22)
for page in ('F1', 'F2', 'F3'):
    QtBind.append(gui, page_field, page)
QtBind.setText(gui, page_field, 'F2')
QtBind.createButton(gui, 'capture_anchor', 'Lấy tọa độ', 10, 84)
QtBind.createButton(gui, 'scan_people', 'Quét người', 112, 84)
anchor_label = QtBind.createLabel(gui, 'Điểm chờ: chưa lấy', 220, 88)
help_line = QtBind.createLabel(gui, '', 10, 112)

# Mode panels y≈132–230; list below.
PANEL_Y = 132

# ---- Mode 1: tọa độ ----
widget('m1', 'createLabel', 'Panel 1 · Đánh theo tọa độ', 10, PANEL_Y)
widget('m1', 'createLabel', 'X tâm', 10, PANEL_Y + 24)
m1_x = widget('m1', 'createLineEdit', '', 55, PANEL_Y + 20, 70, 21)
widget('m1', 'createLabel', 'Y tâm', 140, PANEL_Y + 24)
m1_y = widget('m1', 'createLineEdit', '', 185, PANEL_Y + 20, 70, 21)
widget('m1', 'createButton', 'm1_use_anchor', 'Dùng điểm chờ', 270, PANEL_Y + 19)
widget('m1', 'createButton', 'm1_fill_flow', 'Hiện cơ chế + status', 400, PANEL_Y + 19)
widget('m1', 'createLabel', 'Target Enemy (gợi ý phím)', 10, PANEL_Y + 48)
m1_enemy_key = widget('m1', 'createLineEdit', 'Home', 170, PANEL_Y + 44, 80, 21)
m1_skip_party = widget('m1', 'createCheckBox', 'noop_check', 'Bỏ Party', 270, PANEL_Y + 46)
m1_skip_guild = widget('m1', 'createCheckBox', 'noop_check', 'Bỏ Guild', 360, PANEL_Y + 46)
QtBind.setChecked(gui, m1_skip_party, True)
QtBind.setChecked(gui, m1_skip_guild, True)
m1_status = widget('m1', 'createLabel',
                   'LIVE: quét/tọa độ · Combat: CẦN AutoGhost → tab Auto PK → Bật Auto PK',
                   10, PANEL_Y + 72)

# ---- Mode 2: Follow KS ----
widget('m2', 'createLabel', 'Panel 2 · Follow KS / Leader', 10, PANEL_Y)
widget('m2', 'createLabel', 'Vai trò cấu hình', 10, PANEL_Y + 24)
m2_role = widget('m2', 'createCombobox', 130, PANEL_Y + 20, 100, 22)
for item in ('Phụ', 'Chủ'):
    QtBind.append(gui, m2_role, item)
QtBind.setText(gui, m2_role, 'Phụ')
widget('m2', 'createLabel', 'Tên Chủ', 250, PANEL_Y + 24)
m2_leader = widget('m2', 'createLineEdit', '', 310, PANEL_Y + 20, 150, 21)
widget('m2', 'createButton', 'm2_from_party', 'Từ Party', 470, PANEL_Y + 19)
widget('m2', 'createButton', 'm2_fill_flow', 'Hiện cơ chế + status', 560, PANEL_Y + 19)
m2_want_aks = widget('m2', 'createCheckBox', 'noop_check', 'Dùng AutoKS (ghep)', 10, PANEL_Y + 48)
m2_want_pl = widget('m2', 'createCheckBox', 'noop_check', 'Dùng PartyLeader Phụ', 180, PANEL_Y + 48)
QtBind.setChecked(gui, m2_want_aks, True)
m2_status = widget('m2', 'createLabel',
                   'LIVE: cấu hình · Combat KS: CẦN AutoKS Bật Auto KS hoặc PartyLeader Phụ',
                   10, PANEL_Y + 72)

# ---- Mode 3: phát target ----
widget('m3', 'createLabel', 'Panel 3 · Phát target Leader (Chủ)', 10, PANEL_Y)
m3_broadcast = widget('m3', 'createCheckBox', 'noop_check', 'Chủ: chat ks#UID khi chọn', 10, PANEL_Y + 24)
m3_sync = widget('m3', 'createCheckBox', 'noop_check', 'Đồng bộ F1/F2 → ksgo', 250, PANEL_Y + 24)
QtBind.setChecked(gui, m3_broadcast, True)
QtBind.setChecked(gui, m3_sync, True)
widget('m3', 'createButton', 'm3_fill_flow', 'Hiện cơ chế + lệnh', 10, PANEL_Y + 48)
widget('m3', 'createButton', 'm3_show_cmds', 'Bảng lệnh Chủ', 200, PANEL_Y + 48)
m3_status = widget('m3', 'createLabel',
                   'LIVE: checklist · Phát thật: CẦN PartyLeader (Chủ) + AutoGhost trên Phụ',
                   10, PANEL_Y + 72)

# ---- Mode 4: filter ----
widget('m4', 'createLabel', 'Panel 4 · Filter tím / đỏ / job (quét + đối chiếu)', 10, PANEL_Y)
m4_show_pvp = widget('m4', 'createCheckBox', 'noop_check', 'Ưu tiên hiện pvp/pk', 10, PANEL_Y + 24)
m4_show_job = widget('m4', 'createCheckBox', 'noop_check', 'Hiện job_*', 180, PANEL_Y + 24)
m4_only_flagged = widget('m4', 'createCheckBox', 'noop_check', 'Chỉ dòng có cờ', 300, PANEL_Y + 24)
QtBind.setChecked(gui, m4_show_pvp, True)
QtBind.setChecked(gui, m4_show_job, True)
widget('m4', 'createButton', 'scan_people', 'Quét lại', 10, PANEL_Y + 48)
widget('m4', 'createButton', 'm4_fill_flow', 'Hiện cơ chế + status', 120, PANEL_Y + 48)
m4_status = widget('m4', 'createLabel',
                   'LIVE: quét cờ thô · Filter combat: CẦN AutoGhost Auto PK',
                   10, PANEL_Y + 72)

# ---- Mode 5: exchange / ghost ----
widget('m5', 'createLabel', 'Panel 5 · Ghost / Exchange / Boss nền', 10, PANEL_Y)
widget('m5', 'createLabel', 'Dãy mẫu ID=ms (sau B070)', 10, PANEL_Y + 24)
m5_skills = widget('m5', 'createLineEdit',
                   '80031=100;66007=550;54016=100;81019=550',
                   200, PANEL_Y + 20, 420, 21)
widget('m5', 'createButton', 'm5_fill_flow', 'Hiện cơ chế cut', 10, PANEL_Y + 48)
widget('m5', 'createButton', 'm5_show_checklist', 'Checklist nạp plugin', 160, PANEL_Y + 48)
m5_status = widget('m5', 'createLabel',
                   'LIVE: quy tắc · Cut thật: CẦN AutoGhost / GhostFarm / Probe — không cut từ tab này',
                   10, PANEL_Y + 72)

# ---- Mode 6: commands ----
widget('m6', 'createLabel', 'Panel 6 · Lệnh tham chiếu (không inject)', 10, PANEL_Y)
widget('m6', 'createButton', 'm6_show_cmds', 'Hiện bảng lệnh', 10, PANEL_Y + 24)
widget('m6', 'createButton', 'm6_fill_flow', 'Hiện cơ chế map', 160, PANEL_Y + 24)
m6_status = widget('m6', 'createLabel',
                   'LIVE tham chiếu trong list — không gửi chat / không giả inject',
                   10, PANEL_Y + 72)

list_field = QtBind.createList(gui, 10, 230, 720, 110)
status_field = QtBind.createLabel(
    gui, 'Chọn chế độ → Mở panel. Cơ chế + Probe stack cho biết còn hoạt động không.', 10, 348)


def noop_check(_checked=False):
    return None


def current_mode():
    mode = QtBind.text(gui, mode_field)
    return mode if mode in VIEW_BY_MODE else MODE_ANCHOR


def set_help(mode):
    first = FLOW.get(mode, FLOW[MODE_ANCHOR])[0]
    QtBind.setText(gui, help_line, first[:110] + ('…' if len(first) > 110 else ''))


def show_mode_bundle(mode, extra=None):
    lines = list(FLOW.get(mode, FLOW[MODE_ANCHOR]))
    lines.append('')
    lines.extend(stack_status_lines(mode))
    if extra:
        lines.append('')
        lines.extend(extra)
    render_list(lines)
    set_help(mode)
    set_status('Panel: %s' % mode)


def open_mode_panel():
    mode = current_mode()
    show_view(VIEW_BY_MODE[mode])
    show_mode_bundle(mode)
    # Sync leader line into mode2 field when opening
    if mode == MODE_LEADER:
        name = QtBind.text(gui, leader_field) or ''
        if name and not (QtBind.text(gui, m2_leader) or '').strip():
            QtBind.setText(gui, m2_leader, name)


def show_flow():
    show_mode_bundle(current_mode())


def refresh_stack():
    show_mode_bundle(current_mode(), ['(Đã probe lại stack.)'])


def m1_fill_flow():
    show_mode_bundle(MODE_ANCHOR)


def m2_fill_flow():
    show_mode_bundle(MODE_LEADER)


def m3_fill_flow():
    show_mode_bundle(MODE_PUBLISH)


def m4_fill_flow():
    show_mode_bundle(MODE_DEFEND)


def m5_fill_flow():
    show_mode_bundle(MODE_EXCHANGE, [
        'Mẫu dãy hiện tại: %s' % (QtBind.text(gui, m5_skills) or ''),
        'Nhắc: NativeCut self ONLY sau B070 + Timer(ms).',
    ])


def m6_fill_flow():
    show_mode_bundle(MODE_COMMANDS)


def m3_show_cmds():
    render_list([
        '— Lệnh Chủ (PartyLeader) —',
        'Chọn địch (Target / `) → party ks#UID',
        'F1 / F2 / 3 → ksgo#F#UID (Phụ ARM + Prefer)',
        'F4 / dừng Ghost → dungdanh',
        'Clear → ks#0 / ks clear',
        'Follow cũ → ks / ks off',
        '',
    ] + stack_status_lines(MODE_PUBLISH))
    set_status('Bảng lệnh Chủ — phát thật cần PartyLeader đã Bật + vai trò Chủ.')


def m5_show_checklist():
    render_list([
        '— Checklist Ghost / Farm —',
        '1) AutoGhost PvP: dãy ID=ms · Bật · chọn địch · F',
        '2) Log kỳ vọng: C→S 7081 + B074 02 00 sau B070',
        '3) Đo ms (ghep-2.6): Nạp F1 → Bắt đầu đo → Ghi vào F1',
        '4) GhostFarm: Bật · Self · Start farm · skill ID=ms sau B070',
        '5) GhostNativeProbe: chứng minh NativeCut self',
        '6) Không chạy 2 hook GetTickCount cắt nhau (Probe+AG)',
        '',
    ] + stack_status_lines(MODE_EXCHANGE))
    set_status('Checklist Ghost — tab này không thực hiện cut.')


def m6_show_cmds():
    render_list(['— Lệnh tham chiếu —'] + list(COMMAND_ROWS) + [''] + stack_status_lines(MODE_COMMANDS))
    set_status('Bảng lệnh tham chiếu (không inject).')


def read_position():
    position = bot.get_position() or {}
    point = {axis: float(position.get(axis, 0)) for axis in ('x', 'y', 'z')}
    if 'x' not in position or 'y' not in position or not all(map(math.isfinite, point.values())):
        raise ValueError('Chưa có tọa độ nhân vật.')
    point['region'] = int(position['region'])
    return point


def capture_anchor():
    global anchor
    try:
        anchor = read_position()
    except (TypeError, ValueError, KeyError):
        set_status('Chưa lấy được X/Y/Z và vùng. Vào game trước.')
        return
    QtBind.setText(gui, anchor_label, 'Điểm chờ: X %.1f | Y %.1f | vùng %d' %
                   (anchor['x'], anchor['y'], anchor['region']))
    QtBind.setText(gui, m1_x, '%.1f' % anchor['x'])
    QtBind.setText(gui, m1_y, '%.1f' % anchor['y'])
    set_status('Đã lấy điểm chờ (dùng cho quét / cấu hình Mode 1).')


def m1_use_anchor():
    if anchor is None:
        capture_anchor()
        return
    QtBind.setText(gui, m1_x, '%.1f' % anchor['x'])
    QtBind.setText(gui, m1_y, '%.1f' % anchor['y'])
    set_status('Đã gắn X/Y panel 1 từ điểm chờ.')


def scan_party():
    previous = QtBind.text(gui, leader_field)
    names = sorted({
        str(member.get('name') or member.get('job_name')).strip()
        for member in records('get_party').values()
        if isinstance(member, dict) and (member.get('name') or member.get('job_name'))
    })
    QtBind.clear(gui, leader_field)
    for name in names:
        QtBind.append(gui, leader_field, name)
    if previous in names:
        QtBind.setText(gui, leader_field, previous)
    elif names:
        QtBind.setText(gui, leader_field, names[0])
    set_status('Tìm thấy %d tên trong Party.' % len(names))


def m2_from_party():
    name = (QtBind.text(gui, leader_field) or '').strip()
    if not name:
        scan_party()
        name = (QtBind.text(gui, leader_field) or '').strip()
    if not name:
        set_status('Party trống hoặc chưa vào game.')
        return
    QtBind.setText(gui, m2_leader, name)
    set_status('Đã điền Tên Chủ = %s (cần lưu/cấu hình trên AutoKS hoặc PartyLeader).' % name)


def _flag_keys():
    keys = []
    if QtBind.isChecked(gui, m4_show_pvp):
        keys.extend(('pvp', 'pk', 'pk_state', 'cape', 'murder_level'))
    if QtBind.isChecked(gui, m4_show_job):
        keys.extend(('job_type', 'job_pvp'))
    # Always allow these if both off
    return keys or ('pvp', 'pk', 'job_type')


def scan_people():
    try:
        center = anchor or read_position()
        scan = float(QtBind.text(gui, scan_field))
        attack = float(QtBind.text(gui, attack_field))
        if not 1 <= attack <= scan <= 200:
            raise ValueError
    except (ValueError, TypeError, KeyError):
        set_status('Cần tọa độ hợp lệ và 1 ≤ bán kính đánh ≤ bán kính quét ≤ 200.')
        return
    party_uids = {
        str(row.get('player_id'))
        for row in records('get_party').values()
        if isinstance(row, dict)
    }
    own_uid = str((bot.get_character_data() or {}).get('player_id'))
    flag_keys = _flag_keys()
    only_flagged = QtBind.isChecked(gui, m4_only_flagged)
    found = []
    for uid, person in records('get_players').items():
        if not isinstance(person, dict) or str(uid) == own_uid or person.get('dead'):
            continue
        try:
            if person.get('region') is not None and int(person['region']) != center['region']:
                continue
            distance = math.hypot(float(person['x']) - center['x'], float(person['y']) - center['y'])
        except (ValueError, TypeError, KeyError):
            continue
        if not math.isfinite(distance) or distance > scan:
            continue
        flags = ', '.join(
            '%s=%s' % (key, person[key])
            for key in flag_keys
            if isinstance(person.get(key), (str, int, bool))
        )
        if only_flagged and not flags:
            continue
        tag = 'Party' if str(uid) in party_uids else (
            'trong bán kính đánh' if distance <= attack else 'chỉ trong quét')
        found.append((distance, '%s | UID=%s | %.1f m | %s%s' % (
            person.get('name') or 'Player', uid, distance, tag,
            ' | ' + flags if flags else '')))
    found.sort()
    header = [
        'Quét quanh %s · đánh≤%.0f · quét≤%.0f · nhóm %s' % (
            'điểm chờ' if anchor else 'vị trí hiện tại',
            float(QtBind.text(gui, attack_field) or 0),
            float(QtBind.text(gui, scan_field) or 0),
            QtBind.text(gui, page_field) or 'F2'),
        'Cờ = dữ liệu thô API. Combat filter thật nằm ở AutoGhost.',
        '',
    ]
    body = [line for _, line in found[:50]] or ['Chưa thấy người trong phạm vi hoặc API không trả danh sách.']
    render_list(header + body)
    set_status('Quét được %d người (hiển thị tối đa 50).' % len(found))


def config_owner():
    character = bot.get_character_data() or {}
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


def collect_config():
    return {
        'version': VERSION,
        'mode': current_mode(),
        'scan_m': QtBind.text(gui, scan_field),
        'attack_m': QtBind.text(gui, attack_field),
        'page': QtBind.text(gui, page_field),
        'leader_combo': QtBind.text(gui, leader_field),
        'anchor': anchor,
        'm1': {
            'x': QtBind.text(gui, m1_x),
            'y': QtBind.text(gui, m1_y),
            'enemy_key': QtBind.text(gui, m1_enemy_key),
            'skip_party': QtBind.isChecked(gui, m1_skip_party),
            'skip_guild': QtBind.isChecked(gui, m1_skip_guild),
        },
        'm2': {
            'role': QtBind.text(gui, m2_role),
            'leader': QtBind.text(gui, m2_leader),
            'want_aks': QtBind.isChecked(gui, m2_want_aks),
            'want_pl': QtBind.isChecked(gui, m2_want_pl),
        },
        'm3': {
            'broadcast': QtBind.isChecked(gui, m3_broadcast),
            'sync': QtBind.isChecked(gui, m3_sync),
        },
        'm4': {
            'show_pvp': QtBind.isChecked(gui, m4_show_pvp),
            'show_job': QtBind.isChecked(gui, m4_show_job),
            'only_flagged': QtBind.isChecked(gui, m4_only_flagged),
        },
        'm5': {
            'skills': QtBind.text(gui, m5_skills),
        },
    }


def apply_config(data):
    global anchor
    if not isinstance(data, dict):
        return
    mode = data.get('mode')
    if mode in VIEW_BY_MODE:
        QtBind.setText(gui, mode_field, mode)
        show_view(VIEW_BY_MODE[mode])
    if data.get('scan_m') is not None:
        QtBind.setText(gui, scan_field, str(data['scan_m']))
    if data.get('attack_m') is not None:
        QtBind.setText(gui, attack_field, str(data['attack_m']))
    page = data.get('page')
    if page in ('F1', 'F2', 'F3'):
        QtBind.setText(gui, page_field, page)
    leader = data.get('leader_combo')
    if leader:
        QtBind.append(gui, leader_field, leader)
        QtBind.setText(gui, leader_field, leader)
    if isinstance(data.get('anchor'), dict):
        anchor = data['anchor']
        try:
            QtBind.setText(gui, anchor_label, 'Điểm chờ: X %.1f | Y %.1f | vùng %d' %
                           (float(anchor['x']), float(anchor['y']), int(anchor['region'])))
        except (KeyError, TypeError, ValueError):
            pass
    m1 = data.get('m1') or {}
    QtBind.setText(gui, m1_x, str(m1.get('x') or ''))
    QtBind.setText(gui, m1_y, str(m1.get('y') or ''))
    QtBind.setText(gui, m1_enemy_key, str(m1.get('enemy_key') or 'Home'))
    QtBind.setChecked(gui, m1_skip_party, bool(m1.get('skip_party', True)))
    QtBind.setChecked(gui, m1_skip_guild, bool(m1.get('skip_guild', True)))
    m2 = data.get('m2') or {}
    if m2.get('role') in ('Phụ', 'Chủ'):
        QtBind.setText(gui, m2_role, m2['role'])
    QtBind.setText(gui, m2_leader, str(m2.get('leader') or ''))
    QtBind.setChecked(gui, m2_want_aks, bool(m2.get('want_aks', True)))
    QtBind.setChecked(gui, m2_want_pl, bool(m2.get('want_pl', False)))
    m3 = data.get('m3') or {}
    QtBind.setChecked(gui, m3_broadcast, bool(m3.get('broadcast', True)))
    QtBind.setChecked(gui, m3_sync, bool(m3.get('sync', True)))
    m4 = data.get('m4') or {}
    QtBind.setChecked(gui, m4_show_pvp, bool(m4.get('show_pvp', True)))
    QtBind.setChecked(gui, m4_show_job, bool(m4.get('show_job', True)))
    QtBind.setChecked(gui, m4_only_flagged, bool(m4.get('only_flagged', False)))
    m5 = data.get('m5') or {}
    if m5.get('skills') is not None:
        QtBind.setText(gui, m5_skills, str(m5['skills']))


def save_config():
    global loaded_owner
    try:
        owner = config_owner()
        path = config_path(owner)
    except ValueError as error:
        set_status(str(error))
        return
    data = collect_config()
    temp = path.with_suffix('.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(path)
        loaded_owner = owner
        set_status('Đã lưu %s' % path.name)
        _log('saved %s' % path)
    except OSError as error:
        set_status('Lưu lỗi: %s' % error)


def load_config(quiet=False):
    global loaded_owner
    try:
        owner = config_owner()
        path = config_path(owner)
    except ValueError as error:
        if not quiet:
            set_status(str(error))
        return None
    if not path.is_file():
        if not quiet:
            set_status('Chưa có file cấu hình %s' % path.name)
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        if not quiet:
            set_status('Tải lỗi: %s' % error)
        return None
    apply_config(data)
    loaded_owner = owner
    if not quiet:
        set_status('Đã tải %s' % path.name)
        show_mode_bundle(current_mode())
    return data


def joined_game():
    load_config(quiet=True)


# Initial view
show_view('m1')
set_help(MODE_ANCHOR)
render_list(list(FLOW[MODE_ANCHOR]) + [''] + stack_status_lines(MODE_ANCHOR))
set_status('AutoPKList v%s — chọn chế độ → Mở panel / Cơ chế / Probe stack.' % VERSION)
_log('loaded v%s' % VERSION)
