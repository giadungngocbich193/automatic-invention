# -*- coding: utf-8 -*-
"""Ghost PvP và Boss nền theo ID cho phBot Stable."""

import ctypes
import hashlib
import json
import logging
import math
import os
import re
import struct
import sys
from pathlib import Path, PureWindowsPath
from threading import Event, RLock, Thread, Timer
from time import monotonic, perf_counter_ns, sleep, time
from ctypes import wintypes

import QtBind
import phBot as phbot_api
from phBot import (get_character_data, get_config_dir, get_monsters,
                   get_npcs, get_position, get_skills, get_status, inject_joymax, log)


NAME = 'AutoGhost'
VERSION = '1.8.38'
CONFIG_NAME = 'GhostControl'  # Read the same profiles saved by previous releases.
PAGES = ('F1', 'F2', 'F3', 'F4')
PVP_EDIT_PAGES = PAGES[:3]
PVP_STOP_PAGE = PAGES[-1]
PAGE_KEYS = (0x70, 0x71, 0x72, 0x73)
AUTO_HUNT_RADIUS = 50
AUTO_HUNT_INTERVAL = 0.06
PVP_KEY_INTERVAL = 0.03
AUTO_PK_SCAN_INTERVAL = 0.075
AUTO_PK_FAST_SCAN_INTERVAL = 0.040
AUTO_PK_MAX_SCAN_RADIUS = 120
AUTO_PK_TARGET_OUTSIDE_CONFIRM = 0.35
AUTO_PK_CAST_RETRY_DELAY = 2.0
AUTO_PK_SELECT_TIMEOUT = 1.5
AUTO_PK_NATIVE_TIMEOUT = 0.75
AUTO_PK_NATIVE_KEYS = {
    **{'F%d' % number: 0x6F + number for number in range(9, 13)},
    'HOME': 0x24, 'END': 0x23, 'INSERT': 0x2D, 'PAGEUP': 0x21, 'PAGEDOWN': 0x22,
}
AUTO_PK_TARGET_RETRY_DELAY = 2.0
AUTO_PK_PROTECTION_DELAY = 5.0
AUTO_PK_PROTECTED = 'tạm bỏ qua UID này'
AUTO_PK_RETURN_STALL_TIMEOUT = 8.0
AUTO_PK_RETURN_MIN_PROGRESS = 0.5
AUTO_PK_RETURN_FORCE_AFTER = 3.0
AUTO_PK_RETURN_CANCEL_GAP = 0.15
AUTO_PK_RETURN_MOVE_INTERVAL = 2.0
AUTO_PK_RETURN_STEP = 8.0
AUTO_PK_MAX_RADIUS = 40
AUTO_PK_REPORT_RADIUS = 60
AUTO_PK_APPROACH_RANGE = 6.0
AUTO_PK_OUTSIDE_SELF = 'nhân vật vượt bán kính canh'
AUTO_PK_OUTSIDE_TARGET = 'mục tiêu vượt bán kính canh'
NUMERIC_KEY_INTERVAL = 0.02
PVP_CAST_WAIT = 0.4
RECLICK_WAIT = 0.65
RECLICK_MAX_RETRIES = 3
PVP_RECOVERY_AFTER = 4.0
DIRECT_CAST_WAIT = 1.5
PVP_PUSH_RECOVERY_WINDOW = 3 * DIRECT_CAST_WAIT
PVP_ACTION_REFUSAL = b'\x03\x00\x04\x40'
PVP_STUN_BIT = 1 << 14
DIRECT_TRIAL_WAIT = 6.0
DIRECT_BASELINE_END_WAIT = 8.0
PVP_BACKGROUND_PRESET = '80031=100; 66007=550; 54016=100; 81019=550; 7678=100; 81016=850; 7653=550'
DIRECT_DELAY_FACTOR = 0.95  # Slightly faster interrupt timing in packet-only PvP.
BOSS_ESC_GAP = 0.08
SKILL_PROBE_DURATION = 60
TRACE_DURATION = 20
TRACE_MAX_PACKETS = 400
HUNG_VUONG_DK_DD = (('Strike Twishing', 1050),
 ('Heavenly Chain', 1150),
 ('Destruction Smash', 1150),
 ('Thousand Army Chain', 1500),
 ('Ghost Spear - Hell', 1),
 ('Ly than nhat kich', 680),
 ('§¹i Tinh Ph¸p', 1),
 ('Soul Spear - King', 680),
 ('Ghost Spear - Sea God', 1),
 ('Soul Spear - Destruction', 650),
 ('Heaven Spear Force', 850),
 ('V¹n BÝch ThuËt ThÇn Th\xad¬ng', 100),
 ('Chain Spear - Nachal', 50))
user32 = ctypes.WinDLL('user32') if sys.platform == 'win32' else None
if user32:
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindowAsync.restype = wintypes.BOOL
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.keybd_event.argtypes = [
        wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t
    ]
    user32.keybd_event.restype = None
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
    user32.MapVirtualKeyW.restype = wintypes.UINT
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]

gui = QtBind.init(__name__, '%s v%s' % (NAME, VERSION))
ui_views = {}
ui_sync = False
run_section = 'pvp'
pvp_right_editor = 'F2'
hidden_game = None


def get_client():
    client = phbot_api.get_client()
    if client and client.get('running'):
        runtime = auto_pk_runtime if auto_pk_running else None
        window, pid = client.get('window'), client.get('pid')
        if window and runtime is not None and pid:
            runtime['client_window'] = (window, pid)
        elif not window:
            session = client_exchange
            known = (session['key'][1], session['key'][0]) if session is not None else hidden_game
            if known is None and runtime is not None:
                known = runtime.get('client_window')
            if known is not None and pid == known[1] and game_window_belongs_to(known[0], pid):
                return dict(client, window=known[0])
    return client

def widget(view, kind, *args):
    handle = getattr(QtBind, kind)(gui, *args)
    offset = -4 if kind in ('createLineEdit', 'createCombobox', 'createList') else -2
    x, y = args[offset:offset + 2] if offset != -2 else args[-2:]
    ui_views.setdefault(view, []).append((handle, x, y))
    return handle

def show_view(view):
    global run_section
    if view in ('pvp', 'boss'):
        run_section = view
    for name, controls in ui_views.items():
        visible = name == view or (view == 'pvp' and name == 'pvp_' + pvp_right_editor)
        for handle, x, y in controls:
            QtBind.move(gui, handle, x if visible else -10000, y)
    for handle,x,y in globals().get('shared_combat_controls',()):
        QtBind.move(gui,handle,-10000 if view in ('tools','auto_pk','auto_pk_options','auto_pk_buffs','presets','boss','meter') else x,y)

def view_pvp(): show_view('pvp')
def view_boss(): show_view('boss')
def view_gear(): show_view('gear')
def view_damage_meter(): show_view('meter')
def view_tools():
    show_view('tools')
    if 'refresh_skill_finder' in globals():refresh_skill_finder()

QtBind.createButton(gui, 'view_pvp', 'PvP', 10, 5)
QtBind.createButton(gui, 'view_tools', 'Tìm ID skill', 198, 5)
QtBind.createButton(gui, 'view_damage_meter', 'Đo ms ngắt', 294, 5)
QtBind.createButton(gui, 'view_auto_pk', 'Auto pk', 104, 5)
QtBind.createButton(gui, 'view_presets', 'Bộ cấu hình', 575, 5)



QtBind.createLabel(gui, '%s v%s' % (NAME, VERSION), 465, 10)
start_button = QtBind.createButton(gui, 'start_clicked', 'Bật', 10, 273)
stop_button = QtBind.createButton(gui, 'stop_clicked', 'Dừng', 90, 273)
save_button = QtBind.createButton(gui, 'save_clicked', 'Lưu cấu hình', 175, 273)
status_label = QtBind.createLabel(gui, 'Đang tắt', 10, 297)
reclick_box = QtBind.createCheckBox(gui, 'reclick_changed', 'Reclick tối đa 3 lần', 325, 276)
reclick_wait_label = QtBind.createLabel(gui, 'Chờ ms', 478, 277)
reclick_wait_field = QtBind.createLineEdit(gui, '650', 530, 273, 55, 20)
shared_combat_controls=[(start_button,10,273),(stop_button,90,273),(save_button,175,273),
                        (status_label,10,297),(reclick_box,325,276),(reclick_wait_label,478,277),(reclick_wait_field,530,273)]

# All views share one phBot tab. Off-screen widgets retain their settings.
pvp_box = widget('pvp', 'createCheckBox', 'pvp_changed', 'Auto Ghost', 10, 36)
ghost_box = widget('hidden', 'createCheckBox', 'mode_changed', 'Auto ô số', 140, 36)
direct_box = widget('hidden', 'createCheckBox', 'mode_changed', 'Gói tin (thử)', 260, 36)
pvp_background_box = widget('hidden', 'createCheckBox', 'background_mode_changed', 'Skill nền bằng ID', 150, 36)
packet_mode_box = widget('hidden', 'createCheckBox', 'packet_mode_changed', 'PvP nền ID (F1)', 280, 36)
widget('pvp', 'createLabel', 'Dùng F', 10, 61)
widget('pvp', 'createLabel', 'Dãy skill', 70, 61)
page_fields, page_boxes = {}, {}
for index, page in enumerate(PAGES):
    y = 82 + index * 24
    callback = 'numeric_' + page.lower() + '_changed'
    globals()[callback] = lambda checked: None  # Legacy profile fields stay hidden.
    page_boxes[page] = widget('hidden' if page == 'F4' else 'pvp', 'createCheckBox', callback, 'Auto '+page, 10, y)
    page_fields[page] = widget('hidden' if page == 'F4' else 'pvp', 'createLineEdit', '', 70, y - 3, 115, 20)
widget('pvp', 'createLabel', 'F4', 10, 154)
widget('pvp', 'createLabel', 'Đao/khiên + dừng đánh', 70, 154)
widget('pvp', 'createLabel', 'F1–F3: bấm lại để dừng', 280, 130)
widget('pvp', 'createLabel', 'F4: đổi đồ + dừng; X: bỏ target + dừng', 280, 150)
widget('pvp', 'createLabel', 'Cách kích hoạt', 280, 61)
trigger_field = widget('pvp', 'createCombobox', 280, 79, 264, 20)
TRIGGER_MANUAL = 'Chọn người → bấm F một lần'
TRIGGER_TARGET = 'Chọn người → tự đổi F và Ghost'
QtBind.append(gui, trigger_field, TRIGGER_MANUAL)
QtBind.append(gui, trigger_field, TRIGGER_TARGET)
widget('pvp', 'createLabel', 'Tự target: tích 1 F. Bấm F: dùng nhiều F.', 280, 108)
legacy_box = widget('hidden', 'createCheckBox', 'legacy_changed', 'Luồng cũ ổn định (tắt Reclick)', 280, 126)
widget('hidden', 'createLabel', 'Dãy ID PvP gói tin (thử)', 280, 145)
direct_field = widget('hidden', 'createLineEdit', '', 280, 162, 310, 20)
ID_METHOD_EXCHANGE = 'ID: Trao đổi API (chưa hoạt động)'
ID_METHOD_CHAIN = 'THỬ: nối ID, không Trao đổi (1 vòng)'
ID_METHOD_BASELINE = 'ĐỐI CHIẾU: chờ B074 kết thúc (1 vòng)'
ID_METHOD_NATIVE = 'PvP: skill ID nền'
id_method_field = widget('hidden', 'createCombobox', 280, 173, 310, 22)
QtBind.append(gui,id_method_field,ID_METHOD_EXCHANGE)
QtBind.append(gui,id_method_field,ID_METHOD_CHAIN)
QtBind.append(gui,id_method_field,ID_METHOD_BASELINE)
QtBind.append(gui,id_method_field,ID_METHOD_NATIVE)
widget('hidden', 'createLabel', 'Mốc ngắt: ID=ms hoặc tên=ms; ...', 10, 182)
skills_field = widget('hidden', 'createLineEdit', '', 10, 198, 580, 20)
widget('hidden', 'createLabel', 'Trao đổi mặc định', 10, 225)
exchange_field = widget('hidden', 'createLineEdit', '0', 135, 222, 35, 20)

widget('hidden', 'createButton', 'start_chat_pvp', 'PvP nền F1 (ID)', 300, 219)
hybrid_box = widget('hidden', 'createCheckBox', 'hybrid_mode_changed', 'PvP nổi', 155, 223)

boss_box = widget('boss', 'createCheckBox', 'mode_changed', 'Ghost Boss', 10, 36)
boss_esc_box = widget('boss', 'createCheckBox', 'mode_changed', 'Ngắt Boss (thử)', 170, 36)
hunt_box = widget('boss', 'createCheckBox', 'mode_changed', 'Tự tìm quái 50 m', 380, 36)
widget('boss', 'createLabel', 'TARGET hoặc tên/mã/Model boss; ...', 10, 58)
boss_names_field = widget('boss', 'createLineEdit', '', 10, 78, 420, 20)
widget('boss', 'createLabel', 'Bán kính', 460, 58)
radius_field = widget('boss', 'createLineEdit', '30', 460, 78, 70, 20)
widget('boss', 'createLabel', 'Dãy boss', 10, 111)
boss_keys_field = widget('boss', 'createLineEdit', '', 100, 108, 140, 20)
widget('boss', 'createLabel', 'Phím ngắt (bỏ nếu ESC)', 300, 111)
boss_interrupt_field = widget('boss', 'createLineEdit', '', 520, 108, 45, 20)
widget('boss', 'createLabel', 'Mốc ngắt Boss ID=ms; ... / tọa độ cũ', 10, 143)
boss_dialog_field = widget('boss', 'createLineEdit', '', 10, 161, 580, 20)
widget('boss', 'createButton', 'start_boss_esc', 'Bật thử Boss 3456789', 10, 190)
widget('boss', 'createButton', 'scan_clicked', 'Quét quái vào Log', 220, 190)
widget('boss', 'createButton', 'start_boss_trace', 'Ghi Boss 30s', 425, 190)
widget('boss', 'createButton', 'stop_boss_trace', 'Dừng ghi', 425, 219)
boss_method_field = widget('boss', 'createCombobox', 10, 219, 180, 22)
for _method in ('ESC → ESC (cũ)', 'Alt+Tab (thử)', 'Alt+Esc (thử)'):
    QtBind.append(gui, boss_method_field, _method)
widget('boss', 'createLabel', 'Ra ngoài 120 ms rồi về game', 200, 219)

widget('gear', 'createLabel', 'F', 10, 38)
widget('gear', 'createLabel', 'Vũ khí: ID / servername', 55, 38)
widget('gear', 'createLabel', 'Khiên: trống giữ; 0 tháo', 285, 38)
weapon_fields, shield_fields = {}, {}
for index, page in enumerate(PAGES):
    y = 63 + index * 25
    widget('gear', 'createLabel', page, 10, y)
    weapon_fields[page] = widget('gear', 'createLineEdit', '', 55, y - 3, 70, 18)
    shield_fields[page] = widget('gear', 'createLineEdit', '', 285, y - 3, 63, 18)
    widget('gear', 'createButton', 'capture_' + page.lower() + '_gear', 'Lấy đồ', 470, y - 5)
widget('gear', 'createLabel', 'Mặc bộ đồ muốn dùng rồi bấm Lấy đồ ở dòng F tương ứng.', 10, 165)
imbue_box = widget('gear', 'createCheckBox', 'imbue_mode_changed', 'Tự duy trì tay phép', 10, 189)
imbue_field = widget('gear', 'createCombobox', 10, 212, 270, 22)
QtBind.append(gui, imbue_field, '(Không dùng)')
widget('gear', 'createButton', 'refresh_imbues', 'Quét tay phép', 420, 209)
# Imbue applies globally; Stop disables maintenance.

widget('hidden', 'createLabel', 'Dò skill: bấm nút rồi sang game bấm 1 ô số.', 10, 36)
widget('hidden', 'createButton', 'arm_skill_probe', 'Dò phím số', 10, 60)
widget('hidden', 'createButton', 'list_skills_clicked', 'Skill trong Log', 145, 60)
widget('hidden', 'createButton', 'start_manual_trace', 'Ghi Ghost tay', 310, 60)
widget('hidden', 'createButton', 'probe_exchange_clicked', 'Kiểm tra gửi nền (1 lần)', 10, 94)
probe_result_field = widget('hidden', 'createLineEdit', '', 215, 97, 375, 20)
widget('hidden', 'createLabel', 'ID skill', 10, 134)
probe_id_field = widget('hidden', 'createLineEdit', '', 80, 130, 100, 20)
widget('hidden', 'createLabel', 'Ngắt ms (nhập)', 190, 134)
probe_delay_field = widget('hidden', 'createLineEdit', '500', 295, 130, 90, 20)
widget('hidden', 'createButton', 'add_boss_skill', 'Thêm vào Ghost Boss', 10, 173)
widget('hidden', 'createButton', 'stop_skill_probe', 'Dừng dò', 455, 60)
widget('hidden', 'createButton', 'copy_probe_to_pvp', 'Chép dãy sang PvP', 215, 173)
widget('hidden', 'createButton', 'clear_probe_draft', 'Xóa dãy nháp', 420, 173)
widget('hidden', 'createLabel', 'Dãy nháp tự gom: ID=ms; ... — sửa tại đây, Ctrl+A / Ctrl+C để copy', 10, 199)
probe_draft_field = widget('hidden', 'createLineEdit', '', 10, 216, 580, 20)
# The old probe widgets remain hidden compatibility storage. The visible finder
# only reads learned skills and the clipboard; it never edits combat settings.
widget('tools','createLabel','Tìm tên / ID',10,36)
finder_query_field=widget('tools','createLineEdit','',100,32,340,22)
widget('tools','createButton','search_skill_finder','Tìm',450,31)
widget('tools','createButton','refresh_skill_finder','Quét lại',510,31)
widget('tools','createButton','clear_skill_finder','Xóa lọc',590,31)
finder_status_label=widget('tools','createLabel','Tìm theo tên không dấu hoặc ID. Copy ID ngay tại bảng.',10,64)
widget('tools','createLabel','ID skill',10,87)
widget('tools','createLabel','Tên skill',110,87)
widget('tools','createLabel','Cấp',540,87)
finder_row_fields=[]
for index in range(6):
    y=107+index*23
    uid=widget('tools','createLineEdit','',10,y,85,21)
    name=widget('tools','createLineEdit','',105,y,425,21)
    level=widget('tools','createLineEdit','',540,y,42,21)
    callback='copy_finder_id_'+str(index)
    globals()[callback]=lambda index=index:copy_finder_id(index)
    widget('tools','createButton',callback,'Copy ID',595,y-1)
    finder_row_fields.append((uid,name,level))
widget('tools','createButton','finder_previous','Trước',10,247)
finder_page_label=widget('tools','createLabel','0 kết quả',110,251)
widget('tools','createButton','finder_next','Sau',350,247)
widget('tools','createLabel','Có thể Ctrl+A / Ctrl+C trực tiếp trong ô ID.',440,251)
finder_owner=None
finder_skills=[]
finder_matches=[]
finder_offset=0
finder_visible_ids=[]
widget('tools','createButton','start_hotbar_finder','Dò ô số',10,273)
widget('tools','createButton','stop_hotbar_finder','Dừng dò',105,273)
hotbar_slot_label=widget('tools','createLabel','Ô: —',185,277)
hotbar_id_field=widget('tools','createLineEdit','',240,273,90,22)
hotbar_name_field=widget('tools','createLineEdit','',340,273,245,22)
widget('tools','createButton','copy_hotbar_id','Copy ID',595,272)
hotbar_status_label=widget('tools','createLabel','Bấm Dò ô số → sang game bấm skill → quay lại copy ID.',10,299)
hotbar_found=None

widget('auto_pk','createLabel','AUTO PK · tự lấy điểm chờ khi bật · vùng đánh tối đa 40 m.',10,35)
widget('auto_pk','createLabel','Vùng đánh (m)',10,69)
auto_pk_radius_field=widget('auto_pk','createLineEdit',str(AUTO_PK_MAX_RADIUS),106,65,45,22)
widget('auto_pk','createLabel','Vùng quét (m)',171,69)
auto_pk_scan_radius_field=widget('auto_pk','createLineEdit',str(AUTO_PK_REPORT_RADIUS),265,65,55,22)
widget('auto_pk','createLabel','Nhóm Ghost',340,69)
auto_pk_page_field=widget('auto_pk','createCombobox',427,65,75,22)
for page in ('F1','F2'):QtBind.append(gui,auto_pk_page_field,page)
QtBind.setText(gui,auto_pk_page_field,'F2')
widget('auto_pk','createButton','save_auto_pk_settings','Lưu Auto PK',545,64)
auto_pk_anchor_label=widget('auto_pk','createLabel','Điểm chờ: tự lấy khi bật.',10,103)
widget('auto_pk','createLabel','Target Enemy',465,103)
auto_pk_enemy_key_field=widget('auto_pk','createLineEdit','',560,98,92,22)
auto_pk_patrol_box=widget('auto_pk','createCheckBox','auto_pk_patrol_changed','Chạy vòng',10,130)
widget('auto_pk','createLabel','Bán kính (m)',117,133)
auto_pk_patrol_radius_field=widget('auto_pk','createLineEdit','10',200,128,50,22)
auto_pk_fast_box=widget('auto_pk','createCheckBox','auto_pk_fast_changed','Quét nhanh',270,130)
widget('auto_pk','createButton','view_auto_pk_options','Tọa độ',410,127)
widget('auto_pk','createButton','view_auto_pk_buffs','Skill buff',505,127)
widget('auto_pk','createButton','scan_auto_pk_now','Quét ngay',10,157)
widget('auto_pk','createButton','request_auto_pk_arm','Bật Auto PK',410,157)
widget('auto_pk','createButton','stop_auto_pk','Dừng canh',505,157)
auto_pk_result_fields=[
    widget('auto_pk','createLineEdit','',10,184+index*21,655,20) for index in range(3)
]
auto_pk_status_label=widget('auto_pk','createLineEdit','Đã tắt. Bấm Bật Auto PK tại vị trí muốn canh.',10,250,655,22)
auto_pk_scan_field=widget('auto_pk','createLineEdit','Tự quét khi bật Auto PK.',10,276,655,20)

widget('auto_pk_options','createLabel','TỌA ĐỘ TÂM VÙNG · bỏ trống cả X và Y để dùng mặc định.',10,36)
widget('auto_pk_options','createLabel','Vùng đánh: vị trí khi bật Auto PK. Vùng quét và chạy vòng: tâm vùng đánh.',10,61)
auto_pk_center_fields = {}
for index, (kind, title) in enumerate((('attack','Vùng đánh'),('scan','Vùng quét'),('patrol','Chạy vòng'))):
    y = 91 + index * 33
    widget('auto_pk_options','createLabel',title,10,y+5)
    widget('auto_pk_options','createLabel','X',130,y+5)
    widget('auto_pk_options','createLabel','Y',303,y+5)
    auto_pk_center_fields[kind] = (
        widget('auto_pk_options','createLineEdit','',150,y,115,22),
        widget('auto_pk_options','createLineEdit','',324,y,115,22),
    )
widget('auto_pk_options','createLabel','Tọa độ áp dụng khi bật Auto PK. Vòng chạy phải nằm trong vùng đánh.',10,205)
widget('auto_pk_options','createButton','save_auto_pk_settings','Lưu Auto PK',10,238)
widget('auto_pk_options','createButton','view_auto_pk','Quay lại Auto PK',140,238)
auto_pk_options_status=widget('auto_pk_options','createLabel','',10,272)

widget('auto_pk_buffs','createLabel','SKILL BUFF AUTO PK · nhập ID skill tự buff. Để trống dòng không dùng.',10,36)
widget('auto_pk_buffs','createLabel','Chỉ tự buff lúc canh rảnh. Bật lại Auto PK để áp dụng danh sách.',10,61)
auto_pk_buffs_box=widget('auto_pk_buffs','createCheckBox','auto_pk_buffs_changed','Tự buff',10,86)
auto_pk_buff_fields=[]
for index in range(5):
    y = 113 + index * 25
    widget('auto_pk_buffs','createLabel','Buff %d' % (index+1),10,y+4)
    auto_pk_buff_fields.append(widget('auto_pk_buffs','createLineEdit','',95,y,110,22))
widget('auto_pk_buffs','createButton','save_auto_pk_buffs','Lưu buff',310,113)
widget('auto_pk_buffs','createButton','view_auto_pk','Quay lại Auto PK',310,146)
auto_pk_buffs_status=widget('auto_pk_buffs','createLabel','',10,253)
auto_pk_anchor=None
auto_pk_running=False
auto_pk_returning=False
auto_pk_runtime=None
auto_pk_owner=None

view_pvp()

settings = None
current_page = None
active_sequence = None
sequence_index = 0
profile_owner = None
imbue_saved_selection = None
imbue_scan_pending = False
imbue_save_after = 0.0
pvp_lock = RLock()
pvp_delays = {}
direct_skills = ()
direct_index = 0
direct_target = 0
direct_blocked_target = 0
manual_trace = None
direct_select_request = 0
direct_expected = None
direct_log_left = 0
pvp_background = False
pvp_background_error = False
pvp_cast_deadline = 0.0
exchange_key = None
boss_interrupt_key = None
boss_esc_enabled = False
boss_method = 'ESC → ESC (cũ)'
boss_esc_closing = False
boss_esc_count = 0
boss_interrupt_delays = {}
pending = None
direct_exchange_wait = None
direct_action_ended = False
background_exchange_failed_uid = 0
foreground_slot_retry_at = 0.0
exchange_transport_probe = None
exchange_probe_target = None
hybrid_exchange_mode = False
direct_chain_mode = False
direct_baseline_mode = False
direct_native_exchange = False
direct_retry_state = None
direct_missed_skills = {}
pvp_push_recovery_until = 0.0
pvp_push_recovery = {}
pvp_wait_push_until = None
direct_recovery_used = False
pvp_push = None
pvp_push_action = None
direct_chain_cast = None
direct_chain_transition = None
direct_chain_count = 0
direct_interrupt_request = None
last_trigger = None
blocked_until = 0.0
hunt_stop = None
selected_monster_uid = 0
auto_hunt = False
hunt_request = None
hunt_retry_at = 0.0
skill_probe = None
skill_probe_result = None
skill_probe_results = []
mouse_capture = None
mouse_capture_result = None
profile_fields = dict(page_fields, boss=boss_names_field, boss_keys=boss_keys_field,
                      radius=radius_field, skills=skills_field, exchange=exchange_field, boss_method=boss_method_field,
                      boss_dialog=boss_dialog_field, boss_interrupt=boss_interrupt_field, direct_skills=direct_field,
                      pvp_trigger=trigger_field, id_method=id_method_field, imbue_choice=imbue_field, reclick_wait_ms=reclick_wait_field,
                      probe_delay_ms=probe_delay_field, probe_draft=probe_draft_field)
for _page in PAGES:
    profile_fields.update({'weapon_' + _page: weapon_fields[_page],
                           'shield_' + _page: shield_fields[_page]})


# PvP activation and equipment state. Runtime configuration is frozen on Start.
pvp_trigger_mode = None
pvp_pause_controls = False
pvp_paused = False
pvp_allowed_pages = ()
pvp_page_exchanges = {}
pvp_target = 0
pvp_selection_request = 0
pvp_armed = False
pvp_activation = None
pvp_resume_page = None
pvp_synthetic_page = None
pvp_three_held = False
pvp_x_held = False
gear_blocked_page = None
f_keys_held = set()
runtime_gear = {}
gear_inflight = None
pvp_first_skill = False
pvp_stunned_character = None
imbue_id = 0
imbue_next_check = 0.0
imbue_retry_at = 0.0
imbue_until = 0.0
imbue_seen_active = False
reclick_enabled = False
reclick_wait = RECLICK_WAIT
key_attempt = None


def set_checked_silent(widget_id, value):
    global ui_sync
    old = ui_sync
    ui_sync = True
    try:
        QtBind.setChecked(gui, widget_id, value)
    finally:
        ui_sync = old


def skill_table():
    return {int(uid): data for uid, data in (get_skills() or {}).items()}


def is_imbue(skill):
    code = (skill.get('servername') or '').upper()
    name = (skill.get('name') or '').casefold()
    return ('_GIGONGTA_' in code or bool(re.fullmatch(
        r'(fire|cold|ice|lightning|thunder) .*(force|power)', name)))


def refresh_imbues(selected=None):
    global imbue_scan_pending
    selected = selected if isinstance(selected, str) else QtBind.text(gui, imbue_field)
    skills = skill_table()
    imbue_scan_pending = not skills
    match = re.search(r'\[(\d+)\]$', selected)
    selected_id = int(match[1]) if match else None
    QtBind.clear(gui, imbue_field)
    QtBind.append(gui, imbue_field, '(Không dùng)')
    current = None
    for uid, data in sorted(skills.items()):
        if not is_imbue(data):
            continue
        label = '%s [%d]' % (data.get('name') or data.get('servername'), uid)
        QtBind.append(gui, imbue_field, label)
        if uid == selected_id:
            current = label
    if selected_id is not None and current is None:
        QtBind.append(gui, imbue_field, selected)
        current = selected
    QtBind.setText(gui, imbue_field, current or '(Không dùng)')


def configured_imbue():
    if not QtBind.isChecked(gui, imbue_box):
        return 0
    value = QtBind.text(gui, imbue_field)
    match = re.search(r'\[(\d+)\]$', value)
    uid = int(match[1]) if match else 0
    skill = skill_table().get(uid)
    if not skill or not is_imbue(skill):
        raise ValueError('Chọn tay phép của acc trên trang PvP rồi bật lại.')
    return uid


def capture_page_gear(page):
    stop_clicked()
    inventory_fn = getattr(phbot_api, 'get_inventory', None)
    items = ((inventory_fn() or {}).get('items') or []) if inventory_fn else []
    if len(items) < 8 or not items[6]:
        report_error('Chưa đọc được vũ khí đang mặc; hãy vào game và trang bị trước.')
        return
    weapon = items[6]
    offhand = items[7] or {}
    # Slot 7 may contain arrows/bolts. Only save an actual shield.
    shield = offhand if is_shield_item(offhand) else {}
    QtBind.setText(gui, weapon_fields[page], str(weapon['model']))
    QtBind.setText(gui, shield_fields[page], str(shield['model']) if shield else '0')
    report('%s: lấy vũ khí %s; khiên %s. Bấm Lưu cấu hình.' %
           (page, weapon.get('name', weapon['model']), shield.get('name', 'không đổi')))


def capture_f1_gear(): capture_page_gear('F1')
def capture_f2_gear(): capture_page_gear('F2')
def capture_f3_gear(): capture_page_gear('F3')
def capture_f4_gear(): capture_page_gear('F4')


def is_shield_item(item):
    if not item:
        return False
    fn = getattr(phbot_api, 'get_item', None)
    data = (fn(item.get('model')) or {}) if fn else {}
    return data.get('tid2') == 4 or '_SHIELD_' in (item.get('servername') or '').upper()


def matches_gear(item, identity):
    if not item or not identity:
        return False
    return (str(item.get('model')) == identity if identity.isdigit()
            else (item.get('servername') or '').casefold() == identity.casefold())


def pvp_person_target(uid, character=None, monsters=None):
    character = character or get_character_data() or {}
    if not uid or uid == character.get('player_id'):
        return False
    players_fn = getattr(phbot_api, 'get_players', None)
    players = players_fn() if callable(players_fn) else None
    # Prefer get_players: opposing-faction enemies are often dual-listed in
    # get_monsters() on phBot Stable. A living player entry wins.
    if isinstance(players, dict):
        player = players.get(uid, players.get(str(uid)))
        if isinstance(player, dict):
            return not player.get('dead')
    if monsters is None:
        monsters = get_monsters()
    # Missing monster lists are not evidence that a server-confirmed UID is a mob.
    if isinstance(monsters, dict) and (uid in monsters or str(uid) in monsters):
        return False
    npcs = get_npcs() or {}
    if uid in npcs or str(uid) in npcs:
        return False
    # Missing/empty/partial player lists are not evidence that a server-confirmed
    # UID is invalid. This API is disabled or incomplete on some phBot builds.
    return True


def reset_pvp_activation(clear_target=True):
    global pvp_target, pvp_selection_request, pvp_armed, pvp_activation, gear_blocked_page, pvp_resume_page, pvp_synthetic_page
    pvp_resume_page = None
    pvp_synthetic_page = None
    pvp_armed = False
    pvp_activation = None
    gear_blocked_page = None
    if clear_target:
        pvp_target = pvp_selection_request = 0


def request_pvp_page(page, physical=False):
    global pvp_activation, pvp_armed, current_page, active_sequence, sequence_index, exchange_key, gear_blocked_page, pvp_paused, direct_index, direct_blocked_target
    global pvp_first_skill, pvp_resume_page
    if page == PVP_STOP_PAGE or (get_character_data() or {}).get('dead'):
        return
    if page in pvp_allowed_pages and physical and pvp_selection_request and not pvp_target:
        pvp_resume_page = (pvp_selection_request, page, monotonic() + 1.5)
        return
    if page not in pvp_allowed_pages or not pvp_person_target(pvp_target):
        if physical:
            request_gear_only(page)
        return
    if (direct_native_exchange or runtime_skill_groups) and not runtime_skill_groups.get(page):
        fail_pvp_activation('nhóm %s chưa có skill đang bật' % page)
        return
    previous_switch = (pvp_activation or {}).get('emergency')
    if previous_switch and previous_switch['target'] == pvp_target:
        # Repeated F presses must not tear down the 7081 session already in flight.
        return
    switching = (direct_native_exchange and current_page is not None and current_page != page
                 and not direct_action_ended
                 and (pvp_armed or pending is not None or direct_expected is not None))
    if switching and direct_exchange_wait is not None:
        switching = False
    old_page = current_page
    clear_pending()
    pvp_paused = False
    gear_blocked_page = None
    pvp_armed = False
    pvp_first_skill = True
    current_page = page
    if runtime_skill_groups:
        use_skill_group(page, runtime=True)
    active_sequence = None
    sequence_index = 0
    slot = pvp_page_exchanges.get(page)
    exchange_key = ord(slot) if slot else None
    if direct_skills:
        direct_index=0
        direct_blocked_target=0  # Explicit fresh F press permits one new attempt, never an automatic retry.
    pvp_activation = {'page': page, 'target': pvp_target,
                      'page_sent': physical or direct_native_exchange,
                      'ready_at': monotonic(), 'move': None, 'gear_only': False}
    if switching:
        pvp_activation['emergency'] = {'target': pvp_target, 'sent': False,
                                      'observed': False, 'deadline': monotonic()+2.0}
        report('Đổi %s → %s: ngắt khẩn cấp trước khi đổi vũ khí.' % (old_page,page))
    report('PvP %s: kích hoạt %s cho UID=%d; chờ trang/vũ khí sẵn sàng.' %
           ('bấm F' if physical else 'target', page, pvp_target))


def pause_pvp(reason, clear_target=False, cancel_action=True, notify=True):
    global pvp_paused, pvp_armed, pvp_activation, active_sequence, sequence_index
    global pvp_target, pvp_selection_request, pvp_resume_page, direct_target, direct_select_request
    global auto_pk_returning
    push_trace_note('Ghost tạm dừng: ' + reason)
    if clear_target and auto_pk_running:
        if auto_pk_runtime is not None:
            auto_pk_runtime.pop('select_in_event', None)
            auto_pk_runtime.pop('target_outside', None)
            auto_pk_runtime.update(requested=0, select_until=0.0, native_probe_until=0.0, skill_probe_uid=0)
        if (not auto_pk_returning and auto_pk_runtime is not None and pvp_target and pvp_armed
                and direct_exchange_wait is None and not auto_pk_in_background(get_client() or {})):
            auto_pk_runtime['withdraw']={'target':pvp_target,'sent':False,'observed':False,
                                         'deadline':monotonic()+2.0}
        auto_pk_returning=True
    pvp_resume_page = None
    was_active = (pvp_armed or key_attempt is not None or pending is not None or direct_expected is not None
                  or (pvp_activation and pvp_activation.get('emergency'))
                  or (not pvp_trigger_mode and active_sequence is not None))
    clear_pending()
    pvp_paused = True
    pvp_armed = False
    if not clear_target or not (pvp_activation and pvp_activation['page'] == PVP_STOP_PAGE):
        pvp_activation = None
    active_sequence = None
    sequence_index = 0
    if clear_target:
        pvp_target = pvp_selection_request = 0
        direct_target = direct_select_request = 0
    if was_active and cancel_action:
        accepted = inject_joymax(0x7074, b'\x02', False)
        if accepted is False:
            report_error('Đã ngừng bấm skill; phBot từ chối lệnh hủy tác vụ đang chạy.')
    message = 'Auto Ghost dừng (%s): %s.' % (current_page or 'PvP', reason.rstrip('.'))
    QtBind.setText(gui, status_label, message)
    if notify:
        report_error(message)


def request_gear_only(page):
    """A physical F press may change equipment without authorizing an attack."""
    global pvp_activation, pvp_armed, current_page, active_sequence, sequence_index, gear_blocked_page, exchange_key, pvp_resume_page
    global pvp_first_skill
    pvp_first_skill = False
    pvp_resume_page = None
    clear_pending()
    gear_blocked_page = None
    pvp_armed = False
    pvp_activation = None
    active_sequence = None
    sequence_index = 0
    current_page = page
    if page in pvp_page_exchanges:
        slot = pvp_page_exchanges[page]
        exchange_key = ord(slot) if slot else None
    if not any(runtime_gear.get(page, {}).values()):
        fail_pvp_activation('chưa cài vũ khí hoặc khiên cho nhóm %s' % page)
        return False
    pvp_activation = {'page': page, 'target': pvp_target, 'page_sent': True,
                      'ready_at': monotonic(), 'move': None, 'gear_only': True}
    report('%s: nhận phím, đổi bộ đồ đã cài; chưa cho phép đánh.' % page)
    return True


def fail_pvp_activation(message):
    global pvp_activation, pvp_armed, gear_blocked_page
    gear_blocked_page = current_page
    pvp_activation = None
    pvp_armed = False
    reason = 'Auto Ghost dừng (%s): %s.' % (current_page or 'PvP', message.rstrip('.'))
    QtBind.setText(gui, status_label, reason)
    report_error(reason)
    if auto_pk_running:
        hold_auto_pk('lỗi chuẩn bị nhóm: ' + message, retry_after=5.0)


def prepare_pvp_page(client):
    """Serialize equip requests and observe actual inventory before attacking."""
    global pvp_activation, pvp_armed, gear_inflight
    job = pvp_activation
    if job is None:
        return pvp_armed
    if not job.get('gear_only'):
        monsters = get_monsters()
        if monsters is None:
            return False
        if job['target'] != pvp_target or not pvp_person_target(pvp_target, monsters=monsters):
            if not pvp_target or not release_auto_pk_target(pvp_target, 'mục tiêu không còn hợp lệ'):
                pause_pvp('mục tiêu không còn hợp lệ khi chuẩn bị đánh', clear_target=True,
                          cancel_action=False, notify=False)
            return False
    now = monotonic()
    if not job['page_sent']:
        if not press_pvp_key(PAGE_KEYS[PAGES.index(job['page'])], client):
            return False
        job['page_sent'] = True
        job['ready_at'] = now + 0.005
        return False
    if now < job['ready_at']:
        return False
    emergency = job.get('emergency')
    if emergency and emergency.get('natural_end'):
        close_client_exchange()
        job.pop('emergency', None)
        report('Đổi F: server đã báo kỹ năng cũ kết thúc tự nhiên.')
        emergency = None
    if emergency:
        if now >= emergency['deadline']:
            pause_pvp('đổi F: chưa thấy xác nhận ngắt trong 2s; tạm dừng đổi đồ')
            return False
        if not emergency['sent']:
            emergency['sent'] = True
            try:
                send_pvp_interrupt(emergency)
            except (OSError, ValueError, RuntimeError) as error:
                pause_pvp('đổi F: ' + str(error))
                return False
            return False
        if not auxiliary_exchange_ready(emergency):
            return False
        job.pop('emergency',None)
        report('Đổi F: đã thấy tín hiệu ngắt; tiếp tục đổi đồ %s.' % job['page'])
    wanted = runtime_gear.get(job['page'], {})
    if any(wanted.values()) or (gear_inflight and gear_inflight['owner'] == profile_owner):
        fn = getattr(phbot_api, 'get_inventory', None)
        items = ((fn() or {}).get('items') or []) if fn else []
        if len(items) < 8:
            fail_pvp_activation('không đọc được hành trang')
            return False
        if gear_inflight and gear_inflight['owner'] != profile_owner:
            gear_inflight = None
        # A quick F change replaces the desired loadout, while the previous
        # equipment request still needs confirmation before another is sent.
        move = gear_inflight['move'] if gear_inflight else job['move']
        if move:
            identity, destination, deadline = move
            ready = (not is_shield_item(items[7]) if identity == '__remove_shield__'
                     else matches_gear(items[destination], identity))
            if ready:
                job['move'] = None
                gear_inflight = None
            elif now >= deadline:
                gear_inflight = None
                fail_pvp_activation('server chưa xác nhận đổi trang bị trong 3 giây')
                return False
            else:
                return False
        # A captured two-handed setup has shield=0. Remove a shield first,
        # while leaving bow arrows alone. Wait for actual inventory update.
        if wanted.get('shield') == '0' and is_shield_item(items[7]):
            empty = next((i for i, item in enumerate(items) if i >= 13 and not item), None)
            if empty is None or empty > 255:
                fail_pvp_activation('không có ô trống để cất khiên')
                return False
            job['move'] = ('__remove_shield__', 7, now + 3.0)
            gear_inflight = {'owner': profile_owner, 'move': job['move'], 'job': job}
            report('%s: gửi cất khiên từ ô 7 sang ô túi %d.' % (job['page'], empty))
            if inject_joymax(0x7034, struct.pack('<BBBH', 0, 7, empty, 0), False) is False:
                gear_inflight = None
                fail_pvp_activation('phBot từ chối cất khiên 0x7034')
            return False
        for destination, key in ((6, 'weapon'), (7, 'shield')):
            identity = wanted.get(key, '')
            if not identity or identity == '0' or matches_gear(items[destination], identity):
                continue
            slots = [i for i, item in enumerate(items) if i >= 13 and matches_gear(item, identity)]
            if len(slots) != 1 or slots[0] > 255:
                name = 'vũ khí' if destination == 6 else 'khiên'
                issue = 'không tìm thấy' if not slots else 'không xác định được đúng ô túi của'
                fail_pvp_activation('%s %s %s đã cài' % (issue, name, identity))
                return False
            item_fn = getattr(phbot_api, 'get_item', None)
            data = (item_fn(items[slots[0]]['model']) or {}) if item_fn else {}
            if data and data.get('tid2') != (6 if destination == 6 else 4):
                fail_pvp_activation('ID %s không phải %s' % (identity, key))
                return False
            job['move'] = (identity, destination, now + 3.0)
            gear_inflight = {'owner': profile_owner, 'move': job['move'], 'job': job}
            report('%s: gửi đổi ID=%s từ ô túi %d sang ô trang bị %d.' %
                   (job['page'], identity, slots[0], destination))
            if inject_joymax(0x7034, struct.pack('<BBBH', 0, slots[0], destination, 0), False) is False:
                gear_inflight = None
                fail_pvp_activation('phBot từ chối đổi trang bị 0x7034')
            return False
    # AutoPK can cast once target and gear are ready. Install the 7081
    # transport only when a confirmed cast actually needs interruption.
    if (not auto_pk_running and not job.get('gear_only') and direct_native_exchange
            and any(skill not in runtime_natural_skills for skill in direct_skills)
            and not prepare_client_exchange(job, client)):
        return False
    pvp_activation = None
    if job.get('gear_only'):
        pvp_armed = False
        report('%s: đã xác nhận bộ đồ; chưa kích hoạt Ghost.' % job['page'])
        return False
    pvp_armed = True
    if direct_native_exchange:
        QtBind.setText(gui, status_label, '%s đã sẵn sàng. Ghost theo ID.' % job['page'])
    report('%s đã sẵn sàng; Ghost UID=%d.' % (job['page'], pvp_target))
    return True


def observe_gear_reply(data):
    global gear_inflight
    if not gear_inflight or not data or data[0] != 2:
        return
    request, gear_inflight = gear_inflight, None
    job = pvp_activation
    if request['owner'] != profile_owner or job is None or request['job'] is not job:
        return
    identity, destination, _ = request['move']
    item = 'cất khiên' if identity == '__remove_shield__' else 'trang bị ID=%s vào ô %d' % (identity, destination)
    fail_pvp_activation('server từ chối %s (B034 %s)' % (item, bytes(data[:12]).hex(' ').upper()))


def pvp_gate_tick(client, character):
    global f_keys_held, pvp_paused, pvp_synthetic_page, pvp_three_held, pvp_x_held
    global auto_pk_running, auto_pk_returning, auto_pk_runtime
    window = client.get('window')
    foreground = window and user32.GetForegroundWindow() == window
    states = {page: user32.GetAsyncKeyState(key)
              for page, key in zip(PAGES, PAGE_KEYS)}
    held = {page for page, state in states.items() if state & 0x8000}
    three = bool(user32.GetAsyncKeyState(ord('3')) & 0x8000)
    three_fresh = foreground and three and not pvp_three_held
    pvp_three_held = three
    x = bool(user32.GetAsyncKeyState(ord('X')) & 0x8000)
    x_fresh = foreground and x and not pvp_x_held
    pvp_x_held = x
    if character.get('dead') or not character.get('player_id'):
        f_keys_held = held
        return False
    if foreground and any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12)):
        f_keys_held = held
        return False
    if x_fresh:
        pause_pvp('bấm X bỏ đối thủ', clear_target=True, notify=False)
        f_keys_held = held
        return False
    fresh = held - f_keys_held
    f_keys_held = held
    if not foreground:
        if (PVP_STOP_PAGE in fresh and direct_native_exchange
                and not any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12))
                and (pvp_armed or (pvp_activation and not pvp_activation.get('gear_only'))
                     or auto_pk_running)):
            pause_pvp('F4: dừng Ghost nền', notify=False)
            if auto_pk_running:
                stop_auto_pk(reason='bấm F4')
            return False
        fresh = set()
    if pvp_synthetic_page is not None:
        if monotonic()<=pvp_synthetic_page['until']:
            fresh.discard(pvp_synthetic_page['page'])
        else:pvp_synthetic_page=None
    if PVP_STOP_PAGE in fresh and pvp_pause_controls:
        if auto_pk_running:
            stop_auto_pk_patrol(auto_pk_runtime)
            auto_pk_running = auto_pk_returning = False
            auto_pk_runtime = None
            QtBind.setText(gui, auto_pk_status_label, 'AUTO PK ĐÃ TẮT.')
        pause_pvp('F4: dừng Ghost và đổi bộ thủ', notify=False)
        if request_gear_only(PVP_STOP_PAGE):
            prepare_pvp_page(client)
        return False
    if auto_pk_running:
        if not tick_auto_pk():
            return False
        fresh = set()
        three_fresh = False
    if len(fresh) == 1:
        page = next(iter(fresh))
        if pvp_trigger_mode and page not in pvp_allowed_pages:
            pause_pvp('nhóm %s đã tắt hoặc chưa có skill' % page)
            return False
        if (direct_native_exchange
                and pvp_activation and not pvp_activation.get('gear_only')
                and pvp_activation['page'] == page):
            return prepare_pvp_page(client)
        if (pvp_pause_controls and current_page == page
              and (pvp_armed or (pvp_activation and not pvp_activation.get('gear_only'))
                   or (not pvp_trigger_mode and not pvp_paused))):
            pause_pvp('bấm %s lần nữa' % page, notify=False)
            f_keys_held = held
        elif not pvp_trigger_mode:
            pvp_paused = False
            request_gear_only(page)
            f_keys_held = held
        elif page in pvp_allowed_pages:
            request_pvp_page(page, physical=True)
        else:
            if pvp_trigger_mode:
                pause_pvp('trang %s chưa bật cho Ghost' % page, cancel_action=False)
            request_gear_only(page)
            f_keys_held = held
    if three_fresh and current_page not in pvp_allowed_pages and len(pvp_allowed_pages)==1:
        # With one configured group there is no ambiguity, even on first start.
        request_gear_only(pvp_allowed_pages[0])
    if (three_fresh and not fresh and pvp_trigger_mode == 'manual'
            and not pvp_armed and (pvp_activation is None or pvp_activation.get('gear_only'))
            and current_page in pvp_allowed_pages
            and (pvp_selection_request or pvp_person_target(pvp_target, character))):
        request_pvp_page(current_page,physical=True)
    if pvp_activation is not None and pvp_activation.get('gear_only'):
        prepare_pvp_page(client)
        return False
    if pvp_pause_controls and pvp_paused:
        return False
    if not pvp_trigger_mode:
        return gear_blocked_page != current_page or gear_blocked_page is None
    monsters = get_monsters()
    if monsters is None:
        return False
    if not pvp_person_target(pvp_target, character, monsters):
        if pvp_target and not release_auto_pk_target(pvp_target, 'mục tiêu không còn hợp lệ hoặc đã chết'):
            pause_pvp('mục tiêu không còn hợp lệ hoặc đã chết', clear_target=True,
                      cancel_action=False, notify=False)
        return False
    return prepare_pvp_page(client)


def stun_option_changed(checked):
    if not ui_sync and pvp_armed and pvp_stunned_character is not None:
        text = 'PvP đang choáng · chờ server báo hết.' if checked else 'Đã tắt chế độ nối sau choáng.'
        QtBind.setText(gui, status_label, text)


def pvp_stun_blocks(character):
    return (pvp_trigger_mode and pvp_stunned_character is not None
            and pvp_stunned_character == (owner_of(character), character.get('player_id'))
            and QtBind.isChecked(gui, pvp_stun_box))


def observe_pvp_stun(opcode, data):
    global pvp_stunned_character, direct_expected, direct_retry_state, pvp_cast_deadline
    global pvp_wait_push_until, pending, pvp_first_skill
    if opcode != 0x3057 or not data or len(data) < 11:
        return
    uid, _, flags = struct.unpack_from('<IHB', data)
    # HP and MP are optional uint32 fields before the bad-effect mask.
    if not flags & 0x04 or flags & ~0x07:
        return
    offset = 7 + 4 * (bool(flags & 0x01) + bool(flags & 0x02))
    if len(data) < offset + 4:
        return
    character = get_character_data() or {}
    owner = owner_of(character)
    if not owner or not uid or uid != character.get('player_id'):
        return
    key = owner, uid
    stunned = bool(struct.unpack_from('<I', data, offset)[0] & PVP_STUN_BIT)
    with pvp_lock:
        was_stunned = pvp_stunned_character == key
        pvp_stunned_character = key if stunned else None
        if stunned == was_stunned:
            return
        message = 'Server báo bắt đầu choáng.' if stunned else 'Server báo hết choáng.'
        push_trace_note(message)
        if not (pvp_trigger_mode and pvp_armed and not pvp_paused
                and QtBind.isChecked(gui, pvp_stun_box)):
            return
        QtBind.setText(gui, status_label, message)
        if stunned:
            return
        pvp_wait_push_until = None
        direct_missed_skills.clear()
        if (pending is not None and not pending[2] and natural_cast is None
                and direct_exchange_wait is None and direct_action_ended):
            pending[1].cancel()
            pending = None
        if pending is None and direct_exchange_wait is None and natural_cast is None:
            now = monotonic()
            attempt = direct_retry_state or {}
            refused = (attempt.get('first_reply') == PVP_ACTION_REFUSAL
                       and not attempt.get('reply_ambiguous'))
            if direct_expected is not None and (refused or now >= pvp_cast_deadline):
                direct_expected = direct_retry_state = None
            if direct_expected is None:
                pvp_cast_deadline = 0.0
                pvp_first_skill = True


def imbue_seconds(data, key):
    try:
        seconds = float(data.get(key) or 0) / 1000
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return seconds if math.isfinite(seconds) and seconds > 0 else 0.0


def imbue_refresh_delay(data, early):
    duration = imbue_seconds(data, 'duration') or imbue_seconds(data, 'cooldown')
    return max(1.0, duration - early) if duration else 0.0


def imbue_is_active(api, uid, data):
    getter = getattr(api, 'get_active_skills', None)
    active = getter() if getter else None
    return data.get('active') is True or (isinstance(active, dict) and (uid in active or str(uid) in active))


def tick_imbue(character):
    global imbue_next_check, imbue_retry_at, imbue_seen_active, imbue_until, blocked_until
    now = monotonic()
    if (direct_baseline_mode or not imbue_id or (settings is None and not direct_skills) or now < imbue_next_check
            or character.get('dead') or owner_of(character) != profile_owner or get_status()):
        return False
    if pvp_pause_controls and (pvp_paused or not pvp_armed):
        return False
    if pvp_stun_blocks(character) or (pvp_trigger_mode and pvp_first_skill):
        return False
    # A busy attack must not push the polling deadline into the next attack.
    # Once Exchange completes, the overdue imbue gets first use of that gap.
    if (pending is not None or pvp_activation is not None or key_attempt is not None
            or direct_exchange_wait is not None or natural_cast is not None
            or skill_probe is not None
            or (direct_skills and direct_expected is not None) or now < blocked_until):
        return False
    imbue_next_check = now + 0.1
    data = skill_table().get(imbue_id) or {}
    if imbue_is_active(phbot_api, imbue_id, data):
        if not imbue_seen_active and not imbue_until:
            delay = imbue_refresh_delay(data, runtime_imbue_early)
            if delay:
                imbue_until = now + delay
        imbue_seen_active = True
        if not imbue_until or now < imbue_until:
            return False
    elif imbue_seen_active:
        imbue_seen_active = False
        imbue_until = 0.0
    elif now < imbue_until:
        return False
    if now < imbue_retry_at or data.get('can_cast') is False:
        return False
    # Self buff, no target/page dependency. Still respect the actual cooldown.
    imbue_retry_at = now + max(1.0, imbue_seconds(data, 'cooldown'))
    if inject_joymax(0x7074, struct.pack('<BBIB', 1, 4, imbue_id, 0), False) is False:
        imbue_retry_at = max(imbue_retry_at, now + 2.0)
        report('Tay phép: phBot từ chối ID=%d; sẽ thử lại sau.' % imbue_id)
        return False
    blocked_until = now + max(0.2, imbue_seconds(data, 'cast_time') + 0.1)
    report('Tay phép: gửi %s (ID=%d).' % (data.get('name', ''), imbue_id))
    return True


def observe_imbue(opcode, data):
    global imbue_until, imbue_retry_at
    if imbue_id and opcode == 0xB070 and len(data) >= 11 and data[:1] == b'\x01':
        uid, source = struct.unpack_from('<II', data, 3)
        if uid == imbue_id and source == (get_character_data() or {}).get('player_id'):
            now = monotonic()
            delay = imbue_refresh_delay(skill_table().get(uid) or {}, runtime_imbue_early)
            imbue_retry_at = now + 0.5
            imbue_until = now + (delay or 1.0)
            return True
    return False



def owner_of(character):
    if character.get('name'):
        return (str(character.get('server', '')), str(character['name']))
    return None


def config_path():
    return Path(get_config_dir()) / (CONFIG_NAME + '.json')


def read_profiles():
    try:
        with config_path().open(encoding='utf-8') as stream:
            profiles = json.load(stream)
    except FileNotFoundError:
        return {}
    if not isinstance(profiles, dict):
        raise ValueError('Định dạng cấu hình không hợp lệ.')
    return profiles


def write_profiles(profiles):
    import tempfile
    path = config_path()
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=str(path.parent), delete=False) as stream:
            temp = stream.name
            json.dump(profiles, stream, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)


def remember_imbue(owner):
    global imbue_saved_selection, imbue_save_after
    if not owner or owner != profile_owner or ui_sync:
        return
    selection = (QtBind.text(gui, imbue_field), QtBind.isChecked(gui, imbue_box))
    if selection == imbue_saved_selection or monotonic() < imbue_save_after:
        return
    if selection[0] != '(Không dùng)' and not re.search(r'\[\d+\]$', selection[0]):
        return
    try:
        profiles = read_profiles()
        profile = profiles.setdefault(json.dumps(owner), {})
        if not isinstance(profile, dict):
            raise ValueError('Hồ sơ nhân vật không hợp lệ.')
        profile.update(imbue_choice=selection[0], imbue_enabled=selection[1])
        write_profiles(profiles)
    except (OSError, ValueError) as error:
        imbue_save_after = monotonic() + 5
        report_error('Chưa lưu được tay phép: %s' % error)
        return
    imbue_saved_selection = selection
    report('Đã nhớ tay phép PvP cho %s: %s.' % (owner[1], selection[0]))


def load_profile(owner, profile_override=None):
    global profile_owner, imbue_saved_selection, imbue_save_after
    stop_clicked()
    profile_owner = owner
    try:
        profile = (profile_override if profile_override is not None else read_profiles().get(json.dumps(owner), {}))
        if not isinstance(profile, dict):
            raise ValueError('Hồ sơ nhân vật không hợp lệ.')
    except (OSError, ValueError) as error:
        profile = {}
        report_error('Lỗi đọc cấu hình: %s' % error)
    refresh_imbues(profile.get('imbue_choice', '(Không dùng)'))
    for name, field in profile_fields.items():
        default = ('30' if name == 'radius' else ('500' if name == 'probe_delay_ms' else '650' if name == 'reclick_wait_ms'
                   else (TRIGGER_MANUAL if name == 'pvp_trigger' else 'ESC → ESC (cũ)' if name == 'boss_method' else '')))
        if name=='id_method':default=ID_METHOD_EXCHANGE
        if name == 'numeric_interval_ms':default='20'
        if name == 'numeric_keys':default='4567890'
        if name == 'boss_skill_group':default='F1'
        if name == 'exchange':
            QtBind.setText(gui, field, str(profile.get(name, '')).strip() or '0')
            continue
        if name != 'imbue_choice':
            QtBind.setText(gui, field, str(profile.get(name, default)))
    selected_auto_page = next((page for page in PAGES if profile.get('use_' + page, bool(profile.get(page)))), None)
    for page in PAGES:
        set_checked_silent(page_boxes[page], page == selected_auto_page)
    legacy_page = next((page for page in PAGES if profile.get('use_' + page) is True
                        and str(profile.get(page, '')).strip()), None)
    legacy_page = legacy_page or next((page for page in PAGES if str(profile.get(page, '')).strip()), None)
    if 'numeric_keys' not in profile and legacy_page:
        QtBind.setText(gui, numeric_keys_field, str(profile[legacy_page]))
        QtBind.setText(gui, numeric_ms_field, str(profile.get('numeric_ms_' + legacy_page, '20')))
    boss_enabled = profile.get('boss_shared_mode') is True
    pvp_enabled = not boss_enabled and profile.get('pvp_enabled') is True
    set_checked_silent(boss_mode_box, boss_enabled)
    numeric_enabled = profile.get('numeric_enabled', selected_auto_page is not None) is True
    set_checked_silent(numeric_box, numeric_enabled and not pvp_enabled and not boss_enabled)
    saved_pages = profile.get('pvp_enabled_pages')
    for page in PAGES:
        set_checked_silent(pvp_page_boxes[page], page in PVP_EDIT_PAGES and
                           (page in saved_pages if isinstance(saved_pages, list) else page != 'F3'))
    set_checked_silent(imbue_box, profile.get('imbue_enabled') is True)
    set_checked_silent(pvp_stun_box, profile.get('resume_after_stun', True) is True)
    imbue_saved_selection = (QtBind.text(gui, imbue_field), QtBind.isChecked(gui, imbue_box))
    imbue_save_after = 0.0
    stable = False  # Recovery control is hidden; use the current working PvP engine.
    set_checked_silent(legacy_box, stable)
    set_checked_silent(reclick_box, not stable and profile.get('reclick_enabled') is True)
    for name, box in (('keys_enabled', ghost_box), ('boss_enabled', boss_box), ('pvp_enabled', pvp_box), ('hunt_enabled', hunt_box), ('pvp_background', pvp_background_box), ('direct_pvp', direct_box), ('boss_esc', boss_esc_box)):
        set_checked_silent(box, name != 'direct_pvp' and profile.get(name) is True)
    set_checked_silent(pvp_box, pvp_enabled)
    set_checked_silent(packet_mode_box,False)
    if profile.get('packet_f1') is True:set_checked_silent(pvp_background_box,True)
    set_checked_silent(hybrid_box,profile.get('hybrid_exchange_test') is True)
    if QtBind.isChecked(gui,hybrid_box):set_checked_silent(pvp_background_box,False)
    load_pvp_editor(profile)
    if boss_enabled:
        start_clicked(arm_only=True)  # Arm F1 only; no skill starts on profile load.


def save_clicked():
    global imbue_saved_selection
    owner = owner_of(get_character_data() or {})
    if owner is None or owner != profile_owner:
        report_error('Hãy chờ nhân vật vào game rồi lưu.')
        return
    applied_rows = False
    try:
        sync_pvp_editor()
        with pvp_lock:
            active_worker = hunt_stop
            active_pages = pvp_allowed_pages if pvp_trigger_mode and direct_skills else ()
            saved_groups = compile_skill_groups(active_pages, allow_empty=True) if active_pages else {}
        profiles = read_profiles()
        profile = {name: QtBind.text(gui, field) for name, field in profile_fields.items()}
        profile.update({'use_' + page: QtBind.isChecked(gui, page_boxes[page]) for page in PAGES})
        profile['numeric_enabled'] = QtBind.isChecked(gui, numeric_box)
        profile['boss_shared_mode'] = QtBind.isChecked(gui, boss_mode_box)
        profile['pvp_enabled_pages'] = [page for page in PVP_EDIT_PAGES if QtBind.isChecked(gui, pvp_page_boxes[page])]
        profile['skill_rows'] = [dict(row) for row in skill_rows]
        profile['pvp_mode_choice'] = QtBind.text(gui, pvp_mode_field)
        profile['imbue_early_seconds'] = QtBind.text(gui, imbue_early_field)
        profile['imbue_enabled'] = QtBind.isChecked(gui, imbue_box)
        profile['resume_after_stun'] = QtBind.isChecked(gui, pvp_stun_box)
        profile['reclick_enabled'] = QtBind.isChecked(gui, reclick_box)
        profile['packet_f1'] = QtBind.isChecked(gui,pvp_background_box)
        profile['hybrid_exchange_test'] = QtBind.isChecked(gui,hybrid_box)
        profile['legacy_pvp'] = QtBind.isChecked(gui, legacy_box)
        for name, box in (('keys_enabled', ghost_box), ('boss_enabled', boss_box), ('pvp_enabled', pvp_box), ('hunt_enabled', hunt_box), ('pvp_background', pvp_background_box), ('direct_pvp', direct_box), ('boss_esc', boss_esc_box)):
            profile[name] = QtBind.isChecked(gui, box)
        profiles[json.dumps(owner)] = profile
        write_profiles(profiles)
        imbue_saved_selection = (profile['imbue_choice'], profile['imbue_enabled'])
        with pvp_lock:
            if owner == profile_owner and pvp_trigger_mode:
                runtime_gear[PVP_STOP_PAGE] = {
                    'weapon': profile['weapon_F4'].strip(),
                    'shield': profile['shield_F4'].strip(),
                }
                if active_worker is hunt_stop and active_pages == pvp_allowed_pages and direct_skills:
                    for page in active_pages:
                        runtime_skill_groups[page] = saved_groups.get(page)
                    applied_rows = bool(active_pages)
    except (OSError, ValueError) as error:
        report_error('Lỗi lưu cấu hình: %s' % error)
        return
    QtBind.setText(gui, status_label, 'Đã lưu cấu hình cho %s.%s' %
                   (owner[1], ' Đã áp dụng các ô Tắt và Ngắt cho lượt kế tiếp.' if applied_rows else ''))
    if QtBind.isChecked(gui, boss_mode_box) and not boss_running():
        disarm_boss()
        start_clicked(arm_only=True)
    return profile


named_profile_name = widget('presets','createLineEdit','',130,65,300,20)
named_profile_choice = widget('presets','createCombobox',130,110,300,22)
widget('presets','createLabel','Tên bộ cần lưu',15,68)
widget('presets','createLabel','Bộ đã lưu',15,113)
widget('presets','createButton','save_named_profile','Lưu bộ',450,63)
widget('presets','createButton','apply_named_profile','Nạp cho acc này',450,108)
widget('presets','createButton','refresh_named_profiles','Làm mới',565,108)
widget('presets','createButton','hide_game_clicked','Ẩn game',15,150)
widget('presets','createButton','show_game_clicked','Hiện game',108,150)
widget('presets', 'createLabel', 'Acc hỗ trợ ngắt Boss', 225, 154)
boss_exchange_player_field = widget('presets', 'createLineEdit', '', 370, 149, 190, 22)
profile_fields['boss_exchange_player'] = boss_exchange_player_field
pvp_stun_box = widget('presets', 'createCheckBox', 'stun_option_changed',
                      'Hiệu ứng ngoài lề · Nối sau choáng (PvP)', 15, 173)
set_checked_silent(pvp_stun_box, True)
widget('presets','createLabel','Bỏ trống = Solo Boss (client-7081 như PvP). Có tên = Exchange acc hỗ trợ.',15,195)
widget('presets','createLabel','Nạp sẽ thay cấu hình acc hiện tại. Cùng tên: lưu cập nhật bộ cũ.',15,220)


client_exchange = None
phbot_bridge_process=None
phbot_bridge_pending=None
phbot_bridge_ready=False
phbot_bridge_stats={'calls':0,'confirmed':0,'total_ms':0,'max_ms':0}
phbot_mouse_verified=False
phbot_mouse_probe_ticket=None
phbot_detail_box=widget('hidden','createCheckBox','phbot_detail_changed','Log chi tiết đường ngắt',300,247)
widget('presets','createButton','stop_packet_trace','Dừng ghi',225,245)
widget('presets','createButton','start_push_trace','Đo đẩy lùi',15,245)
widget('presets','createButton','mark_push_trace','Mốc bị đẩy',120,245)
trace_status_label = widget('presets', 'createLabel', '', 15, 275)


PHBOT_EXCHANGE_SCRIPT = r"""
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class HHFocusSnapshot {
 [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
 [DllImport("user32.dll",SetLastError=true)] public static extern bool PostMessage(IntPtr hwnd,uint msg,UIntPtr wp,IntPtr lp);
 [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hwnd,ref POINT point);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);
 [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }
 [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
 [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO info);
 public static uint InputTick() { var info=new LASTINPUTINFO(); info.cbSize=(uint)Marshal.SizeOf(info); return GetLastInputInfo(ref info)?info.dwTime:0; }
}
'@
[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)
$button=$null
[Console]::WriteLine('{"stage":"ready"}')
while ($line=[Console]::ReadLine()) {
 $q=$null
 try {
  $q=$line|ConvertFrom-Json
  @{id=$q.id;stage='searching_button'}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}
  if ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires) {throw 'Request expired'}
  if (!$button -or $button.Current.ProcessId -ne [int]$q.pid) {
   do {
   $roots=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$q.pid)))
   $matches=New-Object System.Collections.Generic.List[System.Windows.Automation.AutomationElement]
   $captions=New-Object System.Collections.Generic.List[string]
   foreach($root in $roots) {
    $buttons=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)
    foreach($b in $buttons) {
     $caption=$b.Current.Name
     $normalized=($caption -replace '&','' -replace '\s','').ToLowerInvariant()
     if($b.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and $captions.Count -lt 30){$captions.Add($caption)}
     if($normalized -eq 'requestexchange'){$matches.Add($b)}
    }
   }
   if($q.action -in @('probe','mouse_probe') -and $matches.Count -ne 1){Start-Sleep -Milliseconds 500}
   } while($q.action -in @('probe','mouse_probe') -and $matches.Count -ne 1 -and [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -lt [long]$q.expires)
   if($matches.Count -ne 1){throw ('Request Exchange button count: '+$matches.Count+'; ProcessId='+$q.pid+'; roots='+$roots.Count+'; buttons=['+($captions -join ' | ')+']')}
   $button=$matches[0]
  }
  if(!$button.Current.IsEnabled -or $button.Current.IsOffscreen){throw 'Open phBot Inventory / Exchange page and leave it visible'}
  $scope=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($button)
  $combos=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::ComboBox)))
  for($depth=0;$combos.Count -eq 0 -and $depth -lt 3;$depth++) {
   $parent=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($scope)
   if(!$parent -or $parent.Current.ProcessId -ne [int]$q.pid){break}
   $scope=$parent
   $combos=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::ComboBox)))
  }

  $matched=0
  $comboDetails=New-Object System.Collections.Generic.List[string]
  foreach($combo in $combos) {
   $selectedText=''
   $source='none'
   $sp=$null
   if($combo.TryGetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern,[ref]$sp)) {
    $selected=$sp.Current.GetSelection()
    if($selected.Count -eq 1){$selectedText=$selected[0].Current.Name;$source='SelectionPattern'}
   }
   if(!$selectedText) {
    $vp=$null
    if($combo.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$vp)) {
     $value=$vp.Current.Value
     $selectedText=$value
     $source=if($vp.Current.IsReadOnly){'ReadOnlyValue'}else{'EditableValue'}
    }
   }
   $comboDetails.Add(('Name='+$combo.Current.Name+', selected='+$selectedText+', source='+$source))
   if($selectedText -and (($q.action -in @('probe','mouse_probe') -and !$q.name) -or $selectedText -ceq [string]$q.name)){$matched++;$selectedName=$selectedText;$matchedCombo=$combo;$matchedSource=$source}
  }
  if($matched -ne 1){throw ('Player selection matches='+$matched+'; expected=['+$q.name+']; ComboBoxes='+$combos.Count+'; details=['+($comboDetails -join ' | ')+']')}
  if($q.action -in @('probe','verify')) {
   @{id=$q.id;ok=$true;name=$selectedName;probe=$true}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}
   continue
  }
  if([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires){throw 'Request expired before background click'}
  if($matchedSource -eq 'EditableValue' -or $matchedSource -eq 'ReadOnlyValue') {
   $verify=$matchedCombo.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)
   if($verify.Current.Value -cne $selectedName){throw 'Player changed before background click'}
  } else {
   $verify=$matchedCombo.GetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern)
   $verifyItems=$verify.Current.GetSelection()
   if($verifyItems.Count -ne 1 -or $verifyItems[0].Current.Name -cne $selectedName){throw 'Player changed before background click'}
  }
  $focusBefore=[HHFocusSnapshot]::GetForegroundWindow().ToInt64()
  $inputBefore=[HHFocusSnapshot]::InputTick()
  $watch=[Diagnostics.Stopwatch]::StartNew()
  if($q.transport -eq 'postmouse') {
   [uint32]$foregroundPid=0
   [HHFocusSnapshot]::GetWindowThreadProcessId([IntPtr]$focusBefore,[ref]$foregroundPid)|Out-Null
   if($q.action -eq 'mouse_probe' -and $foregroundPid -eq [uint32]$q.pid){throw 'Switch to game or another window before the one-shot test; phBot must not be foreground'}
   $rect=$button.Current.BoundingRectangle
   if($rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0){throw 'Invalid Exchange button rectangle'}
   $node=$button
   $hwnd=[IntPtr]::Zero
   for($n=0;$node -and $n -lt 12;$n++) {
    if($node.Current.ProcessId -ne [int]$q.pid){break}
    $handle=$node.Current.NativeWindowHandle
    if($handle){$hwnd=[IntPtr]$handle;break}
    $node=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($node)
   }
   if($hwnd -eq [IntPtr]::Zero){throw 'No native ancestor window for Exchange button'}
   [uint32]$ownerPid=0
   [HHFocusSnapshot]::GetWindowThreadProcessId($hwnd,[ref]$ownerPid)|Out-Null
   if($ownerPid -ne [uint32]$q.pid){throw 'Exchange window belongs to another process'}
   $point=New-Object HHFocusSnapshot+POINT
   $point.X=[int]($rect.Left+$rect.Width/2);$point.Y=[int]($rect.Top+$rect.Height/2)
   if(![HHFocusSnapshot]::ScreenToClient($hwnd,[ref]$point)){throw 'Cannot map Exchange coordinates'}
   if($point.X -lt 0 -or $point.Y -lt 0 -or $point.X -gt 32767 -or $point.Y -gt 32767){throw 'Exchange coordinates outside supported range'}
   if([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires){throw 'Request expired before PostMessage'}
   $lp=[IntPtr](($point.Y -shl 16) -bor ($point.X -band 65535))
   @{id=$q.id;stage='posting_mouse'}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}
   [Console]::Out.Flush()
   if(![HHFocusSnapshot]::PostMessage($hwnd,0x0201,[UIntPtr]::new([uint32]1),$lp)){throw 'WM_LBUTTONDOWN rejected'}
   $released=[HHFocusSnapshot]::PostMessage($hwnd,0x0202,[UIntPtr]::Zero,$lp)
   if(!$released){throw 'WM_LBUTTONUP rejected; inspect phBot button state'}
   @{id=$q.id;stage='mouse_posted'}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}
   [Console]::Out.Flush()
   Start-Sleep -Milliseconds 120
   $after=[HHFocusSnapshot]::GetForegroundWindow().ToInt64()
   [uint32]$afterPid=0
   [HHFocusSnapshot]::GetWindowThreadProcessId([IntPtr]$after,[ref]$afterPid)|Out-Null
   $stolen=($foregroundPid -ne [uint32]$q.pid -and $afterPid -eq [uint32]$q.pid)
   @{id=$q.id;ok=$true;name=$selectedName;transport='postmouse';ms=$watch.ElapsedMilliseconds;focus_before=$focusBefore;focus_after=$after;focus_stolen=$stolen;input_before=$inputBefore;input_after=[HHFocusSnapshot]::InputTick();mouse_probe=($q.action -eq 'mouse_probe')}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}
  } else {throw 'Only PostMessage transport is supported'}
 } catch {
  $button=$null
  @{id=$q.id;ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}
 }
}
"""


def phbot_detail_changed(checked):
    pass  # Logging preference never changes a running combat session.


def bridge_detail(message):
    if QtBind.isChecked(gui,phbot_detail_box):report(message)


def probe_phbot_mouse():
    global phbot_mouse_verified,phbot_mouse_probe_ticket
    stop_clicked()
    phbot_mouse_verified=False
    ticket=object()
    phbot_mouse_probe_ticket=ticket
    report('THỬ NỀN 1 LẦN: có 5s mở Hòm đồ/Exchange, chọn Player và chuyển sang game/cửa sổ khác. Chỉ gửi một cặp thông điệp chuột; không tự xác nhận giao dịch.')
    Timer(5.0,run_phbot_mouse_probe,args=(ticket,owner_of(get_character_data() or {}))).start()


def run_phbot_mouse_probe(ticket,owner):
    global phbot_bridge_pending
    import time
    with pvp_lock:
        if ticket is not phbot_mouse_probe_ticket or owner is None or owner!=owner_of(get_character_data() or {}):return
        try:
            if os.name!='nt':raise ValueError('Cần Windows.')
            if phbot_bridge_pending is not None:raise ValueError('Đang có lượt thử khác.')
            process=ensure_phbot_bridge()
            request_id='mouse-probe-'+str(monotonic())
            phbot_bridge_pending={'id':request_id,'probe':True,'mouse_probe':True,'stage':'queued'}
            process.stdin.write(json.dumps({'id':request_id,'pid':os.getpid(),'name':'','action':'mouse_probe','transport':'postmouse','expires':round((time.time()+20)*1000)})+'\n')
            process.stdin.flush()
            Timer(21.0,expire_phbot_probe,args=(request_id,)).start()
        except (OSError,ValueError) as error:report('THỬ NỀN 1 LẦN: '+str(error))


def close_phbot_bridge():
    global phbot_bridge_process,phbot_bridge_pending,phbot_bridge_ready
    phbot_bridge_ready=False
    process=phbot_bridge_process
    phbot_bridge_process=phbot_bridge_pending=None
    if process is not None:
        try:process.kill()
        except (OSError,AttributeError):pass


# Verified Hùng Vương client builds with the same code and GetTickCount slot.
CLIENT_SHA256 = {
    'bd2aba5bb7ac74890f3a73795106339e556bd1499f019f4d637f0528fc3baa30',
    '5a67d0dd86436e1b1cde1fb8aa339b19286fcb8953c9437de1922fc60343d2de',
}
TICK_SLOT = 0xD801B8
CLIENT_SIGNATURES = {
    0x53CEA0: '668b442404568bf1b998cdee00c706e4',
    0x508FE0: '8b44240453558b6c241085ed8bd98944',
    0x8418D0: '6aff680e55d20064a10000000050b808',
    0x5097A0: '53578bf9c707e431d800e811caffff8b',
}


def kernel_api():
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    handle, pointer, size, dword, boolean = (wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                              wintypes.DWORD, wintypes.BOOL)
    entries = {
        'OpenProcess': (handle, dword, boolean, dword),
        'CloseHandle': (boolean, handle),
        'GetExitCodeProcess': (boolean, handle, ctypes.POINTER(dword)),
        'QueryFullProcessImageNameW': (boolean, handle, dword, wintypes.LPWSTR, ctypes.POINTER(dword)),
        'K32GetMappedFileNameW': (dword, handle, pointer, wintypes.LPWSTR, dword),
        'VirtualAllocEx': (pointer, handle, pointer, size, dword, dword),
        'VirtualFreeEx': (boolean, handle, pointer, size, dword),
        'VirtualProtectEx': (boolean, handle, pointer, size, dword, ctypes.POINTER(dword)),
        'FlushInstructionCache': (boolean, handle, pointer, size),
        'ReadProcessMemory': (boolean, handle, pointer, pointer, size, ctypes.POINTER(size)),
        'WriteProcessMemory': (boolean, handle, pointer, pointer, size, ctypes.POINTER(size)),
    }
    for name, (result, *args) in entries.items():
        function = getattr(api, name)
        function.restype, function.argtypes = result, args
    return api


class NativeCut:
    def __init__(self, job):
        self.api = kernel_api()
        # QUERY_INFORMATION and VM_OPERATION/READ/WRITE.
        self.handle = self.api.OpenProcess(0x0438, False, job['pid'])
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        self.page = self.code = self.original = 0
        self.published = False
        try:
            self.install(job)
        except Exception:
            self.close()
            raise

    def read(self, address, count):
        data = ctypes.create_string_buffer(count)
        size = ctypes.c_size_t()
        if not self.api.ReadProcessMemory(self.handle, address, data, count, ctypes.byref(size)) or size.value != count:
            raise OSError('Không đọc được bộ nhớ client tại 0x%X.' % address)
        return data.raw

    def write(self, address, data):
        size = ctypes.c_size_t()
        buffer = ctypes.create_string_buffer(data)
        if not self.api.WriteProcessMemory(self.handle, address, buffer, len(data), ctypes.byref(size)) or size.value != len(data):
            raise OSError('Không ghi được bộ nhớ client tại 0x%X.' % address)

    def protect(self, address, count, flags):
        old = wintypes.DWORD()
        if not self.api.VirtualProtectEx(self.handle, address, count, flags, ctypes.byref(old)):
            raise OSError('Không đổi được quyền trang tại 0x%X.' % address)
        return old.value

    def install(self, job):
        tid_pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(job['window'], ctypes.byref(tid_pid))
        if not tid or tid_pid.value != job['pid']:
            raise RuntimeError('HWND không thuộc PID client đã chọn.')
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        if not self.api.QueryFullProcessImageNameW(self.handle, 0, path, ctypes.byref(length)):
            raise OSError('Không đọc được đường dẫn client.')
        with open(path.value, 'rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        if digest not in CLIENT_SHA256:
            raise RuntimeError('Client đang chạy khác bản Hùng Vương đã đối chiếu. SHA256=' + digest)
        for address, signature in CLIENT_SIGNATURES.items():
            expected = bytes.fromhex(signature)
            if self.read(address, len(expected)) != expected:
                raise RuntimeError('Mã client trong bộ nhớ khác bản đã đối chiếu tại 0x%X.' % address)
        self.original = struct.unpack('<I', self.read(TICK_SLOT, 4))[0]
        if not self.api.K32GetMappedFileNameW(self.handle, self.original, path, len(path)):
            raise RuntimeError('Không xác minh được đích GetTickCount.')
        if PureWindowsPath(path.value).name.casefold() not in ('kernel32.dll', 'kernelbase.dll'):
            raise RuntimeError('GetTickCount đang qua một móc khác. Dừng thử.')
        self.page = self.api.VirtualAllocEx(self.handle, None, 8192, 0x3000, 0x04) or 0
        if not self.page or self.page + 8191 > 0xffffffff:
            raise RuntimeError('Không cấp phát được vùng 32-bit cho lượt thử.')
        self.code = self.page + 4096
        thunk = THUNK.replace(b'DCBa', struct.pack('<I', self.page)).replace(b'DCBb', struct.pack('<I', self.page + 12))
        self.write(self.page, struct.pack('<IIII', 0, tid, job['target'], self.original))
        self.write(self.code, thunk)
        self.protect(self.code, 4096, 0x20)
        if not self.api.FlushInstructionCache(self.handle, self.code, len(thunk)):
            raise OSError('Không đồng bộ được mã thử với client.')
        if self.read(TICK_SLOT, 4) != struct.pack('<I', self.original):
            raise RuntimeError('GetTickCount vừa đổi trong khi chuẩn bị.')
        old = self.protect(TICK_SLOT, 4, 0x04)
        try:
            # Once published, the remote page remains mapped for in-flight callers.
            self.published = True
            self.write(TICK_SLOT, struct.pack('<I', self.code))
        finally:
            self.protect(TICK_SLOT, 4, old)

    def arm(self, value):
        self.write(self.page, struct.pack('<I', value))

    def completed(self, value):
        state = struct.unpack('<I', self.read(self.page, 4))[0]
        if state == 6:
            raise RuntimeError('Client chưa có đối tượng mạng hoặc hàng đợi gửi.')
        if state == 7:
            raise RuntimeError('Client không cấp được bộ đệm dựng gói 7081.')
        return state == value

    def close(self):
        if not self.handle:
            return
        try:
            exit_code = wintypes.DWORD()
            if self.api.GetExitCodeProcess(self.handle, ctypes.byref(exit_code)) and exit_code.value != 259:
                return
            if self.published:
                # Stop new work before restoring. Keep mapped code for any thread
                # which already fetched the old pointer.
                try:
                    self.arm(0)
                finally:
                    current = self.read(TICK_SLOT, 4)
                    original = struct.pack('<I', self.original)
                    if current == struct.pack('<I', self.code):
                        old = self.protect(TICK_SLOT, 4, 0x04)
                        try:
                            self.write(TICK_SLOT, original)
                        finally:
                            self.protect(TICK_SLOT, 4, old)
                    if self.read(TICK_SLOT, 4) != original:
                        raise OSError('Con trỏ GetTickCount không trở về giá trị gốc.')
            elif self.page:
                self.api.VirtualFreeEx(self.handle, self.page, 0, 0x8000)
        finally:
            self.api.CloseHandle(self.handle)
            self.handle = None

# x86 thunk. Marker DCBa is the state pointer, DCBb is the original API slot in that state.
THUNK = bytes.fromhex(
    '9c60bb4443426164a1240000003b43040f85130100008b03'
    '83f801740983f8020f850301000089c2b903000000f00fb1'
    '0b0f85f200000083fa010f84db000000833d68ceee00000f'
    '84d6000000803d50cdee0000751a833dc0b01501000f84c0'
    '000000833d7ccdee00000f84b300000089e583e4f081ec20'
    '0200000fae442420fc31c089042489442404894424088944'
    '240c8944241089442414894424188944241c89e168817000'
    '00b8a0ce5300ffd0837c241000744bc644240c018b442410'
    '89442414c74424080000000089e18d53086a0452b8e08f50'
    '00ffd0c644240c008b44241089442414c744240400000000'
    '54b8d0188400ffd083c404bf05000000eb05bf0700000089'
    'e1b8a0975000ffd00fae4c242089ec893beb0ec703040000'
    '00eb06c70306000000619dff2544434262'
)

def close_client_exchange():
    global client_exchange
    session, client_exchange = client_exchange, None
    if session is not None:
        try:
            session['bridge'].close()
        except (OSError, ValueError) as error:
            report_error('7081 trực tiếp: chưa xác minh được tháo móc. Đóng client game trước khi thử lại. ' + str(error))


def stop_invalid_native_pvp(character):
    # Check the live session before a pending 7081 or another PvP skill.
    session = client_exchange
    dead = character.get('dead')
    if not session and not (dead and pvp_trigger_mode and
                            (pvp_target or pvp_selection_request or pvp_armed or pvp_activation)):
        return False
    owner = owner_of(character)
    changed_owner = not owner or owner != profile_owner
    if dead:
        reason = 'nhân vật đã chết'
    elif changed_owner:
        reason = 'đã đổi nhân vật hoặc mất dữ liệu nhân vật'
    elif get_status():
        reason = 'bot chính đã bật'
    else:
        client = get_client() or {}
        if not client.get('running'):
            reason = 'client game không còn chạy'
        elif (client.get('pid'), client.get('window')) != session['key'][:2]:
            context = direct_exchange_wait
            if auto_pk_running and client.get('pid') == session['key'][0] and not client.get('window'):
                close_client_exchange()
                if context and context.get('transport') == 'client_7081':
                    wait_for_background_skill_end(context['owner'], context['target'], context,
                                                  'không còn HWND hợp lệ để ngắt Ghost nền')
                return False
            reason = ('client game đã đổi hoặc mất cửa sổ '
                      '(PID %s → %s, HWND %s → %s)' %
                      (session['key'][0], client.get('pid'), session['key'][1], client.get('window')))
        else:
            return False
    if auto_pk_running:
        if owner and owner != auto_pk_runtime['owner']:
            stop_auto_pk(reason='đã đổi nhân vật')
        else:
            hold_auto_pk(reason, retry_after=1.0)
        return True
    pause_pvp(reason, clear_target=bool(dead) or changed_owner, cancel_action=False)
    return True


def get_client_exchange(client, target):
    global client_exchange
    if not client.get('running') or not client.get('window') or not client.get('pid'):
        raise ValueError('Cần client Silkroad đang chạy; kiểm tra Clientless.')
    key = (client['pid'], client['window'], target)
    if client_exchange is None or client_exchange['key'] != key:
        close_client_exchange()
        bridge = NativeCut({'pid': key[0], 'window': key[1], 'target': target})
        client_exchange = {'key': key, 'bridge': bridge, 'verified': False}
    return client_exchange


def prepare_client_exchange(job, client):
    try:
        session = get_client_exchange(client, job['target'])
        if session['verified']:
            return True
        if 'client_check_until' not in job:
            session['bridge'].arm(1)
            job['client_check_until'] = monotonic() + 3.0
        if session['bridge'].completed(4):
            session['verified'] = True
            report('7081 trực tiếp: đã xác minh client và luồng gửi cho UID=%d.' % job['target'])
            return True
        if monotonic() >= job['client_check_until']:
            raise ValueError('không nhận được nhịp luồng của cửa sổ game.')
    except (OSError, ValueError, RuntimeError) as error:
        close_client_exchange()
        fail_pvp_activation('7081 trực tiếp: ' + str(error))
    return False


def client_exchange_confirmed(context):
    if not context.get('observed_request') or context.get('cancel_reply') is None:
        return False
    session = context['client_session']
    client = get_client() or {}
    if (session is not client_exchange or not client.get('running')
            or (client.get('pid'), client.get('window')) != session['key'][:2]):
        raise ValueError('client đã đổi trong lúc ngắt.')
    if session['bridge'].completed(5):
        session['verified'] = True
        return True
    return False


def auxiliary_exchange():
    return (pvp_activation or {}).get('emergency') or (auto_pk_runtime or {}).get('withdraw')


def auxiliary_exchange_ready(context):
    if context.get('transport') == 'phbot_button':
        return context.get('invoked') and context.get('cancel_reply') is not None
    if context.get('transport') == 'client_7081':
        try:
            return client_exchange_confirmed(context)
        except (OSError, ValueError, RuntimeError) as error:
            if auto_pk_returning:
                report('7081 trực tiếp: ' + str(error))
                context['deadline'] = 0.0
            else:
                pause_pvp('7081 trực tiếp: ' + str(error))
            return False
    return context['observed']


def send_pvp_interrupt(context):
    session = get_client_exchange(get_client() or {}, context['target'])
    context.update(transport='client_7081', client_session=session,
                   observed_request=False, cancel_reply=None)
    session['bridge'].arm(2)


def phbot_bridge_reader(process):
    global phbot_bridge_pending,phbot_bridge_ready,phbot_mouse_verified
    try:
        for line in process.stdout:
            try:reply=json.loads(line)
            except ValueError:
                if line.strip() and not line.strip().startswith('#< CLIXML'):report('Request Exchange phBot: helper: '+line.strip()[:350])
                continue
            with pvp_lock:
                if process is not phbot_bridge_process:continue
                if reply.get('stage')=='ready':
                    phbot_bridge_ready=True
                    report('Request Exchange phBot: helper đã khởi động, nạp UI Automation xong.')
                    continue
                pending_request=phbot_bridge_pending
                if process is not phbot_bridge_process or not pending_request or reply.get('id')!=pending_request['id']:continue
                if reply.get('stage'):
                    pending_request['stage']=reply['stage']
                    if reply['stage']=='posting_mouse' and 'context' in pending_request:
                        pending_request['context']['posting']=True
                    (report if pending_request.get('probe') else bridge_detail)('Request Exchange phBot: bước '+str(reply['stage']))
                    continue
                if pending_request.get('activation') is not None:
                    phbot_bridge_pending = None
                    job = pending_request['activation']
                    if job is pvp_activation:
                        job['exchange_verified'] = (reply.get('ok') is True
                                                    and reply.get('name') == pending_request['name'])
                        job['exchange_check_error'] = reply.get('error')
                        if not job['exchange_verified']:
                            error = str(reply.get('error') or '')
                            if 'Player selection matches=' in error and 'ComboBoxes=0;' not in error:
                                hint = 'Chọn Player ' + pending_request['name']
                            else:
                                hint = 'Mở Hòm đồ phBot để thấy nút Request Exchange'
                            QtBind.setText(gui, status_label, 'Đang chờ: ' + hint)
                        job['exchange_check_after'] = monotonic() + 0.4
                    continue
                if pending_request.get('probe'):
                    phbot_bridge_pending=None
                    if pending_request.get('mouse_probe'):
                        phbot_mouse_verified=(reply.get('ok') is True and reply.get('transport')=='postmouse'
                            and reply.get('focus_stolen') is False and reply.get('focus_before')==reply.get('focus_after')
                            and reply.get('input_before')==reply.get('input_after'))
                        report('THỬ NỀN 1 LẦN: %s | focus trước=%s sau=%s | %s. Chỉ xác minh gửi thông điệp/tiêu điểm, chưa chứng minh ngắt skill.'%
                            ('đã gửi, tiêu điểm giữ nguyên' if phbot_mouse_verified else 'CHƯA ĐẠT',reply.get('focus_before'),reply.get('focus_after'),reply.get('error','không tự lặp')))
                        continue
                    report('Request Exchange phBot KIỂM TRA: '+('tìm được nút và Player='+str(reply.get('name'))+'; chưa bấm nút.' if reply.get('ok') else str(reply.get('error'))))
                    continue
                phbot_bridge_pending=None
                context=pending_request['context']
                if context is not direct_exchange_wait and context is not auxiliary_exchange():continue
                if reply.get('ok') is not True or reply.get('transport')!='postmouse' or reply.get('focus_stolen') is not False:
                    reason = str(reply.get('error') or 'Không xác nhận được tiêu điểm giữ nguyên.')
                    if (context is direct_exchange_wait and not context.get('posting')
                            and not context.get('ui_retry_at') and not context.get('ui_retried')
                            and monotonic() + 0.4 < context['deadline']
                            and exchange_ui_unavailable(reason)):
                        context['ui_retry_at'] = monotonic() + 0.15
                        bridge_detail('Exchange nền: Hòm đồ tạm thời chưa đọc được; sẽ dò lại một lần.')
                        continue
                    if (context.get('auto_background') and not context.get('posting')
                            and reply.get('focus_stolen') is not True):
                        wait_for_background_skill_end(context['owner'], context['target'], context, reason)
                        continue
                    if auto_pk_returning:
                        report('Exchange nền phBot: '+reason)
                        withdraw = (auto_pk_runtime or {}).get('withdraw')
                        if withdraw:
                            withdraw['deadline'] = 0.0
                    else:
                        pause_pvp('Exchange nền phBot: '+reason)
                    continue
                context['invoked']=True
                elapsed=round((monotonic()-context.get('queued_at',monotonic()))*1000)
                phbot_bridge_stats['calls']+=1
                phbot_bridge_stats['total_ms']+=elapsed
                phbot_bridge_stats['max_ms']=max(phbot_bridge_stats['max_ms'],elapsed)

                bridge_detail('Exchange nền phBot: đã gửi tới %s, %s ms; chờ phản hồi ngắt.'%(reply.get('name'),reply.get('ms')))
                bridge_detail('Request Exchange phBot: từ lúc yêu cầu đến phản hồi gọi nút %d ms.'%round((monotonic()-context.get('queued_at',monotonic()))*1000))
                check_direct_exchange()
        if process is phbot_bridge_process:report('Request Exchange phBot: helper kết thúc; mã=%s.'%process.poll())
    except (OSError,ValueError) as error:
        report('Request Exchange phBot: lỗi đọc phản hồi '+str(error))


def ensure_phbot_bridge():
    global phbot_bridge_process,phbot_bridge_ready
    import subprocess,base64
    process=phbot_bridge_process
    if process is None or process.poll() is not None:
        phbot_bridge_ready=False
        script=base64.b64encode(PHBOT_EXCHANGE_SCRIPT.encode('utf-16le')).decode('ascii')
        executable=str(Path(os.environ.get('SystemRoot','C:/Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe')
        process=subprocess.Popen([executable,'-NoProfile','-NonInteractive','-EncodedCommand',script],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',creationflags=0x08000000,bufsize=1)
        phbot_bridge_process=process
        Thread(target=phbot_bridge_reader,args=(process,),daemon=True).start()
    return process


def exchange_ui_unavailable(error):
    return ('ComboBoxes=0;' in error or 'Request Exchange button count: 0;' in error
            or error.startswith('Open phBot Inventory'))


def phbot_exchange_target_name(uid):
    getter = getattr(phbot_api, 'get_players', None)
    players = getter() if callable(getter) else None
    player = (players.get(uid) or players.get(str(uid))) if isinstance(players, dict) else None
    return player.get('name') if isinstance(player, dict) else None


def prepare_phbot_exchange(job):
    global phbot_bridge_pending
    if job.get('exchange_verified'):
        return True
    now = monotonic()
    name = phbot_exchange_target_name(job['target'])
    if 'exchange_check_until' not in job:
        job['exchange_check_until'] = now + 10.0
        QtBind.setText(gui, status_label, 'Đang chờ Hòm đồ và Player %s…' % (name or job['target']))
        report('Exchange nền: mở Hòm đồ phBot, chọn Player %s. Chờ kiểm tra trước khi đánh.' % (name or job['target']))
    if now >= job['exchange_check_until']:
        if (phbot_bridge_pending or {}).get('activation') is job:
            close_phbot_bridge()
        error = str(job.get('exchange_check_error') or '')
        if error:
            report('Exchange nền: kiểm tra nút/Player thất bại: ' + error[:450])
        if not name:
            fail_pvp_activation('chưa đọc được tên UID %d; đứng gần rồi chọn lại đối thủ' % job['target'])
        elif 'Player selection matches=' in error and not exchange_ui_unavailable(error):
            fail_pvp_activation('chọn đúng Player %s trong Hòm đồ' % name)
        else:
            fail_pvp_activation('chưa xác nhận Request Exchange; mở Hòm đồ và chọn Player %s' % name)
        return False
    if not name or phbot_bridge_pending is not None or now < job.get('exchange_check_after', 0):
        return False
    try:
        process = ensure_phbot_bridge()
        request_id = 'verify-' + str(now)
        phbot_bridge_pending = {'id': request_id, 'activation': job, 'name': name, 'stage': 'queued'}
        process.stdin.write(json.dumps({'id': request_id, 'pid': os.getpid(), 'name': name,
                                        'action': 'verify', 'expires': round((time() + 2) * 1000)}) + '\n')
        process.stdin.flush()
    except (OSError, ValueError) as error:
        close_phbot_bridge()
        fail_pvp_activation('lỗi kiểm tra Exchange nền: ' + str(error))
    return False


def queue_phbot_exchange(context):
    global phbot_bridge_pending
    from time import time
    if os.name!='nt':raise ValueError('Cần Windows để gọi nút phBot.')
    if phbot_bridge_pending is not None:raise ValueError('Đang có yêu cầu nút chưa hoàn tất.')
    name=phbot_exchange_target_name(context['target'])
    if not name:raise ValueError('Không đọc được tên target để đối chiếu Player.')
    process=ensure_phbot_bridge()
    context['queued_at']=monotonic()
    request_id=str(monotonic())
    phbot_bridge_pending={'id':request_id,'context':context,'stage':'queued'}
    process.stdin.write(json.dumps({'id':request_id,'pid':os.getpid(),'name':name,'action':'cut','transport':'postmouse','expires':round((time()+max(0,context['deadline']-monotonic()))*1000)},ensure_ascii=False)+'\n')
    process.stdin.flush()


def probe_phbot_button():
    stop_clicked()
    report('Request Exchange phBot KIỂM TRA: có 30 giây để mở Thùng đồ → Exchange và chọn Player. Tự dò lại; không gửi trao đổi.')
    Timer(0.5,run_phbot_button_probe).start()


def run_phbot_button_probe():
    global phbot_bridge_pending
    import time
    try:
        if os.name!='nt':raise ValueError('Cần Windows.')
        process=ensure_phbot_bridge()
        request_id='probe-'+str(monotonic())
        phbot_bridge_pending={'id':request_id,'probe':True,'stage':'queued'}
        process.stdin.write(json.dumps({'id':request_id,'pid':os.getpid(),'name':'','action':'probe','expires':round((time.time()+30)*1000)})+'\n')
        process.stdin.flush()
        Timer(31.0,expire_phbot_probe,args=(request_id,)).start()
    except (OSError,ValueError) as error:report('Request Exchange phBot KIỂM TRA: '+str(error))


def expire_phbot_probe(request_id):
    with pvp_lock:
        request=phbot_bridge_pending
        if request and request.get('probe') and request.get('id')==request_id:
            report('Request Exchange phBot KIỂM TRA: hết 30s; helper_ready=%s; bước=%s. Dừng helper.'%(phbot_bridge_ready,request.get('stage')))
            close_phbot_bridge()


def named_profiles_path():
    return Path(get_config_dir()) / (CONFIG_NAME + '_BoCauHinh.json')


def read_named_profiles():
    try:
        data = json.loads(named_profiles_path().read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    if not isinstance(data,dict):raise ValueError('Danh sách bộ cấu hình không hợp lệ.')
    return data


def view_presets():
    show_view('presets')
    refresh_named_profiles()


def game_window_belongs_to(window, pid):
    if not user32 or not window or not pid:
        return False
    actual_pid = wintypes.DWORD()
    return bool(user32.GetWindowThreadProcessId(window, ctypes.byref(actual_pid)) and actual_pid.value == pid)


def set_game_window_visibility(window, pid, visible):
    return game_window_belongs_to(window, pid) and bool(
        user32.ShowWindowAsync(window, 4 if visible else 0))  # SW_SHOWNOACTIVATE / SW_HIDE


def hide_game_clicked():
    global hidden_game
    client = get_client() or {}
    window, pid = client.get('window'), client.get('pid')
    if not client.get('running') or not set_game_window_visibility(window, pid, False):
        report_error('Ẩn game: không tìm được cửa sổ game đang chạy của acc này.')
        return
    hidden_game = (window, pid)
    report('Đã yêu cầu ẩn game. Bấm Hiện game trong Bộ cấu hình để mở lại.')


def show_game_clicked():
    global hidden_game
    client = get_client() or {}
    window, pid = client.get('window'), client.get('pid')
    if not client.get('running') or not set_game_window_visibility(window, pid, True):
        report_error('Hiện game: không tìm được cửa sổ game đang chạy của acc này.')
        return
    if hidden_game == (window, pid):
        hidden_game = None
    report('Đã yêu cầu hiện lại cửa sổ game.')


def refresh_named_profiles(selected=None):
    try:
        profiles=read_named_profiles()
        selected = selected or QtBind.text(gui, named_profile_choice)
        QtBind.clear(gui,named_profile_choice)
        for name in sorted(profiles,key=str.casefold):QtBind.append(gui,named_profile_choice,name)
        if selected in profiles:QtBind.setText(gui,named_profile_choice,selected)
    except (OSError,ValueError) as error:report_error('Lỗi đọc bộ cấu hình: %s'%error)


def save_named_profile():
    name=QtBind.text(gui,named_profile_name).strip()
    if not name or len(name)>80:
        report('Nhập tên bộ cấu hình từ 1 đến 80 ký tự.');return
    temporary=None
    try:
        profiles=read_named_profiles()
        profile=save_clicked()
        if profile is None:return
        profiles[name]=profile
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=str(named_profiles_path().parent),delete=False) as stream:
            temporary=stream.name
            json.dump(profiles,stream,ensure_ascii=False,indent=2)
        os.replace(temporary,named_profiles_path())
        refresh_named_profiles(name)
        report('Đã lưu bộ "%s". Lưu cùng tên sẽ cập nhật bộ đó.'%name)
    except (OSError,ValueError) as error:report_error('Lỗi lưu bộ cấu hình: %s'%error)
    finally:
        if temporary and os.path.exists(temporary):os.unlink(temporary)


def apply_named_profile():
    owner = owner_of(get_character_data() or {})
    try:
        if owner is None or owner != profile_owner:
            raise ValueError('Chờ phBot nhận diện acc đã vào game.')
        name = (QtBind.text(gui, named_profile_choice) or '').strip()
        profile = read_named_profiles().get(name)
        if not isinstance(profile, dict):
            raise ValueError('Chọn một bộ cấu hình trong danh sách Bộ đã lưu.')
        profiles = read_profiles()
        profiles[json.dumps(owner)] = profile
        write_profiles(profiles)
        load_profile(owner, profile_override=profile)
        QtBind.setText(gui, named_profile_name, name)
        message = 'Đã nạp bộ "%s" cho %s.' % (name, owner[1])
        QtBind.setText(gui, trace_status_label, message)
        log('[%s] %s' % (NAME, message))
    except Exception as error:
        message = 'Lỗi nạp bộ cấu hình: %s' % error
        QtBind.setText(gui, trace_status_label, message)
        report_error(message)


def parse_keys(value):
    keys = tuple(char for char in value if not char.isspace() and char != ',')
    if any(char not in '0123456789' for char in keys):
        raise ValueError('Dãy phím chỉ nhận các số 0–9, dấu phẩy và khoảng trắng.')
    return keys


def report(message):
    logging.getLogger(NAME).debug(message)


def report_error(message):
    log('[%s] %s' % (NAME, message))


def stop_clicked(keep_bridge=False):
    global phbot_mouse_probe_ticket
    phbot_mouse_probe_ticket=None
    if 'phbot_bridge_process' in globals() and (not keep_bridge or phbot_bridge_pending is not None):close_phbot_bridge()
    global auto_pk_running,auto_pk_returning,auto_pk_runtime
    stop_auto_pk_patrol(auto_pk_runtime)
    auto_pk_running=False
    auto_pk_returning=False
    auto_pk_runtime=None
    global numeric_running, numeric_sequence
    numeric_running = False
    numeric_sequence = ()
    global settings, current_page, active_sequence, sequence_index, auto_hunt, hunt_request, hunt_retry_at, hunt_stop, boss_interrupt_key, boss_interrupt_delays, boss_esc_enabled, boss_esc_closing
    global pvp_trigger_mode, imbue_id, imbue_until, imbue_retry_at, imbue_next_check, imbue_seen_active, reclick_enabled, skill_probe, skill_probe_result, pvp_pause_controls, pvp_paused, exchange_transport_probe, hybrid_exchange_mode
    with pvp_lock:
        exchange_transport_probe = None
        hybrid_exchange_mode = False
        if manual_trace and manual_trace.get('kind') in ('boss', 'exchange'):
            finish_trace()
        pvp_trigger_mode = None
        pvp_pause_controls = False
        pvp_paused = False
        skill_probe = skill_probe_result = None
        skill_probe_results.clear()
        reclick_enabled = False
        imbue_id = 0
        imbue_until = imbue_retry_at = imbue_next_check = 0.0
        imbue_seen_active = False
        reset_pvp_activation()
        stop_hunt_worker()
        boss_interrupt_key = None
        boss_esc_enabled = False
        boss_esc_closing = False
        boss_interrupt_delays = {}
        clear_pending()
        auto_hunt = False
        hunt_request = None
        hunt_retry_at = 0.0
        stop_pvp()
    settings = None
    current_page = None
    active_sequence = None
    sequence_index = 0
    QtBind.setText(gui, status_label, 'Đang tắt')


def mode_changed(checked):
    if ui_sync or auto_pk_running:
        return
    if settings is not None or direct_skills:
        stop_clicked()
        report('Đã đổi chế độ. Bấm Bật để áp dụng.')


def packet_mode_changed(checked):
    if ui_sync:return
    set_checked_silent(direct_box,False)
    mode_changed(checked)


def reclick_changed(checked):
    if ui_sync:
        return
    if checked:
        set_checked_silent(legacy_box, False)
    mode_changed(checked)


def legacy_changed(checked):
    if ui_sync:
        return
    if checked:
        set_checked_silent(reclick_box, False)
    mode_changed(checked)


def background_mode_changed(checked):
    if ui_sync:return
    if checked:set_checked_silent(hybrid_box,False)
    mode_changed(checked)


def hybrid_mode_changed(checked):
    if ui_sync:return
    if checked:
        set_checked_silent(pvp_background_box,False)
        set_checked_silent(direct_box,False)
        set_checked_silent(legacy_box,False)
    mode_changed(checked)


def pvp_changed(checked):
    if ui_sync:
        return
    if checked:
        view_pvp()
        set_checked_silent(numeric_box, False)
        set_checked_silent(boss_mode_box, False)
        set_checked_silent(boss_box, False)
        set_checked_silent(hunt_box, False)
        start_clicked()
    else:
        stop_clicked()
        report('PvP đã tắt. Auto ô số không tự bật; muốn dùng hãy chọn và Bật riêng.')


def start_boss_esc():
    """Configure the user's working key order; only change boss-related fields."""
    view_boss()
    stop_clicked()
    raw = QtBind.text(gui, skills_field).partition('/')[0].strip()
    try:
        if raw:
            known = get_skills() or {}
            pairs = []
            for entry in raw.split(';'):
                if not entry.strip():
                    continue
                name, delay = (part.strip() for part in entry.rsplit('=', 1))
                matches = [int(uid) for uid, skill in known.items()
                           if str(uid) == name or (skill.get('name') or '').casefold() == name.casefold()]
                if len(matches) != 1:
                    raise ValueError('Không khớp skill %s; hãy dùng ID trong Log.' % name)
                pairs.append('%d=%s' % (matches[0], delay))
            delays = '; '.join(pairs)
        else:
            delays = QtBind.text(gui, boss_dialog_field).partition('/')[0].strip()
        parse_boss_interrupt_delays(delays)
    except ValueError as error:
        report('Boss ESC chưa bật: %s' % error)
        return
    for box in (ghost_box, pvp_box, direct_box, hunt_box, pvp_background_box):
        set_checked_silent(box, False)
    set_checked_silent(boss_box, True)
    set_checked_silent(boss_esc_box, True)
    QtBind.setText(gui, boss_names_field, 'TARGET')
    QtBind.setText(gui, boss_keys_field, '3456789')
    # Preserve previously captured mouse coordinates after the slash.
    old = QtBind.text(gui, boss_dialog_field)
    _, slash, tail = old.partition('/')
    QtBind.setText(gui, boss_dialog_field, delays + (' / ' + tail if slash else ''))
    start_clicked()


def close_boss_esc(ticket, owner, source, window, pid):
    global pending, boss_esc_closing, blocked_until
    with pvp_lock:
        if pending is None or pending[0] is not ticket:
            return
        try:
            character = get_character_data() or {}
            client = get_client() or {}
            if (boss_esc_enabled and owner_of(character) == owner
                    and character.get('player_id') == source and not character.get('dead')
                    and client.get('running') and client.get('window') == window
                    and client.get('pid') == pid and press_key(0x1B, window)):
                blocked_until = monotonic() + 0.08
                if boss_esc_count <= 20:
                    report('BOSS ESC #%d: gửi ESC đóng; tiếp tục dãy skill.' % boss_esc_count)
            else:
                stop_clicked()
                report('Boss ESC đã dừng do không đóng được menu. Kiểm tra cửa sổ game trước khi bật lại.')
        finally:
            if pending is not None and pending[0] is ticket:
                pending = None
            boss_esc_closing = False


def start_chat_pvp():
    view_pvp()
    stop_clicked()
    for box in (ghost_box, boss_box, hunt_box, pvp_background_box):
        set_checked_silent(box, False)
    set_checked_silent(pvp_box, True)
    set_checked_silent(direct_box, True)
    set_checked_silent(packet_mode_box,False)
    set_checked_silent(pvp_background_box,True)
    QtBind.setText(gui,skills_field,PVP_BACKGROUND_PRESET)
    report('Đã nạp đúng dãy PvP nền: '+PVP_BACKGROUND_PRESET+'. Muốn chỉnh riêng, sửa ô rồi bấm Bật.')
    QtBind.setText(gui,direct_field,'')  # Order comes from the visible ID=ms field.
    set_checked_silent(legacy_box,False)
    start_clicked()


def start_clicked(auto_pk_page=None):
    global runtime_skill_groups, runtime_imbue_early
    global settings, auto_hunt, hunt_stop, boss_interrupt_key, boss_interrupt_delays, boss_esc_enabled, boss_esc_count, boss_method
    global pvp_trigger_mode, pvp_allowed_pages, pvp_page_exchanges, runtime_gear, imbue_id, reclick_enabled, reclick_wait, pvp_pause_controls
    stop_clicked(keep_bridge=True)
    phbot_bridge_stats.update(calls=0,confirmed=0,total_ms=0,max_ms=0)
    with pvp_lock:
        check_manual_trace(None)
    if not user32:
        report_error('Chế độ bấm phím cần client Windows.')
        return
    auto_pk = auto_pk_page is not None
    try:
        if not auto_pk and run_section == 'pvp' and not QtBind.isChecked(gui, pvp_box):
            if not QtBind.isChecked(gui, numeric_box):
                raise ValueError('Bật Auto ô số hoặc Ghost PvP trước.')
            start_numeric_sequence()
            return
        if run_section == 'pvp':
            enabled_pages = ({auto_pk_page} if auto_pk else
                             {page for page in PVP_EDIT_PAGES if QtBind.isChecked(gui, pvp_page_boxes[page])})
            if not enabled_pages:
                raise ValueError('Ghost PvP: bật ít nhất một nhóm F.')
            sync_pvp_editor()
            active_groups = compile_skill_groups(enabled_pages)
            runtime_skill_groups = {page: active_groups.get(page) for page in PVP_EDIT_PAGES if page in enabled_pages}
            runtime_imbue_early = float(QtBind.text(gui, imbue_early_field) or '0.8')
            if not 0 <= runtime_imbue_early <= 10:
                raise ValueError('Làm mới tay phép sớm cần từ 0 đến 10 giây.')
            use_skill_group(next(iter(active_groups)))
        hybrid = not auto_pk and QtBind.isChecked(gui,hybrid_box) and run_section=='pvp' and QtBind.isChecked(gui,pvp_box)
        stable = not auto_pk and not hybrid and QtBind.isChecked(gui, legacy_box) and QtBind.isChecked(gui, pvp_box) and not QtBind.isChecked(gui,pvp_background_box)
        ghost_enabled = QtBind.isChecked(gui, ghost_box)
        boss_enabled = not stable and run_section == 'boss' and QtBind.isChecked(gui, boss_box)
        pages = {}
        boss_names = set()
        boss_keys = ()
        radius = 0.0
        interrupt_key = None
        esc_enabled = boss_enabled and QtBind.isChecked(gui, boss_esc_box)
        interrupt_delays = {}
        pvp_enabled = auto_pk or ((stable or run_section == 'pvp') and QtBind.isChecked(gui, pvp_box))
        hunt_enabled = not stable and run_section == 'boss' and QtBind.isChecked(gui, hunt_box)
        direct_enabled = auto_pk or (not hybrid and not stable and pvp_enabled and (QtBind.isChecked(gui,direct_box) or QtBind.isChecked(gui,pvp_background_box)))
        if pvp_enabled and get_status():
            raise ValueError('Dừng bot chính của phBot trước khi bật Ghost PvP.')
        if direct_enabled:
            if not pvp_enabled or hunt_enabled or boss_enabled:
                raise ValueError('PvP trực tiếp: tích Ghost PvP và tắt Auto quái/Ghost Boss.')
            if get_status():
                raise ValueError('Dừng bot chính của phBot trước khi bật PvP khi chat.')
            ghost_enabled = False
        if pvp_enabled and not direct_enabled and not boss_enabled and not hunt_enabled:
            ghost_enabled = True
        selected_imbue = configured_imbue()
        try:
            retry_wait_ms = int(QtBind.text(gui, reclick_wait_field).strip() or '650')
        except ValueError:
            raise ValueError('Chờ Reclick phải là số ms, ví dụ 650.') from None
        if not 200 <= retry_wait_ms <= 2000:
            raise ValueError('Chờ Reclick cần trong khoảng 200–2000 ms.')
        mode = None
        allowed = ()
        exchanges = {}
        gear = {page: {'weapon': QtBind.text(gui, weapon_fields[page]).strip(),
                       'shield': QtBind.text(gui, shield_fields[page]).strip()} for page in PAGES}
        if not (ghost_enabled or boss_enabled or pvp_enabled or hunt_enabled):
            raise ValueError('Hãy chọn ít nhất một chế độ.')
        if ghost_enabled or hunt_enabled:
            pages = {page: parse_keys(QtBind.text(gui, field))
                     for page, field in page_fields.items()}
            if ghost_enabled and not hunt_enabled and not any(pages.values()):
                raise ValueError('Hãy nhập dãy phím cho ít nhất một trang F1–F4.')
        if direct_enabled:
            mode='target' if not auto_pk and QtBind.text(gui, trigger_field) == TRIGGER_TARGET else 'manual'
            # ID groups authorize PvP pages independently of Auto number keys
            # and of whether individual skills use an Exchange interruption.
            allowed=tuple(page for page in PAGES if page in runtime_skill_groups)
            if auto_pk or QtBind.text(gui,id_method_field)==ID_METHOD_NATIVE:
                exchanges = dict.fromkeys(allowed)
        if pvp_enabled and ghost_enabled and not hunt_enabled and not boss_enabled:
            mode = None if stable else ('target' if QtBind.text(gui, trigger_field) == TRIGGER_TARGET else 'manual')
            allowed = tuple(page for page in PAGES if pages.get(page)) if stable else tuple(
                page for page in PAGES if page != 'F4' and QtBind.isChecked(gui, page_boxes[page]))
            if not allowed or any(not pages.get(page) for page in allowed):
                raise ValueError('Tích F muốn dùng và nhập dãy skill cho mỗi F đó.')
            if mode == 'target' and len(allowed) != 1:
                raise ValueError('Target tự Ghost: chỉ tích đúng một F, ví dụ F2.')
            for page in allowed:
                if hybrid:
                    exchanges[page]=None
                    continue
                key = pvp_exchange_slot()
                if key in pages[page]:
                    raise ValueError('%s: cần ô Trao đổi 0–9 nằm ngoài dãy skill.' % page)
                exchanges[page] = key
            missing_groups = [page for page in allowed if page not in runtime_skill_groups]
            if missing_groups:
                raise ValueError('Chưa có hàng ID cho nhóm '+', '.join(missing_groups))
        if boss_enabled or hunt_enabled:
            boss_names = {name.strip().casefold()
                          for name in QtBind.text(gui, boss_names_field).split(';')
                          if name.strip()}
            boss_keys = parse_keys(QtBind.text(gui, boss_keys_field))
            if hunt_enabled and (not boss_names or 'target' in boss_names or not boss_enabled):
                boss_names = {'target'}
                radius = AUTO_HUNT_RADIUS
            else:
                radius = float(QtBind.text(gui, radius_field).strip().replace(',', '.'))
            if hunt_enabled and not (boss_keys or any(pages.values())):
                raise ValueError('Chưa bật auto quái: nhập Dãy boss hoặc dãy F1–F4, ví dụ 456789.')
            if boss_enabled and (not boss_names or not (boss_keys or (hunt_enabled and any(pages.values())))
                                 or not math.isfinite(radius) or radius <= 0):
                raise ValueError('Ghost Boss: cần mục tiêu, bán kính và dãy phím. Boss chuột đã tắt.')
        if boss_enabled:
            key = QtBind.text(gui, boss_interrupt_field).strip()
            if esc_enabled:
                interrupt_delays = parse_boss_interrupt_delays(QtBind.text(gui, boss_dialog_field))
            elif key:
                if len(key) != 1 or key not in '0123456789':
                    raise ValueError('Phím ngắt Boss phải là một phím số 0–9.')
                if key in boss_keys or any(key in sequence for sequence in pages.values()):
                    raise ValueError('Phím ngắt Boss phải nằm ngoài dãy phím đánh.')
                interrupt_delays = parse_boss_interrupt_delays(QtBind.text(gui, boss_dialog_field))
                interrupt_key = ord(key)
    except ValueError as error:
        message = 'Chưa bật được chế độ đánh: %s' % error
        QtBind.setText(gui, status_label, message)
        report_error(message)
        return

    if pvp_enabled and not start_pvp(direct_enabled, next(iter(exchanges.values()), None),
                                     hybrid=hybrid, auto_pk=auto_pk):
        return
    if ghost_enabled or boss_enabled or hunt_enabled:
        settings = (pages, boss_names, boss_keys, radius)
        if not mode and (pages or boss_keys) and not (hunt_enabled and boss_keys):
            report('Giữ F1–F4 trong client đến khi Log báo đã nhận trang.')
    with pvp_lock:
        pvp_trigger_mode = mode
        pvp_pause_controls = pvp_enabled
        pvp_allowed_pages = allowed
        pvp_page_exchanges = exchanges
        runtime_gear = gear
        imbue_id = selected_imbue
        reclick_enabled = not stable and (not direct_enabled or direct_native_exchange) and QtBind.isChecked(gui, reclick_box)
        reclick_wait = retry_wait_ms / 1000.0
        boss_interrupt_key = interrupt_key
        boss_esc_enabled = esc_enabled
        boss_method = QtBind.text(gui, boss_method_field) or 'ESC → ESC (cũ)'
        boss_esc_count = 0
        boss_interrupt_delays = interrupt_delays
        auto_hunt = hunt_enabled
        if selected_imbue or esc_enabled or auto_hunt or (pvp_enabled and (ghost_enabled or direct_enabled)):
            hunt_stop = Event()
            Thread(target=hunt_worker, args=(hunt_stop,), daemon=True).start()
    if auto_hunt:
        if boss_keys:
            report('Auto quái 50 m: sẽ dùng Dãy boss trên trang skill đang mở khi cửa sổ game ở phía trước.')
        else:
            report('Auto quái 50 m: giữ trang F có dãy phím rồi thả để bắt đầu.')
    if stable:
        set_checked_silent(reclick_box, False)
        report('LUỒNG CŨ PvP: bấm F rồi xoay ô số/Trao đổi; không chặn target và không chờ Reclick. Đổi đồ, tay phép vẫn bật.')
    if reclick_enabled:
        report('Reclick bật: chờ tối đa %d ms; thử lại ô hiện tại tối đa 3 lần trước ô kế tiếp. Mốc ngắt theo từng skill.' % retry_wait_ms)
    for page, loadout in gear.items():
        if any(loadout.values()):
            report('%s bộ đồ: vũ khí=%s; khiên=%s.' %
                   (page, loadout['weapon'] or 'giữ nguyên', loadout['shield'] or 'giữ nguyên'))
    if pvp_pause_controls:
        report('Ghost PvP: F1/F2/F3 bật riêng. F4 dừng Ghost và đổi vũ khí/khiên. X bỏ target.')
    if mode and not auto_pk:
        report('PvP theo F: %s; dùng %s. Bấm F hoặc số 3 cho từng mục tiêu trong chế độ bấm tay.' %
               ('target tự Ghost' if mode == 'target' else 'chọn người rồi bấm F một lần', ', '.join(allowed)))
    if 'target' in boss_names and not auto_hunt:
        report('TARGET: chọn quái hoặc boss trong game. Chế độ chỉ áp dụng cho mục tiêu đó.')
    if esc_enabled:
        report('BOSS THỬ %s: nhận skill → chờ ID=ms → thử ngắt. Giữ game phía trước; chưa xác nhận ngắt thành công.' % boss_method)
    if interrupt_key is not None:
        report('Đã bật thử phím ngắt Boss %s cho %d skill.' % (chr(interrupt_key), len(interrupt_delays)))
    if auto_pk:
        status = 'Auto PK đã bật. Tự chọn mục tiêu và đánh theo ID.'
    elif direct_enabled:
        status = 'Đã bật: chọn người để tự đánh.' if mode == 'target' else 'Đã bật: chọn người rồi bấm F để đánh.'
    elif auto_hunt:
        status = 'Auto quái 50 m đã bật. Chuyển sang cửa sổ game.'
    else:
        status = 'Đã bật. Xem Log.'
    QtBind.setText(gui, status_label, status)
    if auto_pk:
        return True


def nearby_boss(names, radius):
    if not names:
        return None
    position = get_position() or {}
    if not all(key in position for key in ('region', 'x', 'y')):
        return None
    monsters = get_monsters() or {}
    if 'target' in names:
        uid = selected_monster_uid
        if uid and target_matches_boss(uid, monsters, (names, radius)):
            return uid, monsters[uid].get('name', uid)
        return None
    closest = None
    closest_distance = radius
    for uid, monster in monsters.items():
        if monster.get('region') != position['region'] or not monster.get('hp', 0) > 0:
            continue
        identifiers = {str(monster.get(key, '')).strip().casefold()
                       for key in ('name', 'servername', 'model')}
        if not names.intersection(identifiers) or 'x' not in monster or 'y' not in monster:
            continue
        distance = math.hypot(monster['x'] - position['x'], monster['y'] - position['y'])
        if distance <= closest_distance:
            closest = (uid, monster.get('name', uid))
            closest_distance = distance
    return closest


def scan_clicked():
    monsters = get_monsters() or {}
    if not monsters:
        report('Chưa thấy quái. Hãy đưa nhân vật tới gần boss rồi quét lại.')
        return
    seen = set()
    for monster in monsters.values():
        entry = (monster.get('name', ''), monster.get('servername', ''), monster.get('model', ''))
        if entry not in seen:
            seen.add(entry)
            report('Tên=%s | Mã=%s | Model=%s' % entry)


def hunt_target():
    """Keep a live selected monster or request the nearest eligible target."""
    global hunt_request, hunt_retry_at
    position = get_position() or {}
    candidates = []
    for uid, monster in (get_monsters() or {}).items():
        if (not uid or monster.get('hp', 0) <= 0
                or monster.get('region') != position.get('region')):
            continue
        try:
            distance = math.hypot(monster['x'] - position['x'], monster['y'] - position['y'])
        except (KeyError, TypeError):
            continue
        if distance <= AUTO_HUNT_RADIUS:
            if uid == selected_monster_uid and hunt_request is None:
                return uid
            candidates.append((distance, uid))
    now = monotonic()
    if now < hunt_retry_at:
        return None
    if hunt_request is not None:
        report('Chưa nhận xác nhận chọn quái UID=%s từ server.' % hunt_request)
    hunt_request = None
    if candidates:
        _, uid = min(candidates)
        hunt_request = uid
        hunt_retry_at = now + 1.5
        if inject_joymax(0x7045, struct.pack('<I', uid), False) is False:
            hunt_request = None
            report('phBot từ chối yêu cầu chọn quái UID=%s.' % uid)
    else:
        hunt_retry_at = now + 5.0
        report('Chưa thấy quái sống cùng khu trong bán kính 50 m.')
    return None


def stop_hunt_worker():
    global hunt_stop
    if hunt_stop is not None:
        hunt_stop.set()
        hunt_stop = None


def hunt_worker(stop):
    try:
        while not stop.wait(0.005 if pvp_trigger_mode or numeric_running else (PVP_KEY_INTERVAL if pvp_delays and not auto_hunt else AUTO_HUNT_INTERVAL)):
            with pvp_lock:
                if stop is not hunt_stop:
                    return
                character = get_character_data() or {}
                if stop_invalid_native_pvp(character):
                    continue
                if owner_of(character) == profile_owner:
                    tick_push_trace()
                    if numeric_running:
                        tick_numeric(character)
                        continue
                    if pvp_trigger_mode and not pvp_gate_tick(get_client() or {}, character):
                        continue
                    if tick_imbue(character):
                        continue
                    if direct_skills:
                        rotate_direct(character, gate_checked=True)
                    else:
                        rotate(character)
    except Exception as error:
        with pvp_lock:
            if stop is hunt_stop:
                if auto_pk_running:
                    stop_auto_pk(reason='luồng đánh bị lỗi và đã thoát')
                else:
                    stop_clicked()
        report_callback_failure('vòng bấm phím', error)


def event_loop():
    global direct_interrupt_request
    with pvp_lock:
        character = get_character_data() or {}
        if stop_invalid_native_pvp(character):
            return
    owner = owner_of(character)
    if owner is not None and owner != profile_owner:
        load_profile(owner)
    if owner is not None:
        if imbue_scan_pending:
            refresh_imbues()
        remember_imbue(owner)
    show_skill_probe_result(owner)
    show_mouse_capture(owner)
    with pvp_lock:
        check_manual_trace(owner)
        tick_push_trace()
        check_direct_exchange()
        if auto_pk_running:tick_auto_pk(from_event=True)
        tick_exchange_transport_probe()
        request = direct_interrupt_request
        direct_interrupt_request = None
        if request is not None:
            fire_interrupt(*request)
        if hunt_stop is None and not tick_imbue(character):
            rotate(character)


def report_direct(message):
    global direct_log_left
    if direct_log_left > 0:
        direct_log_left -= 1
        report('PvP trực tiếp: ' + message)


def rotate_direct(character, gate_checked=False):
    global direct_index, direct_expected, pvp_cast_deadline, blocked_until, direct_retry_state
    global pvp_wait_push_until
    now = monotonic()
    if pvp_trigger_mode and not gate_checked and not pvp_gate_tick(get_client() or {}, character):
        return
    if pvp_stun_blocks(character):
        return
    if direct_exchange_wait and (direct_exchange_wait.get('ui_retry_at')
                                 or direct_exchange_wait.get('transport') == 'client_7081'):
        check_direct_exchange()
    if pvp_push is not None and recover_pvp_push(character, now):
        return
    if (skill_probe is not None or not direct_skills or not direct_target
            or (pvp_trigger_mode and (not pvp_armed or direct_target != pvp_target))
            or direct_target == direct_blocked_target or pending is not None or direct_exchange_wait is not None
            or now < max(blocked_until, pvp_cast_deadline) or character.get('dead')
            or not character.get('player_id') or direct_target == character['player_id']
            or get_status()):
        return
    client = get_client() or {}
    if not client.get('running') or (not client.get('window') and not auto_pk_running):
        return
    monsters = get_monsters()
    if monsters is None or direct_target in monsters or direct_target in (get_npcs() or {}):
        return
    if auto_pk_running:
        if auto_pk_returning:
            return
        inside, reason = auto_pk_radius_check(direct_target)
        if not inside:
            if reason == AUTO_PK_OUTSIDE_SELF:
                force_auto_pk_return(auto_pk_runtime, reason)
            return
    pk_runtime = auto_pk_runtime if auto_pk_running else None
    probing_uid = pk_runtime is not None and pk_runtime.get('skill_probe_uid') == direct_target
    if pvp_wait_push_until:
        if now >= pvp_wait_push_until:
            pause_pvp('hết cửa sổ phục hồi, chưa thấy cú đẩy mới từ mục tiêu', cancel_action=False)
        return
    if direct_expected is not None and pvp_trigger_mode:
        if probing_uid:
            release_auto_pk_target(direct_target, 'thử skill theo UID nhưng không có B070')
            return
        next_group = runtime_skill_groups.get(current_page)
        if current_page in runtime_skill_groups and (not next_group or direct_expected[0] not in next_group['delays']):
            direct_expected = direct_retry_state = None
            pvp_cast_deadline = 0.0
        elif direct_native_exchange and reclick_enabled and direct_retry_state is not None:
            if not retry_direct_native_skill(character):
                return
        elif direct_native_exchange:
            reason = 'chưa có B070 khớp ID=%d' % direct_expected[0]
            if not recover_auto_pk_cast(direct_target, direct_expected[0], reason):
                pause_pvp(reason + '; chờ lệnh bắt đầu mới', cancel_action=False)
            return
        elif direct_chain_mode:
            pause_pvp('ID THỬ: hết 6s chưa có B070 cho ID=%d; kết thúc đo, không gửi hủy tác vụ, không gửi lại'%direct_expected[0],cancel_action=False)
            return
        else:
            pause_pvp('server chưa xác nhận skill ID=%d; không tự bỏ sang skill kế tiếp'%direct_expected[0])
            return
    if direct_expected is not None:
        report_direct('hết %.1fs chờ 0xB070 cho skill ID=%d.' % (DIRECT_CAST_WAIT, direct_expected[0]))
    if pvp_trigger_mode and not apply_skill_row_changes():
        return
    if auto_pk_running and not auto_pk_ready_to_cast(auto_pk_runtime, direct_target, now):
        return
    skill_id = direct_skills[direct_index]
    skills = skill_table()
    skill_retry_at = pk_runtime.get('skill_retry_at', {}) if pk_runtime is not None else {}
    for _ in range(len(direct_skills)):
        skill_id = direct_skills[direct_index]
        if (skill_retry_at.get(skill_id, 0) <= now and skill_id not in direct_missed_skills
                and (skills.get(skill_id) or {}).get('can_cast') is not False):
            break
        if skill_id not in direct_missed_skills:
            report_direct('ID=%d chưa thể dùng theo dữ liệu phBot; xét skill kế tiếp.' % skill_id)
        direct_index = (direct_index + 1) % len(direct_skills)
    else:
        pvp_cast_deadline = now + 0.05
        return
    cast_target = direct_target
    direct_expected = (skill_id, cast_target)
    if probing_uid:
        pvp_cast_deadline = now + DIRECT_CAST_WAIT
    else:
        pvp_cast_deadline = now + (reclick_wait if direct_native_exchange and reclick_enabled
                                   else DIRECT_TRIAL_WAIT if direct_chain_mode else DIRECT_CAST_WAIT)
    direct_index = (direct_index + 1) % len(direct_skills)
    packet = struct.pack('<BBIBI', 1, 4, skill_id, 1, direct_target)
    if direct_native_exchange:
        direct_retry_state={'owner':owner_of(character),'skill':skill_id,'target':direct_target,'packet':packet,'retries':0,'sent_at':now}
    report_direct('gửi 0x7074 skill ID=%d, UID=%d.' % (skill_id, direct_target))
    first_pk_cast = pk_runtime is not None and not pk_runtime.get('first_cast_sent')
    if first_pk_cast:
        pk_runtime['first_cast_sent'] = True
        pk_uid = direct_target
    push_trace_mark('skill đầu gửi', 'ID=%d' % skill_id)
    push_trace_note('Ghost gửi skill ID=%d UID=%d.' % (skill_id, direct_target), after_hit=True)
    cast_sent_at = monotonic()
    result=inject_joymax(0x7074, packet, False)
    if first_pk_cast:
        locked = pk_runtime.get('target_locked_at', cast_sent_at)
        selected = pk_runtime.get('target_sent_at', locked)
        seen = pk_runtime.get('target_seen_at', selected)
        message = 'UID %d · skill đầu ID %d · %s.' % (
            pk_uid, skill_id, 'API từ chối' if result is False else 'đã gửi, chờ B070')
        if probing_uid:
            log('[%s] Auto PK thử UID trực tiếp: %s' % (NAME, message))
        else:
            log('[%s] Auto PK: %s Dò→chọn %d ms · chọn→B045 %d ms · B045→gửi skill %d ms.' %
                (NAME, message, round((selected-seen)*1000), round((locked-selected)*1000),
                 round((cast_sent_at-locked)*1000)))
        if auto_pk_runtime is pk_runtime and pvp_target == pk_uid:
            QtBind.setText(gui, auto_pk_status_label, message)
    if result is False:
        push_trace_note('phBot trả False khi gửi skill ID=%d.' % skill_id, after_hit=True)
    if direct_chain_mode:
        report('ID THỬ: yêu cầu skill=%d, UID=%d, API=%r; chờ B070.'%(skill_id,direct_target,result))
    if result is False:
        if probing_uid:
            if (auto_pk_runtime is pk_runtime and pk_runtime.get('skill_probe_uid') == cast_target
                    and direct_expected == (skill_id, cast_target)):
                release_auto_pk_target(cast_target, 'phBot từ chối skill thử theo UID')
            return
        if direct_native_exchange:
            if auto_pk_running:
                recover_auto_pk_cast(cast_target, skill_id, 'phBot từ chối gửi skill')
            else:
                pause_pvp('PvP ID/ô số: API từ chối gửi skill ID=%d; không tự gửi lại'%skill_id)
            return
        if direct_chain_mode:
            pause_pvp('ID THỬ: API từ chối skill ID=%d; không gửi lặp'%skill_id)
            return
        report_direct('phBot từ chối gửi 0x7074.')
        direct_expected = None
        blocked_until = now + 0.5


def rotate(character):
    global current_page, active_sequence, sequence_index, pvp_cast_deadline, f_keys_held, key_attempt
    if direct_skills or settings is None or skill_probe is not None:
        return

    client = get_client() or {}
    window = client.get('window')
    if not client.get('running') or not window or not character.get('name') or character.get('dead'):
        current_page = None
        active_sequence = None
        return
    foreground = user32.GetForegroundWindow() == window
    if not foreground and not (pvp_background and pvp_delays and not auto_hunt):
        f_keys_held = set()
        if not pvp_trigger_mode:
            current_page = None
        active_sequence = None
        return

    if pvp_trigger_mode and get_status():
        return
    if not pvp_gate_tick(client, character):
        return
    if foreground:
        # Giữ Ctrl, Alt hoặc Shift để tạm ngừng bấm số.
        if any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12)):
            return
        for page, key in (() if pvp_trigger_mode else zip(PAGES, PAGE_KEYS)):
            if user32.GetAsyncKeyState(key) & 0x8000:
                if current_page != page:
                    current_page = page
                    active_sequence = None
                    report('Đã nhận trang %s.' % page)
                return

    pages, boss_names, boss_keys, radius = settings
    if current_page is None and not (auto_hunt and boss_keys):
        return
    if auto_hunt:
        sequence = boss_keys or pages.get(current_page, ())
        if not sequence or get_status():
            return
        with pvp_lock:
            if pending is not None or monotonic() < blocked_until:
                return
            uid = hunt_target()
        if uid is None:
            return
        mode = (current_page, uid)
    else:
        boss = nearby_boss(boss_names, radius)
        if boss:
            uid, name = boss
            sequence = boss_keys
            mode = (current_page, uid)
            if active_sequence != mode:
                report('Ghost Boss: thấy %s (UID=%s). Dùng dãy boss trên %s.' % (name, uid, current_page))
        else:
            sequence = pages.get(current_page, ())
            mode = (current_page, None)

    if active_sequence != mode:
        key_attempt = None
        active_sequence = mode
        sequence_index = 0
    with pvp_lock:
        now = monotonic()
        if not sequence or pending is not None or direct_exchange_wait is not None or now < max(blocked_until, pvp_cast_deadline):
            return
        pvp_rotation = bool(pvp_delays and not auto_hunt and boss is None)
        send = (lambda key: press_pvp_key(key, client)) if pvp_rotation else (lambda key: press_key(key, window))
        if reclick_enabled and key_attempt is not None:
            attempt = key_attempt
            if attempt['context'] != (mode, sequence):
                key_attempt = None
            elif now < attempt['deadline']:
                return
            elif attempt['retries'] < RECLICK_MAX_RETRIES:
                # Hold this slot for at most three additional send attempts.
                # Mark before send because outgoing/response hooks may be synchronous.
                attempt['retries'] += 1
                attempt['deadline'] = now + reclick_wait
                if send(attempt['key']):
                    pvp_cast_deadline = 0.0
                    report('Reclick: ô %s chưa thấy skill được xác nhận; thử lại %d/%d.' % (chr(attempt['key']), attempt['retries'], RECLICK_MAX_RETRIES))
                else:
                    report('Reclick: ô %s gửi phím thất bại ở lần %d/%d.' % (chr(attempt['key']), attempt['retries'], RECLICK_MAX_RETRIES))
                return
            else:
                detail = ('đã thấy yêu cầu skill ID=%d, chưa có xác nhận server' % attempt['expected'][0]
                          if attempt['expected'] else 'chưa quan sát được yêu cầu skill từ client')
                report('Reclick: ô %s sau %d lần thử lại: %s; chuyển ô kế tiếp.' %
                       (chr(attempt['key']), attempt['retries'], detail))
                key_attempt = None
                sequence_index = (sequence_index + 1) % len(sequence)
                pvp_cast_deadline = 0.0
        if pvp_rotation:
            pvp_cast_deadline = now + PVP_CAST_WAIT
        key = ord(sequence[sequence_index])
        if reclick_enabled:
            key_attempt = {'key': key, 'context': (mode, sequence), 'index': sequence_index,
                           'deadline': now + reclick_wait, 'retries': 0,
                           'expected': None, 'owner': owner_of(character),
                           'target': (pvp_target if pvp_trigger_mode else (uid if auto_hunt or boss else selected_monster_uid))}
        sent = send(key)
        if sent:
            if not reclick_enabled:
                sequence_index = (sequence_index + 1) % len(sequence)
        else:
            key_attempt = None
            pvp_cast_deadline = 0.0


def observe_key_request(opcode, data):
    """Bind the current slot press to the skill request actually emitted by the client."""
    if not reclick_enabled or key_attempt is None or opcode != 0x7074:
        return
    if len(data) < 7 or data[0] != 1 or data[1] != 4:
        return
    skill_id = struct.unpack_from('<I', data, 2)[0]
    target = struct.unpack_from('<I', data, 7)[0] if data[6] == 1 and len(data) >= 11 else 0
    if data[6] not in (0, 1) or (data[6] == 1 and len(data) < 11):
        return
    if key_attempt['target'] and target and key_attempt['target'] != target:
        return
    if key_attempt['owner'] != owner_of(get_character_data() or {}):
        return
    expected = (skill_id, target)
    if key_attempt['expected'] is None:
        key_attempt['expected'] = expected


def observe_key_confirmation(opcode, data):
    global key_attempt, sequence_index, pvp_cast_deadline
    if not reclick_enabled or key_attempt is None or opcode != 0xB070 or len(data) < 19:
        return
    if data[0] != 1:
        return
    skill_id, source = struct.unpack_from('<II', data, 3)
    target = struct.unpack_from('<I', data, 15)[0]
    character = get_character_data() or {}
    attempt = key_attempt
    if (source != character.get('player_id') or attempt['owner'] != owner_of(character)
            or attempt['expected'] != (skill_id, target)
            or attempt['context'][0] != active_sequence):
        return
    sequence = attempt['context'][1]
    sequence_index = (attempt['index'] + 1) % len(sequence)
    key_attempt = None
    pvp_cast_deadline = 0.0
    if attempt['retries']:
        report('Reclick: ô %s đã nhận xác nhận skill ID=%d.' % (chr(attempt['key']), skill_id))


def post_game_key(key,window):
    client=get_client() or {}
    if not user32 or not window or window!=client.get('window') or not client.get('running') or not client.get('pid'):
        return False
    try:
        pid=wintypes.DWORD()
        scan=user32.MapVirtualKeyW(key,4)  # MAPVK_VK_TO_VSC_EX
        if not scan or not user32.GetWindowThreadProcessId(window,ctypes.byref(pid)) or pid.value!=client['pid']:
            return False
        flags=1|((scan & 0xff)<<16)
        if scan & 0xff00 == 0xe000:
            flags |= 1 << 24
        if not user32.PostMessageW(window,0x0100,key,flags):return False
        return bool(user32.PostMessageW(window,0x0101,key,ctypes.c_int32(flags|0xc0000000).value))
    except (AttributeError,OSError,ValueError):return False


def press_key(key, window, direct_exchange_only=False, direct_page_only=False):
    if direct_exchange_only and window!=(get_client() or {}).get('window'):return False
    page_ok=(direct_page_only and pvp_activation is not None and not pvp_activation.get('page_sent')
             and key==PAGE_KEYS[PAGES.index(pvp_activation['page'])])
    allowed_direct=page_ok or (direct_exchange_only and direct_native_exchange and key==exchange_key)
    if (direct_skills and not allowed_direct) or not user32 or not window:
        return False
    if user32.GetForegroundWindow()!=window:
        if direct_exchange_only and direct_native_exchange and key==exchange_key:
            return post_game_key(key,window)
        return False
    if any(user32.GetAsyncKeyState(code) & 0x8000 for code in (0x10, 0x11, 0x12, key)):
        return False
    user32.keybd_event(key, 0, 0, 0)
    user32.keybd_event(key, 0, 2, 0)
    return True


def press_pvp_key(key, client):
    global pvp_background_error,pvp_synthetic_page
    window = client.get('window')
    if not user32 or not window:
        return False
    if direct_skills:
        if (pvp_activation is None or pvp_activation.get('page_sent') or key not in PAGE_KEYS
                or key!=PAGE_KEYS[PAGES.index(pvp_activation['page'])]):return False
        if user32.GetForegroundWindow()!=window:
            return post_game_key(key,window)
        page=pvp_activation['page']
        pvp_synthetic_page={'page':page,'until':monotonic()+.15}
        if press_key(key,window,direct_page_only=True):return True
        pvp_synthetic_page=None
        return False
    if user32.GetForegroundWindow() == window:
        return press_key(key, window)
    if not pvp_background:
        return False

    pid = wintypes.DWORD()
    scan = user32.MapVirtualKeyW(key, 0)
    if (client.get('pid') and scan
            and user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
            and pid.value == client['pid']):
        flags = 1 | ((scan & 0xff) << 16)
        if (user32.PostMessageW(window, 0x0100, key, flags)
                and user32.PostMessageW(window, 0x0101, key, ctypes.c_int32(flags | 0xc0000000).value)):
            return True
    if not pvp_background_error:
        pvp_background_error = True
        report_error('Không gửi được phím PvP nền tới cửa sổ game.')
    return False


def arm_skill_probe():
    global skill_probe, skill_probe_result
    client = get_client() or {}
    owner = owner_of(get_character_data() or {})
    if not user32 or not owner or not client.get('running') or not client.get('window'):
        report_error('Dò skill: cần nhân vật và cửa sổ game đang chạy.')
        return
    probe = {'owner': owner, 'window': client['window'], 'deadline': monotonic() + SKILL_PROBE_DURATION,
             'slot': None, 'pressed_at': 0.0, 'matches': set()}
    with pvp_lock:
        if pending is not None:
            report('Chờ thao tác Ghost đang chạy hoàn tất trước khi dò skill.')
            return
        skill_probe_result = None
        skill_probe_results.clear()
        skill_probe = probe
    report('Dò ô số 60 giây: sang game bấm ô skill; ID hiện ở hàng Dò ô số trong Tìm ID skill. Không tự sửa PvP.')
    Thread(target=watch_skill_key, args=(probe,), daemon=True).start()


def watch_skill_key(probe):
    global skill_probe, skill_probe_result
    previous = set()
    while monotonic() < probe['deadline']:
        held = set()
        if user32.GetForegroundWindow() == probe['window']:
            held = {digit for digit in '0123456789' if user32.GetAsyncKeyState(ord(digit)) & 0x8000}
        with pvp_lock:
            if skill_probe is not probe:
                return
            fresh = held - previous
            if len(fresh) == 1:
                probe['slot'] = next(iter(fresh))
                probe['pressed_at'] = monotonic()
            elif fresh:
                probe['slot'] = None
        previous = held
        sleep(0.015)
    with pvp_lock:
        if skill_probe is probe:
            skill_probe = None
            skill_probe_result = (probe['owner'], None, 'Dò skill hết 60 giây: đã nhận %d mục. Dãy nháp được giữ để sửa/copy.' % len(probe['matches']))


def stop_skill_probe():
    global skill_probe, skill_probe_result
    with pvp_lock:
        if skill_probe is not None:
            probe = skill_probe
            skill_probe_result = (probe['owner'], None, 'Đã dừng dò: %d mục; giữ dãy nháp.' % len(probe['matches']))
            skill_probe = None


def append_probe_draft(skill_id):
    try:
        delay = int(QtBind.text(gui, probe_delay_field).strip())
        if not 0 <= delay <= 5000:
            raise ValueError
        raw = QtBind.text(gui, probe_draft_field).strip()
        if raw:
            parse_boss_interrupt_delays(raw)
        pairs = [part.strip() for part in raw.partition('/')[0].split(';') if part.strip()]
        new = '%d=%d' % (skill_id, delay)
        for index, pair in enumerate(pairs):
            if pair.split('=', 1)[0].strip() == str(skill_id):
                pairs[index] = new
                break
        else:
            pairs.append(new)
        QtBind.setText(gui, probe_draft_field, '; '.join(pairs))
    except ValueError:
        report('Đã dò được ID nhưng chưa ghép dãy: kiểm tra Ngắt ms (0–5000) và dãy nháp đang sửa.')


def clear_probe_draft():
    QtBind.setText(gui, probe_draft_field, '')


def copy_probe_to_pvp():
    global skill_rows, skill_row_offset
    raw = QtBind.text(gui, probe_draft_field).strip()
    try:
        delays = parse_boss_interrupt_delays(raw)
        if any(uid not in skill_table() for uid in delays):
            raise ValueError('Dãy có skill không thuộc acc hiện tại.')
    except ValueError as error:
        report('Chưa chép sang PvP: %s' % error)
        return
    stop_skill_probe()
    mode_changed(False)
    sync_skill_rows()
    skill_rows = [{'stt': str(index + 1), 'id': str(uid), 'page': 'F1', 'ms': str(round(delay * 1000))}
                  for index, (uid, delay) in enumerate(delays.items())] + [row for row in skill_rows if row['page'] != 'F1']
    skill_row_offset['F1'] = 0
    skill_row_selected['F1'] = None
    show_skill_rows()
    report('Đã chép dãy nháp vào các hàng F1. Kiểm tra, Lưu rồi Bật để áp dụng.')


def show_skill_probe_result(owner):
    global skill_probe_result
    with pvp_lock:
        results = list(skill_probe_results)
        skill_probe_results.clear()
        if skill_probe_result is not None:
            results.append(skill_probe_result)
            skill_probe_result = None
    for result in results:
        if result[0] != owner:
            continue
        _, skill_id, message = result
        if skill_id is not None:
            QtBind.setText(gui, probe_id_field, str(skill_id))
            append_probe_draft(skill_id)
        update_hotbar_finder(skill_id,message)
        QtBind.setText(gui, probe_result_field, message)
        report(message)


def add_boss_skill():
    try:
        skill_id = int(QtBind.text(gui, probe_id_field).strip())
        delay = int(QtBind.text(gui, probe_delay_field).strip())
        if skill_id not in {int(key) for key in (get_skills() or {})} or not 0 <= delay <= 5000:
            raise ValueError
    except (ValueError, TypeError):
        report('Nhập ID skill của acc và thời gian ngắt 0–5000 ms.')
        return
    raw = QtBind.text(gui, boss_dialog_field).strip()
    pairs, separator, mouse = raw.partition('/')
    remaining = [pair.strip() for pair in pairs.split(';')
                 if pair.strip() and pair.split('=', 1)[0].strip() != str(skill_id)]
    remaining.append('%d=%d' % (skill_id, delay))
    QtBind.setText(gui, boss_dialog_field, '; '.join(remaining) + (' / ' + mouse.strip() if separator and mouse.strip() else ''))
    report('Đã điền ID=%d, ngắt=%d ms. Kiểm tra tọa độ Boss chuột rồi lưu.' % (skill_id, delay))


def start_hotbar_finder():
    arm_skill_probe()
    QtBind.setText(gui,hotbar_status_label,
        'Đang dò 60s: sang game bấm ô skill, rồi quay lại copy ID.' if skill_probe is not None
        else 'Chưa bắt đầu dò: kiểm tra nhân vật/client hoặc đợi lượt skill đang chạy xong.')


def stop_hotbar_finder():
    stop_skill_probe()
    QtBind.setText(gui,hotbar_status_label,'Đã dừng dò; giữ ID vừa tìm để copy.')


def update_hotbar_finder(skill_id,message):
    global hotbar_found
    if skill_id is not None:
        hotbar_found=(owner_of(get_character_data() or {}),int(skill_id))
        match=re.search(r'Ô ([0-9]):',message)
        QtBind.setText(gui,hotbar_slot_label,'Ô: '+(match.group(1) if match else '—'))
        QtBind.setText(gui,hotbar_id_field,str(skill_id))
        QtBind.setText(gui,hotbar_name_field,str((skill_table().get(int(skill_id)) or {}).get('name','')))
    QtBind.setText(gui,hotbar_status_label,('Đã đọc ID %s từ ô số; bấm Copy ID. Không tự thêm vào PvP.'%skill_id) if skill_id is not None else message)


def observe_hotbar_finder_request(opcode,data):
    """Read the ID emitted by a real hotbar press, even if cast is refused."""
    if opcode!=0x7074 or skill_probe is None:return
    raw=bytes(data or b'')
    if len(raw)<7 or raw[:2]!=b'\x01\x04' or raw[6] not in (0,1) or (raw[6]==1 and len(raw)<11):return
    with pvp_lock:
        probe=skill_probe
        character=get_character_data() or {}
        if (probe is None or owner_of(character)!=probe['owner'] or monotonic()>=probe['deadline']
                or not user32 or user32.GetForegroundWindow()!=probe['window']):return
        held=[digit for digit in '0123456789' if user32.GetAsyncKeyState(ord(digit)) & 0x8000]
        slot=(held[0] if len(held)==1 else probe['slot'] if not held and monotonic()-probe['pressed_at']<=2 else None)
        uid=struct.unpack_from('<I',raw,2)[0]
        skill=skill_table().get(uid)
        if slot is None or not skill or (slot,uid) in probe['matches']:return
        probe['matches'].add((slot,uid))
        message='Ô %s: %s | ID=%d (đọc yêu cầu từ client, chưa xác nhận đã dùng skill).'%(slot,skill.get('name') or skill.get('servername',''),uid)
        skill_probe_results.append((probe['owner'],uid,message))


def copy_hotbar_id():
    if not hotbar_found or hotbar_found[0]!=owner_of(get_character_data() or {}):
        QtBind.setText(gui,hotbar_status_label,'Chưa có ID của acc hiện tại; bấm Dò ô số rồi dùng skill.')
        return
    uid=str(hotbar_found[1])
    if put_finder_clipboard(uid):
        QtBind.setText(gui,hotbar_status_label,'Đã copy ID '+uid+'.')
    else:
        QtBind.setText(gui,hotbar_status_label,'ID '+uid+': chọn ô ID, Ctrl+A rồi Ctrl+C để copy.')


def auto_pk_settings_path():
    return Path(get_config_dir())/'GhostControl_AutoPK.json'


def view_auto_pk():
    global auto_pk_owner,auto_pk_anchor
    show_view('auto_pk')
    owner=owner_of(get_character_data() or {})
    if owner==auto_pk_owner:return
    auto_pk_owner=owner
    auto_pk_anchor=None
    load_auto_pk_options({})
    QtBind.setText(gui,auto_pk_radius_field,str(AUTO_PK_MAX_RADIUS))
    QtBind.setText(gui,auto_pk_page_field,'F2')
    QtBind.setText(gui,auto_pk_enemy_key_field,'')
    try:
        profiles=json.loads(auto_pk_settings_path().read_text(encoding='utf-8'))
        if not isinstance(profiles,dict):profiles={}
        profile=profiles.get(json.dumps(owner),{})
        if isinstance(profile,dict):
            load_auto_pk_options(profile)
            radius=float(profile.get('attack_radius', profile.get('radius', profile.get('scan_radius', AUTO_PK_MAX_RADIUS))))
            page=profile.get('page','F2')
            QtBind.setText(gui,auto_pk_enemy_key_field,str(profile.get('target_enemy_key') or ''))
            if math.isfinite(radius) and radius >= 1:
                QtBind.setText(gui, auto_pk_radius_field, '%g' % min(radius, AUTO_PK_MAX_RADIUS))
            if page in ('F1','F2'):QtBind.setText(gui,auto_pk_page_field,page)
            anchor=profile.get('anchor')
            if isinstance(anchor,dict) and all(k in anchor for k in ('x','y','region')):
                values={k:float(anchor.get(k,0)) for k in ('x','y','z')}
                if all(math.isfinite(value) for value in values.values()):
                    auto_pk_anchor=dict(values,region=int(anchor['region']))
    except (OSError,ValueError,TypeError):pass
    show_auto_pk_anchor()
    for field in auto_pk_result_fields:QtBind.setText(gui,field,'')
    QtBind.setText(gui, auto_pk_scan_field, 'Tự quét nhận diện khi bật Auto PK.')
    QtBind.setText(gui,auto_pk_status_label,'Bấm Bật Auto pk để lưu vị trí hiện tại và tự canh.')


def read_auto_pk_settings():
    owner=owner_of(get_character_data() or {})
    if not owner:raise ValueError('Nhân vật chưa vào game.')
    if owner!=auto_pk_owner:raise ValueError('Nhân vật đã đổi; mở lại tab Auto pk trước.')
    try:radius=float(QtBind.text(gui,auto_pk_radius_field).strip())
    except ValueError:
        raise ValueError('Bán kính cần là số từ 1 đến 40 m.') from None
    if not math.isfinite(radius) or radius < 1:
        raise ValueError('Bán kính cần trong khoảng 1–40 m.')
    if radius > AUTO_PK_MAX_RADIUS:
        radius = AUTO_PK_MAX_RADIUS
        QtBind.setText(gui, auto_pk_radius_field, str(AUTO_PK_MAX_RADIUS))
    page=QtBind.text(gui,auto_pk_page_field)
    if page not in ('F1','F2'):raise ValueError('Chọn nhóm Auto pk F1 hoặc F2.')
    return owner,radius,page


def show_auto_pk_anchor():
    if auto_pk_anchor:
        text='Điểm chờ: x=%.1f, y=%.1f, vùng=%s'%(auto_pk_anchor['x'],auto_pk_anchor['y'],auto_pk_anchor['region'])
    else:text='Điểm chờ: chưa lấy.'
    QtBind.setText(gui,auto_pk_anchor_label,text)


def current_auto_pk_anchor():
    position = get_position() or {}
    x, y, z = float(position['x']), float(position['y']), float(position.get('z', 0))
    if not all(map(math.isfinite, (x, y, z))):
        raise ValueError('Chưa đọc được tọa độ/vùng.')
    return {'x': x, 'y': y, 'z': z, 'region': int(position['region'])}


def view_auto_pk_options():
    view_auto_pk()
    show_view('auto_pk_options')


def view_auto_pk_buffs():
    view_auto_pk()
    show_view('auto_pk_buffs')


def load_auto_pk_options(profile):
    QtBind.setText(gui, auto_pk_scan_radius_field, str(profile.get('scan_radius', AUTO_PK_REPORT_RADIUS)))
    QtBind.setText(gui, auto_pk_patrol_radius_field, str(profile.get('patrol_radius', 10)))
    for box, name in ((auto_pk_fast_box,'fast_scan'),(auto_pk_patrol_box,'patrol_enabled'),
                      (auto_pk_buffs_box,'buffs_enabled')):
        set_checked_silent(box, profile.get(name) is True)
    centers = profile.get('centers') or {}
    if not isinstance(centers, dict):
        centers = {}
    for kind, fields in auto_pk_center_fields.items():
        values = centers.get(kind)
        for i, field in enumerate(fields):
            text = str(values[i]) if isinstance(values,(list,tuple)) and len(values)==2 else ''
            QtBind.setText(gui, field, text)
    buffs = profile.get('buff_ids') or []
    for i, field in enumerate(auto_pk_buff_fields):
        QtBind.setText(gui, field, str(buffs[i]) if isinstance(buffs,list) and i<len(buffs) else '')


def auto_pk_option_radius(field, name, limit):
    value = float(QtBind.text(gui, field))
    if not math.isfinite(value) or not 1 <= value <= limit:
        raise ValueError('%s phải từ 1 đến %d m.' % (name,limit))
    return value


def read_auto_pk_centers():
    centers = {}
    for kind, fields in auto_pk_center_fields.items():
        texts = [QtBind.text(gui, field).strip() for field in fields]
        if not any(texts):
            continue
        if not all(texts):
            raise ValueError('Nhập cả X và Y cho mỗi tâm vùng, hoặc để trống cả hai.')
        values = [float(text) for text in texts]
        if not all(map(math.isfinite, values)):
            raise ValueError('Tọa độ X và Y phải là số hữu hạn.')
        centers[kind] = values
    return centers


def read_auto_pk_buff_ids():
    buffs = []
    for row, field in enumerate(auto_pk_buff_fields, 1):
        text = QtBind.text(gui, field).strip()
        if not text:
            continue
        try:
            uid = int(text)
        except ValueError:
            raise ValueError('Buff %d: nhập ID bằng số.' % row) from None
        if not 0 <= uid <= 0xffffffff:
            raise ValueError('Buff %d: ID phải là số dương hợp lệ.' % row)
        if uid and uid not in buffs:
            buffs.append(uid)
    return buffs


def read_auto_pk_options():
    try:
        buffs, buff_error = read_auto_pk_buff_ids(), None
    except ValueError as error:
        buffs, buff_error = [], str(error)
    return {
        'scan_radius':auto_pk_option_radius(auto_pk_scan_radius_field,'Vùng quét',AUTO_PK_MAX_SCAN_RADIUS),
        'patrol_radius':auto_pk_option_radius(auto_pk_patrol_radius_field,'Bán kính chạy vòng',AUTO_PK_MAX_RADIUS),
        'patrol_enabled':QtBind.isChecked(gui,auto_pk_patrol_box),
        'fast_scan':QtBind.isChecked(gui,auto_pk_fast_box),
        'buffs_enabled':QtBind.isChecked(gui,auto_pk_buffs_box),
        'buff_ids':buffs, 'buff_error':buff_error, 'centers':read_auto_pk_centers(),
    }


def auto_pk_center(anchor, centers, kind):
    values = centers.get(kind)
    return dict(anchor, x=values[0], y=values[1]) if values else anchor


def validate_auto_pk_patrol(runtime):
    center = runtime['patrol_center']
    anchor = runtime['anchor']
    offset = math.hypot(center['x']-anchor['x'], center['y']-anchor['y'])
    if offset + runtime['patrol_radius'] > runtime['radius']:
        raise ValueError('Vòng chạy phải nằm trọn trong vùng đánh.')


def auto_pk_option_status(message):
    for field in (auto_pk_status_label, auto_pk_options_status, auto_pk_buffs_status):
        QtBind.setText(gui, field, message)


def save_auto_pk_buffs():
    save_auto_pk_settings(require_valid_buffs=True)


def save_auto_pk_settings(require_valid_buffs=False):
    try:
        owner,radius,page=read_auto_pk_settings()
        path=auto_pk_settings_path()
        try:profiles=json.loads(path.read_text(encoding='utf-8'))
        except FileNotFoundError:profiles={}
        if not isinstance(profiles,dict):raise ValueError('File cấu hình Auto pk không hợp lệ; không ghi đè.')
        key_name, _ = read_auto_pk_enemy_key()
        options = read_auto_pk_options()
        buff_error = options.pop('buff_error')
        owner_key = json.dumps(owner)
        if buff_error:
            if require_valid_buffs:
                QtBind.setText(gui, auto_pk_buffs_status, 'Chưa lưu buff: ' + buff_error)
                return
            previous = profiles.get(owner_key)
            if not isinstance(previous, dict):
                previous = {}
            options['buff_ids'] = previous.get('buff_ids', [])
            options['buffs_enabled'] = options['buffs_enabled'] and previous.get('buffs_enabled') is True
        profiles[owner_key] = dict(options, radius=radius, attack_radius=radius, page=page,
                                   target_enemy_key=key_name, anchor=auto_pk_anchor, enabled=False)
        import tempfile
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=str(path.parent),delete=False) as stream:
                temporary=stream.name;json.dump(profiles,stream,ensure_ascii=False,indent=2,allow_nan=False)
            os.replace(temporary,path);temporary=None
        finally:
            if temporary and os.path.exists(temporary):os.unlink(temporary)
        if buff_error:
            auto_pk_option_status('Đã lưu Auto PK · giữ bảng buff đã lưu trước đó.')
            QtBind.setText(gui, auto_pk_buffs_status, 'Chưa lưu buff: ' + buff_error)
        else:
            auto_pk_option_status('Đã lưu Auto PK và bảng buff · cấu hình áp dụng khi bật lại.')
    except (OSError,ValueError,TypeError) as error:
        auto_pk_option_status('Chưa lưu: '+str(error))


def scan_auto_pk_now():
    with pvp_lock:
        scan_auto_pk_evidence(auto_pk_runtime if auto_pk_running else None)


def scan_auto_pk_evidence(runtime=None):
    try:
        position = current_auto_pk_anchor()
        if runtime is None:
            _, radius, _ = read_auto_pk_settings()
            centers = read_auto_pk_centers()
            anchor = auto_pk_center(position, centers, 'attack')
            center = auto_pk_center(anchor, centers, 'scan')
            scan_radius = auto_pk_option_radius(auto_pk_scan_radius_field,'Vùng quét',AUTO_PK_MAX_SCAN_RADIUS)
        else:
            anchor, radius = runtime['anchor'], runtime['radius']
            center = runtime.get('scan_center', anchor)
            scan_radius = runtime.get('scan_radius', AUTO_PK_REPORT_RADIUS)
        players = auto_pk_players()
        character = get_character_data() or {}
        monsters = get_monsters() if callable(get_monsters) else None
        player_id = character.get('player_id')
        now = monotonic()
        rows = []
        for uid, player in (players or {}).items():
            if not isinstance(player, dict) or str(uid) == str(player_id):
                continue
            scan_distance = auto_pk_scan_distance(player, center)
            if scan_distance is None or scan_distance > scan_radius:
                continue
            attack_distance = auto_pk_target_distance(player, anchor, runtime)
            unavailable = (auto_pk_target_unavailable(runtime, int(uid), player, now)
                           if runtime is not None and str(uid).isdigit() else None)
            try:
                uid_key = int(uid) if str(uid).isdigit() else uid
            except (TypeError, ValueError):
                uid_key = uid
            hostility, is_opponent = auto_pk_hostility_label(
                player, character, uid=uid_key, monsters=monsters)
            rows.append(dict(uid=str(uid), name=player.get('name','?'), distance_m=scan_distance,
                             dead=player.get('dead'), unavailable=unavailable,
                             in_attack_range=attack_distance is not None and attack_distance <= radius,
                             hostility=hostility,
                             opponent=is_opponent))
        rows.sort(key=lambda row: (not row['opponent'], row['distance_m']))
        for i, field in enumerate(auto_pk_result_fields):
            row = rows[i] if i<len(rows) else None
            text = ('%s | UID=%s | %.1f m từ tâm quét | %s | %s' %
                    (row['name'], row['uid'], row['distance_m'], row['hostility'],
                     'đã chết' if row['dead'] else row['unavailable'] or
                     ('trong vùng đánh' if row['in_attack_range'] else 'chỉ báo'))) if row else ''
            QtBind.setText(gui, field, text)
        message = ('Quét %g m · %d người · %d ngoài vùng đánh.' %
                   (scan_radius,len(rows),sum(not row['in_attack_range'] for row in rows)))
        if not players:
            message += ' Chưa có UID từ phBot.'
        QtBind.setText(gui, auto_pk_scan_field, message)
        return {'players': rows}
    except (KeyError, ValueError, TypeError, OSError, OverflowError) as error:
        QtBind.setText(gui, auto_pk_scan_field, 'Chưa quét: ' + str(error))


def auto_pk_scan_distance(target, center):
    # World-sector neighbours share world X/Y. Keep instance regions isolated.
    region = target.get('region')
    if region is not None:
        try:
            region = int(region)
        except (ValueError, TypeError, OverflowError):
            return None
        home = center['region']
        if region != home:
            if not (0 < region < 0x8000 and 0 < home < 0x8000
                    and abs((region & 255)-(home & 255)) <= 1
                    and abs((region >> 8)-(home >> 8)) <= 1):
                return None
            return auto_pk_distance(dict(target,region=home), center)
    return auto_pk_distance(target, center)


def auto_pk_enemy_key_name():
    name = ''.join((QtBind.text(gui, auto_pk_enemy_key_field) or '').upper().split())
    return 'INSERT' if name == 'INS' else name


def read_auto_pk_enemy_key():
    name = auto_pk_enemy_key_name()
    special = {'': 0, 'SPACE': 0x20, 'TAB': 0x09, '`': 0xC0}  # VK_OEM_3
    if name in special:
        return name, special[name]
    if name in AUTO_PK_NATIVE_KEYS:
        return name, AUTO_PK_NATIVE_KEYS[name]
    if len(name) == 1 and 'A' <= name <= 'Z' and name != 'X':
        return name, ord(name)
    raise ValueError('Dùng Home, End, Insert, Page Up, Page Down, F9–F12 hoặc phím thử tay.')



class AutoPKInputInfo(ctypes.Structure):
    _fields_ = [('size', wintypes.UINT), ('tick', wintypes.DWORD)]


if user32:
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(AutoPKInputInfo)]
    user32.GetLastInputInfo.restype = wintypes.BOOL
    auto_pk_get_tick_count = ctypes.WinDLL('kernel32').GetTickCount
    auto_pk_get_tick_count.argtypes = []
    auto_pk_get_tick_count.restype = wintypes.DWORD


def auto_pk_input_tick():
    info = AutoPKInputInfo(ctypes.sizeof(AutoPKInputInfo), 0)
    return int(info.tick) if user32 and user32.GetLastInputInfo(ctypes.byref(info)) else None


def auto_pk_in_background(client):
    window = client.get('window')
    return auto_pk_running and (not window or user32.GetForegroundWindow() != window)


def auto_pk_can_cut_in_background(client, target):
    return (direct_native_exchange and background_exchange_failed_uid != target
            and game_window_belongs_to(client.get('window'), client.get('pid')))


def auto_pk_manual_input(input_tick):
    window = (get_client() or {}).get('window')
    if not user32 or not window or user32.GetForegroundWindow() != window or input_tick is None:
        return False
    age = (auto_pk_get_tick_count() - input_tick) & 0xffffffff
    return age <= 350


def auto_pk_self_in_radius(runtime, position=None):
    """Own character still inside the Auto PK attack radius."""
    position = position or get_position() or {}
    if 'region' not in position:
        return False, 'thiếu tọa độ hoặc đã đổi vùng'
    own_distance = auto_pk_distance(position, runtime['anchor'])
    if own_distance is None:
        return False, 'thiếu tọa độ hoặc đã đổi vùng'
    if own_distance > runtime['radius']:
        return False, AUTO_PK_OUTSIDE_SELF
    return True, own_distance


def auto_pk_allow_unlisted_target(runtime, uid):
    """Accept a select when get_players omits opposing-faction enemies."""
    if not pvp_person_target(uid):
        return False, 'mục tiêu không hợp lệ'
    ok, reason = auto_pk_radius_check(uid)
    if ok:
        return True, reason
    if reason != 'tạm thiếu dữ liệu Player':
        return False, reason
    self_ok, self_reason = auto_pk_self_in_radius(runtime)
    if not self_ok:
        return False, self_reason
    return True, 'thiếu Player list · giữ chọn server/Target Enemy'


def auto_pk_outgoing_selection(data):
    global pvp_selection_request, direct_select_request
    runtime = auto_pk_runtime
    if not runtime or auto_pk_returning or len(data or b'') != 4:
        return False
    uid = struct.unpack('<I', data)[0]
    if uid and uid == runtime['requested']:
        return True
    if runtime['requested'] or pvp_target or not uid:
        return False
    now = monotonic()
    if runtime['retired'].get(uid, 0) > now:
        return False
    native_probe = runtime.get('native_probe_until', 0) > now
    if not native_probe and not auto_pk_manual_input(auto_pk_input_tick()):
        return False
    # Native/manual Target Enemy must not be blocked just because opposing-faction
    # players are missing from get_players or dual-listed in get_monsters.
    if not auto_pk_allow_unlisted_target(runtime, uid)[0]:
        return False
    runtime.pop('select_in_event', None)
    runtime.update(requested=uid, select_until=now + AUTO_PK_SELECT_TIMEOUT, native_uid=uid,
                   target_seen_at=now, target_sent_at=now, native_probe_until=0.0,
                   native_source='Target Enemy' if native_probe else 'chọn tay')
    QtBind.setText(gui, auto_pk_status_label,
                   '%s UID %d · chờ B045.' % (runtime['native_source'], uid))
    pvp_selection_request = direct_select_request = uid
    return True


def auto_pk_players():
    getter = getattr(phbot_api, 'get_players', None)
    try:
        players = getter() if callable(getter) else None
    except (RuntimeError, OSError):
        return None
    return players if isinstance(players, dict) else None


# Hostile name colors after war-scarf and/or Alt hostile mode (purple→red).
# Red = primary opponent mark; purple = hostile/alt mode (also treat as enemy).
_HOSTILE_COLOR_KEYS = (
    'color', 'name_color', 'namecolor', 'colour', 'player_color', 'NameColor',
    'nameColor', 'Name_Color', 'text_color', 'font_color',
)
_HOSTILE_COLOR_WORDS = {
    'red', 'đỏ', 'do', 'scarlet', 'crimson',
    'purple', 'tím', 'tim', 'violet', 'magenta', 'fuchsia',
    'hostile', 'enemy', 'pk', 'war',
}
# Small enums seen on some private builds (0=normal …).
_HOSTILE_COLOR_ENUMS = {3, 4, 5, 6, 7, 8, 9}


def _auto_pk_color_rgb(value):
    """Normalize a color field to (r, g, b) when possible."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        if value < 0:
            return None
        if value <= 0xffffff:
            return (value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff
        if value <= 0xffffffff:
            return (value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff
        return None
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            return int(value[0]) & 0xff, int(value[1]) & 0xff, int(value[2]) & 0xff
        except (TypeError, ValueError):
            return None
    if isinstance(value, dict):
        try:
            if all(k in value for k in ('r', 'g', 'b')):
                return int(value['r']) & 0xff, int(value['g']) & 0xff, int(value['b']) & 0xff
            if all(k in value for k in ('R', 'G', 'B')):
                return int(value['R']) & 0xff, int(value['G']) & 0xff, int(value['B']) & 0xff
        except (TypeError, ValueError, KeyError):
            return None
    if isinstance(value, str):
        text = value.strip().casefold()
        if text.startswith('#') and len(text) in (4, 7):
            raw = text[1:]
            if len(raw) == 3:
                raw = ''.join(ch * 2 for ch in raw)
            try:
                number = int(raw, 16)
                return (number >> 16) & 0xff, (number >> 8) & 0xff, number & 0xff
            except ValueError:
                return None
        if text.startswith('0x'):
            try:
                return _auto_pk_color_rgb(int(text, 16))
            except ValueError:
                return None
        if text.isdigit():
            try:
                return _auto_pk_color_rgb(int(text))
            except ValueError:
                return None
    return None


def auto_pk_player_color_value(player):
    if not isinstance(player, dict):
        return None
    for key in _HOSTILE_COLOR_KEYS:
        if key in player and player[key] is not None and player[key] != '':
            return player[key]
    return None


def auto_pk_hostile_name_color(player):
    """True when name color marks a hostile opponent (red primary, purple also).

    Returns None when no usable color field is present (caller may fall back to
    Target Enemy / Insert, war-scarf, or server-confirmed select).
    """
    value = auto_pk_player_color_value(player)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = int(value)
        if number in _HOSTILE_COLOR_ENUMS:
            return True
        # Common non-hostile enums / white-ish packed colors.
        if number in (0, 1, 2):
            return False
    if isinstance(value, str):
        text = value.strip().casefold()
        if not text:
            return None
        if text in _HOSTILE_COLOR_WORDS or any(word in text for word in _HOSTILE_COLOR_WORDS):
            return True
        # Explicit non-hostile labels.
        if text in ('white', 'blue', 'green', 'yellow', 'gray', 'grey', 'black',
                    'ally', 'party', 'guild', 'neutral', 'trắng', 'xanh', 'vàng'):
            return False
    rgb = _auto_pk_color_rgb(value)
    if rgb is None:
        return None
    red, green, blue = rgb
    # Near-white / gray names are not opponents.
    if red >= 200 and green >= 200 and blue >= 200:
        return False
    if abs(red - green) <= 25 and abs(green - blue) <= 25 and abs(red - blue) <= 25:
        return False
    # Red hostile (after Alt hostile mode / war scarf): R dominates.
    if red >= 150 and red >= green + 40 and red >= blue + 40:
        return True
    # Purple / violet hostile mode tint: R and B high, G lower.
    if red >= 110 and blue >= 110 and green <= min(red, blue) - 25:
        return True
    return False


# Job-flag (mặc cờ nghề): đạo tặc vs bảo tiêu (trader/hunter) are always enemies.
_JOB_FIELD_KEYS = (
    'job_type', 'jobtype', 'JobType', 'job', 'job_id', 'jobId', 'job_mode',
    'jobMode', 'job_flag', 'jobflag', 'profession', 'role', 'title', 'job_name',
    'jobName', 'job_title', 'jobTitle', 'nickname', 'desc', 'description',
)
_JOB_THIEF_WORDS = {
    'thief', 'bandit', 'robber', 'đạo tặc', 'dao tac', 'đạotặc', 'daotac', 'tặc',
    'cướp', 'cuop', 'cướp chuyên nghiệp', 'cuop chuyen nghiep', 'cướpchuyênnghiệp',
}
_JOB_ESCORT_WORDS = {
    'trader', 'hunter', 'trade', 'merchant', 'caravan',
    'bảo tiêu', 'bao tieu', 'bảotiêu', 'baotieu',
    'thương nhân', 'thuong nhan', 'thợ săn', 'tho san',
    'tiêu thương', 'tieu thuong',
}
# VSRO / common private enums: 0 none; trader/hunter/thief vary by build.
_JOB_THIEF_ENUMS = {2, 4}          # 2=Thief on many builds; 4=Bandit on some
_JOB_ESCORT_ENUMS = {1, 3}         # 1/3 = Hunter or Trader depending on build


def auto_pk_job_raw(entity):
    if not isinstance(entity, dict):
        return None
    for key in _JOB_FIELD_KEYS:
        if key in entity and entity[key] is not None and entity[key] != '':
            return entity[key]
    return None


def _auto_pk_job_side_from_text(text):
    text = (text or '').strip().casefold()
    if not text or text in ('0', 'none', 'no', 'off', 'false', '-'):
        return None
    # Prefer thief markers before escort (e.g. "Cướp Chuyên Nghiệp").
    if text in _JOB_THIEF_WORDS or any(word in text for word in _JOB_THIEF_WORDS):
        return 'thief'
    if text in _JOB_ESCORT_WORDS or any(word in text for word in _JOB_ESCORT_WORDS):
        return 'escort'
    return None


def auto_pk_job_side(entity):
    """Return 'thief', 'escort' (trader/hunter), or None if no job flag."""
    value = auto_pk_job_raw(entity)
    if value is None or value is False:
        value = None
    elif isinstance(value, bool):
        value = None
    elif isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        if value in _JOB_THIEF_ENUMS:
            return 'thief'
        if value in _JOB_ESCORT_ENUMS:
            return 'escort'
        value = None
    elif value is not None:
        text = str(value).strip().casefold()
        if text.isdigit():
            return auto_pk_job_side({'job_type': int(text)})
        side = _auto_pk_job_side_from_text(text)
        if side:
            return side
    # phBot Stable often omits job_type but still exposes job title text
    # ("Cướp Chuyên Nghiệp", …) in miscellaneous string fields.
    if isinstance(entity, dict):
        for key, entry in entity.items():
            if key in ('name', 'guild', 'servername') or not isinstance(entry, str):
                continue
            side = _auto_pk_job_side_from_text(entry)
            if side:
                return side
    return None


def auto_pk_job_flag_hostile(self_entity, other_entity):
    """True when both wear job flags and are thief vs trader/hunter."""
    mine = auto_pk_job_side(self_entity)
    theirs = auto_pk_job_side(other_entity)
    if not mine or not theirs:
        return False
    return mine != theirs and {mine, theirs} == {'thief', 'escort'}


def auto_pk_dual_listed(uid, monsters=None):
    """Opposing-faction / scarf hostiles are often dual-listed in get_monsters()."""
    if monsters is None:
        monsters = get_monsters()
    if not isinstance(monsters, dict):
        return False
    try:
        return uid in monsters or str(uid) in monsters or int(uid) in monsters
    except (TypeError, ValueError):
        return uid in monsters or str(uid) in monsters


def auto_pk_monster_entry(uid, monsters=None):
    if monsters is None:
        monsters = get_monsters()
    if not isinstance(monsters, dict):
        return None
    if uid in monsters and isinstance(monsters[uid], dict):
        return monsters[uid]
    text = str(uid)
    if text in monsters and isinstance(monsters[text], dict):
        return monsters[text]
    try:
        number = int(uid)
    except (TypeError, ValueError):
        return None
    entry = monsters.get(number)
    return entry if isinstance(entry, dict) else None


def auto_pk_player_view(player, uid=None, monsters=None):
    """Merge dual-listed monster fields under player so job/color cues survive."""
    if not isinstance(player, dict):
        return {}
    entry = auto_pk_monster_entry(uid, monsters) if uid is not None else None
    if not entry:
        return player
    merged = dict(entry)
    merged.update(player)
    return merged


def auto_pk_is_hostile_opponent(player, character=None, require_color=False, uid=None,
                                monsters=None):
    """Opponent for Auto PK list select.

    Priority: job-flag thief↔bảo tiêu; red/purple name color; when color is
    hidden (common on Stable), dual-list in get_monsters (scarf/red hostiles).
    Explicit white/non-hostile color stays skipped. Insert / war-scarf /
    Alt-hostile server selects remain intact.
    """
    self_entity = get_character_data() or {} if character is None else character
    view = auto_pk_player_view(player, uid, monsters)
    if auto_pk_job_flag_hostile(self_entity, view):
        return True
    verdict = auto_pk_hostile_name_color(view)
    if verdict is True:
        return True
    if verdict is False:
        return False
    # Color field missing ("màu tên ẩn"): dual-list (khăn/phe địch) is enough.
    if uid is not None and auto_pk_dual_listed(uid, monsters):
        return True
    # Title-only job cues (e.g. "Cướp Chuyên Nghiệp") when self is bảo tiêu.
    if auto_pk_job_flag_hostile(self_entity, view):
        return True
    theirs = auto_pk_job_side(view)
    mine = auto_pk_job_side(self_entity)
    if theirs and mine and theirs != mine and {mine, theirs} == {'thief', 'escort'}:
        return True
    if require_color:
        return False
    return False


def auto_pk_hostility_label(player, character=None, uid=None, monsters=None):
    """Short VN label for Auto PK scan rows."""
    view = auto_pk_player_view(player, uid, monsters)
    self_entity = character or {}
    if auto_pk_job_flag_hostile(self_entity, view):
        return 'địch cờ nghề', True
    color = auto_pk_hostile_name_color(view)
    if color is True:
        return 'chữ đỏ/tím', True
    if color is False:
        return 'không thù địch', False
    dual = uid is not None and auto_pk_dual_listed(uid, monsters)
    if dual:
        return 'địch (dual-list/khăn)', True
    theirs = auto_pk_job_side(view)
    mine = auto_pk_job_side(self_entity)
    if theirs == 'thief' and mine == 'escort':
        return 'địch cờ nghề', True
    if theirs == 'escort' and mine == 'thief':
        return 'địch cờ nghề', True
    if theirs == 'thief':
        return 'cướp/đạo tặc (thiếu cờ mình)', False
    if theirs == 'escort':
        return 'bảo tiêu (thiếu cờ mình)', False
    return 'màu tên ẩn', False


def auto_pk_distance(target, anchor):
    try:
        if target.get('region') is not None and int(target['region']) != anchor['region']:
            return None
        distance = math.hypot(float(target['x']) - anchor['x'], float(target['y']) - anchor['y'])
        return distance if math.isfinite(distance) else None
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def auto_pk_target_distance(target, center, runtime):
    if runtime is not None and runtime.get('fast_scan'):
        return auto_pk_scan_distance(target, center)
    return auto_pk_distance(target, center)


def auto_pk_radius_check(uid):
    runtime = auto_pk_runtime
    if not runtime:
        return False, 'chưa bật Auto PK'
    anchor = runtime['anchor']
    position = get_position() or {}
    own_distance = auto_pk_distance(position, anchor) if 'region' in position else None
    if own_distance is None:
        return False, 'thiếu tọa độ hoặc đã đổi vùng'
    if own_distance > runtime['radius']:
        return False, AUTO_PK_OUTSIDE_SELF
    players = auto_pk_players() or {}
    target = players.get(uid) or players.get(str(uid))
    if not isinstance(target, dict):
        return False, 'tạm thiếu dữ liệu Player'
    unavailable = auto_pk_target_unavailable(runtime, uid, target, monotonic())
    if unavailable:
        return False, unavailable
    distance = auto_pk_target_distance(target, anchor, runtime)
    if distance is None:
        return False, 'tạm thiếu dữ liệu Player'
    if distance > runtime['radius']:
        return False, AUTO_PK_OUTSIDE_TARGET
    return True, 'mục tiêu cách điểm chờ %.1f m' % distance


def auto_pk_target_unavailable(runtime, uid, target, now):
    if target.get('dead'):
        runtime['dead_uids'].add(uid)
        return 'mục tiêu đã chết'
    if uid in runtime['dead_uids']:
        runtime['dead_uids'].remove(uid)
        runtime['retired'][uid] = max(runtime['retired'].get(uid, 0), now + AUTO_PK_PROTECTION_DELAY)
    if runtime['retired'].get(uid, 0) > now:
        return AUTO_PK_PROTECTED
    return None


def auto_pk_ready_to_cast(runtime, uid, now):
    anchor = runtime['anchor']
    position = get_position() or {}
    players = auto_pk_players() or {}
    target = players.get(uid) or players.get(str(uid))
    own_radius = auto_pk_distance(position, anchor) if 'region' in position else None
    if own_radius is None:
        return False
    if own_radius > runtime['radius']:
        force_auto_pk_return(runtime, AUTO_PK_OUTSIDE_SELF)
        return False
    # Opposing-faction enemies may be absent from get_players; skill packets still
    # use the server-confirmed UID, so allow cast without approach coords.
    if not isinstance(target, dict):
        runtime.pop('approach', None)
        return True
    target_radius = auto_pk_target_distance(target, anchor, runtime)
    if target_radius is None:
        runtime.pop('approach', None)
        return True
    if target_radius > runtime['radius']:
        return False
    x, y = float(position['x']), float(position['y'])
    dx, dy = float(target['x']) - x, float(target['y']) - y
    distance = math.hypot(dx, dy)
    if distance <= AUTO_PK_APPROACH_RANGE:
        runtime.pop('approach', None)
        return True

    approach = runtime.get('approach')
    if approach is None or approach['uid'] != uid:
        approach = runtime['approach'] = dict(uid=uid, best=distance, since=now, move_at=now)
    elif distance <= approach['best'] - AUTO_PK_RETURN_MIN_PROGRESS:
        approach.update(best=distance, since=now)
    elif now - approach['since'] >= AUTO_PK_RETURN_STALL_TIMEOUT:
        runtime['retired'][uid] = now + AUTO_PK_TARGET_RETRY_DELAY
        force_auto_pk_return(runtime, 'không áp sát được mục tiêu')
        return False
    if now >= approach['move_at']:
        approach['move_at'] = now + 2.0
        fraction = (distance - 4.0) / distance
        z = float(position.get('z', anchor['z']))
        if phbot_api.move_to(x + dx * fraction, y + dy * fraction, z) is False:
            runtime['retired'][uid] = now + AUTO_PK_TARGET_RETRY_DELAY
            force_auto_pk_return(runtime, 'phBot từ chối áp sát')
        else:
            QtBind.setText(gui, auto_pk_status_label, 'Đang áp sát UID %d · cách %.1f m.' % (uid, distance))
    return False


def auto_pk_fast_changed(checked):
    with pvp_lock:
        if not ui_sync and auto_pk_runtime is not None:
            auto_pk_runtime['fast_scan'] = bool(checked)


def auto_pk_buffs_changed(checked):
    with pvp_lock:
        if not ui_sync and auto_pk_runtime is not None:
            if checked and not auto_pk_runtime.get('buff_ids'):
                set_checked_silent(auto_pk_buffs_box, False)
                QtBind.setText(gui, auto_pk_buffs_status, 'Lưu ID buff hợp lệ rồi bật lại Auto PK.')
                return
            auto_pk_runtime['buffs_enabled'] = bool(checked)


def auto_pk_patrol_changed(checked):
    with pvp_lock:
        runtime = auto_pk_runtime
        if ui_sync or runtime is None:
            return
        if checked:
            try:
                validate_auto_pk_patrol(runtime)
            except ValueError as error:
                set_checked_silent(auto_pk_patrol_box, False)
                auto_pk_option_status(str(error))
                return
        else:
            stop_auto_pk_patrol(runtime)
        runtime['patrol_enabled'] = bool(checked)


def stop_auto_pk_patrol(runtime):
    if not runtime or not runtime.pop('patrol_destination', None) or get_status():
        return
    try:
        position = current_auto_pk_anchor()
        if position['region'] == runtime['anchor']['region']:
            phbot_api.move_to(position['x'], position['y'], position['z'])
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        report('Auto PK không hủy được bước chạy vòng: %s' % error)


def tick_auto_pk_patrol(runtime, position, now):
    if not runtime.get('patrol_enabled') or auto_pk_returning or now < blocked_until:
        return False
    if now < runtime.get('patrol_move_at', 0):
        return True
    destination = runtime.get('patrol_destination')
    center = runtime['patrol_center']
    radius = runtime['patrol_radius']
    index = runtime.get('patrol_index', 0)
    attempts = runtime.get('patrol_attempts', 0)
    if destination is None or (auto_pk_distance(position, destination) or 0) <= 1 or attempts >= 3:
        attempts = 0
        angle = index * math.tau / 8
        destination = dict(center, x=center['x']+radius*math.cos(angle),
                           y=center['y']+radius*math.sin(angle))
        runtime['patrol_index'] = (index+1) % 8
        runtime['patrol_destination'] = destination
    runtime.update(patrol_move_at=now + 1.5, patrol_attempts=attempts+1)
    try:
        if phbot_api.move_to(destination['x'], destination['y'], destination['z']) is False:
            runtime.pop('patrol_destination', None)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        runtime.pop('patrol_destination', None)
        report('Auto PK chạy vòng: %s' % error)
    QtBind.setText(gui, auto_pk_status_label, 'Đang chạy vòng %.0f m · ưu tiên mục tiêu trong vùng đánh.' % radius)
    return True


def tick_auto_pk_idle_buff(runtime, now):
    global blocked_until
    ids = runtime.get('buff_ids') if runtime.get('buffs_enabled') else None
    if not ids or auto_pk_returning or pvp_target or pvp_stunned_character is not None or now < blocked_until:
        return False
    if pending is not None or direct_expected is not None or direct_exchange_wait is not None:
        return False
    if now < runtime.get('buff_check_at', 0):
        return False
    runtime['buff_check_at'] = now + 0.3
    retry_at = runtime.setdefault('buff_retry_at', {})
    try:
        skills = skill_table()
        for uid in ids:
            data = skills.get(uid)
            if (not data or data.get('can_cast') is False or now < retry_at.get(uid, 0)
                    or imbue_is_active(phbot_api, uid, data)):
                continue
            stop_auto_pk_patrol(runtime)
            retry_at[uid] = now + max(2.0, imbue_seconds(data, 'cooldown'), imbue_seconds(data, 'duration'))
            if inject_joymax(0x7074, struct.pack('<BBIB', 1, 4, uid, 0), False) is False:
                continue
            blocked_until = now + max(0.2, imbue_seconds(data, 'cast_time') + 0.1)
            runtime['buff_cast_until'] = blocked_until
            QtBind.setText(gui, auto_pk_status_label, 'Đã gửi buff ID %d · tiếp tục canh sau khi thi triển.' % uid)
            return True
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        report('Auto PK buff: %s' % error)
    return False


def auto_pk_try_native_enemy_key(runtime, client, now, reason):
    """Fire configured Target Enemy when the player list cannot supply a UID."""
    key = runtime.get('native_key', 0)
    if key not in AUTO_PK_NATIVE_KEYS.values():
        return False
    window = client.get('window')
    runtime['native_probe_until'] = now + AUTO_PK_NATIVE_TIMEOUT
    runtime['select_until'] = runtime['native_probe_until']
    sent = post_game_key(key, window)
    if not sent and window and user32 and user32.GetForegroundWindow() == window:
        # Foreground fallback when PostMessage did not stick.
        sent = press_key(key, window)
    if sent:
        QtBind.setText(gui, auto_pk_status_label,
                       'Đã gửi Target Enemy (%s) · chờ game phát 7045.' % reason)
        return True
    runtime.pop('native_probe_until', None)
    runtime['select_until'] = 0.0
    return False


def auto_pk_select(character, runtime, now, from_event=False):
    global pvp_selection_request, direct_select_request
    if (now < max(runtime['select_until'], runtime.get('native_probe_until', 0),
                  runtime.get('buff_cast_until', 0))
            or (runtime.get('select_in_event') and not from_event)):
        return
    native_expired = bool(runtime.pop('native_probe_until', 0))
    if native_expired and now >= runtime.get('native_notice_at', 0):
        runtime['native_notice_at'] = now + 5.0
        log('[%s] Auto PK: game chưa phát 7045 sau phím Target Enemy.' % NAME)
    runtime.pop('select_in_event', None)
    if runtime['requested']:
        runtime['retired'][runtime['requested']] = now + AUTO_PK_TARGET_RETRY_DELAY
    if pvp_selection_request == runtime['requested']:
        pvp_selection_request = 0
    if direct_select_request == runtime['requested']:
        direct_select_request = 0
    runtime.update(requested=0, native_uid=0)
    players = auto_pk_players()
    monsters = get_monsters() if callable(get_monsters) else None
    anchor = runtime['anchor']
    position = get_position() or {}
    own_distance = auto_pk_distance(position, anchor) if 'region' in position else None
    if own_distance is None or own_distance > runtime['radius']:
        return
    client = get_client() or {}
    if not client.get('running'):
        return
    if players is None:
        # get_players often omits opposing-faction enemies on Stable; still try Target Enemy.
        if auto_pk_try_native_enemy_key(runtime, client, now, 'thiếu Player list'):
            return
        if not tick_auto_pk_patrol(runtime, position, now):
            QtBind.setText(gui, auto_pk_status_label,
                           'phBot chưa trả danh sách Player · gán Target Enemy (Home/End/Insert) để chọn phe địch.')
        return
    runtime['retired'] = {uid: until for uid, until in runtime['retired'].items() if until > now}
    best = None
    origin = {'x': float(position['x']), 'y': float(position['y']), 'region': anchor['region']}
    for raw_uid, target in players.items():
        try:
            uid = int(raw_uid)
        except (ValueError, TypeError):
            continue
        # Do not skip get_players entries that also appear in get_monsters()/NPCs:
        # opposing-faction enemies are dual-listed on some Stable builds.
        if (not 0 < uid <= 0xffffffff or uid == character.get('player_id')
                or not isinstance(target, dict)):
            continue
        if auto_pk_target_unavailable(runtime, uid, target, now):
            continue
        # List-select clear opponents: job-flag thief↔bảo tiêu, red/purple color,
        # or (when color ẩn) dual-list/khăn. Explicit white/non-hostile stays skipped.
        if not auto_pk_is_hostile_opponent(target, character, require_color=True,
                                           uid=uid, monsters=monsters):
            continue
        anchor_distance = auto_pk_target_distance(target, anchor, runtime)
        if anchor_distance is None or anchor_distance > runtime['radius']:
            continue
        candidate = (auto_pk_target_distance(target, origin, runtime), uid)
        if best is None or candidate < best:
            best = candidate
    if best is None:
        # After Insert failed to yield 7045, do not only re-spam the key forever.
        if native_expired:
            runtime['native_misses'] = runtime.get('native_misses', 0) + 1
        if (not native_expired or runtime.get('native_misses', 0) < 2) and auto_pk_try_native_enemy_key(
                runtime, client, now, 'không thấy đối thủ thù địch trong Player list'):
            return
        if not tick_auto_pk_idle_buff(runtime, now) and not tick_auto_pk_patrol(runtime, position, now):
            QtBind.setText(gui, auto_pk_status_label,
                           'Đang canh %.0f m · chưa thấy chữ đỏ/tím, dual-list/khăn hoặc cờ nghề địch.' %
                           runtime['radius'])
        return
    runtime['native_misses'] = 0
    stop_auto_pk_patrol(runtime)
    distance, uid = best
    failed_pid, until = runtime.get('fast_select_fallback', (None, 0))
    prefer_direct = (runtime.get('fast_scan') and auto_pk_in_background(client)
                     and failed_pid == client.get('pid') and now < until)
    # After Insert produced no 7045, prefer direct 7045 inject for the dual-list /
    # job-hostile UID rather than waiting on another native key cycle.
    if (native_expired or prefer_direct) and start_auto_pk_skill_probe(runtime, uid):
        return
    sent_at = monotonic()
    runtime.update(requested=uid, select_until=sent_at + AUTO_PK_SELECT_TIMEOUT,
                   target_seen_at=now, target_sent_at=sent_at)
    pvp_selection_request = direct_select_request = uid
    accepted = inject_joymax(0x7045, struct.pack('<I', uid), False)
    if auto_pk_runtime is not runtime or runtime['requested'] != uid:
        return  # A synchronous reply already handled this request.
    if accepted is not False:
        QtBind.setText(gui, auto_pk_status_label, 'Thử chọn UID %d · cách nhân vật %.1f m.' % (uid, distance))
        return
    runtime.update(requested=0, select_until=0.0)
    pvp_selection_request = direct_select_request = 0
    if not from_event:
        runtime['select_in_event'] = True
        QtBind.setText(gui, auto_pk_status_label, 'Đợi callback phBot gửi lại UID %d.' % uid)
        return

    if auto_pk_in_background(client) and start_auto_pk_skill_probe(runtime, uid):
        if runtime.get('fast_scan') and client.get('pid'):
            runtime['fast_select_fallback'] = (client['pid'], sent_at + 5.0)
        return
    if auto_pk_try_native_enemy_key(runtime, client, monotonic(), 'API từ chối 7045'):
        return
    if start_auto_pk_skill_probe(runtime, uid):
        return
    runtime['retired'][uid] = sent_at + AUTO_PK_TARGET_RETRY_DELAY
    key = runtime.get('native_key', 0)
    message = ('phBot từ chối 7045 · chưa gửi được phím Target Enemy.'
               if key else 'phBot từ chối 7045 · thử gán Target Enemy bằng Home, End hoặc Insert.')
    QtBind.setText(gui, auto_pk_status_label, message)
    if sent_at >= runtime.get('select_error_at', 0):
        runtime['select_error_at'] = sent_at + 5.0
        log('[%s] Auto PK UID %d: API trả False cho 7045 trong event_loop. %s' % (NAME, uid, message))


def start_auto_pk_skill_probe(runtime, uid):
    global pvp_target, direct_target
    if not direct_native_exchange or not auto_pk_allow_unlisted_target(runtime, uid)[0]:
        return False
    pvp_target = direct_target = uid
    runtime.pop('approach', None)
    runtime.pop('missing_since', None)
    runtime.update(skill_probe_uid=uid, first_cast_sent=False)
    request_pvp_page(runtime['page'])
    if auto_pk_runtime is runtime and (pvp_armed or pvp_activation is not None):
        QtBind.setText(gui, auto_pk_status_label, 'Thử skill theo UID %d · chờ xác nhận B070.' % uid)
    return True


def auto_pk_select_reply(data):
    global pvp_selection_request, direct_select_request, pvp_target, direct_target
    runtime = auto_pk_runtime
    uid = runtime['requested']
    now = monotonic()
    if not uid or not data or now >= runtime['select_until']:
        return
    if data[0] != 1:
        runtime['requested'] = runtime['native_uid'] = pvp_selection_request = direct_select_request = 0
        runtime.update(select_until=0.0, scan_at=0.0)
        runtime['retired'][uid] = now + AUTO_PK_PROTECTION_DELAY
        QtBind.setText(gui, auto_pk_status_label, 'Server từ chối UID %d · B045 %s.' %
                       (uid, bytes(data[:8]).hex(' ').upper()))
        return
    if len(data) < 5 or struct.unpack_from('<I', data, 1)[0] != uid:
        return
    runtime['requested'] = pvp_selection_request = direct_select_request = 0
    runtime['select_until'] = 0.0
    # Server confirmation is authoritative. Do not drop opposing-faction locks
    # just because get_players is empty/partial or the UID is dual-listed as a mob.
    allowed, reason = auto_pk_allow_unlisted_target(runtime, uid)
    if not allowed:
        runtime['retired'][uid] = max(runtime['retired'].get(uid, 0), now + AUTO_PK_TARGET_RETRY_DELAY)
        runtime['scan_at'] = 0.0
        QtBind.setText(gui, auto_pk_status_label,
                       'B045 UID %d nhưng chưa khóa: %s.' % (uid, reason))
        return
    stop_auto_pk_patrol(runtime)
    pvp_target = direct_target = uid
    runtime.pop('missing_since', None)
    runtime.pop('approach', None)
    runtime.update(first_cast_sent=False, target_locked_at=now, skill_probe_uid=0)
    request_pvp_page(runtime['page'])
    if auto_pk_runtime is not runtime:
        return
    if not pvp_activation and not pvp_armed:
        message = 'Đã nhận B045 UID %d nhưng nhóm %s chưa kích hoạt được.' % (uid, runtime['page'])
        report_error('Auto PK: ' + message)
        QtBind.setText(gui, auto_pk_status_label, message)
        return
    source = ' qua ' + runtime['native_source'] if uid == runtime['native_uid'] else ''
    message = 'Đã khóa UID %d%s · chuẩn bị đánh nhóm %s.' % (uid, source, runtime['page'])
    QtBind.setText(gui, auto_pk_status_label, message)
    log('[%s] Auto PK: %s' % (NAME, message))



def request_auto_pk_arm():
    global auto_pk_running,auto_pk_returning,auto_pk_runtime,auto_pk_anchor,run_section
    try:
        owner,radius,page=read_auto_pk_settings()
        options = read_auto_pk_options()
        key_name = auto_pk_enemy_key_name()
        if not callable(getattr(phbot_api,'move_to',None)):raise ValueError('phBot chưa cung cấp move_to để quay về.')
        sync_pvp_editor()
        if page not in compile_skill_groups({page}, allow_empty=True):raise ValueError('Nhóm %s chưa có skill.'%page)
        anchor = auto_pk_center(current_auto_pk_anchor(), options['centers'], 'attack')
        options['scan_center'] = auto_pk_center(anchor, options['centers'], 'scan')
        options['patrol_center'] = auto_pk_center(anchor, options['centers'], 'patrol')
        if options['patrol_enabled']:
            validate_auto_pk_patrol(dict(options, anchor=anchor, radius=radius))
        buff_error = options.pop('buff_error')
        if options['buffs_enabled'] and not buff_error:
            if not options['buff_ids']:
                buff_error = 'chưa nhập ID buff.'
            else:
                try:
                    known_skills = skill_table()
                except (OSError, RuntimeError, TypeError, ValueError):
                    buff_error = 'chưa đọc được danh sách skill buff.'
                else:
                    if any(uid not in known_skills for uid in options['buff_ids']):
                        buff_error = 'có ID buff chưa học hoặc không đúng nhân vật.'
        disable_buffs = bool(buff_error and options['buffs_enabled'])
        if disable_buffs:
            options.update(buffs_enabled=False, buff_ids=[])
        run_section='pvp'
        set_checked_silent(boss_mode_box, False)
        set_checked_silent(numeric_box, False)
        set_checked_silent(pvp_box,True)
        with pvp_lock:
            if not start_clicked(auto_pk_page=page):
                raise ValueError('Chưa bật được bộ skill PvP; xem Log.')
            auto_pk_anchor = anchor
            auto_pk_runtime = {'owner': owner, 'radius': radius, 'page': page, 'anchor': anchor,
                               'move_at': 0.0, 'scan_at': 0.0, 'requested': 0, 'select_until': 0.0,
                               'native_uid': 0, 'native_key': AUTO_PK_NATIVE_KEYS.get(key_name, 0),
                               'retired': {}, 'dead_uids': set()}
            auto_pk_runtime.update(options)
            auto_pk_running = True
            auto_pk_returning = False
        show_auto_pk_anchor()
        message = 'Đã bật canh %.0f m · nhóm %s.' % (radius,page)
        if buff_error:
            QtBind.setText(gui, auto_pk_buffs_status, 'Bảng buff: ' + buff_error)
        if disable_buffs:
            set_checked_silent(auto_pk_buffs_box, False)
            message += ' Buff đã tắt vì ID lỗi.'
            log('[%s] Auto PK vẫn chạy · bỏ qua bảng buff: %s' % (NAME, buff_error))
        QtBind.setText(gui, auto_pk_status_label, message)
    except (ValueError,TypeError,KeyError,OSError) as error:
        QtBind.setText(gui,auto_pk_status_label,'Chưa bật: '+str(error))


def stop_auto_pk(reason=None):
    if auto_pk_running:
        stop_clicked()
    message = 'AUTO PK ĐÃ TẮT.'
    if reason:
        message += ' Dừng cưỡng chế: ' + reason + '.'
        report_error(message)
    QtBind.setText(gui, auto_pk_status_label, message)
    QtBind.setText(gui, auto_pk_scan_field, 'Tự quét nhận diện khi bật Auto PK.')


def hold_auto_pk(reason, retry_after=0.0):
    global auto_pk_returning
    runtime = auto_pk_runtime
    if runtime.get('hold_reason') == reason:
        return
    auto_pk_returning = True
    pause_pvp('Auto PK chờ: ' + reason, clear_target=True, cancel_action=False, notify=False)
    runtime.pop('withdraw', None)
    runtime.pop('return_progress', None)
    runtime.pop('patrol_destination', None)
    runtime.update(hold_reason=reason, hold_until=monotonic() + retry_after, move_at=0.0)
    message = 'Auto PK đang chờ: ' + reason + ' · sẽ tự canh lại.'
    QtBind.setText(gui, auto_pk_status_label, message)
    report_error(message)


def release_auto_pk_target(uid, reason, retry_delay=AUTO_PK_TARGET_RETRY_DELAY):
    global direct_target, direct_select_request, active_sequence, sequence_index
    runtime = auto_pk_runtime
    if not auto_pk_running or auto_pk_returning or runtime is None:
        return False
    now = monotonic()
    # Retire the UID briefly in case the next inventory of nearby players
    # still contains the entity that just disappeared.
    runtime['retired'][uid] = max(runtime['retired'].get(uid, 0), now + retry_delay)
    runtime.pop('missing_since', None)
    runtime.pop('approach', None)
    runtime.pop('select_in_event', None)
    runtime.pop('target_outside', None)
    runtime.update(requested=0, native_uid=0, select_until=0.0, scan_at=0.0,
                   native_probe_until=0.0, skill_probe_uid=0)
    clear_pending()
    reset_pvp_activation()
    direct_target = direct_select_request = 0
    active_sequence = None
    sequence_index = 0
    message = 'UID %d: %s · dò ngay mục tiêu khác.' % (uid, reason)
    log('[%s] Auto PK: %s' % (NAME, message))
    QtBind.setText(gui, auto_pk_status_label, message)
    return True


def tick_auto_pk(from_event=False):
    global auto_pk_returning
    if not auto_pk_running:return True
    runtime=auto_pk_runtime
    character=get_character_data() or {}
    if not runtime:
        stop_auto_pk(reason='mất trạng thái Auto PK')
        return False
    owner = owner_of(character)
    if owner and owner != runtime['owner']:
        stop_auto_pk(reason='đã đổi nhân vật')
        return False
    if runtime.get('trade_open'):
        return False
    if not owner or not (get_client() or {}).get('running'):
        hold_auto_pk('đang chờ client hoặc dữ liệu nhân vật')
        return False
    if character.get('dead') or get_status():
        hold_auto_pk('nhân vật đã chết' if character.get('dead') else 'bot chính đang chạy')
        return False
    now = monotonic()
    if now < runtime.get('hold_until', 0):
        return False
    if not auto_pk_returning:
        if now < runtime['scan_at'] and not (from_event and runtime.get('select_in_event')):
            return bool(pvp_target and 'missing_since' not in runtime and 'target_outside' not in runtime)
        interval = AUTO_PK_FAST_SCAN_INTERVAL if not pvp_target and runtime.get('fast_scan') else AUTO_PK_SCAN_INTERVAL
        runtime['scan_at'] = now + interval
    position = get_position() or {}
    distance = auto_pk_distance(position, runtime['anchor']) if 'region' in position else None
    if distance is None:
        hold_auto_pk('chưa có tọa độ hợp lệ trong vùng điểm chờ')
        return False
    if runtime.pop('hold_reason', None):
        runtime.update(hold_until=0.0, scan_at=0.0, move_at=0.0)
    if not auto_pk_returning:
        if distance > runtime['radius']:
            force_auto_pk_return(runtime, AUTO_PK_OUTSIDE_SELF)
            return False
        if not pvp_target:
            auto_pk_select(character, runtime, now, from_event=from_event)
            return False
        eligible, reason = auto_pk_radius_check(pvp_target)
        if reason == AUTO_PK_OUTSIDE_SELF:
            force_auto_pk_return(runtime, reason)
            return False
        if reason == AUTO_PK_OUTSIDE_TARGET:
            uid, since = runtime.get('target_outside', (0, now))
            if uid != pvp_target:
                runtime['target_outside'] = (pvp_target, now)
                runtime.pop('missing_since', None)
            elif now - since >= AUTO_PK_TARGET_OUTSIDE_CONFIRM:
                force_auto_pk_return(runtime, reason)
            return False
        runtime.pop('target_outside', None)
        if reason in ('mục tiêu đã chết', AUTO_PK_PROTECTED):
            release_auto_pk_target(pvp_target, reason)
            return False
        active = pvp_armed or pvp_activation is not None
        if eligible and active:
            runtime.pop('missing_since', None)
            return True
        if active and reason == 'tạm thiếu dữ liệu Player':
            # Opposing-faction enemies are frequently omitted from get_players on
            # Stable. Keep the server-confirmed lock; 0x3015/0x3016 still release
            # vanished UIDs. Do not force-return after one second.
            runtime.pop('missing_since', None)
            if now >= runtime.get('missing_notice_at', 0):
                runtime['missing_notice_at'] = now + 5.0
                QtBind.setText(gui, auto_pk_status_label,
                               'Giữ UID %d · Player list thiếu (thường gặp phe địch).' % pvp_target)
            return True
        runtime.pop('missing_since', None)
        if eligible:
            reason = 'chuỗi đánh đã dừng, xem lý do ngay trước dòng này'
        report_error('Auto PK bỏ khóa UID %d: %s.' % (pvp_target, reason))
        pause_pvp('Auto PK: ' + reason, clear_target=True, notify=False)
        auto_pk_returning = True
        QtBind.setText(gui, auto_pk_status_label, 'Dừng đánh · đang quay về điểm bật.')
    if auto_pk_returning:
        withdraw = runtime.get('withdraw')
        if withdraw and not auxiliary_exchange_ready(withdraw):
            if not auto_pk_running:
                return False
            if monotonic() >= withdraw['deadline']:
                runtime.pop('withdraw', None)
                close_client_exchange()
            elif not withdraw['sent']:
                withdraw['sent'] = True
                try:
                    send_pvp_interrupt(withdraw)
                except (OSError, ValueError, RuntimeError):
                    runtime.pop('withdraw', None)
                    close_client_exchange()
                else:
                    return False
            else:
                return False
        move_auto_pk_to_anchor(runtime)
    return False


def force_auto_pk_return(runtime, reason):
    global auto_pk_returning
    if auto_pk_returning:
        return
    auto_pk_returning = True
    runtime.pop('withdraw', None)
    runtime.pop('patrol_destination', None)
    runtime['move_at'] = 0.0
    pause_pvp('Auto PK: ' + reason, clear_target=True, cancel_action=False, notify=False)
    report_error('Auto PK: %s (%.1f m) · quay về điểm bật.' % (reason, runtime['radius']))
    QtBind.setText(gui, auto_pk_status_label, 'Quay về điểm chờ · ' + reason + '.')
    move_auto_pk_to_anchor(runtime)


def move_auto_pk_to_anchor(runtime):
    global auto_pk_returning
    anchor = runtime['anchor']
    position = get_position() or {}
    try:
        region = int(position['region'])
    except (KeyError, TypeError, ValueError, OverflowError):
        return
    if region != anchor['region']:
        hold_auto_pk('nhân vật đang ở khác vùng điểm chờ')
        return
    distance = auto_pk_distance(position, anchor)
    if distance is None:
        return

    now = monotonic()
    progress = runtime.get('return_progress')
    if distance <= min(2, runtime['radius']):
        if progress is None:
            inject_joymax(0x7074, b'\x02', False)
        auto_pk_returning = False
        runtime.pop('withdraw', None)
        runtime.pop('return_progress', None)
        runtime['move_at'] = 0.0
        close_client_exchange()
        report('Auto pk: đã về điểm chờ (cách %.2f m).' % distance)
        QtBind.setText(gui, auto_pk_status_label, 'Đã về điểm chờ · tự canh đối thủ mới.')
        return

    if progress is None:
        progress = runtime['return_progress'] = {
            'distance': distance, 'since': now, 'move_pending': False,
            'short_steps': False, 'step_index': 0,
        }
    elif distance <= progress['distance'] - AUTO_PK_RETURN_MIN_PROGRESS:
        progress.update(distance=distance, since=now, step_index=0)
    elif now - progress['since'] >= AUTO_PK_RETURN_FORCE_AFTER and not progress['short_steps']:
        progress['short_steps'] = True
        log('[%s] Auto PK chưa tiến gần điểm chờ · tiếp tục hủy đánh và quay về bằng bước ngắn.' % NAME)

    if now < runtime['move_at']:
        return
    if not progress['move_pending']:
        # Clear the current action even when Ghost has already dropped its UID.
        inject_joymax(0x7074, b'\x02', False)
        progress['move_pending'] = True
        runtime['move_at'] = now + AUTO_PK_RETURN_CANCEL_GAP
        return

    progress['move_pending'] = False
    runtime['move_at'] = now + AUTO_PK_RETURN_MOVE_INTERVAL
    x, y, z = anchor['x'], anchor['y'], anchor['z']
    if progress['short_steps']:
        start_x, start_y = float(position['x']), float(position['y'])
        angle = math.atan2(y - start_y, x - start_x)
        angle += math.radians((0, 35, -35)[progress['step_index'] % 3])
        step = min(AUTO_PK_RETURN_STEP, distance)
        x = start_x + math.cos(angle) * step
        y = start_y + math.sin(angle) * step
        progress['step_index'] += 1
    try:
        result = phbot_api.move_to(x, y, z)
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        result = False
        report('Auto PK quay về: lỗi move_to: %s.' % error)
    if result is False:
        progress['short_steps'] = True
        message = 'phBot từ chối di chuyển · sẽ thử lại, đang khóa đánh.'
    elif progress['short_steps']:
        message = 'Ép quay về từng bước · còn %.1f m.' % distance
    else:
        message = 'Đang quay về điểm chờ · còn %.1f m.' % distance
    QtBind.setText(gui, auto_pk_status_label, message)
    report('Auto PK quay về x=%.2f y=%.2f · cách %.2f m · API=%r.' % (x, y, distance, result))


def normalize_finder_text(text):
    import unicodedata
    value=str(text or '').casefold().replace('đ','d')
    return ''.join(char for char in unicodedata.normalize('NFD',value)
                   if not unicodedata.combining(char))


def refresh_skill_finder():
    global finder_owner,finder_skills
    finder_owner=owner_of(get_character_data() or {})
    finder_skills=[]
    if finder_owner is not None:
        for uid,skill in (get_skills() or {}).items():
            try:uid=int(uid)
            except (ValueError,TypeError):continue
            if uid<=0 or not isinstance(skill,dict):continue
            name=str(skill.get('name') or skill.get('servername') or '(chưa có tên)')
            finder_skills.append({'id':uid,'name':name,'level':str(skill.get('level','')),
                                  'search':normalize_finder_text('%s %s %s'%(uid,name,skill.get('servername','')))})
        finder_skills.sort(key=lambda row:(normalize_finder_text(row['name']),row['id']))
    search_skill_finder()


def search_skill_finder():
    global finder_matches,finder_offset
    if finder_owner!=owner_of(get_character_data() or {}):
        refresh_skill_finder()
        return
    query=normalize_finder_text(QtBind.text(gui,finder_query_field)).strip()
    terms=query.split()
    finder_matches=[row for row in finder_skills if all(term in row['search'] for term in terms)]
    if query.isdigit():finder_matches.sort(key=lambda row:(str(row['id'])!=query,normalize_finder_text(row['name']),row['id']))
    finder_offset=0
    show_skill_finder()
    message=('%d skill khớp / %d skill của acc. Bấm Copy ID hoặc copy trực tiếp trong ô ID.'%(len(finder_matches),len(finder_skills))
             if finder_owner else 'Chưa có nhân vật vào game; đăng nhập rồi bấm Quét lại.')
    QtBind.setText(gui,finder_status_label,message)


def show_skill_finder():
    global finder_visible_ids
    rows=finder_matches[finder_offset:finder_offset+len(finder_row_fields)]
    finder_visible_ids=[row['id'] for row in rows]
    for index,fields in enumerate(finder_row_fields):
        row=rows[index] if index<len(rows) else {'id':'','name':'','level':''}
        for field,key in zip(fields,('id','name','level')):QtBind.setText(gui,field,str(row[key]))
    count=len(finder_matches)
    first=finder_offset+1 if count else 0
    QtBind.setText(gui,finder_page_label,'%d–%d / %d kết quả'%(first,min(finder_offset+len(finder_row_fields),count),count))


def clear_skill_finder():
    QtBind.setText(gui,finder_query_field,'')
    search_skill_finder()


def finder_previous():
    global finder_offset
    if finder_owner!=owner_of(get_character_data() or {}):refresh_skill_finder();return
    finder_offset=max(0,finder_offset-len(finder_row_fields))
    show_skill_finder()


def finder_next():
    global finder_offset
    if finder_owner!=owner_of(get_character_data() or {}):refresh_skill_finder();return
    if finder_offset+len(finder_row_fields)<len(finder_matches):finder_offset+=len(finder_row_fields)
    show_skill_finder()


def put_finder_clipboard(text):
    """Use Unicode clipboard only on the UI's explicit Copy action."""
    if sys.platform!='win32':return False
    memory=None
    opened=False
    try:
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        ui=ctypes.WinDLL('user32',use_last_error=True)
        kernel.GlobalAlloc.argtypes=[wintypes.UINT,ctypes.c_size_t];kernel.GlobalAlloc.restype=ctypes.c_void_p
        kernel.GlobalLock.argtypes=[ctypes.c_void_p];kernel.GlobalLock.restype=ctypes.c_void_p
        kernel.GlobalUnlock.argtypes=[ctypes.c_void_p];kernel.GlobalUnlock.restype=wintypes.BOOL
        kernel.GlobalFree.argtypes=[ctypes.c_void_p];kernel.GlobalFree.restype=ctypes.c_void_p
        ui.GetActiveWindow.argtypes=[];ui.GetActiveWindow.restype=wintypes.HWND
        ui.GetForegroundWindow.argtypes=[];ui.GetForegroundWindow.restype=wintypes.HWND
        ui.OpenClipboard.argtypes=[wintypes.HWND];ui.OpenClipboard.restype=wintypes.BOOL
        ui.EmptyClipboard.argtypes=[];ui.EmptyClipboard.restype=wintypes.BOOL
        ui.SetClipboardData.argtypes=[wintypes.UINT,ctypes.c_void_p];ui.SetClipboardData.restype=ctypes.c_void_p
        ui.CloseClipboard.argtypes=[];ui.CloseClipboard.restype=wintypes.BOOL
        owner=ui.GetActiveWindow() or ui.GetForegroundWindow()
        if not owner:return False
        data=(str(text)+'\0').encode('utf-16-le')
        memory=kernel.GlobalAlloc(2,len(data))
        if not memory:return False
        pointer=kernel.GlobalLock(memory)
        if not pointer:return False
        ctypes.memmove(pointer,data,len(data));kernel.GlobalUnlock(memory)
        if not ui.OpenClipboard(owner):return False
        opened=True
        if not ui.EmptyClipboard() or not ui.SetClipboardData(13,memory):return False
        memory=None  # Clipboard owns the allocated memory after successful transfer.
        return True
    except Exception:
        return False
    finally:
        if opened:ui.CloseClipboard()
        if memory:kernel.GlobalFree(memory)


def copy_finder_id(index):
    if finder_owner!=owner_of(get_character_data() or {}):
        refresh_skill_finder()
        QtBind.setText(gui,finder_status_label,'Nhân vật đã đổi; đã quét lại. Chọn ID của acc hiện tại.')
        return
    if not 0<=index<len(finder_visible_ids):
        QtBind.setText(gui,finder_status_label,'Dòng này chưa có skill. Nhập tên hoặc ID rồi bấm Tìm.')
        return
    uid=str(finder_visible_ids[index])
    if put_finder_clipboard(uid):
        QtBind.setText(gui,finder_status_label,'Đã copy ID '+uid+'. Dán vào ô ID trong PvP bằng Ctrl+V.')
    else:
        QtBind.setText(gui,finder_status_label,'Chưa copy được. ID '+uid+': chọn ô ID, Ctrl+A rồi Ctrl+C.')


def list_skills_clicked():
    for skill_id, skill in sorted((get_skills() or {}).items()):
        report('Skill ID=%s | %s' % (skill_id, skill.get('name', '')))


def load_hung_vuong_preset():
    known = get_skills() or {}
    if not known:
        report('Hãy vào game bằng acc muốn áp dụng mẫu Hùng Vương.')
        return
    additions = {}
    names = set()
    skipped = []
    for name, delay in HUNG_VUONG_DK_DD:
        normalized = name.casefold()
        matches = [str(skill_id) for skill_id, skill in known.items()
                   if (skill.get('name') or '').strip().casefold() == normalized]
        if len(matches) == 1:
            additions[matches[0]] = delay
            names.add(normalized)
        else:
            skipped.append(name)
    if additions:
        entries = [entry.strip() for entry in QtBind.text(gui, skills_field).partition('/')[0].split(';')
                   if entry.strip() and entry.split('=', 1)[0].strip().casefold() not in names
                   and entry.split('=', 1)[0].strip() not in additions]
        entries.extend('%s=%d' % (skill_id, delay) for skill_id, delay in additions.items())
        QtBind.setText(gui, skills_field, '; '.join(entries))
    report('Mẫu Hùng Vương DK DD: đã điền %d/%d skill PvP. Kiểm tra rồi bấm Lưu cấu hình.' %
           (len(additions), len(HUNG_VUONG_DK_DD)))
    if skipped:
        report('Skill chưa khớp duy nhất trên acc này: ' + ', '.join(skipped))


def parse_direct_order(raw, known_skills, delays):
    sequence, slash, mouse_config = raw.partition('/')
    if slash and mouse_config.strip() and not re.fullmatch(
            r'\s*\d+\s*[xX]\s*\d+\s*/\s*-?\d+\s*,\s*-?\d+\s*/\s*-?\d+\s*,\s*-?\d+\s*/\s*\d+\s*',
            mouse_config):
        raise ValueError('Dãy ID PvP dùng ID hoặc ID=ms, cách nhau bằng dấu phẩy hoặc chấm phẩy.')
    order = []
    inline = {}
    for entry in re.split(r'[;,\s]+', re.sub(r'\s*=\s*', '=', sequence.strip())):
        if not entry:
            continue
        match = re.fullmatch(r'([0-9]+)(?:=([0-9]+))?', entry)
        if not match:
            raise ValueError('Mục %r không hợp lệ. Dùng ID hoặc ID=ms, ví dụ 66007=350.' % entry)
        skill_id = int(match[1])
        if not 0 < skill_id <= 0xffffffff:
            raise ValueError('ID skill phải nằm trong khoảng 1–4294967295.')
        if skill_id not in known_skills:
            raise ValueError('Acc hiện tại chưa có skill ID %d. Dò lại skill trong game.' % skill_id)
        if match[2] is not None:
            delay = int(match[2])
            if not 0 <= delay <= 5000:
                raise ValueError('Skill ID %d cần mốc ngắt từ 0 đến 5000 ms.' % skill_id)
            if skill_id in inline and inline[skill_id] != delay / 1000:
                raise ValueError('Skill ID %d có hai mốc ngắt khác nhau trong Dãy ID PvP.' % skill_id)
            inline[skill_id] = delay / 1000
        order.append(skill_id)
    if not order:
        raise ValueError('Nhập Dãy ID PvP, ví dụ 66007=350; 7653=650.')
    missing = [str(skill_id) for skill_id in dict.fromkeys(order)
               if skill_id not in delays and skill_id not in inline]
    if missing:
        raise ValueError('Thiếu mốc ngắt cho ID %s. Nhập ID=ms ngay trong Dãy ID PvP hoặc ô PvP.' % ', '.join(missing))
    return tuple(order), {**delays, **inline}


def start_pvp(direct=False, exchange_override=None, hybrid=False, auto_pk=False):
    global pvp_delays, exchange_key, pvp_background, pvp_background_error, direct_skills, hybrid_exchange_mode, direct_chain_mode, direct_baseline_mode, direct_native_exchange
    if not user32 or not owner_of(get_character_data() or {}):
        report_error('Ghost PvP cần nhân vật đã vào game trên Windows.')
        return False
    try:
        key = exchange_override or QtBind.text(gui, exchange_field).strip() or '0'
        native=direct and (auto_pk or QtBind.text(gui,id_method_field)==ID_METHOD_NATIVE)
        background_exchange = native
        if (not direct or native) and not hybrid and not background_exchange and (len(key) != 1 or key not in '0123456789'):
            raise ValueError('Nhập phím 0–9 đặt biểu tượng Exchange trên thanh đang dùng.')
        known_skills = get_skills() or {}
        delays = {}
        for entry in QtBind.text(gui, skills_field).partition('/')[0].split(';'):
            if not entry.strip():
                continue
            if '=' not in entry:
                raise ValueError('Mốc ngắt PvP dùng ID=ms hoặc tên=ms; mục lỗi: %s' % entry.strip())
            name, raw_delay = (part.strip() for part in entry.rsplit('=', 1))
            if not name or not re.fullmatch(r'[0-9]+', raw_delay):
                raise ValueError('Mốc ngắt PvP không hợp lệ: %s. Dùng ID=550, không kèm chữ trong số ms.' % entry.strip())
            delay = int(raw_delay)
            if not 0 <= delay <= 5000:
                raise ValueError('Delay phải nằm trong khoảng 0–5000 ms.')
            ids = [int(skill_id) for skill_id, skill in known_skills.items()
                   if str(skill_id) == name or skill.get('name', '').casefold() == name.casefold()]
            if len(ids) != 1:
                raise ValueError('Không xác định được skill %s. Hãy dùng ID trong Log.' % name)
            if ids[0] in delays:
                raise ValueError('Skill bị nhập trùng: %s' % name)
            delays[ids[0]] = delay / 1000
        order = ()
        if direct:
            from_delays = not auto_pk and QtBind.isChecked(gui, pvp_background_box)
            raw_order = '' if from_delays else QtBind.text(gui, direct_field).strip()
            order, delays = parse_direct_order(raw_order or ';'.join(str(skill_id) for skill_id in delays),
                                               {int(skill_id) for skill_id in known_skills}, delays)
        elif not delays:
            raise ValueError('Nhập ít nhất một cặp skill=delay.')
    except ValueError as error:
        message = 'Chưa bật Auto Ghost: %s' % error
        QtBind.setText(gui, status_label, message)
        report_error(message)
        return False

    with pvp_lock:
        stop_pvp()
        pvp_delays = delays
        direct_skills = order
        hybrid_exchange_mode = hybrid
        direct_native_exchange = native
        direct_chain_mode = direct and not auto_pk and QtBind.text(gui,id_method_field) in (ID_METHOD_CHAIN,ID_METHOD_BASELINE)
        direct_baseline_mode = direct_chain_mode and QtBind.text(gui,id_method_field)==ID_METHOD_BASELINE
        exchange_key = ord(key) if (native and not background_exchange) or (not direct and not hybrid) else None
        pvp_background = not direct and QtBind.isChecked(gui, pvp_background_box)
        pvp_background_error = False
    if pvp_background:
        report('PvP bấm nền: chọn trang F trong game trước khi chuyển cửa sổ.')
    if direct and direct_native_exchange:
        report('Auto Ghost nền: skill ID và 7081 trực tiếp. F4 dừng cả khi game ở nền.')
    elif direct and direct_chain_mode:
        if direct_baseline_mode:report('ID ĐỐI CHIẾU: chỉ thử ID kế tiếp sau B074 02 00/02 01 của lượt hiện tại. Đây là mốc đối chiếu, không chứng minh ngắt; không đổi các ms đã lưu.')
        report('ID THỬ: gọi skill bằng ID, không ô số, không Trao đổi. Mốc ID=ms là lúc thử gửi skill kế tiếp; chưa chứng minh ngắt. Chọn người, bấm F1; thử đúng một vòng rồi tạm dừng.')
        report('ID THỬ: dãy đang dùng '+QtBind.text(gui,skills_field)+'. Không tự thay các mốc ms; nếu còn 1 ms, sửa theo cấu hình bạn muốn trước khi Bật.')
    elif direct:
        report('PvP nền ID: chọn người rồi bấm F1 một lần. Chỉ gửi gói skill/Trao đổi; giữ đúng mốc ms, không bấm số và không cần biểu tượng giao dịch ở ô 0.')
    elif hybrid:
        report('PvP nổi: dùng dãy ô số theo nhóm F đã chọn; Trao đổi gửi nền.')
    else:
        report('Ghost PvP đã bật cho %d skill. Dùng đúng trang có ô Exchange.' % len(delays))
    return True


def clear_pending():
    if globals().get('phbot_bridge_pending') is not None:close_phbot_bridge()
    global pending, last_trigger, blocked_until, pvp_cast_deadline, direct_expected, direct_interrupt_request, key_attempt, direct_exchange_wait, direct_chain_cast, direct_chain_transition, direct_chain_count, direct_retry_state
    global natural_cast, direct_recovery_used, pvp_push, pvp_push_action, direct_action_ended
    global pvp_push_recovery_until, pvp_wait_push_until
    with pvp_lock:
        close_client_exchange()
        natural_cast = None
        direct_action_ended = False
        direct_retry_state=None
        direct_missed_skills.clear()
        pvp_push_recovery_until = 0.0
        pvp_push_recovery.clear()
        pvp_wait_push_until = None
        direct_recovery_used = False
        pvp_push = None
        pvp_push_action = None
        direct_chain_cast=direct_chain_transition=None
        direct_chain_count=0
        direct_interrupt_request = None
        if direct_exchange_wait is not None:
            timeout=direct_exchange_wait.get('timeout')
            if timeout is not None:timeout.cancel()
            direct_exchange_wait=None
        key_attempt = None
        if pending is not None:
            pending[1].cancel()
            pending = None
        last_trigger = None
        direct_expected = None
        blocked_until = 0.0
        pvp_cast_deadline = 0.0


def stop_pvp():
    global background_exchange_failed_uid, foreground_slot_retry_at
    global pvp_delays, exchange_key, pvp_cast_deadline, pvp_background, direct_skills, direct_index, direct_target, direct_select_request, direct_blocked_target, direct_chain_mode, direct_baseline_mode, direct_native_exchange
    with pvp_lock:
        background_exchange_failed_uid = 0
        foreground_slot_retry_at = 0.0
        direct_native_exchange=False
        direct_chain_mode=direct_baseline_mode=False
        if pending is None or not pending[2]:
            clear_pending()
        pvp_delays = {}
        direct_skills = ()
        direct_index = direct_target = direct_select_request = direct_blocked_target = 0
        pvp_cast_deadline = 0.0
        exchange_key = None
        pvp_background = False


def parse_boss_interrupt_delays(value):
    delays = {}
    for pair in value.partition('/')[0].split(';'):
        if not pair.strip():
            continue
        try:
            skill_id, delay = map(int, pair.split('='))
        except ValueError:
            raise ValueError('Cấu hình ngắt Boss dùng mẫu ID=ms; ID=ms.') from None
        if skill_id <= 0 or not 0 <= delay <= 5000:
            raise ValueError('ID skill phải dương và độ trễ từ 0 đến 5000 ms.')
        delays[skill_id] = delay / 1000
    if not delays:
        raise ValueError('Nhập ít nhất một ID=ms để dùng phím ngắt Boss.')
    return delays


def target_matches_boss(target, monsters, dialog):
    names, radius = dialog[:2]
    monster = monsters.get(target) or {}
    position = get_position() or {}
    if monster.get('hp', 0) <= 0 or monster.get('region') != position.get('region'):
        return False
    if 'target' in names:
        if not selected_monster_uid or target != selected_monster_uid:
            return False
    elif not names.intersection(str(monster.get(k, '')).strip().casefold()
                                for k in ('name', 'servername', 'model')):
        return False
    try:
        return math.hypot(monster['x'] - position['x'], monster['y'] - position['y']) <= radius
    except (KeyError, TypeError):
        return False


def start_manual_trace():
    global manual_trace
    character = get_character_data() or {}
    owner = owner_of(character)
    player_id = character.get('player_id')
    if not owner or not player_id:
        report('Ghi Ghost tay: cần đăng nhập nhân vật.')
        return
    stop_clicked()
    with pvp_lock:
        check_manual_trace(None)
        manual_trace = {'owner': owner, 'player_id': player_id, 'start': monotonic(), 'count': 0}
        report('GHOST TAY BẮT ĐẦU (20 giây): chọn đối thủ, bấm skill, Trao đổi, rồi skill tiếp theo.')


def start_boss_trace():
    """Observe the same character while another tool performs the working boss ghost."""
    start_packet_trace('boss')


def start_exchange_trace():
    start_packet_trace('exchange')


def start_push_trace():
    start_packet_trace('push')


def start_packet_trace(kind):
    global manual_trace
    exchange = kind == 'exchange'
    push = kind == 'push'
    label = 'Push' if push else '7081' if exchange else 'Boss'
    duration = 60 if exchange or push else 30
    character = get_character_data() or {}
    owner = owner_of(character)
    source = character.get('player_id')
    if not owner or not source:
        report('Ghi %s: cần nhân vật đã vào game trong phBot.' % label)
        return
    if not push:
        stop_clicked()
    from datetime import datetime
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    safe_name = re.sub(r'[^\w.-]+', '_', owner[1])[:60]
    path = Path(get_config_dir()) / ('%s_%sTrace_%s_%s.log' % (NAME, label, safe_name, stamp))
    try:
        stream = path.open('w', encoding='utf-8')
    except OSError as error:
        report_error('Không mở được file ghi %s: %s' % (label, error))
        return
    with pvp_lock:
        check_manual_trace(None)
        manual_trace = {'kind': kind, 'owner': owner, 'player_id': source,
                        'start': monotonic(), 'count': 0, 'duration': duration,
                        'limit': 1000, 'stream': stream, 'path': str(path),
                        'outgoing': set(), 'counts': {}, 'skills': 0,
                        'exchange_uids': set(), 'phase': 'A', 'phases': {'A': {}, 'B': {}}}
        stream.write('%s v%s — %s TRACE\nOwner=%s | Source UID=%d\n'
                     '%d seconds, observer only; outgoing chat excluded.\n'
                     'No encryption flag is provided by the phBot callback.\n' %
                     (NAME, VERSION, label, owner[1], source, duration))
        if exchange:
            stream.write('A = đánh thường. B = sau khi bấm Mốc SROPlus. Giữ cùng skill, mục tiêu và khoảng cách.\n')
        elif push:
            push_trace_note('Cấu hình đo: Reclick=%s | nhịp Reclick=%d ms | dự phòng sau 3 lần=%d ms | chờ B070 khi tắt Reclick=%d ms | 7081 trực tiếp=%s.' %
                            (reclick_enabled, round(reclick_wait * 1000), round(PVP_RECOVERY_AFTER * 1000),
                             round(DIRECT_CAST_WAIT * 1000), direct_native_exchange))
            tick_push_trace()
    if push:
        report('ĐO ĐẨY LÙI 60s: ghi trên nick bị đẩy. Để Ghost của nick này tự đánh; nick kia dùng skill đẩy. Nút đo chỉ ghi log.')
    elif exchange:
        report('GHI 7081 60s: A đánh thường; sau đó bấm Mốc SROPlus và thử cùng skill/mục tiêu bằng SROPlus.')
    else:
        report('GHI BOSS/JOB 30 GIÂY: AutoGhost đã dừng đánh. Tự đánh hoặc dùng SROPlus trên chính acc này.')
    QtBind.setText(gui, trace_status_label, 'Đang ghi %ds · %s' % (duration, path.name))


def mark_exchange_trace():
    with pvp_lock:
        check_manual_trace(owner_of(get_character_data() or {}))
        trace = manual_trace
        if not trace or trace.get('kind') != 'exchange' or trace['phase'] == 'B':
            return
        trace['phase'] = 'B'
        write_trace_line(trace, '--- +%d ms B: thử SROPlus ---' % round((monotonic() - trace['start']) * 1000))


def mark_push_trace():
    with pvp_lock:
        trace = manual_trace
        if trace and trace.get('kind') == 'push':
            trace['suspect_until'] = monotonic() + 10
            push_trace_note('Mốc tay: vừa thấy bị đẩy hoặc đứng yên. Mốc này không phải thời điểm gói server.')
            tick_push_trace()


def stop_packet_trace():
    with pvp_lock:
        if manual_trace and manual_trace.get('kind') in ('exchange', 'push'):
            finish_trace()


def finish_trace():
    global manual_trace
    trace = manual_trace
    manual_trace = None
    if not trace:
        return
    kind = trace.get('kind')
    if kind not in ('boss', 'exchange', 'push'):
        report('GHOST TAY KẾT THÚC: %d dòng gói tin.' % trace['count'])
        return
    label = 'Push' if kind == 'push' else '7081' if kind == 'exchange' else 'GHOST BOSS'
    summary = ('%s KẾT THÚC: %d dòng; %d gói skill của nhân vật. '
               'Opcode C→S: %s. UID Trao đổi: %s. Chưa tự kết luận ngắt thành công.' %
               (label, trace['count'], trace['skills'],
                ', '.join('0x%04X×%d' % (op, trace['counts'][op]) for op in sorted(trace['outgoing'])) or 'không quan sát được',
                ', '.join(map(str, sorted(trace['exchange_uids']))) or 'không quan sát được'))
    if kind == 'exchange':
        for phase, counts in trace['phases'].items():
            summary += '\n%s: %s' % (phase, ', '.join('%s ×%d' % (name, count)
                                                       for name, count in sorted(counts.items())) or 'chưa thấy gói')
        summary += '\nB074 không mang UID skill. Thiếu C→S 7081 chỉ có nghĩa là hook chưa thấy gói.'
    elif kind == 'push':
        summary = 'ĐO ĐẨY LÙI KẾT THÚC: %d lần thấy cờ đẩy; %d lần thấy B070 đánh trả.' % (
            trace.get('push_count', 0), trace.get('resume_count', 0))
        if trace.get('push_at') is not None:
            summary += ' Lần cuối chưa ghi được B070 đánh trả trước khi dừng đo.'
    stream = trace.get('stream')
    saved = False
    if stream:
        try:
            stream.write(summary + '\n')
            stream.flush()
            saved = True
        except OSError as error:
            report_error('Lỗi hoàn tất file đo: %s' % error)
        finally:
            stream.close()
    report(summary)
    QtBind.setText(gui, trace_status_label, '%s · %s' %
                   ('Đã lưu' if saved else 'Ghi chưa hoàn tất', Path(trace['path']).name))


def write_trace_line(trace, message):
    report(message)
    stream = trace.get('stream')
    if stream:
        try:
            stream.write(message + '\n')
            if trace['count'] % 20 == 0:
                stream.flush()
        except OSError as error:
            report_error('Lỗi ghi file trace: %s' % error)
            stream.close()
            trace['stream'] = None


def push_trace_note(message, after_hit=False):
    trace = manual_trace
    if not trace or trace.get('kind') != 'push' or trace['count'] >= trace['limit']:
        return
    now = monotonic()
    if after_hit and trace.get('push_at') is None and now > trace.get('suspect_until', 0):
        return
    trace['count'] += 1
    write_trace_line(trace, '+%d ms %s' % (round((now - trace['start']) * 1000), message))


def push_trace_mark(event, detail=''):
    trace = manual_trace
    if not trace or trace.get('kind') != 'push' or trace.get('push_at') is None:
        return
    marks = trace['push_marks']
    if event not in marks:
        marks[event] = round((monotonic() - trace['push_at']) * 1000)
        push_trace_note('MỐC +%d ms sau đẩy · %s %s' % (marks[event], event, detail))


def finish_push_sample(trace, outcome):
    marks = ', '.join('%s=%d ms' % (key, value) for key, value in trace['push_marks'].items())
    push_trace_note('KẾT QUẢ ĐẨY #%d: %s | %s' %
                    (trace['push_count'], outcome, marks or 'chưa ghi được mốc phục hồi'))
    trace['push_at'] = None


def tick_push_trace():
    trace = manual_trace
    if not trace or trace.get('kind') != 'push':
        return
    now = monotonic()
    if now < trace.get('sample_after', 0.0):
        return
    trace['sample_after'] = now + 0.1
    previous_sample = trace.get('last_sample_at', now)
    trace['last_sample_at'] = now
    if now - previous_sample >= 1.0:
        push_trace_note('Vòng lấy mẫu ngắt quãng %d ms.' % round((now - previous_sample) * 1000))
    client = get_client() or {}
    window = client.get('window')
    if user32 and window and client.get('running'):
        if user32.IsIconic(window):
            focus = 'thu nhỏ'
        elif not user32.IsWindowVisible(window):
            focus = 'ẩn'
        elif user32.GetForegroundWindow() == window:
            focus = 'đang nhận thao tác'
        else:
            focus = 'ở nền'
    else:
        focus = 'không thấy cửa sổ game'
    if focus != trace.get('client_focus'):
        trace['client_focus'] = focus
        push_trace_note('Cửa sổ game: %s.' % focus)
    pushed_at = trace.get('push_at')
    if pushed_at is not None and now - pushed_at >= 10:
        finish_push_sample(trace, 'sau 10s vẫn chưa thấy B070 đánh trả')
        pushed_at = None
    if pushed_at is None and now > trace.get('suspect_until', 0) and 'snapshot' in trace:
        return
    position = get_position() or {}
    if pushed_at is not None and trace.get('move_origin') is not None:
        region, x, y = trace['move_origin']
        px, py = position.get('x'), position.get('y')
        if (position.get('region') == region and isinstance(px, (int, float))
                and isinstance(py, (int, float)) and math.hypot(px - x, py - y) >= 0.25):
            push_trace_mark('tọa độ đổi sau move_to', '(%.2f, %.2f)' % (px, py))
    snapshot = (pvp_armed, pvp_paused, pvp_target, direct_target, current_page,
                direct_expected, pending is not None, direct_exchange_wait is not None,
                pvp_activation is not None, pvp_push is not None, position.get('region'),
                position.get('x'), position.get('y'), natural_cast is not None,
                (direct_exchange_wait or {}).get('transport'))
    if snapshot == trace.get('snapshot'):
        return
    trace['snapshot'] = snapshot
    push_trace_note('Trạng thái Ghost: armed=%s paused=%s target=%s/%s F=%s '
                    'chờ B070=%s chờ ngắt=%s chờ Exchange=%s đổi F=%s chờ áp sát=%s '
                    'tọa độ=(%s,%s,%s) chờ skill tự hết=%s đường ngắt=%s.' % snapshot)
    if pushed_at is not None:
        push_trace_note('Chờ tại mẫu này: khóa=%d ms, B070=%d ms, đợi phản hồi ngắt=%d ms.' %
                        (round(max(0, blocked_until - now) * 1000),
                         round(max(0, pvp_cast_deadline - now) * 1000),
                         round(max(0, (direct_exchange_wait or {}).get('deadline', 0) - now) * 1000)))


def stop_boss_trace():
    with pvp_lock:
        if manual_trace and manual_trace.get('kind') == 'boss':
            finish_trace()


def check_manual_trace(owner):
    if manual_trace and (owner != manual_trace['owner']
                         or monotonic() - manual_trace['start'] >= manual_trace.get('duration', TRACE_DURATION)
                         or manual_trace['count'] >= manual_trace.get('limit', TRACE_MAX_PACKETS)):
        finish_trace()


def trace_manual_packet(outgoing, opcode, data):
    if manual_trace is None:
        return
    with pvp_lock:
        check_manual_trace(owner_of(get_character_data() or {}))
        trace = manual_trace
        if trace is None or trace.get('kind') == 'push':
            return
        boss_trace = trace.get('kind') == 'boss'
        exchange_trace = trace.get('kind') == 'exchange'
        if boss_trace:
            if outgoing:
                # Observe game control actions, never login/authentication or chat.
                if not 0x7000 <= opcode <= 0x70ff or 0x7025 <= opcode <= 0x702f:
                    return
                trace['outgoing'].add(opcode)
                trace['counts'][opcode] = trace['counts'].get(opcode, 0) + 1
            elif opcode not in ({op + 0x4000 for op in trace['outgoing'] if 0x7000 <= op <= 0x70ff}
                                | {0xB005, 0xB006, 0xB034, 0xB045, 0xB060, 0xB061, 0xB063, 0xB070, 0xB071, 0xB074, 0xB081, 0x3080, 0x3085, 0x3088, 0x3864}):
                return
        else:
            allowed = (0x7045, 0x7046, 0x7074, 0x7081) if outgoing else (0xB045, 0xB070, 0xB074, 0xB081)
            if exchange_trace:
                allowed += (0x7034, 0x7084, 0x7158) if outgoing else (0xB034, 0xB084, 0x3085, 0x3088)
            if opcode not in allowed:
                return
            if exchange_trace and outgoing:
                trace['outgoing'].add(opcode)
                trace['counts'][opcode] = trace['counts'].get(opcode, 0) + 1
        if not outgoing and opcode == 0xB070:
            own_cast=len(data)>=11 and struct.unpack_from('<I',data,7)[0]==trace['player_id']
            if not own_cast and not (boss_trace and len(data)<11):return
            if (boss_trace or exchange_trace) and own_cast:trace['skills'] += 1
        elapsed = round((monotonic() - trace['start']) * 1000)
        detail = ''
        if (boss_trace or exchange_trace) and outgoing and opcode == 0x7081 and len(data) == 4:
            uid = struct.unpack('<I', data)[0]
            trace['exchange_uids'].add(uid)
            kind = ('quái' if uid in (get_monsters() or {}) else
                    'NPC' if uid in (get_npcs() or {}) else
                    'bản thân' if uid == trace['player_id'] else 'người/UID không có trong dữ liệu hiện tại')
            detail = ' | Trao đổi UID=%d (%s)' % (uid, kind)
        label = 'GHOST BOSS' if boss_trace else 'GHOST TAY'
        if exchange_trace:
            phase = trace['phase']
            label = '7081/' + phase
            key = ('C→S' if outgoing else 'S→C') + ' %04X' % opcode
            if not outgoing and opcode in (0xB074, 0xB081):
                key += ':' + bytes(data[:8]).hex(' ').upper()
            counts = trace['phases'][phase]
            counts[key] = counts.get(key, 0) + 1
            if outgoing and opcode == 0x7074 and len(data) >= 7 and data[:2] == b'\x01\x04':
                detail = ' | skill ID=%d' % struct.unpack_from('<I', data, 2)[0]
                if len(data) >= 11 and data[6] == 1:
                    detail += ' → UID=%d' % struct.unpack_from('<I', data, 7)[0]
            elif not outgoing and opcode == 0xB070:
                detail = ' | skill ID=%d' % struct.unpack_from('<I', data, 3)[0]
                if len(data) >= 19:
                    detail += ' → UID=%d' % struct.unpack_from('<I', data, 15)[0]
        file_trace = boss_trace or exchange_trace
        packet_data = bytes(data[:96] if file_trace else data).hex(' ').upper()
        if file_trace and len(data) > 96:
            packet_data += ' ... [len=%d]' % len(data)
        message = '%s +%d ms %s 0x%04X: %s%s' % (
            label, elapsed, 'C→S' if outgoing else 'S→C', opcode, packet_data, detail)
        trace['count'] += 1
        write_trace_line(trace, message)
        if trace['count'] >= trace.get('limit', TRACE_MAX_PACKETS):
            finish_trace()


def handle_silkroad(opcode, data):
    if auto_pk_running and opcode in (0x7045, 0x7046, 0x7074) and get_status():
        return True  # Auto PK yields combat and targeting to phBot's main bot.
    if auto_pk_running and opcode == 0x7045:
        with pvp_lock:
            return auto_pk_outgoing_selection(data)
    if auto_pk_running and auto_pk_returning:
        raw=bytes(data or b'')
        withdraw=(auto_pk_runtime or {}).get('withdraw')
        if withdraw and opcode==0x7081 and raw==struct.pack('<I',withdraw['target']):
            withdraw['observed']=True
            report('Auto pk: client đã phát Trao đổi ngắt đuổi; chuyển sang quay về.')
        if opcode==0x7045 or (opcode==0x7074 and raw and raw[0]==1):
            return False  # No new target/attack can restart pursuit during withdrawal.
    observe_numeric_request(opcode, data)
    global selected_monster_uid, hunt_request, direct_target, direct_select_request, direct_index, pvp_selection_request, active_sequence, sequence_index
    global pvp_target, pvp_resume_page
    trace_manual_packet(True, opcode, data)
    observe_hotbar_finder_request(opcode,data)
    if (opcode==0x7074 and pvp_trigger_mode=='manual' and not pvp_armed
            and user32 and user32.GetForegroundWindow()==(get_client() or {}).get('window')
            and user32.GetAsyncKeyState(ord('3')) & 0x8000):
        pvp_gate_tick(get_client() or {},get_character_data() or {})

    track_exchange_probe_target(True, opcode, data)
    observe_exchange_probe(True, opcode, data)
    with pvp_lock:
        emergency = (pvp_activation or {}).get('emergency')
        if emergency and emergency['sent'] and opcode==0x7081 and bytes(data or b'')==struct.pack('<I',emergency['target']):
            emergency['observed'] = True
        auxiliary = auxiliary_exchange()
        if (opcode == 0x7081 and auxiliary and auxiliary.get('transport') == 'client_7081'
                and bytes(data or b'') == struct.pack('<I', auxiliary['target'])):
            auxiliary['observed_request'] = True
    with pvp_lock:
        if direct_exchange_wait is not None and opcode==0x7081 and bytes(data or b'')==struct.pack('<I',direct_exchange_wait['target']):
            direct_exchange_wait['observed_request']=True
            report_direct('quan sát được yêu cầu trao đổi từ luồng client.')
            check_direct_exchange()
    with pvp_lock:
        observe_key_request(opcode, data)
    if opcode == 0x7025 and len(data) >= 4 and data[0] in (1, 4):
        size = struct.unpack_from('<H', data, 2)[0]
        if size == len(data) - 4 and bytes(data[4:]).strip().lower() == b'!skill':
            arm_skill_probe()
            return False
    if opcode == 0x7046:
        cancel_exchange_probe()
        with pvp_lock:
            selected_monster_uid = 0
            hunt_request = None
            if pvp_pause_controls:
                pause_pvp('đã bỏ target', clear_target=True, notify=False)
            elif pvp_trigger_mode:
                clear_pending()
                reset_pvp_activation()
            if direct_skills:
                clear_pending()
                direct_target = direct_index = direct_select_request = 0
        return True
    if opcode == 0x7045 and len(data) == 4:
        cancel_exchange_probe()
        uid = struct.unpack_from('<I', data)[0]
        with pvp_lock:
            if not uid and pvp_pause_controls:
                selected_monster_uid = 0
                hunt_request = None
                pause_pvp('đã bỏ target', clear_target=True, notify=False)
                return True
            if reclick_enabled and key_attempt is not None and uid != selected_monster_uid:
                clear_pending()
                active_sequence = None
                sequence_index = 0
            if pvp_trigger_mode and (get_character_data() or {}).get('dead'):
                return True
            if (pvp_trigger_mode and (uid not in (pvp_target, pvp_selection_request)
                    or (uid == pvp_target and not pvp_armed and pvp_activation is None))):
                # A manual start belongs to the selected UID. A new request
                # invalidates any previously queued start.
                clear_pending()
                if not (pvp_activation and pvp_activation['page'] == PVP_STOP_PAGE):
                    reset_pvp_activation()
                else:
                    pvp_target = 0
                    pvp_resume_page = None
                pvp_selection_request = uid
                report('PvP: nhận chọn UID=%d (0x7045); đợi server xác nhận.' % uid)
            if uid != hunt_request:
                hunt_request = None
                selected_monster_uid = uid
    if direct_skills and opcode == 0x7045 and len(data) == 4:
        with pvp_lock:
            uid = struct.unpack('<I', data)[0]
            if not uid or uid not in (direct_target, direct_select_request):
                clear_pending()
                direct_target = direct_index = 0
                direct_select_request = uid
    return True


def handle_joymax(opcode, data):
    global pending, last_trigger, skill_probe, skill_probe_result, hunt_request, selected_monster_uid, hunt_retry_at, pvp_cast_deadline, direct_target, direct_select_request, direct_expected, direct_log_left, direct_blocked_target
    global pvp_target, pvp_selection_request, pvp_resume_page
    global direct_action_ended
    if opcode == 0xB074:
        raw = bytes(data or b'')
        if raw in (b'\x02\x00', b'\x02\x01'):
            with pvp_lock:
                if direct_native_exchange and pvp_armed and direct_expected is None:
                    direct_action_ended = True
                    if (pending is not None and not pending[2] and natural_cast is None
                            and direct_exchange_wait is None and last_trigger
                            and last_trigger[0][1] == direct_target
                            and auto_pk_in_background(get_client() or {})):
                        pending[1].cancel()
                        pending = None
                context = direct_exchange_wait
                if raw == b'\x02\x01' and context and context.get('auto_background'):
                    context['natural_end'] = True
                    check_direct_exchange()
                emergency = (pvp_activation or {}).get('emergency')
                if raw == b'\x02\x01' and emergency and emergency['target'] == pvp_target:
                    emergency['natural_end'] = True
        observe_natural_end(raw)
    observe_numeric_response(opcode, data)
    trace_manual_packet(False, opcode, data)
    track_exchange_probe_target(False, opcode, data)
    if opcode == 0xB034 and pvp_activation is not None and pvp_activation.get('move'):
        report('%s: phản hồi đổi đồ 0xB034 = %s.' %
               (pvp_activation['page'], bytes(data[:12]).hex(' ').upper()))
    with pvp_lock:
        if opcode == 0xB034:
            observe_gear_reply(data)
        observe_key_confirmation(opcode, data)
        if observe_imbue(opcode, data):
            return True
    if opcode in (0x3015, 0x3016) and len(data) == 4:
        uid = struct.unpack('<I', data)[0]
        with pvp_lock:
            if uid and uid in (pvp_target, pvp_selection_request):
                if release_auto_pk_target(uid, 'mục tiêu đã biến mất'):
                    return True
                if pvp_pause_controls:
                    pause_pvp('target đã biến mất', clear_target=True, cancel_action=False, notify=False)
                else:
                    clear_pending()
                    reset_pvp_activation()
    if opcode == 0xB045 and auto_pk_running:
        with pvp_lock:
            if auto_pk_runtime is not None and not auto_pk_returning:
                auto_pk_select_reply(data)
        return True
    if opcode == 0xB045 and pvp_trigger_mode and (get_character_data() or {}).get('dead'):
        with pvp_lock:
            stop_invalid_native_pvp(get_character_data() or {})
        return True
    if opcode == 0xB045 and data and data[0] != 1 and pvp_trigger_mode:
        with pvp_lock:
            requested = pvp_selection_request
            if requested:
                pvp_selection_request = 0
                queued_start, pvp_resume_page = pvp_resume_page, None
                if direct_select_request == requested:
                    direct_select_request = 0
                message = 'PvP: server từ chối UID=%d (B045 %s). Chọn lại mục tiêu.' % (
                    requested, bytes(data[:12]).hex(' ').upper())
                QtBind.setText(gui, status_label, message)
                if queued_start:
                    report_error(message)
    if opcode == 0xB045 and len(data) >= 5 and data[0] == 1:
        uid = struct.unpack_from('<I', data, 1)[0]
        with pvp_lock:
            if pvp_trigger_mode and uid == pvp_selection_request:
                pvp_selection_request = 0
                queued_start, pvp_resume_page = pvp_resume_page, None
                if pvp_person_target(uid):
                    pvp_target = uid
                    report('PvP: server đã xác nhận target UID=%d (0xB045).' % uid)
                    if pvp_trigger_mode == 'target' and not pvp_paused and pvp_allowed_pages:
                        page = current_page if current_page in pvp_allowed_pages else pvp_allowed_pages[0]
                        request_pvp_page(page)
                    elif (queued_start and queued_start[0] == uid and monotonic() <= queued_start[2]
                          and queued_start[1] in pvp_allowed_pages):
                        request_pvp_page(queued_start[1], physical=True)
                    else:
                        report('Đã chọn UID=%d; đợi bạn bấm F một lần.' % uid)
                else:
                    report('PvP: UID=%d không hợp lệ: quái/NPC, bản thân, đã chết hoặc chưa đọc được dữ liệu quái.' % uid)
            if direct_skills and uid and uid == direct_select_request:
                direct_target = uid
                direct_select_request = 0
                if direct_blocked_target != uid:
                    direct_blocked_target = 0
                direct_log_left = 18
                report('PvP khi chat: server đã xác nhận mục tiêu UID=%s.' % uid)
            if hunt_request is not None and uid == hunt_request:
                selected_monster_uid = uid
                hunt_request = None
                hunt_retry_at = 0.0
                report('AutoGhost đã chọn quái UID=%s.' % uid)
        return True
    observe_exchange_probe(False, opcode, data)
    trade_started = opcode == 0x3085 or (opcode == 0xB081 and data and data[0] == 1)
    if trade_started and (direct_native_exchange or direct_exchange_wait is not None):
        with pvp_lock:
            if auto_pk_running:
                auto_pk_runtime['trade_open'] = True
                hold_auto_pk('giao dịch đang mở')
            else:
                pause_pvp('server đã mở/chấp nhận giao dịch thật; không tự xác nhận đồ')
        return True
    if opcode in (0xB084, 0x3088):
        with pvp_lock:
            if auto_pk_running and (opcode == 0x3088 or data[:1] == b'\x01'):
                auto_pk_runtime.pop('trade_open', None)
            context = direct_exchange_wait
            if context and context.get('closing'):
                if opcode == 0x3088 or data[:1] == b'\x01':
                    context['closed'] = True
                    check_direct_exchange()
                elif data[:1] == b'\x02':
                    pause_pvp('server từ chối đóng giao dịch Ghost')
        return True
    if opcode==0xB074 and bytes(data or b'') in (b'\x02\x00',b'\x02\x01'):
        observe_direct_baseline_end(bytes(data))
    if opcode==0xB081 and direct_exchange_wait is not None:
        with pvp_lock:
            direct_exchange_wait['reply']=bytes(data or b'')
            check_direct_exchange()
        return True
    if opcode in (0xB074, 0xB081):
        with pvp_lock:
            if opcode == 0xB074 and bytes(data or b'') == b'\x02\x00':
                for context in (direct_exchange_wait, auxiliary_exchange()):
                    if not context:
                        continue
                    transport = context.get('transport')
                    if transport == 'phbot_button' and not context.get('posting'):
                        continue
                    if transport == 'client_7081' and not context.get('observed_request'):
                        continue
                    context['cancel_reply'] = bytes(data)
                check_direct_exchange()
            if direct_skills and direct_target:
                report_direct('server 0x%04X: %s.' % (opcode, bytes(data[:8]).hex(' ').upper()))
        return True
    if opcode != 0xB070 or len(data) < 19:
        return True

    with pvp_lock:
        skill_id, source = struct.unpack_from('<II', data, 3)
        target = struct.unpack_from('<I', data, 15)[0]
        if skill_probe is not None:
            probe = skill_probe
            character = get_character_data() or {}
            now = monotonic()
            if (source == character.get('player_id') and owner_of(character) == probe['owner']
                    and user32.GetForegroundWindow() == probe['window'] and now < probe['deadline']):
                held = [digit for digit in '0123456789' if user32.GetAsyncKeyState(ord(digit)) & 0x8000]
                slot = held[0] if len(held) == 1 else (
                    probe['slot'] if not held and now - probe['pressed_at'] <= 2 else None)
                skill = (get_skills() or {}).get(skill_id)
                if slot and skill and (slot, skill_id) not in probe['matches']:
                    probe['matches'].add((slot, skill_id))
                    message = 'Ô %s: %s | ID=%s' % (slot, skill.get('name') or 'Skill', skill_id)
                    skill_probe_results.append((probe['owner'], skill_id, message))
            return True
        if pvp_pause_controls and pvp_paused:
            return True
        if not (pvp_delays or boss_interrupt_delays) or get_status():
            return True
        character = get_character_data() or {}
        owner = owner_of(character)
        if (owner is None or character.get('dead') or source != character.get('player_id')
                or not target or target == source):
            return True
        monsters = get_monsters()
        if monsters is None:
            return True
        now = monotonic()
        is_boss = target in monsters
        if is_boss:
            if (skill_id not in boss_interrupt_delays or settings is None
                    or not target_matches_boss(target, monsters, (settings[1], settings[3]))):
                return True
            delay = boss_interrupt_delays[skill_id]
        else:
            if pvp_trigger_mode and (not pvp_armed or target != pvp_target):
                return True
            if skill_id not in pvp_delays:
                return True
            delay = pvp_delays[skill_id]
        client = get_client() or {}
        window = client.get('window')
        background_pk = not is_boss and auto_pk_in_background(client)
        if (not client.get('running') or (not window and not background_pk)
                or (user32.GetForegroundWindow() != window and (is_boss or (not direct_skills and not pvp_background)))):
            return True

        if direct_skills:
            if data[0] != 1 or is_boss or target != direct_target or direct_expected != (skill_id, target):
                return True
            direct_expected = None
            direct_action_ended = False
            confirm_direct_native_skill(skill_id)
            runtime = auto_pk_runtime if auto_pk_running else None
            if runtime is not None and runtime.get('skill_probe_uid') == target:
                runtime.update(skill_probe_uid=0, target_locked_at=now)
                message = 'Đã khóa UID %d qua B070 · server đã nhận skill %d.' % (target, skill_id)
                QtBind.setText(gui, auto_pk_status_label, message)
                log('[%s] Auto PK: %s' % (NAME, message))
            if not pvp_trigger_mode:delay *= DIRECT_DELAY_FACTOR
            if direct_chain_mode:
                confirm_direct_chain(skill_id,target,owner,now,delay)
                if direct_baseline_mode:delay=DIRECT_BASELINE_END_WAIT
            elif skill_id not in runtime_natural_skills and not background_pk:
                report_direct('nhận 0xB070 skill ID=%d, hẹn ngắt nền sau %d ms.' %
                              (skill_id, round(delay * 1000)))

        if not is_boss and skill_id in runtime_natural_skills:
            begin_natural_cast(skill_id, target, owner)
            return True
        if background_pk and not auto_pk_can_cut_in_background(client, target):
            begin_natural_cast(skill_id, target, owner)
            return True

        signature = (skill_id, target)
        if not direct_skills and last_trigger and last_trigger[0] == signature and now - last_trigger[1] < 0.25:
            return True
        if is_boss and boss_esc_closing:
            return True
        if pending is not None:
            pending[1].cancel()
        ticket = object()
        timer = Timer(delay, queue_interrupt, args=(ticket, owner, source, target, window, client.get('pid'), is_boss))
        timer.daemon = True
        pending = (ticket, timer, is_boss)
        if not is_boss:
            pvp_cast_deadline = 0.0
        last_trigger = (signature, now)
        timer.start()
    return True


def client_size(window):
    rect = wintypes.RECT()
    if user32.GetClientRect(window, ctypes.byref(rect)):
        return rect.right - rect.left, rect.bottom - rect.top
    return None


def capture_exit_clicked():
    schedule_mouse_capture(2, 'nút Thoát')


def capture_ground_clicked():
    schedule_mouse_capture(3, 'điểm đất trống gần nhân vật')


def schedule_mouse_capture(field, label):
    global mouse_capture
    owner = owner_of(get_character_data() or {})
    window = (get_client() or {}).get('window')
    if not user32 or not owner or not window:
        report('Đo tọa độ: cần vào game trước.')
        return
    stop_clicked()
    ticket = (owner, window, field)
    with pvp_lock:
        mouse_capture = ticket
    report('Trong 3 giây: sang game, trỏ chuột vào %s, không click.' % label)
    timer = Timer(3.0, capture_mouse, args=(ticket,))
    timer.daemon = True
    timer.start()


def capture_mouse(ticket):
    global mouse_capture_result
    owner, window, field = ticket
    if ((get_client() or {}).get('window') != window
            or user32.GetForegroundWindow() != window
            or owner_of(get_character_data() or {}) != owner):
        report('Đo tọa độ: hãy chọn đúng cửa sổ game.')
        return
    point = wintypes.POINT()
    size = client_size(window)
    if (size and user32.GetCursorPos(ctypes.byref(point))
            and user32.ScreenToClient(window, ctypes.byref(point))
            and 0 <= point.x < size[0] and 0 <= point.y < size[1]):
        with pvp_lock:
            if mouse_capture is ticket:
                mouse_capture_result = (ticket, '%dx%d' % size, '%d,%d' % (point.x, point.y))
    else:
        report('Đo tọa độ: con trỏ phải nằm trong vùng game.')


def show_mouse_capture(owner):
    global mouse_capture_result
    with pvp_lock:
        result = mouse_capture_result
        mouse_capture_result = None
    if not result:
        return
    ticket, size, position = result
    if ticket is not mouse_capture or ticket[0] != owner:
        return
    fields = [value.strip() for value in QtBind.text(gui, boss_dialog_field).split('/', 4)]
    fields.extend([''] * (5 - len(fields)))
    if fields[1].lower() != size:
        fields[2] = fields[3] = ''
    fields[1] = size
    fields[ticket[2]] = position
    fields[4] = fields[4] or '120'
    QtBind.setText(gui, boss_dialog_field, ' / '.join(fields))
    report('Đã điền %s = %s cho client %s.' %
           ('nút Thoát' if ticket[2] == 2 else 'điểm đất', position, size))


def queue_interrupt(ticket, owner, source, target, window, pid, is_boss):
    with pvp_lock:
        if pending is None or pending[0] is not ticket:return
        fire_interrupt(ticket,owner,source,target,window,pid,is_boss)


def try_boss_focus_interrupt(window, method):
    """Experimental focus loss only; does not assert a server-side cancellation."""
    if not user32 or user32.GetForegroundWindow() != window:
        return False
    key = 0x09 if method == 'Alt+Tab (thử)' else 0x1B
    try:
        user32.keybd_event(0x12, 0, 0, 0)
        try:
            user32.keybd_event(key, 0, 0, 0)
        finally:
            user32.keybd_event(key, 0, 2, 0)
            user32.keybd_event(0x12, 0, 2, 0)
        # No skill keys are sent while focus belongs to another application.
        sleep(0.12)
        moved = user32.GetForegroundWindow() != window
    finally:
        user32.ShowWindow(window, 9)  # SW_RESTORE
        user32.SetForegroundWindow(window)
    restored = user32.GetForegroundWindow() == window
    report('BOSS THỬ %s: rời game=%s; trở lại=%s; chưa kết luận ngắt skill.' %
           (method, 'có' if moved else 'không', 'có' if restored else 'không'))
    return moved and restored


def track_exchange_probe_target(outgoing,opcode,data):
    """Passive selection evidence, including when Ghost is stopped."""
    global exchange_probe_target
    with pvp_lock:
        owner=owner_of(get_character_data() or {})
        raw=bytes(data or b'')
        if outgoing and opcode==0x7045 and len(raw)==4:
            exchange_probe_target=(owner,struct.unpack('<I',raw)[0],False)
        elif outgoing and opcode==0x7046:
            exchange_probe_target=None
        elif not outgoing and opcode==0xB045 and raw:
            if raw[0]!=1:
                exchange_probe_target=None
            elif len(raw)>=5 and exchange_probe_target:
                uid=struct.unpack_from('<I',raw,1)[0]
                if exchange_probe_target[:2]==(owner,uid):
                    exchange_probe_target=(owner,uid,pvp_person_target(uid))
        elif not outgoing and opcode in (0x3015,0x3016) and len(raw)==4 and exchange_probe_target:
            if struct.unpack('<I',raw)[0]==exchange_probe_target[1]:exchange_probe_target=None


def cancel_exchange_probe():
    global exchange_transport_probe
    with pvp_lock:
        exchange_transport_probe = None


def probe_exchange_clicked():
    # Report before any API call/lock: distinguish a missing click from an
    # exception or wait inside the diagnostic. Never claim the send succeeded.
    report('KIỂM TRA GỬI: ĐÃ NHẬN NÚT — v'+VERSION)
    try:
        QtBind.setText(gui,status_label,'Kiểm tra: đã nhận nút; xem Log')
        queue_exchange_probe()
    except Exception as error:
        report('KIỂM TRA GỬI: lỗi chuẩn bị %s: %s; không tự thử lại.'%(type(error).__name__,error))


def queue_exchange_probe():
    """One idle API call in phBot's callback, never a rotation or flag sweep."""
    global exchange_transport_probe
    with pvp_lock:
        if exchange_transport_probe is not None:
            report('KIỂM TRA GỬI: đang có lượt kiểm tra; không gửi thêm.')
            return
        character=get_character_data() or {}
        client=get_client() or {}
        target=(exchange_probe_target[1] if exchange_probe_target and exchange_probe_target[0]==owner_of(character) and exchange_probe_target[2] else 0)
        if (not pvp_person_target(target) or character.get('dead') or get_status()
                or not client.get('running')):
            report('KIỂM TRA GỬI: cần chọn lại người để server xác nhận, nhân vật còn sống, client đang chạy và bot đã dừng.')
            return
        owner=owner_of(character)
        # Preserve only confirmed target evidence. Stop every combat/buff worker.
        report('KIỂM TRA GỬI: target đã xác nhận UID=%d; đang dừng Ghost/tay phép.'%target)
        stop_clicked()
        exchange_transport_probe={'owner':owner,'target':target,'window':client.get('window'),
                                  'pid':client.get('pid'),'state':'queued','deadline':monotonic()+5,
                                  'api':None,'outgoing':0,'responses':[]}
        report('KIỂM TRA GỬI: đã dừng Ghost/tay phép; đợi đứng yên 3 giây rồi gửi đúng 1 yêu cầu từ event_loop. Không bấm skill hoặc đổi target trong lượt này.')
        exchange_transport_probe['ready_at']=monotonic()+3
        QtBind.setText(gui,status_label,'Kiểm tra: chờ 3 giây, không thao tác')


def tick_exchange_transport_probe():
    global exchange_transport_probe
    probe=exchange_transport_probe
    if probe is None:return
    character=get_character_data() or {}
    client=get_client() or {}
    if (owner_of(character)!=probe['owner'] or character.get('dead') or get_status()
            or not client.get('running') or client.get('window')!=probe['window'] or client.get('pid')!=probe['pid']):
        exchange_transport_probe=None
        report('KIỂM TRA GỬI: hủy vì nhân vật/client/trạng thái bot đã đổi; không gửi lại.')
        return
    if probe['state']=='queued' and monotonic()>=probe['ready_at']:
        # Mark before injection: hooks can be synchronous. Use the exact same
        # bytes/flag as v1.3.8, changing only calling context and idle state.
        report('KIỂM TRA GỬI: event_loop đã nhận lượt; chuẩn bị gọi API đúng một lần.')
        QtBind.setText(gui,status_label,'Kiểm tra: đang gửi 1 yêu cầu')
        probe['state']='sent'
        probe['deadline']=monotonic()+2
        packet=struct.pack('<I',probe['target'])
        try:
            probe['api']=inject_joymax(0x7081,packet,False)
            report('KIỂM TRA GỬI: event_loop | UID=%d | 7081=%s | encrypted=False | API=%r | Python=%s | phBot=%s' %
                   (probe['target'],packet.hex(' '),probe['api'],sys.version.split()[0],
                    getattr(phbot_api,'get_version',lambda:'không có API')()))
        except Exception as error:
            exchange_transport_probe=None
            report('KIỂM TRA GỬI: lỗi API '+str(error)+'; không gửi lại.')
            return
    if monotonic()>=probe['deadline']:
        exchange_transport_probe=None
        QtBind.setText(gui,status_label,'Kiểm tra: đã kết thúc; xem Log')
        report('KIỂM TRA GỬI KẾT THÚC: API=%r; gói client quan sát=%d; phản hồi=%s. Không tự bật Ghost, không tự gửi lại. Hook client không bảo đảm quan sát được gói do API tạo.' %
               (probe['api'],probe['outgoing'],', '.join(probe['responses']) or 'không có'))


def observe_exchange_probe(outgoing,opcode,data):
    with pvp_lock:
        probe=exchange_transport_probe
        if probe is None:return
        if outgoing and opcode in (0x7074,0x7021):
            cancel_exchange_probe()
            report('KIỂM TRA GỬI: hủy vì có thao tác skill/di chuyển; không gửi lại.')
            return
        if probe['state']!='sent':return
        raw=bytes(data or b'')
        if outgoing:
            if opcode==0x7081 and raw==struct.pack('<I',probe['target']):probe['outgoing']+=1
            return
        if opcode not in (0xB074,0xB081,0x3085):return
        response='0x%04X:%s'%(opcode,raw[:16].hex(' '))
        if len(probe['responses'])<12:probe['responses'].append(response)
        report('KIỂM TRA GỬI: nhận '+response+'; chỉ ghi nhận, chưa kết luận ngắt skill.')


def confirm_direct_chain(skill_id,target,owner,now,delay):
    global direct_chain_cast,direct_chain_transition,direct_chain_count
    transition=direct_chain_transition
    if transition is not None and (transition['to'],transition['target'],transition['owner'])==(skill_id,target,owner):
        report('ID THỬ: B070 %d -> %d | khoảng xác nhận=%d ms | mốc cài=%d ms | từ lúc gửi skill sau=%d ms. Đây là đo thời gian, chưa kết luận Ghost.' %
               (transition['from'],skill_id,round((now-transition['confirmed_at'])*1000),
                transition['delay_ms'],round((now-transition['request_at'])*1000)))
    direct_chain_transition=None
    direct_chain_count+=1
    direct_chain_cast={'id':skill_id,'target':target,'owner':owner,
                       'confirmed_at':now,'delay_ms':round(delay*1000)}
    if direct_baseline_mode:
        report('ID ĐỐI CHIẾU: xác nhận skill=%d (%d/%d); chờ B074 kết thúc, tối đa 8s; không tự coi chờ hết 8s là thành công.'%(skill_id,direct_chain_count,len(direct_skills)))
    else:
        report('ID THỬ: xác nhận skill=%d (%d/%d); sau %d ms thử gửi ID kế tiếp.' %
               (skill_id,direct_chain_count,len(direct_skills),round(delay*1000)))


def observe_direct_baseline_end(data):
    global pending
    with pvp_lock:
        if not direct_baseline_mode or not direct_chain_mode or direct_expected is not None:return
        cast=direct_chain_cast
        if cast is None or pending is None or pvp_paused or not pvp_armed:return
        character=get_character_data() or {}
        if (character.get('dead') or get_status() or owner_of(character)!=cast['owner']
                or cast['target']!=pvp_target or cast['target']!=direct_target):return
        pending[1].cancel()
        pending=None
        report('ID ĐỐI CHIẾU: B074=%s sau B070 %d ms; dùng làm mốc tham khảo cho ID=%d, chưa kết luận Ghost.'%
               (data.hex(' '),round((monotonic()-cast['confirmed_at'])*1000),cast['id']))
        advance_direct_chain(character)


def advance_direct_chain(character):
    global direct_chain_cast,direct_chain_transition,blocked_until,pvp_cast_deadline
    cast=direct_chain_cast
    if (cast is None or cast['owner']!=owner_of(character) or cast['target']!=direct_target
            or not pvp_armed or pvp_paused):return
    if direct_chain_count>=len(direct_skills):
        pause_pvp('ID THỬ: đã kiểm tra đủ một vòng, chưa kết luận ngắt; gửi Log để đối chiếu',cancel_action=False)
        return
    # No exchange, action-cancel, equipment operation or generated key here.
    # Sending the next request is an experiment, not proof of cancelling a cast.
    direct_chain_transition=dict(cast)
    direct_chain_transition.update({'from':cast['id'],'to':direct_skills[direct_index],
                                    'request_at':monotonic()})
    direct_chain_cast=None
    blocked_until=pvp_cast_deadline=0.0
    rotate_direct(character)


def push_action(opcode, raw, player_id):
    # Decode only the first target entry in the known vSRO layout.
    if opcode == 0xB070 and len(raw) >= 35 and raw[:3] == b'\x01\x02\x30':
        action, target = struct.unpack_from('<II', raw, 11)
        hit = 19
    elif opcode == 0xB071 and len(raw) >= 25 and raw[:1] == b'\x01':
        action, target = struct.unpack_from('<II', raw, 1)
        hit = 9
    else:
        return None
    if (target != player_id or raw[hit] != 1 or not raw[hit + 1] or not raw[hit + 2]
            or struct.unpack_from('<I', raw, hit + 3)[0] != player_id):
        return None
    flags = raw[hit + 7]
    return action if flags & 1 and not flags & 0x8a else None


def observe_push_packet(outgoing, opcode, data):
    global pvp_push, pvp_push_action, pvp_push_recovery_until
    global pvp_wait_push_until
    if opcode not in ((0x7021, 0x7074, 0x7081) if outgoing else (0xB070, 0xB071, 0xB074)):
        return
    with pvp_lock:
        trace = manual_trace if manual_trace and manual_trace.get('kind') == 'push' else None
        live = direct_native_exchange and pvp_trigger_mode and pvp_armed and not pvp_paused
        watch_skill = (live and direct_retry_state is not None
                       and (auto_pk_running or not reclick_enabled or pvp_stunned_character is not None))
        if not trace and (not live or ((outgoing or opcode == 0xB074) and not watch_skill)):
            return
        character = get_character_data() or {}
        player_id = character.get('player_id')
        if not player_id:
            return
        if trace and owner_of(character) != trace['owner']:
            finish_trace()
            trace = None
        raw = bytes(data or b'')
        now = monotonic()
        if watch_skill:
            observe_direct_skill_reply(outgoing, opcode, raw, now)
            attempt = direct_retry_state
            if (auto_pk_running and not outgoing and opcode == 0xB074
                    and raw == PVP_ACTION_REFUSAL and attempt
                    and direct_expected == (attempt['skill'], attempt['target'])
                    and attempt['target'] == pvp_target and now < pvp_cast_deadline
                    and attempt.get('first_reply') == raw and not attempt.get('reply_ambiguous')
                    and not attempt.get('push_rejected')):
                release_auto_pk_target(pvp_target, 'server từ chối đánh (B074)', AUTO_PK_PROTECTION_DELAY)
        action = push_action(opcode, raw, player_id) if not outgoing else None
        if action is not None:
            new_push = live and direct_target == pvp_target and action != pvp_push_action
            if new_push and pvp_wait_push_until:
                # Only the B070 layout identifies the attacker on this path.
                new_push = (now < pvp_wait_push_until and opcode == 0xB070
                            and struct.unpack_from('<I', raw, 7)[0] == direct_target)
                if new_push:
                    pvp_wait_push_until = 0.0
                    direct_missed_skills.clear()
                    push_trace_note('Cú đẩy mới từ đúng mục tiêu; bắt lại nhịp áp sát và thử skill.')
            if new_push:
                pvp_push_action = action
                pvp_push = (pvp_target, now)
                if pvp_target and not reclick_enabled:
                    pvp_push_recovery_until = now + PVP_PUSH_RECOVERY_WINDOW
                    pvp_push_recovery.clear()
                    pvp_push_recovery['hit_at'] = now
            if trace and action != trace.get('push_action'):
                if trace.get('push_at') is not None:
                    finish_push_sample(trace, 'đòn đẩy mới đến trước B070 đánh trả')
                trace['push_action'] = action
                trace['push_at'] = now
                trace['push_marks'] = {}
                trace['push_target'] = direct_target or pvp_target
                trace['move_origin'] = None
                trace['sample_after'] = now
                trace['snapshot'] = None
                trace['push_count'] = trace.get('push_count', 0) + 1
                push_trace_note('ĐẨY LÙI #%d: S→C %04X action=%d | target đang đánh=%d | %s' %
                                (trace['push_count'], opcode, action, trace['push_target'], raw[:96].hex(' ')))
            return
        if not trace:
            return
        if not outgoing and opcode in (0xB070, 0xB071):
            offset = 15 if opcode == 0xB070 else 5
            if len(raw) >= offset + 4 and raw[:1] == b'\x01' and struct.unpack_from('<I', raw, offset)[0] == player_id:
                trace['suspect_until'] = now + 3
                push_trace_note('S→C %04X hướng vào nick đo, chưa nhận diện cờ đẩy | %s' %
                                (opcode, raw[:96].hex(' ')))
        pushed_at = trace.get('push_at')
        if pushed_at is None:
            if outgoing or opcode == 0xB074:
                push_trace_note('%s %04X | %s' % ('C→S' if outgoing else 'S→C', opcode, raw[:64].hex(' ')), after_hit=True)
            return
        if now - pushed_at > 10:
            finish_push_sample(trace, 'sau 10s vẫn chưa thấy B070 đánh trả')
            return
        if not outgoing and opcode == 0xB070 and len(raw) >= 19 and raw[:2] == b'\x01\x02':
            skill, source, _, target = struct.unpack_from('<IIII', raw, 3)
            if (source == player_id and target not in (0, player_id)
                    and trace['push_target'] in (0, target)):
                push_trace_mark('server nhận B070 đánh lại', 'ID=%d UID=%d' % (skill, target))
                trace['resume_count'] = trace.get('resume_count', 0) + 1
                finish_push_sample(trace, 'server đã nhận skill đánh lại')
                return
        if outgoing and opcode == 0x7021:
            push_trace_mark('gói di chuyển C→S')
        if outgoing and opcode == 0x7074 and len(raw) == 11 and raw[:2] == b'\x01\x04' and raw[6] == 1:
            skill = struct.unpack_from('<I', raw, 2)[0]
            push_trace_mark('gói skill C→S', 'ID=%d' % skill)
        if outgoing or opcode == 0xB074:
            push_trace_note('%s %04X sau đẩy +%d ms | %s' %
                            ('C→S' if outgoing else 'S→C', opcode,
                             round((now - pushed_at) * 1000), raw[:64].hex(' ')))


def observe_direct_skill_reply(outgoing, opcode, raw, now):
    global pvp_cast_deadline
    attempt = direct_retry_state
    if (not attempt or direct_expected != (attempt['skill'], attempt['target'])
            or attempt['target'] != pvp_target or pvp_push is not None
            or now >= pvp_cast_deadline or pending is not None or direct_exchange_wait is not None):
        return
    if outgoing and opcode == 0x7074:
        # A competing client action makes the untagged server reply ambiguous.
        if raw != attempt['packet'] or attempt.get('push_packet_seen'):
            attempt['reply_ambiguous'] = True
        else:
            attempt['push_packet_seen'] = True
        return
    if outgoing or opcode != 0xB074:
        return
    if 'first_reply' in attempt:
        attempt['reply_ambiguous'] = True
        return
    attempt['first_reply'] = raw
    if (raw == PVP_ACTION_REFUSAL and attempt.get('push_packet_seen') and not attempt.get('reply_ambiguous')
            and pvp_push_recovery.get('hit_at', now) <= attempt['sent_at'] < now < pvp_push_recovery_until
            and not pvp_push_recovery.get('fast_used') and len(direct_missed_skills) == 1
            and set(direct_skills) - direct_missed_skills.keys() - {attempt['skill']}):
        pvp_push_recovery['fast_used'] = True
        attempt['push_rejected'] = True
        pvp_cast_deadline = now
        push_trace_note('B074 03 00 04 40 sau 7074 ID=%d; thử skill khác sớm.' % attempt['skill'], after_hit=True)


def recover_pvp_push(character, now):
    global pvp_push, direct_recovery_used, direct_expected, direct_retry_state, pvp_cast_deadline
    uid, hit_at = pvp_push
    if (not pvp_armed or pvp_paused or uid != pvp_target or uid != direct_target
            or character.get('dead') or get_status() or now - hit_at > 0.5):
        push_trace_note('Bỏ nhịp áp sát sau %d ms: quá cửa sổ 500 ms hoặc Ghost/target đã đổi.' %
                        round((now - hit_at) * 1000))
        pvp_push = None
        return False
    if pending is not None or direct_exchange_wait is not None:
        push_trace_mark('áp sát bị giữ', 'đợi phản hồi Exchange' if direct_exchange_wait else 'đợi mốc ngắt')
        return False
    if now - hit_at < 0.025:
        return True  # Sample position after phBot handles the hit packet.
    recovery = pvp_push_recovery if now < pvp_push_recovery_until else None
    moved = not auto_pk_running and approach_pvp_target(uid, minimum=4.0, recovery=recovery)
    pvp_push = None
    direct_recovery_used = True
    direct_expected = direct_retry_state = None
    pvp_cast_deadline = now + 0.05 if moved else 0.0
    if moved:
        message = 'Áp sát sau đẩy lùi: gửi lệnh sau %d ms.' % round((now - hit_at) * 1000)
        trace = manual_trace
        if trace and trace.get('kind') == 'push':
            write_trace_line(trace, '+%d ms %s' % (round((now - trace['start']) * 1000), message))
        else:
            report(message)
    else:
        push_trace_note('Không gửi áp sát; trả quyền chọn skill cho Ghost.')
    return moved


def confirm_push_movement():
    move = pvp_push_recovery.get('move')
    if move is None:
        return False
    region, x, y, dx, dy = move
    position = get_position() or {}
    px, py = position.get('x'), position.get('y')
    if (position.get('region') != region or not isinstance(px, (int, float))
            or not isinstance(py, (int, float))):
        return False
    advance = (px - x) * dx + (py - y) * dy
    push_trace_note('Hậu kiểm áp sát: tiến %.2f m theo hướng đã gửi.' % advance, after_hit=True)
    return advance >= 0.25


def approach_pvp_target(uid, minimum=6.0, recovery=None):
    """One short move towards the confirmed target when usable coordinates exist."""
    move = getattr(phbot_api, 'move_to', None)
    read_players = getattr(phbot_api, 'get_players', None)
    if not callable(move) or not callable(read_players) or uid != pvp_target:
        push_trace_note('Áp sát: thiếu API phBot hoặc target đã đổi.', after_hit=True)
        return False
    try:
        players = read_players() or {}
        target = (players.get(uid) or players.get(str(uid))) if isinstance(players, dict) else None
        if not target or target.get('dead'):
            push_trace_note('Áp sát: không đọc được người chơi UID=%d hoặc target đã chết.' % uid, after_hit=True)
            return False
        position = get_position() or {}
        if target.get('region') is not None and int(target['region']) != int(position['region']):
            push_trace_note('Áp sát: target khác vùng.', after_hit=True)
            return False
        x, y = float(position['x']), float(position['y'])
        dx, dy = float(target['x']) - x, float(target['y']) - y
        z = float(position.get('z', 0.0))
        if not all(map(math.isfinite, (x, y, dx, dy, z))):
            push_trace_note('Áp sát: tọa độ không hữu hạn.', after_hit=True)
            return False
        distance = math.hypot(dx, dy)
        if not minimum <= distance <= 20:
            push_trace_note('Áp sát: khoảng cách %.1f m ngoài khoảng %.1f–20 m.' % (distance, minimum), after_hit=True)
            return False
        fraction = (distance - 4.0) / distance
        dest_x, dest_y = x + dx * fraction, y + dy * fraction
        push_trace_mark('gọi move_to', 'cách đối thủ %.1f m' % distance)
        result = move(dest_x, dest_y, z)
        push_trace_note('Áp sát: move_to (%.2f, %.2f, %.2f), cách đối thủ %.2f m, API=%r%s.' %
                        (dest_x, dest_y, z, distance, result, ' · thiếu Z hiện tại' if 'z' not in position else ''),
                        after_hit=True)
        if result is False:
            return False
        if recovery is not None:
            recovery['move'] = position.get('region'), x, y, dx / distance, dy / distance
        trace = manual_trace
        if trace and trace.get('kind') == 'push' and trace.get('push_at') is not None:
            trace['move_origin'] = position.get('region'), x, y
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        push_trace_note('Áp sát: không dùng được tọa độ (%s).' % error, after_hit=True)
        return False
    report('Phục hồi PvP: đã yêu cầu áp sát UID=%d, khoảng cách %.1f m.' % (uid, distance))
    return True


def recover_auto_pk_cast(target, skill_id, reason):
    global direct_expected, direct_retry_state, pvp_cast_deadline
    runtime = auto_pk_runtime
    if (not auto_pk_running or auto_pk_returning or not pvp_armed or runtime is None
            or target != pvp_target or direct_expected != (skill_id, target)
            or runtime.get('skill_probe_uid') == target):
        return False
    runtime.setdefault('skill_retry_at', {})[skill_id] = monotonic() + AUTO_PK_CAST_RETRY_DELAY
    direct_expected = direct_retry_state = None
    pvp_cast_deadline = 0.0
    message = 'Giữ UID %d · %s · xét skill kế tiếp.' % (target, reason)
    QtBind.setText(gui, auto_pk_status_label, message)
    report(message)
    return True


def retry_direct_native_skill(character):
    global pvp_cast_deadline, direct_expected, direct_retry_state, direct_recovery_used
    attempt=direct_retry_state
    if (not attempt or attempt['owner']!=owner_of(character)
            or (attempt['skill'],attempt['target'])!=direct_expected):return
    if attempt['retries'] >= RECLICK_MAX_RETRIES:
        reason = 'chưa có B070 khớp ID=%d sau %d lần thử lại' % (attempt['skill'], RECLICK_MAX_RETRIES)
        if not recover_auto_pk_cast(attempt['target'], attempt['skill'], reason):
            pause_pvp(reason, cancel_action=False)
        return False
    attempt['retries']+=1
    pvp_cast_deadline=monotonic()+reclick_wait
    push_trace_mark('Reclick đầu tiên', 'ID=%d' % attempt['skill'])
    report('Reclick ID: skill=%d, thử lại %d/3.'%(attempt['skill'],attempt['retries']))
    if inject_joymax(0x7074,attempt['packet'],False) is False:
        reason = 'phBot từ chối lần gửi lại'
        if auto_pk_running:
            recover_auto_pk_cast(attempt['target'], attempt['skill'], reason)
        else:
            pause_pvp('PvP ID/ô số: ' + reason + '; không gửi thêm')


def confirm_direct_native_skill(skill_id):
    global direct_retry_state, pvp_first_skill, direct_recovery_used, pvp_push_recovery_until
    global pvp_wait_push_until
    if direct_native_exchange and direct_retry_state is not None:
        if pvp_push_recovery:
            confirm_push_movement()
            pvp_push_recovery.clear()
        direct_missed_skills.clear()
        pvp_wait_push_until = None
        pvp_push_recovery_until = 0.0
        direct_recovery_used = False
        if pvp_first_skill:
            elapsed = round((monotonic() - direct_retry_state.get('sent_at', monotonic())) * 1000)
            report('%s: skill đầu ID=%d đã được server xác nhận sau %d ms.' % (current_page, skill_id, elapsed))
            pvp_first_skill = False
        if direct_retry_state['retries']:
            report('Reclick ID: đã xác nhận skill=%d sau lần thử lại %d/3.'%(skill_id,direct_retry_state['retries']))
        direct_retry_state=None


def begin_native_cut(owner, target, auto_background=False):
    global direct_exchange_wait, blocked_until
    if direct_action_ended:
        blocked_until = monotonic() + PVP_KEY_INTERVAL
        return
    deadline = monotonic() + 2.0
    context = {'owner': owner, 'target': target, 'deadline': deadline,
               'sending': True, 'engine': 'ids', 'transport': 'client_7081',
               'auto_background': auto_background}
    timeout = Timer(2.0, check_direct_exchange)
    timeout.daemon = True
    context['timeout'] = timeout
    direct_exchange_wait = context
    timeout.start()
    try:
        send_pvp_interrupt(context)
    except (OSError, ValueError, RuntimeError) as error:
        if auto_background:
            close_client_exchange()
            wait_for_background_skill_end(owner, target, context, 'Ghost nền: ' + str(error))
        else:
            pause_pvp('7081 trực tiếp: ' + str(error))
        return
    finally:
        context['sending'] = False
    check_direct_exchange()


def begin_direct_exchange(owner,target):
    global direct_exchange_wait
    context={'owner':owner,'target':target,'deadline':monotonic()+2.0,
             'api_result':None,'observed_request':False,'reply':None,'cancel_reply':None,'sending':True,
             'engine':'keys' if hybrid_exchange_mode else 'ids'}
    direct_exchange_wait=context
    timeout=Timer(2.0,check_direct_exchange)
    timeout.daemon=True
    context['timeout']=timeout
    timeout.start()
    try:
        # One bounded transport attempt. The previous encrypted=True route was
        # returning False on this host. Do not cycle flags or retry automatically.
        result=inject_joymax(0x7081,struct.pack('<I',target),False)
        context['api_result']=result
        report('%s: gửi 0x7081 UID=%d, encrypted=False, API=%r; chờ phản hồi, chưa kết luận ngắt.'%('THỬ SỐ NỔI' if hybrid_exchange_mode else 'PvP nền',target,result))
    except Exception as error:
        pause_pvp('lỗi gọi API trao đổi: '+str(error))
        return
    finally:
        context['sending']=False
    check_direct_exchange()


def close_ghost_exchange(opcode, data):
    """Close only a trade opened for the pending skill's exact Exchange UID."""
    context = direct_exchange_wait
    offset = 1 if opcode == 0xB081 else 0
    if (context is None or len(data) < offset + 4
            or struct.unpack_from('<I', data, offset)[0] != context['target']):
        return False
    if context.get('transport') == 'phbot_button':
        if not context.get('posting'):
            return False
    elif not context['observed_request'] and context.get('api_result') is not True:
        return False
    if context.get('closing'):
        return True
    context['closing'] = True
    context['deadline'] = monotonic() + 2.0
    context['timeout'].cancel()
    timeout = Timer(2.0, check_direct_exchange)
    timeout.daemon = True
    context['timeout'] = timeout
    try:
        if inject_joymax(0x7084, b'', False) is False:
            pause_pvp('phBot từ chối gửi lệnh đóng giao dịch Ghost')
        else:
            report('Ngắt skill: đã gửi đóng giao dịch UID=%d, chờ server.' % context['target'])
            if direct_exchange_wait is context:
                timeout.start()
    except Exception as error:
        pause_pvp('lỗi đóng giao dịch Ghost: %s' % error)
    return True


def wait_for_background_skill_end(owner, target, context=None, reason=None):
    global direct_exchange_wait, background_exchange_failed_uid, foreground_slot_retry_at
    global blocked_until, pvp_cast_deadline
    if context is not None:
        context['timeout'].cancel()
        direct_exchange_wait = None
        if context.get('auto_background'):
            background_exchange_failed_uid = target
            log('[%s] Auto PK UID %d: %s. Chờ skill kết thúc để đánh tiếp.' %
                (NAME, target, reason or 'chưa xác nhận ngắt Ghost nền'))
        elif context.get('transport') != 'client_7081':
            foreground_slot_retry_at = monotonic() + 8.0
        report('PvP: %s; đợi hết skill rồi tiếp tục.' % (reason or 'chưa xác nhận Trao đổi'))
    if direct_action_ended:
        pvp_cast_deadline = 0.0
        blocked_until = monotonic() + PVP_KEY_INTERVAL
    elif last_trigger and last_trigger[0][1] == target:
        begin_natural_cast(last_trigger[0][0], target, owner, reason=reason)
    else:
        pause_pvp('không còn lượt skill để chờ kết thúc', cancel_action=False)


def check_direct_exchange():
    global direct_exchange_wait,blocked_until,pvp_cast_deadline,background_exchange_failed_uid
    with pvp_lock:
        context=direct_exchange_wait
        if not context or context.get('sending'):return
        character=get_character_data() or {}
        if context.get('transport') == 'client_7081':
            if stop_invalid_native_pvp(character) or direct_exchange_wait is not context:
                return
        if (owner_of(character)!=context['owner'] or character.get('dead')
                or context['target']!=(pvp_target if context.get('engine')=='keys' else direct_target) or (pvp_trigger_mode and (pvp_paused or not pvp_armed or pvp_target!=context['target']))):
            context['timeout'].cancel()
            direct_exchange_wait=None
            if context.get('transport') == 'client_7081':
                close_client_exchange()
            return
        if context.get('transport') == 'client_7081':
            try:
                if get_status():
                    pause_pvp('bot chính đã bật', cancel_action=False)
                elif client_exchange_confirmed(context):
                    context['timeout'].cancel()
                    direct_exchange_wait = None
                    pvp_cast_deadline = 0.0
                    blocked_until = monotonic() + (0 if auto_pk_running else PVP_KEY_INTERVAL)
                    if background_exchange_failed_uid == context['target']:
                        background_exchange_failed_uid = 0
                    if context.get('auto_background'):
                        target = context['target']
                        message = 'Ghost nền đã ngắt UID %d · xác nhận 7081 và B074 02 00.' % target
                        QtBind.setText(gui, auto_pk_status_label, message)
                        runtime = auto_pk_runtime
                        if runtime is not None and runtime.get('ghost_logged_uid') != target:
                            runtime['ghost_logged_uid'] = target
                            log('[%s] %s' % (NAME, message))
                    else:
                        report_direct('7081 đúng UID và B074 02 00; tiếp tục skill kế.')
                elif context.get('auto_background') and context.get('natural_end'):
                    close_client_exchange()
                    context['timeout'].cancel()
                    direct_exchange_wait = None
                    blocked_until = pvp_cast_deadline = 0.0
                    report_direct('Skill tự kết thúc trong khi đợi ngắt nền.')
                elif monotonic() >= context['deadline']:
                    close_client_exchange()
                    wait_for_background_skill_end(context['owner'], context['target'], context,
                                                  '7081 chưa xác nhận đúng UID và B074 02 00 sau 2 giây')
            except (OSError, ValueError, RuntimeError) as error:
                if context.get('auto_background'):
                    close_client_exchange()
                    wait_for_background_skill_end(context['owner'], context['target'], context,
                                                  'Ghost nền: ' + str(error))
                else:
                    pause_pvp('7081 trực tiếp: ' + str(error))
            return
        if context.get('closing'):
            if context.get('closed') and (context.get('transport') != 'phbot_button' or context.get('invoked')):
                context['timeout'].cancel()
                direct_exchange_wait = None
                blocked_until = monotonic() + PVP_KEY_INTERVAL
                pvp_cast_deadline = 0.0
                report('Ngắt skill: server đã đóng giao dịch, tiếp tục skill kế.')
            elif monotonic() >= context['deadline']:
                pause_pvp('chưa thấy xác nhận đóng giao dịch Ghost sau 2s')
            return
        if context.get('transport')=='phbot_button':
            retry_at = context.get('ui_retry_at')
            if retry_at and retry_at <= monotonic() < context['deadline']:
                context.pop('ui_retry_at')
                context['ui_retried'] = True
                try:
                    queue_phbot_exchange(context)
                except (OSError, ValueError) as error:
                    pause_pvp('Exchange nền phBot: ' + str(error))
                return
            if context.get('invoked') and context.get('cancel_reply') is not None:
                context['timeout'].cancel()
                direct_exchange_wait=None
                blocked_until=monotonic()+PVP_KEY_INTERVAL
                pvp_cast_deadline=0.0
                phbot_bridge_stats['confirmed']+=1
                count=phbot_bridge_stats['confirmed']
                if count==1 or count%20==0:
                    calls=max(1,phbot_bridge_stats['calls'])
                    report('Request Exchange phBot: %d lượt có phản hồi ngắt; gọi nút TB=%d ms, cao nhất=%d ms; tiếp tục xác nhận skill kế.'%(count,round(phbot_bridge_stats['total_ms']/calls),phbot_bridge_stats['max_ms']))
                bridge_detail('Request Exchange phBot: đã có phản hồi kết thúc; tiếp tục skill kế, chờ B070.')
                return
            if monotonic()>=context['deadline']:
                if context.get('auto_background'):
                    close_phbot_bridge()
                    wait_for_background_skill_end(context['owner'], context['target'], context)
                    return
                pause_pvp('Request Exchange phBot: quá 2s; helper_ready=%s, bước=%s, invoked=%s, cancel_reply=%s; không gọi lại'%(phbot_bridge_ready,(phbot_bridge_pending or {}).get('stage','đã trả lời'),context.get('invoked'),context.get('cancel_reply') is not None))
                close_phbot_bridge()
            return
        if context.get('transport')=='native' and context['observed_request'] and context['cancel_reply'] is not None:
            context['timeout'].cancel()
            direct_exchange_wait=None
            # Keep the original keyboard engine's next-request gap. The
            # outgoing exchange proves the configured slot emitted the action,
            # not by itself that the next cast or Ghost succeeded.
            pvp_cast_deadline=0.0
            blocked_until=monotonic()+PVP_KEY_INTERVAL
            report_direct('PvP ID/ô số: đã thấy Trao đổi đúng UID và B074; chờ B070 của ID kế tiếp.')
            return
        if context.get('transport')=='native':
            if monotonic()>=context['deadline']:
                wait_for_background_skill_end(context['owner'], context['target'], context)
            return
        # The user's working capture contains B074 02 00, not B081.
        # A normal action can also finish with B074: never use it to hide an
        # explicitly failed injection unless the outgoing request was observed.
        if context.get('cancel_reply') is not None and (context['api_result'] is not False or context['observed_request']):
            context['timeout'].cancel()
            direct_exchange_wait=None
            blocked_until=pvp_cast_deadline=0.0
            report('PvP nền: thấy B074 02 00 sau yêu cầu trao đổi; thử skill kế tiếp, chờ B070 xác nhận. Chưa kết luận tốc độ Ghost.')
            if context.get('engine')=='keys':rotate(character)
            else:rotate_direct(character)
            return
        reply=context['reply']
        if reply is not None:
            context['timeout'].cancel()
            direct_exchange_wait=None
            report('PvP nền: nhận server 0xB081='+reply.hex(' ')+', API trước đó=%r.'%context['api_result'])
            if not reply or reply[0]!=2:
                pause_pvp('trao đổi đã được chấp nhận hoặc phản hồi chưa hiểu; không tự xác nhận giao dịch')
                return
            # Rejection of an exchange is not itself failure of the cancel trick.
            # Attempt exactly the next skill and require its B070 confirmation.
            blocked_until=pvp_cast_deadline=0.0
            report_direct('server từ chối lời mời; thử nối skill kế tiếp, vẫn phải có B070 xác nhận.')
            if context.get('engine')=='keys':rotate(character)
            else:rotate_direct(character)
            return
        if monotonic()>=context['deadline']:
            context['timeout'].cancel()
            direct_exchange_wait=None
            if context.get('transport')=='native':
                pause_pvp('PvP ID/ô số: sau 2s chưa thấy client gửi Trao đổi; kiểm tra biểu tượng ở ô %s và đóng khung chat, không tự bấm lại'%chr(exchange_key))
                return
            pause_pvp('chưa xác minh gửi/ngắt sau 2s (API=%r, thấy yêu cầu=%s); B074 tự kết thúc không đủ chứng minh ngắt, không tự gửi lặp'%(context['api_result'],context['observed_request']))


def fire_interrupt(ticket, owner, source, target, window, pid, is_boss):
    global pending, blocked_until, direct_blocked_target, boss_esc_closing, boss_esc_count
    with pvp_lock:
        if pending is None or pending[0] is not ticket:
            return
        pending = None
        character = get_character_data() or {}
        client = get_client() or {}
        monsters = get_monsters()
        background_pk = not is_boss and auto_pk_in_background(client)
        if (get_status() or owner_of(character) != owner or character.get('dead')
                or character.get('player_id') != source or monsters is None
                or not client.get('running') or client.get('pid') != pid
                or (client.get('window') != window and not (background_pk and not client.get('window')))):
            return
        if is_boss:
            if (boss_esc_enabled and settings is not None
                    and target_matches_boss(target, monsters, (settings[1], settings[3]))):
                if boss_method in ('Alt+Tab (thử)', 'Alt+Esc (thử)'):
                    try:
                        success = try_boss_focus_interrupt(window, boss_method)
                    except Exception as error:
                        success = False
                        report('Lỗi thử ngắt Boss: %s' % error)
                    if not success:
                        stop_clicked()
                        report('Đã dừng Boss: không chuyển cửa sổ và quay lại được. Chọn game rồi bật thử lại.')
                    else:
                        blocked_until = monotonic() + 0.08
                    return
                if press_key(0x1B, window):
                    boss_esc_closing = True
                    boss_esc_count += 1
                    close_ticket = object()
                    close_timer = Timer(BOSS_ESC_GAP, close_boss_esc,
                                        args=(close_ticket, owner, source, window, pid))
                    close_timer.daemon = True
                    pending = (close_ticket, close_timer, True)
                    if boss_esc_count <= 20:
                        report('BOSS ESC #%d: gửi ESC mở, mục tiêu UID=%d.' % (boss_esc_count, target))
                    close_timer.start()
            elif (boss_interrupt_key is not None and settings is not None
                    and target_matches_boss(target, monsters, (settings[1], settings[3]))
                    and press_key(boss_interrupt_key, window)):
                report('Ghost Boss: đã gửi phím ngắt %s cho UID=%s.' % (chr(boss_interrupt_key), target))
        elif direct_skills:
            if (target == direct_target and target not in monsters and target not in (get_npcs() or {})):
                if background_pk:
                    if (pvp_armed and pvp_target == target and auto_pk_radius_check(target)[0]
                            and auto_pk_can_cut_in_background(client, target)):
                        report('Ghost nền: ngắt UID %d · chờ 7081 và B074.' % target)
                        begin_native_cut(owner, target, auto_background=True)
                    else:
                        wait_for_background_skill_end(owner, target)
                elif direct_native_exchange:
                    begin_native_cut(owner, target)
                elif direct_baseline_mode:
                    pause_pvp('ID ĐỐI CHIẾU: hết 8s chưa thấy B074 kết thúc; không gửi skill tiếp, không gửi hủy',cancel_action=False)
                elif direct_chain_mode:advance_direct_chain(character)
                else:begin_direct_exchange(owner,target)
        elif hybrid_exchange_mode:
            if (target == pvp_target and pvp_armed and target not in monsters
                    and target not in (get_npcs() or {})):
                begin_direct_exchange(owner,target)
        elif (target not in monsters and (not pvp_trigger_mode or (pvp_armed and target == pvp_target))
              and exchange_key is not None and press_pvp_key(exchange_key, client)):
            blocked_until = monotonic() + PVP_KEY_INTERVAL


def disconnected():
    global profile_owner
    teleported()
    if auto_pk_running:
        stop_auto_pk(reason='mất kết nối game')
    else:
        stop_clicked()
    profile_owner = None


def teleported():
    global exchange_probe_target, numeric_selection
    exchange_probe_target=None
    numeric_selection = (None, 0)
    cancel_exchange_probe()
    global current_page, active_sequence, selected_monster_uid, skill_probe, skill_probe_result, hunt_request, hunt_retry_at, mouse_capture, mouse_capture_result, direct_target, direct_select_request, direct_index, direct_blocked_target, manual_trace
    with pvp_lock:
        check_manual_trace(None)
        reset_pvp_activation()
        direct_target = direct_select_request = direct_index = direct_blocked_target = 0
        skill_probe = skill_probe_result = None
        mouse_capture = mouse_capture_result = None
        selected_monster_uid = 0
        hunt_request = None
        hunt_retry_at = 0.0
        clear_pending()
    current_page = None
    active_sequence = None


def finished():
    with pvp_lock:
        stop_hunt_worker()
    teleported()
    stop_pvp()


def numeric_mode_changed(checked):
    if ui_sync:
        return
    if checked:
        set_checked_silent(pvp_box, False)
        set_checked_silent(boss_mode_box, False)
        start_clicked()
        if not numeric_running:
            set_checked_silent(numeric_box, False)
            QtBind.setText(gui, status_label, 'Auto số chưa bật được. Xem nguyên nhân trong Log.')
    elif numeric_running:
        stop_clicked()


def start_numeric_sequence():
    global numeric_running, numeric_sequence, numeric_index, numeric_next_at, numeric_post_error
    global numeric_page, numeric_held_pages, numeric_start_pending, numeric_bg_check
    global settings, imbue_id, runtime_imbue_early, hunt_stop
    sequence = parse_keys(QtBind.text(gui, numeric_keys_field))
    if not sequence:
        raise ValueError('Auto ô số: nhập dãy số dùng chung.')
    if numeric_interval() is None:
        return
    if get_status():
        raise ValueError('Dừng bot chính trước khi bật Auto ô số.')
    client = get_client() or {}
    if not client.get('running') or not client.get('window') or not owner_of(get_character_data() or {}):
        raise ValueError('Auto số nền: mở cửa sổ game và vào nhân vật trước.')
    early = float(QtBind.text(gui, imbue_early_field) or '0.8')
    if not 0 <= early <= 10:
        raise ValueError('Làm mới tay phép sớm cần từ 0 đến 10 giây.')
    imbue_id = configured_imbue()
    runtime_imbue_early = early
    numeric_sequence = sequence
    numeric_index = 0
    numeric_next_at = 0.0
    numeric_post_error = False
    numeric_page = None
    numeric_held_pages = set()
    numeric_start_pending = True
    numeric_bg_check = None
    settings = ({}, set(), (), 0)
    numeric_running = True
    hunt_stop = Event()
    Thread(target=hunt_worker, args=(hunt_stop,), daemon=True).start()
    QtBind.setText(gui, status_label, 'Auto số nền: vào game chọn mục tiêu. Mặc định bắt đầu ở F1.')
    report('Auto số nền: dãy %s theo nhịp ms đã cài. Chọn mục tiêu trong game để bắt đầu ở F1, hoặc bấm F2/F3. F4 tạm dừng.' % ''.join(sequence))


def tick_numeric(character):
    global numeric_index, numeric_next_at, numeric_post_error
    global numeric_page, numeric_held_pages, numeric_start_pending, numeric_bg_check
    sequence = numeric_sequence
    if not numeric_running or not sequence or character.get('dead') or get_status():
        return
    client = get_client() or {}
    window = client.get('window')
    if not user32 or not window or not client.get('running'):
        return
    held = {page for page, key in zip(PAGES, PAGE_KEYS)
            if user32.GetAsyncKeyState(key) & 0x8000}
    fresh = held - numeric_held_pages
    numeric_held_pages = held
    foreground = user32.GetForegroundWindow() == window
    if PVP_STOP_PAGE in fresh:
        numeric_page = None
        numeric_start_pending = False
        QtBind.setText(gui, status_label, 'Auto số nền: F4 tạm dừng. Bấm F1–F3 để chạy tiếp.')
        return
    if foreground:
        numeric_bg_check = None
        if any(user32.GetAsyncKeyState(key) & 0x8000 for key in (0x10, 0x11, 0x12)):
            return
        if len(fresh) == 1:
            page = next(iter(fresh))
            if page != numeric_page:
                numeric_start_pending = False
                numeric_page = page
                numeric_index = 0
                # Let the client process the physical F key before posting a digit.
                numeric_next_at = max(numeric_next_at, monotonic() + 0.03)
                QtBind.setText(gui, status_label, 'Auto số nền: %s đang bật. F4 tạm dừng.' % page)
    owner, target = numeric_selection
    if owner != owner_of(character) or not target or target == character.get('player_id') or target in (get_npcs() or {}):
        return
    now = monotonic()
    if numeric_start_pending and foreground:
        if press_key(PAGE_KEYS[0], window):
            numeric_page = 'F1'
            numeric_start_pending = False
            numeric_next_at = now + 0.03
            QtBind.setText(gui, status_label, 'Auto số nền: F1 đang bật. F4 tạm dừng.')
        return
    if numeric_page is None or tick_imbue(character):
        return
    if now < max(blocked_until, numeric_next_at):
        return
    interval = numeric_interval()
    if interval is None:
        return
    numeric_next_at = now + interval
    key = ord(sequence[numeric_index])
    if foreground:
        if press_key(key, window):
            numeric_index = (numeric_index + 1) % len(sequence)
        return
    if post_game_key(key, window):
        numeric_index = (numeric_index + 1) % len(sequence)
        numeric_post_error = False
        if numeric_bg_check is None:
            numeric_bg_check = now + 5.0
        elif numeric_bg_check and now >= numeric_bg_check:
            numeric_bg_check = 0.0
            report_error('Auto số nền: đã gửi phím 5 giây nhưng chưa thấy game phát lệnh đánh mục tiêu. Kiểm tra skill ở các ô số, khoảng cách và thử lại khi game ở phía trước.')
    elif not numeric_post_error:
        numeric_post_error = True
        report_error('Auto ô số nền: chưa gửi được phím tới cửa sổ game. Kiểm tra client còn mở.')


def observe_numeric_request(opcode, data):
    global numeric_selection, numeric_bg_check
    if opcode in (0x7045, 0x7046):
        numeric_selection = (None, 0)
    elif numeric_running and numeric_bg_check and opcode == 0x7074:
        raw = bytes(data or b'')
        target = numeric_selection[1]
        if (target and len(raw) >= 11 and raw[:2] == b'\x01\x04' and raw[6] == 1
                and struct.unpack_from('<I', raw, 7)[0] == target):
            numeric_bg_check = 0.0
            report('Auto số nền: đã thấy game phát lệnh skill tới mục tiêu đang chọn.')


def observe_numeric_response(opcode, data):
    global numeric_selection, numeric_index
    if opcode == 0xB045 and data:
        target = struct.unpack_from('<I', data, 1)[0] if data[0] == 1 and len(data) >= 5 else 0
        numeric_selection = (owner_of(get_character_data() or {}), target)
        numeric_index = 0
    elif opcode in (0x3015, 0x3016) and len(data) == 4 and struct.unpack('<I', data)[0] == numeric_selection[1]:
        numeric_selection = (None, 0)


def begin_natural_cast(skill_id, target, owner, reason=None):
    global pending, natural_cast, pvp_cast_deadline
    if pending is not None:
        pending[1].cancel()
    ticket = object()
    data = skill_table().get(skill_id) or {}
    timeout_seconds = max(10.0, float(data.get('cast_time') or 0) / 1000 + 5)
    timer = Timer(timeout_seconds, natural_cast_timeout, args=(ticket,))
    timer.daemon = True
    pending = (ticket, timer, False)
    natural_cast = {'ticket': ticket, 'owner': owner, 'target': target,
                    'skill': skill_id, 'page': current_page, 'reason': reason}
    pvp_cast_deadline = 0.0
    if reason:
        QtBind.setText(gui, status_label, 'ID %d: đang chờ skill kết thúc để tự đánh tiếp.' % skill_id)
    report('Skill ID=%d: chờ server báo kết thúc.' % skill_id)
    timer.start()


def natural_cast_timeout(ticket):
    with pvp_lock:
        if natural_cast and natural_cast['ticket'] is ticket:
            reason = natural_cast.get('reason')
            message = 'chưa nhận kết thúc skill ID=%d từ server' % natural_cast['skill']
            pause_pvp('%s; %s' % (reason, message) if reason else message, cancel_action=False)


def observe_natural_end(data):
    global pending, natural_cast, blocked_until, pvp_cast_deadline
    if data not in (b'\x02\x00', b'\x02\x01'):
        return
    with pvp_lock:
        cast = natural_cast
        if (not cast or pending is None or pending[0] is not cast['ticket']
                or owner_of(get_character_data() or {}) != cast['owner']
                or cast['target'] != pvp_target or cast['page'] != current_page
                or pvp_paused or not pvp_armed):
            return
        pending[1].cancel()
        pending = None
        natural_cast = None
        blocked_until = pvp_cast_deadline = 0.0
        if cast.get('reason'):
            QtBind.setText(gui, status_label, '%s đang đánh.' % current_page)
        report('Skill ID=%d: server đã báo kết thúc; chuyển skill kế tiếp.' % cast['skill'])


# The editor stores every row, including rows outside the current five-row page.
PVP_MODE_KEYS = 'Ô số nổi / Trao đổi'
PVP_MODE_IDS = 'Skill ID nền'
PVP_MODE_FLOAT = 'PvP nổi'
skill_rows = []
skill_row_offset = dict.fromkeys(PVP_EDIT_PAGES, 0)
skill_row_selected = dict.fromkeys(PVP_EDIT_PAGES)
runtime_skill_groups = {}
applied_skill_group = None
runtime_imbue_early = 0.8
runtime_natural_skills = set()
natural_cast = None
numeric_running = False
numeric_sequence = ()
numeric_selection = (None, 0)
numeric_next_at = 0.0
numeric_index = 0
numeric_interval_error = None
numeric_post_error = False
numeric_page = None
numeric_held_pages = set()
numeric_start_pending = False
numeric_bg_check = None


def numeric_interval():
    global numeric_interval_error
    raw = QtBind.text(gui, numeric_ms_field).strip()
    try:
        value = int(raw)
        if not 10 <= value <= 5000:
            raise ValueError()
    except ValueError:
        if numeric_interval_error != raw:
            report_error('Auto ô số: nhịp cần từ 10 đến 5000 ms.')
            numeric_interval_error = raw
        return None
    numeric_interval_error = None
    return value / 1000.0


def skill_cut_changed(checked):
    pass  # Settings are applied on Start, alongside the other row fields.


def page_skill_rows(page):
    return [row for row in skill_rows if row['page'] == page]


def replace_page_skill_rows(page, rows):
    # Keep the legacy rank field so existing profile readers retain the order.
    for index, row in enumerate(rows, 1):
        if row.get('stt', ''):
            row['stt'] = str(index)
    skill_rows[:] = [row for row in skill_rows if row['page'] != page] + rows


def sync_skill_rows():
    for page, fields in skill_row_fields.items():
        rows = page_skill_rows(page)
        start = skill_row_offset[page]
        for i, (skill, delay, cut, selected) in enumerate(fields, start):
            uid = QtBind.text(gui, skill).strip()
            ms = QtBind.text(gui, delay).strip()
            if i >= len(rows) and not (uid or ms):
                continue
            while len(rows) <= i:
                rows.append({'page': page, 'id': '', 'ms': '', 'cut': True, 'stt': ''})
            previous = rows[i]
            enabled = bool(previous.get('stt')) or uid != previous['id'] or ms != previous['ms']
            rows[i] = dict(page=page, id=uid, ms=ms, cut=QtBind.isChecked(gui, cut),
                           disabled=bool(uid) and QtBind.isChecked(gui, selected),
                           stt=str(i + 1) if uid and enabled else '')
        while rows and not (rows[-1]['id'] or rows[-1]['ms']):
            rows.pop()
        replace_page_skill_rows(page, rows)


def show_skill_rows():
    for page, fields in skill_row_fields.items():
        rows = page_skill_rows(page)
        start = skill_row_offset[page]
        for i, (skill, delay, cut, selected) in enumerate(fields, start):
            row = rows[i] if i < len(rows) else {}
            QtBind.setText(gui, skill, row.get('id', ''))
            QtBind.setText(gui, delay, row.get('ms', ''))
            QtBind.setChecked(gui, cut, row.get('cut', True))
            set_checked_silent(selected, row.get('disabled', False))
        QtBind.setText(gui, skill_row_labels[page], '%d–%d' % (start + 1, start + len(fields)))


def select_skill_row(page, row, checked):
    if ui_sync:
        return
    index = skill_row_offset[page] + row
    fields = skill_row_fields[page]
    if not QtBind.text(gui, fields[row][0]).strip():
        set_checked_silent(fields[row][3], False)
        return
    if checked:
        skill_row_selected[page] = index
    elif skill_row_selected[page] == index:
        skill_row_selected[page] = next((skill_row_offset[page] + i for i, (_, _, _, box) in enumerate(fields)
                                        if QtBind.isChecked(gui, box)), None)
    with pvp_lock:
        sync_skill_rows()
        if pvp_trigger_mode and direct_skills and page in pvp_allowed_pages:
            try:
                runtime_skill_groups[page] = compile_skill_groups({page}, allow_empty=True).get(page)
            except ValueError as error:
                report_error('Chưa áp dụng thay đổi %s: %s' % (page, error))


def move_selected_skill_row(page, direction):
    index = skill_row_selected[page]
    if index is None:
        index = next((skill_row_offset[page] + i for i, (_, _, _, box) in enumerate(skill_row_fields[page])
                      if QtBind.isChecked(gui, box)), None)
    if index is None:
        report('Tích một dòng skill ở bảng %s để dùng Lên/Xuống.' % page)
        return
    move_skill_row(page, index - skill_row_offset[page], direction)


def shift_skill_table(page, direction):
    sync_skill_rows()
    size = len(skill_row_fields[page])
    offset = skill_row_offset[page]
    if direction > 0 and not any(row['id'] for row in page_skill_rows(page)[offset:offset + size]):
        return
    new_offset = max(0, offset + direction * size)
    if new_offset != offset:
        skill_row_selected[page] = None
    skill_row_offset[page] = new_offset
    show_skill_rows()


def move_skill_row(page, index, direction):
    sync_skill_rows()
    rows = page_skill_rows(page)
    index += skill_row_offset[page]
    destination = index + direction
    if 0 <= index < len(rows) and 0 <= destination < len(rows) and rows[index]['id']:
        rows[index], rows[destination] = rows[destination], rows[index]
        replace_page_skill_rows(page, rows)
        size = len(skill_row_fields[page])
        skill_row_offset[page] = destination // size * size
        skill_row_selected[page] = destination
    show_skill_rows()


def sync_pvp_editor():
    sync_skill_rows()
    mode = QtBind.text(gui, pvp_mode_field)
    set_checked_silent(pvp_background_box, True)
    set_checked_silent(hybrid_box, False)
    set_checked_silent(legacy_box, False)
    set_checked_silent(direct_box, False)
    QtBind.setText(gui, id_method_field, ID_METHOD_NATIVE)


def pvp_exchange_slot():
    key = QtBind.text(gui, exchange_field).strip() or '0'
    if len(key) != 1 or key not in '0123456789':
        raise ValueError('Nhập một ô Trao đổi chung từ 0–9 cho F1–F3.')
    return key


def pvp_page_changed(page, checked):
    global pvp_allowed_pages
    if page not in PVP_EDIT_PAGES or ui_sync or not pvp_trigger_mode or auto_pk_running or not QtBind.isChecked(gui, pvp_box):
        return
    with pvp_lock:
        if checked:
            try:
                sync_skill_rows()
                group = compile_skill_groups({page}, allow_empty=True).get(page)
                key = None
            except (ValueError, KeyError) as error:
                set_checked_silent(pvp_page_boxes[page], False)
                report(str(error))
                return
            runtime_skill_groups[page] = group
            pvp_page_exchanges[page] = key
            enabled = set(pvp_allowed_pages) | {page}
            pvp_allowed_pages = tuple(p for p in PAGES if p in enabled)
            report('Ghost PvP: đã bật nhóm %s.' % page)
        else:
            pvp_allowed_pages = tuple(p for p in pvp_allowed_pages if p != page)
            if current_page == page or (pvp_activation or {}).get('page') == page:
                pause_pvp('đã tắt nhóm %s' % page, notify=False)


def compile_skill_groups(enabled_pages=None, allow_empty=False):
    groups = {}
    known = set(skill_table())
    ranks = {}
    ranked_rows = []
    for index, row in enumerate(skill_rows):
        if enabled_pages is not None and row['page'] not in enabled_pages:
            continue
        if row.get('disabled') or (not row['id'] and not row['ms']):
            continue
        raw = str(row.get('stt', index + 1)).strip()
        if not raw:
            continue
        if not raw.isdigit() or int(raw) < 1:
            raise ValueError('STT phải lớn hơn 0; để trống để tắt skill.')
        key = (row['page'], int(raw))
        if key in ranks:
            raise ValueError('%s bị trùng STT %s.' % (row['page'], raw))
        ranks[key] = True
        ranked_rows.append((int(raw), index, row))
    for rank, _, row in sorted(ranked_rows, key=lambda item: item[:2]):
        if not row['id'] and not row['ms']:
            continue
        if row['page'] not in PAGES:
            raise ValueError('Mỗi hàng skill phải chọn nhóm F1–F4.')
        cut = row.get('cut', True)
        ids = [part.strip() for part in row['id'].split('+')]
        if not 1 <= len(ids) <= 2 or any(not part.isdigit() for part in ids):
            raise ValueError('Ô ID dùng một ID hoặc hai ID dạng 123+345.')
        ms = [part.strip() for part in row['ms'].split('+')] if cut else ['0']
        if len(ms) == 1:
            ms *= len(ids)
        if len(ms) != len(ids):
            raise ValueError('Dùng một số ms chung hoặc đúng một số cho mỗi ID, ví dụ 20+35.')
        page = groups.setdefault(row['page'], {'order': [], 'delays': {}, 'natural': set(), 'ranks': []})
        for position, (skill, delay) in enumerate(zip(ids, ms)):
            expression = skill + ('=' + delay if delay else '')
            order, delays = parse_direct_order(expression, known, {})
            uid = order[0]
            if uid in page['delays'] and page['delays'][uid] != delays[uid]:
                raise ValueError('%s: ID %d có hai mốc ngắt khác nhau.' % (row['page'], uid))
            if uid in page['delays'] and ((uid in page['natural']) == cut):
                raise ValueError('%s: cùng ID không được vừa ngắt vừa không ngắt.' % row['page'])
            if not cut:
                page['natural'].add(uid)
            page['order'].append(uid)
            page['ranks'].append((rank, position))
            page['delays'].update(delays)
    if not groups and not allow_empty:
        raise ValueError('Chưa có skill được bật. Bỏ tích Tắt hoặc nhập ID ở nhóm F muốn dùng.')
    return groups


def use_skill_group(page, runtime=False, index=0):
    global pvp_delays, direct_skills, direct_index, runtime_natural_skills, applied_skill_group
    group = runtime_skill_groups.get(page)
    if runtime:
        applied_skill_group = group
        pvp_delays = dict(group['delays']) if group else {}
        runtime_natural_skills = set(group['natural']) if group else set()
        if direct_skills and group:
            direct_skills = tuple(group['order'])
            direct_index = index
        return
    if not group:
        raise ValueError('%s chưa có hàng skill ID.' % page)
    runtime_natural_skills = set(group['natural'])
    QtBind.setText(gui, skills_field, ';'.join('%d=%d' % (uid, round(group['delays'][uid]*1000))
                                             for uid in dict.fromkeys(group['order'])))
    QtBind.setText(gui, direct_field, ';'.join(str(uid) for uid in group['order']))


def apply_skill_row_changes():
    if current_page not in runtime_skill_groups:
        return True
    group = runtime_skill_groups[current_page]
    if group is not applied_skill_group:
        next_rank = applied_skill_group['ranks'][direct_index] if applied_skill_group else (1, 0)
        index = next((i for i, rank in enumerate(group['ranks']) if rank >= next_rank), 0) if group else 0
        use_skill_group(current_page, runtime=True, index=index)
    return group is not None


def load_pvp_editor(profile):
    global skill_rows, skill_row_offset
    if isinstance(profile.get('skill_rows'), list):
        skill_rows = [{'stt': str(row.get('stt', index + 1)), 'id': str(row.get('id', '')),
                       'page': str(row.get('page', 'F1')), 'ms': str(row.get('ms', '')),
                       'cut': row.get('cut', True) is not False, 'disabled': row.get('disabled') is True}
                      for index, row in enumerate(profile['skill_rows']) if isinstance(row, dict)]
    else:
        # Resolve old named delays only when this character has a unique matching skill.
        known = skill_table()
        delays = {}
        for entry in str(profile.get('skills', '')).partition('/')[0].split(';'):
            if not entry.strip() or '=' not in entry:
                continue
            name, ms = (part.strip() for part in entry.rsplit('=', 1))
            matches = [str(uid) for uid, data in known.items() if data.get('name', '').casefold() == name.casefold()]
            uid = name if name.isdigit() or len(matches) != 1 else matches[0]
            delays[uid] = ms
        direct = profile.get('pvp_background') or profile.get('packet_f1') or profile.get('direct_pvp')
        pages = ['F1'] if direct else [page for page in ('F1', 'F2', 'F3') if profile.get('use_'+page, bool(profile.get(page)))] or ['F1']
        order = []
        for entry in re.split('[;,]', str(profile.get('direct_skills', ''))):
            if entry.strip():
                uid, _, ms = entry.strip().partition('=')
                order.append((uid, ms or delays.get(uid, '')))
        if not order or profile.get('pvp_background') or profile.get('packet_f1'):
            order = list(delays.items())
        skill_rows = [{'id': uid, 'page': page, 'ms': ms} for page in pages for uid, ms in order]
    for index, row in enumerate(skill_rows):
        row.setdefault('stt', str(index + 1))
    for page in PVP_EDIT_PAGES:
        rows = page_skill_rows(page)
        rows.sort(key=lambda row: int(row['stt']) if row['stt'].isdigit() and int(row['stt']) else float('inf'))
        replace_page_skill_rows(page, rows)
    skill_row_offset = dict.fromkeys(PVP_EDIT_PAGES, 0)
    for page in PVP_EDIT_PAGES:
        skill_row_selected[page] = None
    choice = profile.get('pvp_mode_choice') or (PVP_MODE_FLOAT if profile.get('hybrid_exchange_test') else
             PVP_MODE_IDS if profile.get('pvp_background') or profile.get('packet_f1') else PVP_MODE_KEYS)
    QtBind.setText(gui, pvp_mode_field, choice if choice in (PVP_MODE_KEYS,PVP_MODE_IDS) else PVP_MODE_KEYS)
    QtBind.setText(gui, imbue_early_field, str(profile.get('imbue_early_seconds', '0.8')))
    show_skill_rows()


# Keep old fields as compatibility storage while rendering the consolidated PvP page.
for view in ('pvp', 'gear'):
    ui_views.setdefault('hidden', []).extend(ui_views.get(view, []))
    ui_views[view] = []


def place_pvp(handle, x, y):
    for controls in ui_views.values():
        controls[:] = [record for record in controls if record[0] != handle]
    ui_views['pvp'].append((handle, x, y))


place_pvp(pvp_box, 10, 34)
pvp_mode_field = widget('hidden', 'createCombobox', 140, 32, 190, 22)
for mode in (PVP_MODE_KEYS, PVP_MODE_IDS):
    QtBind.append(gui, pvp_mode_field, mode)
skill_row_fields = {}
skill_row_labels = {}
pvp_page_boxes = {}


def switch_pvp_editor():
    global pvp_right_editor
    pvp_right_editor = 'F3' if pvp_right_editor == 'F2' else 'F2'
    view_pvp()


widget('pvp', 'createButton', 'switch_pvp_editor', 'F2 / F3', 315, 54)
for column, page in enumerate(PAGES):
    toggle = 'pvp_toggle_' + page.lower()
    globals()[toggle] = lambda checked, selected=page: pvp_page_changed(selected, checked)
    if page not in PVP_EDIT_PAGES:
        pvp_page_boxes[page] = widget('hidden', 'createCheckBox', toggle, page, 0, 0)
        continue
    x = 10 if column == 0 else 210
    editor_view = 'pvp' if column == 0 else 'pvp_' + page
    pvp_page_boxes[page] = widget(editor_view, 'createCheckBox', toggle, page + ' · Bật đánh', x, 56)
    set_checked_silent(pvp_page_boxes[page], page != 'F3')
    for offset, label in ((0, 'Tắt'), (34, 'ID skill'), (121, 'ms'), (165, 'Ngắt')):
        widget(editor_view, 'createLabel', label, x + offset, 77)
    fields = []
    for row in range(5):
        y = 92 + row * 21
        name = 'skill_select_%s_%d' % (page, row)
        globals()[name] = lambda checked, p=page, r=row: select_skill_row(p, r, checked)
        selector = widget(editor_view, 'createCheckBox', name, '', x + 4, y)
        skill = widget(editor_view, 'createLineEdit', '', x + 34, y, 77, 18)
        delay = widget(editor_view, 'createLineEdit', '', x + 119, y, 37, 18)
        cut = widget(editor_view, 'createCheckBox', 'skill_cut_changed', '', x + 171, y)
        fields.append((skill, delay, cut, selector))
    skill_row_fields[page] = fields
    up, down = 'skill_up_' + page, 'skill_down_' + page
    globals()[up] = lambda p=page: move_selected_skill_row(p, -1)
    globals()[down] = lambda p=page: move_selected_skill_row(p, 1)
    widget(editor_view, 'createButton', up, '▲ Lên', x, 201)
    widget(editor_view, 'createButton', down, '▼ Xuống', x + 112, 201)
    back, more = 'skill_back_' + page, 'skill_more_' + page
    globals()[back] = lambda p=page: shift_skill_table(p, -1)
    globals()[more] = lambda p=page: shift_skill_table(p, 1)
    widget(editor_view, 'createButton', back, 'Trước', x, 225)
    skill_row_labels[page] = widget(editor_view, 'createLabel', '1–5', x + 83, 229)
    widget(editor_view, 'createButton', more, 'Thêm / Sau', x + 112, 225)

boss_mode_box = widget('pvp', 'createCheckBox', 'boss_mode_changed', 'Auto Boss', 140, 34)
widget('pvp', 'createLabel', 'Nhóm Boss', 244, 36)
boss_group_field = widget('pvp', 'createCombobox', 319, 31, 65, 22)
for page in PVP_EDIT_PAGES:
    QtBind.append(gui, boss_group_field, page)
QtBind.setText(gui, boss_group_field, 'F1')
profile_fields['boss_skill_group'] = boss_group_field
numeric_box = widget('pvp', 'createCheckBox', 'numeric_mode_changed', 'Auto số', 413, 34)
widget('pvp', 'createLabel', 'Dãy', 515, 36)
numeric_keys_field = widget('pvp', 'createLineEdit', '4567890', 542, 31, 65, 19)
widget('pvp', 'createLabel', 'ms', 616, 36)
numeric_ms_field = widget('pvp', 'createLineEdit', '20', 639, 31, 38, 19)
profile_fields.update(numeric_keys=numeric_keys_field, numeric_interval_ms=numeric_ms_field)
widget('pvp', 'createLabel', 'F4: Dừng', 634, 64)
place_pvp(trigger_field, 413, 83)
widget('pvp', 'createLabel', 'F', 413, 112)
widget('pvp', 'createLabel', 'Vũ khí', 443, 112)
widget('pvp', 'createLabel', 'Khiên', 522, 112)
for index, page in enumerate(PAGES):
    y = 131 + index * 19
    widget('pvp', 'createLabel', page, 413, y)
    place_pvp(weapon_fields[page], 443, y-3)
    place_pvp(shield_fields[page], 522, y-3)
    widget('pvp', 'createButton', 'capture_'+page.lower()+'_gear', 'Lấy', 594, y-4)
place_pvp(imbue_box, 413, 205)
widget('pvp', 'createButton', 'refresh_imbues', 'Quét', 594, 205)
place_pvp(imbue_field, 413, 225)
widget('pvp', 'createLabel', 'Làm mới sớm (giây)', 413, 252)
imbue_early_field = widget('pvp', 'createLineEdit', '0.8', 548, 248, 52, 20)
widget('pvp', 'createLabel', 'F4 dừng Ghost và Auto số. Ghost PvP mặc bộ F4.', 10, 252)
show_skill_rows()
view_pvp()



# Production Boss engine, isolated from PvP state and sharing the existing GUI.
import types as _boss_types
_bg_base_start=start_clicked
_bg_base_stop=stop_clicked
_bg_base_event=event_loop
_bg_base_joymax=handle_joymax
_bg_base_silkroad=handle_silkroad
_bg_base_teleported=teleported
_bg_base_disconnected=disconnected
_bg_base_finished=finished
ui_views['legacy_boss']=ui_views.pop('boss',[])
_boss_engine=_boss_types.ModuleType(__name__+'_boss_background')
_boss_engine.__file__=__file__
sys.modules[_boss_engine.__name__]=_boss_engine


def _boss_send(opcode,payload,encrypted=False):
    # Native writes pass through the registered parent plugin's Python frame.
    # Keep the caller's opcode, payload and flag; no fallback/retry here.
    return inject_joymax(opcode,payload,encrypted)


class _BossAPI:
    def __getattr__(self,name):
        if name=='inject_joymax':return _boss_send
        return getattr(phbot_api,name)


boss_plan = None


def disarm_boss():
    global boss_plan
    with _boss_engine.LOCK:
        boss_plan = None


_boss_engine.__dict__.update(_boss_bot=_BossAPI(), _disarm_boss=disarm_boss,
                             imbue_seconds=imbue_seconds, imbue_refresh_delay=imbue_refresh_delay,
                             imbue_is_active=imbue_is_active)
exec(compile('# -*- coding: utf-8 -*-\n"""Ghost Boss nền theo ID, đồng bộ từng lượt đánh với phản hồi server."""\nimport json\nimport os\nimport queue\nimport struct\nimport subprocess\nimport tempfile\nfrom collections import deque\nfrom datetime import datetime\nfrom pathlib import Path\nfrom threading import Event, RLock, Thread\nfrom time import monotonic, time\nbot = _boss_bot\n\nNAME, VERSION = \'GhostBossBackground\', \'1.0.8\'\nLOCK=RLock()\nactive=None\nselected=0\nconfirmed_target=0\nselection_revision=0\nupdates=deque(maxlen=5)\n\n\ndef emit(j,text,quiet=False,error=False):\n    with LOCK:\n        if j and j.get(\'stream\'):\n            j[\'stream\'].write(\'[%s] +%d ms %s\\n\' % (datetime.now().strftime(\'%H:%M:%S.%f\')[:-3],round((monotonic()-j[\'start\'])*1000),text))\n            j[\'stream\'].flush()\n        if j and not j.get(\'details\') and j.get(\'cycle\',0)>1 and not any(k in text for k in (\'DỪNG\',\'KẾT THÚC\',\'Vòng\')):quiet=True\n        if not quiet:updates.append(text)\n    if error:bot.log(\'[Auto Boss] %s\' % text)\n\n\ndef identity(c):return c.get(\'server\'),c.get(\'name\'),c.get(\'player_id\')\n\n\ndef entity(records,uid):\n    if not isinstance(records,dict):return None\n    return records.get(uid) or records.get(str(uid))\n\n\ndef mob_alive(mob):\n    if not mob or mob.get(\'dead\'):\n        return False\n    try:\n        return float(mob.get(\'hp\') or 0) > 0\n    except (TypeError, ValueError):\n        return False\n\n\ndef live_target(uid):\n    return mob_alive(entity(bot.get_monsters() or {}, uid))\n\n\ndef stop(reason=\'bấm DỪNG\', notify=True):\n    with LOCK:\n        j=active\n        if not j:return\n        first=not j[\'stop\'].is_set()\n        if first:j[\'reason\']=reason\n        j[\'stop\'].set()\n        if first:\n            try:\n                mob=entity(bot.get_monsters() or {},j[\'target\'])\n                snapshot=dict(uid=j[\'target\'],expected=j.get(\'expected\'),visible=mob is not None,\n                              hp=(mob or {}).get(\'hp\'),dead=(mob or {}).get(\'dead\'))\n            except Exception:snapshot={\'uid\':j[\'target\'],\'expected\':j.get(\'expected\')}\n            emit(j,\'DỪNG: \'+reason, error=notify)\n            emit(j,\'Trạng thái khi dừng: \'+json.dumps(snapshot,ensure_ascii=False), quiet=True)\n\n\ndef valid(j):\n    if j[\'stop\'].is_set():return False\n    if any(monotonic() - at > 3 for at in j[\'cut_requests\'].values()):\n        stop(\'quá 3 giây chưa có hậu kiểm nút ngắt Boss\')\n        return False\n    c=bot.get_character_data() or {}\n    if identity(c)!=j[\'owner\'] or c.get(\'dead\') or bot.get_status():\n        stop(\'nhân vật thay đổi/chết hoặc bot chính được bật\');return False\n    mob=entity(bot.get_monsters() or {},j[\'target\'])\n    if not mob:\n        stop(\'không còn dữ liệu boss/quái trong tầm nhìn\');return False\n    if not mob_alive(mob):\n        if mob.get(\'dead\') or mob.get(\'hp\') == 0:\n            stop(\'boss/quái đã chết\', notify=False)\n        else:\n            stop(\'không đọc được HP của boss/quái\')\n        return False\n    return True\n\n\ndef wait(j,predicate,seconds):\n    end=monotonic()+seconds\n    while valid(j):\n        with LOCK:\n            if predicate():return True\n        if monotonic()>=end:return False\n        j[\'stop\'].wait(0.01)\n    return False\n\n\ndef pause(j,seconds):\n    end=monotonic()+seconds\n    return wait(j,lambda:monotonic()>=end,seconds+0.2)\n\n\ndef reader(j,process):\n    try:\n        for line in process.stdout:\n            try:\n                reply=json.loads(line)\n                # The focus report arrives after the cut\'s posted-message ack.\n                # Monitor it independently: it must not hold up the next skill.\n                with LOCK:\n                    cut=j.get(\'cut_requests\',{}).get(reply.get(\'id\'))\n                    if cut is not None and not reply.get(\'stage\'):\n                        j[\'cut_requests\'].pop(reply[\'id\'],None)\n                        emit(j,\'HẬU KIỂM postmouse: focus=%s → %s | gọi nút=%s ms | lỗi=%s\' %\n                             (reply.get(\'focus_before\'),reply.get(\'focus_after\'),reply.get(\'ms\'),reply.get(\'error\',\'không\')))\n                        if (reply.get(\'ok\') is not True or reply.get(\'focus_stolen\')) and active is j:\n                            stop(\'hậu kiểm Exchange lỗi hoặc phBot giành tiêu điểm; không chuyển Invoke\')\n                j[\'replies\'].put(reply)\n            except ValueError:\n                if line.strip():emit(j,\'HELPER: \'+line.strip()[:250],True)\n    finally:j[\'replies\'].put({\'ended\':True})\n\n\ndef request(j,action):\n    with LOCK:\n        if not valid(j):return None\n        if action == \'cut\' and j[\'ended\']:\n            return {\'ended_naturally\': True}\n        request_id=str(monotonic())\n        timeout=15 if action==\'probe\' else 2\n        q=dict(id=request_id,pid=os.getpid(),name=j[\'preferred_player\'] if action==\'probe\' else j[\'player\'],\n               own_name=j[\'owner\'][1],transport=\'postmouse\',\n               action=action,expires=round((time()+timeout)*1000))\n        process=j[\'process\']\n        if action==\'cut\':\n            j.setdefault(\'cut_requests\',{})[request_id]=monotonic()\n            j[\'cut_wait\']=dict(request_id=request_id,skill=j[\'expected\'],armed_at=monotonic(),cancel_at=None)\n        process.stdin.write(json.dumps(q,ensure_ascii=False)+\'\\n\');process.stdin.flush()\n    deadline=monotonic()+timeout+0.3\n    while valid(j) and monotonic()<deadline:\n        try:r=j[\'replies\'].get(timeout=0.03)\n        except queue.Empty:continue\n        if r.get(\'ended\'):raise ValueError(\'Helper đã dừng.\')\n        if r.get(\'id\')!=request_id:continue\n        if r.get(\'stage\'):\n            emit(j,\'POSTMESSAGE: \'+str(r[\'stage\']),True)\n            if action==\'cut\' and r[\'stage\']==\'mouse_posted\':\n                emit(j,\'ĐƯỜNG=postmouse | đã gửi cặp thông điệp, %s ms trong helper; chờ B074 02 00 rồi mới nối skill.\' % r.get(\'post_ms\'))\n                return r\n            continue\n        if not r.get(\'ok\'):raise ValueError(str(r.get(\'error\',\'Không gọi được nút Exchange\')))\n        if r.get(\'focus_stolen\'):raise ValueError(\'phBot giành tiêu điểm; dừng, không thử Invoke.\')\n        if action!=\'probe\':\n            emit(j,\'ĐƯỜNG=postmouse | Player=%s | gọi nút=%s ms | focus=%s → %s; không phải xác nhận server.\' %\n                 (r.get(\'name\'),r.get(\'ms\'),r.get(\'focus_before\'),r.get(\'focus_after\')))\n        return r\n    if valid(j):raise ValueError(\'Hết thời gian gọi nút phBot; không gửi lại.\')\n    return None\n\n\ndef acquire_player(j):\n    announced = False\n    while valid(j):\n        reply = request(j, \'probe\')\n        if reply is None:\n            return False\n        if reply.get(\'needs_phbot_foreground\'):\n            if announced != \'foreground\':\n                emit(j, \'Auto Boss: mở cửa sổ phBot để tự chọn acc hỗ trợ; sau đó có thể chuyển cửa sổ.\')\n                announced = \'foreground\'\n            j[\'stop\'].wait(1.0)\n            continue\n        player = str(reply.get(\'name\') or \'\').strip()\n        if player and not reply.get(\'no_player\') and player.casefold() != str(j[\'owner\'][1]).casefold():\n            j[\'player\'] = player\n            j[\'recheck_player\'] = False\n            emit(j, \'Đã chọn Player hỗ trợ Boss: \' + player)\n            return True\n        if announced != \'player\':\n            emit(j, \'Chưa có Player hỗ trợ trong tầm. Đang tự làm mới danh sách.\')\n            announced = \'player\'\n        j[\'stop\'].wait(1.0)\n    return False\n\n\ndef send_action(j, payload):\n    """Register an exact match before sending, including delayed callbacks."""\n    now = monotonic()\n    recent = j[\'recent_actions\']\n    while recent and recent[0][1] < now:\n        recent.popleft()\n    recent.append((payload, now + 1.5))\n    return bot.inject_joymax(0x7074, payload, False)\n\n\ndef describe_action(raw):\n    if raw == b\'\\x02\':\n        return \'hủy tác vụ\'\n    if len(raw) == 7 and raw[:3] == b\'\\x01\\x01\\x01\':\n        return \'đánh thường UID=%d\' % struct.unpack_from(\'<I\', raw, 3)[0]\n    if len(raw) in (7, 11) and raw[:2] == b\'\\x01\\x04\':\n        skill = struct.unpack_from(\'<I\', raw, 2)[0]\n        if len(raw) == 11 and raw[6] == 1:\n            return \'skill ID=%d UID=%d\' % (skill, struct.unpack_from(\'<I\', raw, 7)[0])\n        if len(raw) == 7 and raw[6] == 0:\n            return \'skill tự buff ID=%d\' % skill\n    return \'tác vụ chưa nhận diện\'\n\n\ndef maintain_imbue(j):\n    """Run only between attacks, before arming the next attack\'s B070 wait."""\n    uid = j.get(\'imbue_id\')\n    now = monotonic()\n    if not uid:\n        return True\n    data = entity(bot.get_skills() or {}, uid)\n    if not data:\n        return True\n    active = imbue_is_active(bot, uid, data)\n    payload = struct.pack(\'<BBIB\', 1, 4, uid, 0)\n    cast_time = max(0.2, imbue_seconds(data, \'cast_time\') + 0.1)\n    with LOCK:\n        if not valid(j):\n            return False\n        if uid != j[\'imbue_id\']:\n            return True\n        delay = imbue_refresh_delay(data, j[\'imbue_early\'])\n        if active:\n            if not j[\'imbue_seen_active\'] and not j[\'imbue_until\'] and delay:\n                j[\'imbue_until\'] = now + delay\n            j[\'imbue_seen_active\'] = True\n            if not j[\'imbue_until\']:\n                return True\n        elif j[\'imbue_seen_active\']:\n            j[\'imbue_seen_active\'] = False\n            j[\'imbue_until\'] = 0.0\n        if now < max(j[\'imbue_retry\'], j[\'imbue_until\']) or data.get(\'can_cast\') is False:\n            return True\n        j.update(imbue_payload=payload, imbue_ack=None)\n        j[\'imbue_retry\'] = now + max(2.0, imbue_seconds(data, \'cooldown\'))\n        accepted = send_action(j, payload)\n        emit(j, \'Tay phép Boss: %s (ID=%d), API=%r.\' % (data.get(\'name\') or \'Tự buff\', uid, accepted))\n    try:\n        if accepted is False:\n            with LOCK:\n                if uid == j[\'imbue_id\']:\n                    j[\'imbue_retry\'] = monotonic() + 2.0\n            return True\n        if wait(j, lambda: j[\'imbue_ack\'] is not None, 1.0):\n            with LOCK:\n                if uid == j[\'imbue_id\']:\n                    j[\'imbue_until\'] = j[\'imbue_ack\'] + (delay or 1.0)\n        elif not j[\'stop\'].is_set():\n            emit(j, \'Tay phép Boss: chưa thấy B070 xác nhận, tiếp tục chuỗi đánh.\')\n        return pause(j, max(0, now + cast_time - monotonic()))\n    finally:\n        with LOCK:\n            j[\'imbue_payload\'] = None\n\n\ndef skill_available(skill):\n    data = entity(bot.get_skills() or {}, skill)\n    return data is not None and data.get(\'can_cast\') is not False\n\n\n# B074 carries no skill ID. Use the ordered start/end pair only to\n# permit one reclick of the same skill, never as evidence of a hit.\nCAST_RECOVERY_GRACE = 0.35\n\n\ndef cast_attack(j, skill):\n    data = struct.pack(\'<BBIBI\', 1, 4, skill, 1, j[\'target\'])\n    for attempt in range(2):\n        if not skill_available(skill):\n            emit(j, \'ID=%d: phBot báo chưa thể dùng; đợi dữ liệu cập nhật.\' % skill)\n            if not wait(j, lambda: skill_available(skill) or (attempt and j[\'ack\'] is not None), 6):\n                if j[\'stop\'].is_set():\n                    return False\n                raise ValueError(\'ID=%d chưa thể dùng trong 6 giây; kiểm tra hồi chiêu, vũ khí và điều kiện của skill.\' % skill)\n        with LOCK:\n            if not valid(j):\n                return False\n            if attempt and j[\'ack\'] is not None:\n                return True\n            if attempt:\n                emit(j, \'Boss ID=%d: đã thấy B074 01 01 → 02 00, thiếu B070; thử lại đúng skill một lần.\' % skill)\n            j[\'cast_replies\'].clear()\n            j.update(expected=skill, expected_packet=data, ack=None, ended=False, sent=monotonic(),\n                     cast_started=False, cast_closed_at=None)\n            result = send_action(j, data)\n            emit(j, \'Gửi skill ID=%d; API=%r; chờ B070 đúng UID.\' % (skill, result))\n            if result is False:\n                raise ValueError(\'phBot từ chối gửi skill ID=%d.\' % skill)\n\n        def cast_resolved():\n            return j[\'ack\'] is not None or (\n                j[\'cast_closed_at\'] is not None and monotonic() >= j[\'cast_closed_at\'] + CAST_RECOVERY_GRACE)\n\n        wait(j, cast_resolved, 6)\n        with LOCK:\n            if not valid(j):\n                return False\n            if j[\'ack\'] is not None:\n                return True\n            if not attempt and j[\'cast_closed_at\'] is not None and cast_resolved():\n                continue\n            elapsed = round((monotonic() - j[\'sent\']) * 1000)\n            replies = \' | \'.join(j[\'cast_replies\']) or \'chưa thấy B070 của nhân vật hoặc B074\'\n            retry = \'Đã thử lại một lần. \' if attempt else \'\'\n            raise ValueError(\'ID=%d UID=%d: sau %d ms chưa có B070 khớp. %s. %sLog: %s\' %\n                             (skill, j[\'target\'], elapsed, replies, retry, j[\'path\']))\n\n\ndef stage(j):\n    for skill, delay in j[\'sequence\']:\n        if delay is not None and j[\'recheck_player\'] and not acquire_player(j):\n            return False\n        with LOCK:\n            if not valid(j):return False\n            ready_at=j[\'ready\'].get(skill,0)\n        if not wait(j,lambda:monotonic()>=ready_at,max(0,ready_at-monotonic())+0.5):return False\n        if not maintain_imbue(j):return False\n        if not cast_attack(j, skill):\n            return False\n        ack = j[\'ack\']\n        j[\'ready\'][skill] = ack + j[\'cooldowns\'].get(skill, 0) + 0.05\n        if delay is not None:\n            cut_at = ack + delay / 1000\n            if not wait(j, lambda: j[\'ended\'] or monotonic() >= cut_at, delay / 1000 + 0.5):\n                return False\n            with LOCK:\n                if not valid(j):\n                    return False\n                should_cut = not j[\'ended\']\n            if should_cut:\n                reply = request(j, \'cut\')\n                if reply is None:\n                    return False\n                if not reply.get(\'ended_naturally\'):\n                    wait(j, lambda: j[\'ended\'] or j[\'cut_wait\'][\'cancel_at\'] is not None, 1.5)\n                    with LOCK:\n                        if not valid(j):\n                            return False\n                        if j[\'cut_wait\'][\'cancel_at\'] is None:\n                            emit(j, \'Chưa xác nhận ngắt ID=%d. Đợi skill kết thúc rồi tự tìm lại Player.\' % skill)\n                            j[\'recheck_player\'] = True\n                        j[\'cut_wait\'] = None\n        if not wait(j, lambda: j[\'ended\'], 12):\n            if j[\'stop\'].is_set():\n                return False\n            raise ValueError(\'Thiếu B074 kết thúc cho skill ID=%d; dừng chuỗi.\' % skill)\n        if not pause(j, 0.1):\n            return False\n    return True\n\n\ndef run(j):\n    global active\n    helper_path = None\n    try:\n        emit(j,\'BẮT ĐẦU | target=%d | dãy=%r | log=%s\' % (j[\'target\'],j[\'sequence\'],j[\'path\']))\n        if any(delay is not None for _, delay in j[\'sequence\']):\n            emit(j, \'Auto Boss đang mở Hòm đồ phBot và chọn acc hỗ trợ.\')\n            # Windows caps the command line at 32767 characters. Keep the\n            # script in a file and use UTF-8 BOM for Windows PowerShell 5.1.\n            with tempfile.NamedTemporaryFile(mode=\'w\', encoding=\'utf-8-sig\', prefix=\'AGBoss-\',\n                                             suffix=\'.ps1\', delete=False) as script:\n                helper_path = Path(script.name)\n                script.write(HELPER)\n            exe = Path(os.environ.get(\'SystemRoot\', \'C:/Windows\')) / \'System32/WindowsPowerShell/v1.0/powershell.exe\'\n            with LOCK:\n                if not valid(j):\n                    return\n                process = subprocess.Popen(\n                    [str(exe), \'-NoProfile\', \'-NonInteractive\', \'-ExecutionPolicy\', \'Bypass\',\n                     \'-File\', str(helper_path)],\n                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,\n                    text=True, encoding=\'utf-8\', creationflags=0x08000000, bufsize=1)\n                j[\'process\'] = process\n            Thread(target=reader, args=(j, process), daemon=True).start()\n            if not acquire_player(j):\n                return\n        with LOCK:\n            if not valid(j) or confirmed_target != j[\'target\']:\n                return\n        emit(j,\'Đã sẵn sàng: Ghost Boss nền theo ID. F4 dừng.\')\n        quiet_after = monotonic() + j[\'rest\']\n        def ready_to_attack():\n            now = monotonic()\n            if now >= quiet_after and now - j[\'last_foreign_action\'] >= 1.4:\n                j[\'starting\'] = False\n                return True\n            return False\n        if not wait(j, ready_to_attack, j[\'rest\'] + 4):\n            if not j[\'stop\'].is_set():\n                stop(\'vẫn thấy lệnh ngoài khi chuẩn bị Boss; tắt Auto khác và ngừng đánh tay\')\n            return\n        while valid(j):\n            j[\'cycle\']+=1\n            if not stage(j):break\n            if j[\'cycle\']==1 or j[\'cycle\']%10==0:emit(j,\'Vòng %d đã hoàn tất đủ %d skill; tiếp tục, chờ hồi riêng từng ID.\' % (j[\'cycle\'],len(j[\'sequence\'])))\n    except Exception as error:\n        if not j[\'reason\']:\n            j[\'reason\'] = str(error)\n            emit(j, \'DỪNG: \' + j[\'reason\'], error=True)\n    finally:\n        with LOCK:\n            j[\'stop\'].set()\n            process = j.get(\'process\')\n        if process is not None and process.poll() is None:\n            try:\n                process.kill()\n                process.wait(timeout=2)\n            except (OSError, subprocess.TimeoutExpired):\n                pass\n        if helper_path is not None:\n            try:\n                helper_path.unlink(missing_ok=True)\n            except OSError as error:\n                emit(j, \'Chưa dọn được tệp helper tạm: \' + str(error), quiet=True)\n        with LOCK:\n            emit(j,\'KẾT THÚC: %s | FILE: %s\' % (j[\'reason\'] or \'đã dừng chuỗi\',j[\'path\']))\n            j[\'stream\'].close();j[\'stream\']=None\n            if active is j:active=None\n\n\ndef start(target, sequence, imbue_id, imbue_early, player):\n    global active, selected\n    with LOCK:\n        if active:\n            emit(None, \'Boss đang kết thúc lượt trước hoặc đã chạy.\')\n            return\n        try:\n            if os.name != \'nt\':\n                raise ValueError(\'Auto Boss dùng trên Windows/phBot.\')\n            c = bot.get_character_data() or {}\n            if not c.get(\'player_id\') or c.get(\'dead\'):\n                raise ValueError(\'Vào game và còn sống trước.\')\n            if bot.get_status():\n                raise ValueError(\'Dừng bot chính trước khi bật Auto Boss.\')\n            if not live_target(target):\n                raise ValueError(\'Chọn Boss/quái còn sống trong game rồi bấm Bật.\')\n            learned = {int(k): v for k, v in (bot.get_skills() or {}).items()}\n            if any(skill not in learned or skill == imbue_id for skill, _ in sequence):\n                raise ValueError(\'Kiểm tra ID skill và bỏ tay phép khỏi dãy đánh Boss.\')\n            rest = 0\n            folder=Path(bot.get_config_dir())/NAME;folder.mkdir(parents=True,exist_ok=True)\n            path=folder/(\'GhostBoss_\'+datetime.now().strftime(\'%Y%m%d_%H%M%S_%f\')+\'.log\')\n            selected=target\n            j=dict(owner=identity(c),source=c[\'player_id\'],target=target,sequence=sequence,rest=rest,ready={s:monotonic()+max(0,float(learned[s].get(\'cooldown\') or 0)/1000) for s,_ in sequence if learned[s].get(\'can_cast\') is False},cooldowns={s:max(0,float(learned[s].get(\'cooldown\') or 0)/1000) for s,_ in sequence},cycle=0,details=False,\n                   stream=path.open(\'w\',encoding=\'utf-8\'),path=path,start=monotonic(),stop=Event(),reason=\'\',\n                   expected=None,expected_packet=None,ack=None,ended=False,cast_replies=deque(maxlen=4),\n                   cast_started=False,cast_closed_at=None,\n                   preferred_player=player,player=\'\',recheck_player=False,process=None,replies=queue.Queue(),cut_requests={},cut_wait=None,\n                   imbue_id=imbue_id,imbue_early=imbue_early,imbue_seen_active=False,imbue_payload=None,imbue_ack=None,imbue_retry=0.0,imbue_until=0.0,\n                   starting=True,last_foreign_action=0.0,recent_actions=deque(maxlen=16))\n            emit(j, \'Auto Boss dùng chung dãy skill của Auto Ghost.\')\n            active=j;Thread(target=run,args=(j,),daemon=True).start()\n        except Exception as error:emit(None, str(error), error=True)\n\n\ndef packet(outgoing,opcode,data):\n    global selected, confirmed_target, selection_revision\n    raw=bytes(data or b\'\')\n    with LOCK:\n        if outgoing and opcode == 0x7045 and len(raw) == 4:\n            selected = struct.unpack(\'<I\', raw)[0]\n            if selected != confirmed_target:\n                confirmed_target = 0\n        elif outgoing and opcode == 0x7046:\n            selected = confirmed_target = 0\n        elif not outgoing and opcode == 0xB045:\n            target = struct.unpack_from(\'<I\', raw, 1)[0] if len(raw) >= 5 and raw[0] == 1 else 0\n            if target and target != confirmed_target:\n                selection_revision += 1\n            selected = confirmed_target = target\n        j=active\n        if not j or j[\'stop\'].is_set():return\n        if selected != j[\'target\']:\n            stop(\'đổi hoặc bỏ mục tiêu khi đang Auto Boss\', notify=False)\n            return\n        if outgoing and opcode == 0x7074:\n            now = monotonic()\n            if not any(payload == raw and now <= expires for payload, expires in j[\'recent_actions\']):\n                description = \'%s | 7074=%s | Boss đang chờ ID=%s\' % (\n                    describe_action(raw), raw[:48].hex(\' \').upper(), j[\'expected\'])\n                if j[\'starting\']:\n                    j[\'last_foreign_action\'] = now\n                    emit(j, \'Chuẩn bị: thấy lệnh ngoài, đợi ngừng đánh | \' + description, True)\n                else:\n                    stop(\'có lệnh ngoài: \' + description)\n                    return\n        if outgoing and opcode in (0x7034,0x7005):stop(\'đổi đồ hoặc thoát game khi Ghost Boss\')\n        if opcode==0x3085 or (not outgoing and opcode==0xB081 and raw[:1]==b\'\\x01\'):\n            stop(\'giao dịch thật được mở; không tự xác nhận đồ\')\n        if not outgoing and opcode==0xB070 and len(raw)>=11 and raw[0]==1:\n            skill, source = struct.unpack_from(\'<II\', raw, 3)\n            payload = j.get(\'imbue_payload\')\n            if (payload and skill == struct.unpack_from(\'<I\', payload, 2)[0]\n                    and source == j[\'source\'] and j[\'imbue_ack\'] is None):\n                j[\'imbue_ack\'] = monotonic()\n        waiting_cast = j[\'expected\'] is not None and j[\'ack\'] is None\n        if not outgoing and waiting_cast and opcode == 0xB074:\n            j[\'cast_replies\'].append(\'B074 \' + raw[:8].hex(\' \').upper())\n            if raw == b\'\\x02\\x00\' and j[\'cast_started\'] and j[\'cast_closed_at\'] is None:\n                j[\'cast_closed_at\'] = monotonic()\n            elif raw == b\'\\x01\\x01\':\n                j[\'cast_closed_at\'] = None\n            j[\'cast_started\'] = raw == b\'\\x01\\x01\'\n        if not outgoing and waiting_cast and opcode == 0xB070 and len(raw) >= 11 and raw[0] == 1:\n            skill, source = struct.unpack_from(\'<II\', raw, 3)\n            if source == j[\'source\']:\n                target = struct.unpack_from(\'<I\', raw, 15)[0] if len(raw) >= 19 else None\n                if skill == j[\'expected\'] and target == j[\'target\']:\n                    j[\'ack\'] = monotonic()\n                else:\n                    j[\'cast_replies\'].append(\'B070 ID=%d UID=%s\' % (skill, target))\n                    emit(j, \'B070 chưa khớp: \' + raw.hex(\' \').upper(), quiet=True)\n        if not outgoing and opcode == 0xB074 and not j.get(\'imbue_payload\') and j[\'ack\'] is not None:\n            if raw in (b\'\\x02\\x00\', b\'\\x02\\x01\'):\n                j[\'ended\'] = True\n            cut = j[\'cut_wait\']\n            if raw == b\'\\x02\\x00\' and cut and cut[\'skill\'] == j[\'expected\'] and cut[\'cancel_at\'] is None:\n                cut[\'cancel_at\'] = monotonic()\n                emit(j, \'Boss ID=%d · nhận B074 02 00 sau yêu cầu ngắt.\' % j[\'expected\'])\n        if j.get(\'details\') and opcode in (0x7045,0xB045,0x7074,0xB070,0xB074,0x3085):\n            emit(j,\'%s %04X: %s\' % (\'C→S\' if outgoing else \'S→C\',opcode,raw.hex(\' \').upper()),True)\n\n\ndef handle_silkroad(opcode,data):packet(True,opcode,data);return True\ndef handle_joymax(opcode,data):packet(False,opcode,data);return True\ndef disconnected():stop(\'mất kết nối\')\ndef teleported():stop(\'dịch chuyển\')\ndef finished():stop(\'đóng plugin\')\ndef stop_button():stop()\n\n\nHELPER = \'\\n$ErrorActionPreference=\\\'Stop\\\'\\nAdd-Type -AssemblyName UIAutomationClient\\nAdd-Type -AssemblyName UIAutomationTypes\\nAdd-Type -TypeDefinition @\\\'\\nusing System;\\nusing System.Runtime.InteropServices;\\npublic static class HHFocusSnapshot {\\n [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }\\n [DllImport("user32.dll",SetLastError=true)] public static extern bool PostMessage(IntPtr hwnd,uint msg,UIntPtr wp,IntPtr lp);\\n [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hwnd,ref POINT point);\\n [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid);\\n [StructLayout(LayoutKind.Sequential)] public struct LASTINPUTINFO { public uint cbSize; public uint dwTime; }\\n [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();\\n [DllImport("user32.dll")] public static extern bool GetLastInputInfo(ref LASTINPUTINFO info);\\n public static uint InputTick() { var info=new LASTINPUTINFO(); info.cbSize=(uint)Marshal.SizeOf(info); return GetLastInputInfo(ref info)?info.dwTime:0; }\\n}\\n\\\'@\\n[Console]::InputEncoding=New-Object System.Text.UTF8Encoding($false)\\n[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)\\n\\nfunction Send-NavMouse($element,[int]$expectedPid) {\\n if($element.Current.IsOffscreen){\\n  $scroll=$null\\n  if($element.TryGetCurrentPattern([System.Windows.Automation.ScrollItemPattern]::Pattern,[ref]$scroll)){$scroll.ScrollIntoView();Start-Sleep -Milliseconds 100}\\n }\\n $rect=$element.Current.BoundingRectangle\\n if($element.Current.IsOffscreen -or $rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0){throw \\\'Inventory navigation has no visible rectangle\\\'}\\n $node=$element;$hwnd=[IntPtr]::Zero\\n for($i=0;$node -and $i -lt 12;$i++){\\n  if($node.Current.ProcessId -ne $expectedPid){break}\\n  if($node.Current.NativeWindowHandle){$hwnd=[IntPtr]$node.Current.NativeWindowHandle;break}\\n  $node=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($node)\\n }\\n [uint32]$owner=0\\n [HHFocusSnapshot]::GetWindowThreadProcessId($hwnd,[ref]$owner)|Out-Null\\n if($hwnd -eq [IntPtr]::Zero -or $owner -ne $expectedPid){throw \\\'Inventory navigation window mismatch\\\'}\\n $point=New-Object HHFocusSnapshot+POINT\\n $point.X=[int]($rect.Left+$rect.Width/2);$point.Y=[int]($rect.Top+$rect.Height/2)\\n if(![HHFocusSnapshot]::ScreenToClient($hwnd,[ref]$point)){throw \\\'Inventory coordinate mapping failed\\\'}\\n if($point.X -lt 0 -or $point.Y -lt 0 -or $point.X -gt 32767 -or $point.Y -gt 32767){throw \\\'Inventory coordinates outside range\\\'}\\n $lp=[IntPtr](($point.Y -shl 16) -bor ($point.X -band 65535))\\n if(![HHFocusSnapshot]::PostMessage($hwnd,0x0201,[UIntPtr]::new([uint32]1),$lp)){throw \\\'Inventory mouse-down rejected\\\'}\\n if(![HHFocusSnapshot]::PostMessage($hwnd,0x0202,[UIntPtr]::Zero,$lp)){throw \\\'Inventory mouse-up rejected\\\'}\\n}\\n\\nfunction Test-PhBotForeground([int]$expectedPid) {\\n [uint32]$foregroundPid=0\\n [HHFocusSnapshot]::GetWindowThreadProcessId([HHFocusSnapshot]::GetForegroundWindow(),[ref]$foregroundPid)|Out-Null\\n return $foregroundPid -eq [uint32]$expectedPid\\n}\\n\\nfunction Test-PlayerName([string]$name,$q) {\\n if([string]::IsNullOrWhiteSpace($name) -or $name -ieq [string]$q.own_name){return $false}\\n if($q.name){return ($name -ieq [string]$q.name)}\\n return ($name.Trim() -notin @(\\\'-\\\',\\\'--\\\',\\\'(none)\\\',\\\'none\\\',\\\'player\\\',\\\'players\\\',\\\'select player\\\',\\\'no player\\\',\\\'no players\\\',\\\'...\\\',\\\'chọn người chơi\\\',\\\'không có người chơi\\\',\\\'chọn player\\\'))\\n}\\n\\n$button=$null\\n$inventoryOpened=$false\\n[Console]::WriteLine(\\\'{"stage":"ready"}\\\')\\nwhile ($line=[Console]::ReadLine()) {\\n $q=$null\\n try {\\n  $q=$line|ConvertFrom-Json\\n  @{id=$q.id;stage=\\\'searching_button\\\'}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n  if ([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires) {throw \\\'Request expired\\\'}\\n  if($q.action -eq \\\'probe\\\' -and !$inventoryOpened -and (Test-PhBotForeground ([int]$q.pid))) {\\n   $roots=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$q.pid)))\\n   $navDone=$false;$labels=New-Object System.Collections.Generic.List[string]\\n   foreach($root in $roots) {\\n    if($navDone){break}\\n    $nodes=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)\\n    foreach($node in $nodes) {\\n     $name=($node.Current.Name -replace \\\'[\\\\p{P}\\\\p{S}\\\\s]\\\',\\\'\\\').ToLowerInvariant()\\n     if($labels.Count -lt 30 -and $node.Current.Name){$labels.Add($node.Current.Name)}\\n     if($name -in @(\\\'inventory\\\',\\\'hòmđồ\\\',\\\'thùngđồ\\\')) {\\n      if([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires){throw \\\'Expired before Inventory navigation\\\'}\\n      Send-NavMouse $node ([int]$q.pid)\\n      @{id=$q.id;stage=\\\'inventory_mouse_posted\\\'}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n      $navDone=$true;break\\n     }\\n    }\\n   }\\n   if(!$navDone){@{id=$q.id;stage=(\\\'inventory_navigation_not_found; labels=\\\'+($labels -join \\\' | \\\'))}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}}\\n   $inventoryOpened=$navDone\\n   $button=$null\\n  }\\n  if (!$button -or $button.Current.ProcessId -ne [int]$q.pid -or $button.Current.IsOffscreen) {\\n   $exchangeOpened=$false\\n   do {\\n   $roots=[System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,[int]$q.pid)))\\n   $matches=New-Object System.Collections.Generic.List[System.Windows.Automation.AutomationElement]\\n   $exchangeTabs=@()\\n   $captions=New-Object System.Collections.Generic.List[string]\\n   foreach($root in $roots) {\\n    $buttons=$root.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)\\n    foreach($b in $buttons) {\\n     $caption=$b.Current.Name\\n     $normalized=($caption -replace \\\'&\\\',\\\'\\\' -replace \\\'\\\\s\\\',\\\'\\\').ToLowerInvariant()\\n     if($b.Current.ControlType -eq [System.Windows.Automation.ControlType]::Button -and $captions.Count -lt 30){$captions.Add($caption)}\\n     if($b.Current.ControlType -eq [System.Windows.Automation.ControlType]::TabItem -and !$b.Current.IsOffscreen -and $normalized -in @(\\\'exchange\\\',\\\'traođổi\\\',\\\'giaodịch\\\')){$exchangeTabs+= $b}\\n     if(!$b.Current.IsOffscreen -and $normalized -in @(\\\'requestexchange\\\',\\\'yêucầugiaodịch\\\',\\\'yêucầutraođổi\\\')) {\\n      $ip=$null\\n      $matches.Add($b)\\n     }\\n    }\\n   }\\n   if($q.action -eq \\\'probe\\\' -and $matches.Count -eq 0 -and !(Test-PhBotForeground ([int]$q.pid))){\\n    break\\n   }\\n   if($q.action -eq \\\'probe\\\' -and $matches.Count -eq 0 -and !$exchangeOpened -and $exchangeTabs.Count -eq 1){\\n    Send-NavMouse $exchangeTabs[0] ([int]$q.pid)\\n    $exchangeOpened=$true\\n   }\\n   if($q.action -in @(\\\'probe\\\',\\\'mouse_probe\\\') -and $matches.Count -ne 1){Start-Sleep -Milliseconds 100}\\n   } while($q.action -in @(\\\'probe\\\',\\\'mouse_probe\\\') -and $matches.Count -ne 1 -and [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -lt [long]$q.expires)\\n   if($q.action -eq \\\'probe\\\' -and $matches.Count -eq 0 -and !(Test-PhBotForeground ([int]$q.pid))){\\n    @{id=$q.id;ok=$true;needs_phbot_foreground=$true}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n    continue\\n   }\\n   if($matches.Count -ne 1){throw (\\\'Request Exchange button count: \\\'+$matches.Count+\\\'; ProcessId=\\\'+$q.pid+\\\'; roots=\\\'+$roots.Count+\\\'; buttons=[\\\'+($captions -join \\\' | \\\')+\\\']\\\')}\\n   $button=$matches[0]\\n  }\\n  if($button.Current.IsOffscreen -or ($q.action -ne \\\'probe\\\' -and !$button.Current.IsEnabled)){throw \\\'Open phBot Inventory / Exchange page and leave it visible\\\'}\\n  $scope=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($button)\\n  $combos=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::ComboBox)))\\n  for($depth=0;$combos.Count -eq 0 -and $depth -lt 3;$depth++) {\\n   $parent=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($scope)\\n   if(!$parent -or $parent.Current.ProcessId -ne [int]$q.pid){break}\\n   $scope=$parent\\n   $combos=$scope.FindAll([System.Windows.Automation.TreeScope]::Descendants,(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,[System.Windows.Automation.ControlType]::ComboBox)))\\n  }\\n\\n  if($q.action -eq \\\'probe\\\' -and $combos.Count -eq 1) {\\n   $combo=$combos[0]\\n   $focusBeforeSelection=[HHFocusSnapshot]::GetForegroundWindow().ToInt64()\\n   $selection=$null\\n   $selectedText=\\\'\\\'\\n   if($combo.TryGetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern,[ref]$selection)){\\n    $current=$selection.Current.GetSelection()\\n    if($current.Count -eq 1){$selectedText=$current[0].Current.Name}\\n   }\\n   $valuePattern=$null\\n   if(!$selectedText -and $combo.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$valuePattern)){\\n    $selectedText=$valuePattern.Current.Value\\n   }\\n   if(!(Test-PlayerName $selectedText $q)){\\n    if(!(Test-PhBotForeground ([int]$q.pid))){\\n     @{id=$q.id;ok=$true;needs_phbot_foreground=$true}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n     continue\\n    }\\n    $row=$combo.Current.BoundingRectangle\\n    $refresh=@()\\n    $refreshScope=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($scope)\\n    if(!$refreshScope -or $refreshScope.Current.ProcessId -ne [int]$q.pid){$refreshScope=$scope}\\n    foreach($node in $refreshScope.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)){\\n     $caption=($node.Current.Name -replace \\\'[&\\\\s]\\\',\\\'\\\').ToLowerInvariant()\\n     if($node.Current.ControlType -ne [System.Windows.Automation.ControlType]::Button -or $node.Current.IsOffscreen -or !$node.Current.IsEnabled -or $caption -notin @(\\\'refresh\\\',\\\'refreshplayers\\\',\\\'làmmới\\\',\\\'cậpnhật\\\')){continue}\\n     $rect=$node.Current.BoundingRectangle\\n     if($rect.Left -ge $row.Right-4 -and [Math]::Abs(($rect.Top+$rect.Bottom)-($row.Top+$row.Bottom)) -le 30){$refresh+= $node}\\n    }\\n    if($refresh.Count -eq 1){\\n     Send-NavMouse $refresh[0] ([int]$q.pid)\\n     Start-Sleep -Milliseconds 100\\n    }\\n   }\\n   if(!$combo.Current.IsEnabled){\\n    @{id=$q.id;ok=$true;no_player=$true}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n    continue\\n   }\\n   if(!(Test-PlayerName $selectedText $q)){\\n    $selectedText=\\\'\\\'\\n    $expand=$null\\n    if(!$combo.TryGetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern,[ref]$expand)){\\n     throw \\\'Không đọc được danh sách Player tự động của phBot.\\\'\\n    }\\n    $wasCollapsed=$expand.Current.ExpandCollapseState -eq [System.Windows.Automation.ExpandCollapseState]::Collapsed\\n    try{\\n     if($wasCollapsed){$expand.Expand();Start-Sleep -Milliseconds 100}\\n     foreach($item in $combo.FindAll([System.Windows.Automation.TreeScope]::Descendants,[System.Windows.Automation.Condition]::TrueCondition)){\\n      $selector=$null\\n      $candidate=$item.Current.Name\\n      if($item.Current.ProcessId -eq [int]$q.pid -and (Test-PlayerName $candidate $q) -and $item.TryGetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern,[ref]$selector)){\\n       if([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires){throw \\\'Hết thời gian chọn Player hỗ trợ.\\\'}\\n       $selector.Select()\\n       $selectedText=$candidate\\n       break\\n      }\\n     }\\n    } finally {\\n     if($wasCollapsed -and $expand.Current.ExpandCollapseState -eq [System.Windows.Automation.ExpandCollapseState]::Expanded){$expand.Collapse()}\\n    }\\n   }\\n   [uint32]$ownerAfter=0\\n   $focusAfterSelection=[HHFocusSnapshot]::GetForegroundWindow()\\n   [HHFocusSnapshot]::GetWindowThreadProcessId($focusAfterSelection,[ref]$ownerAfter)|Out-Null\\n   if($focusAfterSelection.ToInt64() -ne $focusBeforeSelection -and $ownerAfter -eq [uint32]$q.pid){\\n    @{id=$q.id;ok=$true;needs_phbot_foreground=$true}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n    continue\\n   }\\n   if(!$selectedText){\\n    @{id=$q.id;ok=$true;no_player=$true}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n    continue\\n   }\\n  }\\n\\n  $matched=0\\n  $comboDetails=New-Object System.Collections.Generic.List[string]\\n  foreach($combo in $combos) {\\n   $selectedText=\\\'\\\'\\n   $source=\\\'none\\\'\\n   $sp=$null\\n   if($combo.TryGetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern,[ref]$sp)) {\\n    $selected=$sp.Current.GetSelection()\\n    if($selected.Count -eq 1){$selectedText=$selected[0].Current.Name;$source=\\\'SelectionPattern\\\'}\\n   }\\n   if(!$selectedText) {\\n    $vp=$null\\n    if($combo.TryGetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern,[ref]$vp)) {\\n     $value=$vp.Current.Value\\n     $selectedText=$value\\n     $source=if($vp.Current.IsReadOnly){\\\'ReadOnlyValue\\\'}else{\\\'EditableValue\\\'}\\n    }\\n   }\\n   $comboDetails.Add((\\\'Name=\\\'+$combo.Current.Name+\\\', selected=\\\'+$selectedText+\\\', source=\\\'+$source))\\n   if(Test-PlayerName $selectedText $q){$matched++;$selectedName=$selectedText;$matchedCombo=$combo;$matchedSource=$source}\\n  }\\n  if($matched -ne 1){throw (\\\'Player selection matches=\\\'+$matched+\\\'; expected=[\\\'+$q.name+\\\']; ComboBoxes=\\\'+$combos.Count+\\\'; details=[\\\'+($comboDetails -join \\\' | \\\')+\\\']\\\')}\\n  if($q.action -eq \\\'probe\\\') {\\n   @{id=$q.id;ok=$true;name=$selectedName;probe=$true}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n   continue\\n  }\\n  @{id=$q.id;stage=\\\'posting_mouse\\\'}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n  if([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires){throw \\\'Request expired before invoke\\\'}\\n  if($matchedSource -eq \\\'EditableValue\\\' -or $matchedSource -eq \\\'ReadOnlyValue\\\') {\\n   $verify=$matchedCombo.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern)\\n   if($verify.Current.Value -cne $selectedName){throw \\\'Player changed before invoke\\\'}\\n  } else {\\n   $verify=$matchedCombo.GetCurrentPattern([System.Windows.Automation.SelectionPattern]::Pattern)\\n   $verifyItems=$verify.Current.GetSelection()\\n   if($verifyItems.Count -ne 1 -or $verifyItems[0].Current.Name -cne $selectedName){throw \\\'Player changed before invoke\\\'}\\n  }\\n  $focusBefore=[HHFocusSnapshot]::GetForegroundWindow().ToInt64()\\n  $inputBefore=[HHFocusSnapshot]::InputTick()\\n  $watch=[Diagnostics.Stopwatch]::StartNew()\\n  if($q.transport -eq \\\'postmouse\\\') {\\n   [uint32]$foregroundPid=0\\n   [HHFocusSnapshot]::GetWindowThreadProcessId([IntPtr]$focusBefore,[ref]$foregroundPid)|Out-Null\\n   if($q.action -eq \\\'mouse_probe\\\' -and $foregroundPid -eq [uint32]$q.pid){throw \\\'Switch to game or another window before the one-shot test; phBot must not be foreground\\\'}\\n   $rect=$button.Current.BoundingRectangle\\n   if($rect.IsEmpty -or $rect.Width -le 0 -or $rect.Height -le 0){throw \\\'Invalid Exchange button rectangle\\\'}\\n   $node=$button\\n   $hwnd=[IntPtr]::Zero\\n   for($n=0;$node -and $n -lt 12;$n++) {\\n    if($node.Current.ProcessId -ne [int]$q.pid){break}\\n    $handle=$node.Current.NativeWindowHandle\\n    if($handle){$hwnd=[IntPtr]$handle;break}\\n    $node=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($node)\\n   }\\n   if($hwnd -eq [IntPtr]::Zero){throw \\\'No native ancestor window for Exchange button\\\'}\\n   [uint32]$ownerPid=0\\n   [HHFocusSnapshot]::GetWindowThreadProcessId($hwnd,[ref]$ownerPid)|Out-Null\\n   if($ownerPid -ne [uint32]$q.pid){throw \\\'Exchange window belongs to another process\\\'}\\n   $point=New-Object HHFocusSnapshot+POINT\\n   $point.X=[int]($rect.Left+$rect.Width/2);$point.Y=[int]($rect.Top+$rect.Height/2)\\n   if(![HHFocusSnapshot]::ScreenToClient($hwnd,[ref]$point)){throw \\\'Cannot map Exchange coordinates\\\'}\\n   if($point.X -lt 0 -or $point.Y -lt 0 -or $point.X -gt 32767 -or $point.Y -gt 32767){throw \\\'Exchange coordinates outside supported range\\\'}\\n   if([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() -gt [long]$q.expires){throw \\\'Request expired before PostMessage\\\'}\\n   $lp=[IntPtr](($point.Y -shl 16) -bor ($point.X -band 65535))\\n   if(![HHFocusSnapshot]::PostMessage($hwnd,0x0201,[UIntPtr]::new([uint32]1),$lp)){throw \\\'WM_LBUTTONDOWN rejected\\\'}\\n   $released=[HHFocusSnapshot]::PostMessage($hwnd,0x0202,[UIntPtr]::Zero,$lp)\\n   if(!$released){throw \\\'WM_LBUTTONUP rejected; inspect phBot button state\\\'}\\n   @{id=$q.id;stage=\\\'mouse_posted\\\';post_ms=$watch.ElapsedMilliseconds}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n   [Console]::Out.Flush()\\n   Start-Sleep -Milliseconds 120\\n   $after=[HHFocusSnapshot]::GetForegroundWindow().ToInt64()\\n   [uint32]$afterPid=0\\n   [HHFocusSnapshot]::GetWindowThreadProcessId([IntPtr]$after,[ref]$afterPid)|Out-Null\\n   $stolen=($foregroundPid -ne [uint32]$q.pid -and $afterPid -eq [uint32]$q.pid)\\n   @{id=$q.id;ok=$true;name=$selectedName;transport=\\\'postmouse\\\';ms=$watch.ElapsedMilliseconds;focus_before=$focusBefore;focus_after=$after;focus_stolen=$stolen;input_before=$inputBefore;input_after=[HHFocusSnapshot]::InputTick();mouse_probe=($q.action -eq \\\'mouse_probe\\\')}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n  } else {throw \\\'Only PostMessage transport is supported\\\'}\\n } catch {\\n  $button=$null\\n  $inventoryOpened=$false\\n  @{id=$q.id;ok=$false;error=$_.Exception.Message}|ConvertTo-Json -Compress|%{[Console]::WriteLine($_)}\\n }\\n}\\n\'\n', __file__+':boss_background', 'exec'), _boss_engine.__dict__)

# Solo Auto Ghost Boss: no support account required. Keep Exchange-helper path
# when "Acc hỗ trợ ngắt Boss" is filled.
#
# Monster/Boss ghost ≠ PvP player ghost. Do NOT reuse NativeCut / client-7081
# (those are for player targets). Solo Boss uses the classic AutoGhost Boss
# cancel path: interrupt key or ESC→ESC timing, with optional inject 0x7081
# to the monster UID (hiep-style packet) and soft 7074 cancel. PvP untouched.
_boss_request_exchange = _boss_engine.request
_boss_run_exchange = _boss_engine.run
_boss_start_exchange = _boss_engine.start
_boss_stage_exchange = _boss_engine.stage
_boss_packet_exchange = _boss_engine.packet


def _boss_solo_send_key(key):
    """Send one key to the game window without touching PvP NativeCut."""
    client = get_client() or {}
    window = client.get('window')
    if not window or not client.get('running'):
        return False
    if post_game_key(key, window):
        return True
    if not user32 or user32.GetForegroundWindow() != window:
        return False
    try:
        if any(user32.GetAsyncKeyState(code) & 0x8000 for code in (0x10, 0x11, 0x12, key)):
            return False
        user32.keybd_event(key, 0, 0, 0)
        user32.keybd_event(key, 0, 2, 0)
        return True
    except (AttributeError, OSError, ValueError):
        return False


def _boss_solo_esc_cut():
    """Classic Ghost Boss ESC open → gap → ESC close (monster cast cancel)."""
    if not _boss_solo_send_key(0x1B):
        return False
    sleep(BOSS_ESC_GAP)
    _boss_solo_send_key(0x1B)
    return True


def _boss_solo_key_cut():
    """Optional GUI 'Phím ngắt' for Solo Boss (same idea as Ghost Boss key cut)."""
    key = boss_interrupt_key
    if key is None:
        return False
    return _boss_solo_send_key(key)


def _boss_solo_cut(j):
    """Solo monster/Boss interrupt — ESC/key path, never PvP NativeCut."""
    with _boss_engine.LOCK:
        if not _boss_engine.valid(j):
            return None
        if j['ended']:
            return {'ended_naturally': True}
        target = int(j['target'])
        skill = j['expected']
        j['cut_wait'] = dict(request_id='solo-cut', skill=skill,
                             armed_at=monotonic(), cancel_at=None,
                             exchange_uid=target)
    method = None
    used = []

    # 1) hiep-style monster packet: inject 0x7081 → Boss/monster UID (not NativeCut).
    #    Soft: if phBot refuses, remember and continue; never abort the Boss loop.
    if not j.get('solo_inject_7081_blocked'):
        with _boss_engine.LOCK:
            if not _boss_engine.valid(j) or j['ended']:
                return {'ended_naturally': True} if j.get('ended') else None
            j['solo_exchange_uid'] = target
            j['solo_exchange_until'] = monotonic() + 2.0
            accepted = _boss_send(0x7081, struct.pack('<I', target), False)
            if accepted is False:
                j['solo_inject_7081_blocked'] = True
                j.pop('solo_exchange_uid', None)
                j.pop('solo_exchange_until', None)
                _boss_engine.emit(
                    j,
                    'Solo Boss: phBot từ chối inject 0x7081→UID %d · chuyển ESC/phím ngắt Boss (không dùng NativeCut PvP).' %
                    target)
            else:
                method = 'inject-7081'
                used.append(method)
                j['cut_wait']['request_id'] = 'solo-inject-7081'
                _boss_engine.emit(
                    j,
                    'Solo Boss ngắt inject-7081→UID quái/Boss %d, API=%r; chờ B074 02 00.' %
                    (target, accepted))

    # If inject was accepted, give the server a brief window before ESC fallback.
    if method == 'inject-7081':
        _boss_engine.wait(
            j,
            lambda: j['ended'] or (j.get('cut_wait') or {}).get('cancel_at') is not None,
            0.35)
        with _boss_engine.LOCK:
            if j.get('ended') or (j.get('cut_wait') or {}).get('cancel_at') is not None:
                return {'ok': True, 'solo': True, 'method': method, 'uid': target, 'used': used}

    # 2) Classic AutoGhost Boss cancel: custom interrupt key, else ESC→ESC.
    if _boss_solo_key_cut():
        method = 'interrupt-key'
        used.append(method)
        with _boss_engine.LOCK:
            if j.get('cut_wait') is not None:
                j['cut_wait']['request_id'] = 'solo-key'
            _boss_engine.emit(
                j,
                'Solo Boss ngắt phím %s (Ghost Boss); chờ B074 02 00.' %
                (chr(boss_interrupt_key) if boss_interrupt_key else '?'))
    elif _boss_solo_esc_cut():
        method = 'ESC'
        used.append(method)
        with _boss_engine.LOCK:
            if j.get('cut_wait') is not None:
                j['cut_wait']['request_id'] = 'solo-esc'
            _boss_engine.emit(j, 'Solo Boss ngắt ESC→ESC (Ghost Boss cũ); chờ B074 02 00.')

    # 3) Soft packet cancel only if no key/ESC could be delivered.
    if method is None:
        with _boss_engine.LOCK:
            accepted_cancel = _boss_engine.send_action(j, b'\x02')
            if accepted_cancel is not False:
                method = '7074-02'
                used.append(method)
                j['cut_wait']['request_id'] = 'solo-7074'
                _boss_engine.emit(
                    j,
                    'Solo Boss ngắt fallback 7074 hủy tác vụ, API=%r; chờ B074 02 00.' % accepted_cancel)

    if method is None:
        with _boss_engine.LOCK:
            _boss_engine.emit(
                j,
                'Solo Boss: chưa gửi được ngắt cho ID=%s · đợi skill tự kết thúc, không dừng Auto Boss.' %
                skill)
            return {'ok': False, 'solo': True, 'soft_fail': True, 'uid': target, 'used': used}
    return {'ok': True, 'solo': True, 'method': method, 'uid': target, 'used': used}


def _boss_packet(outgoing, opcode, data):
    """Allow intentional solo 7081↔monster cuts; do not treat auto-rejected trade as fatal."""
    raw = bytes(data or b'')
    with _boss_engine.LOCK:
        job = _boss_engine.active
        solo = bool(job and job.get('solo_cut') and not job['stop'].is_set())
        exchange_uid = job.get('solo_exchange_uid') if solo else None
        armed = bool(solo and exchange_uid and monotonic() < job.get('solo_exchange_until', 0))
        if armed and outgoing and opcode == 0x7081 and len(raw) == 4:
            if struct.unpack('<I', raw)[0] == exchange_uid:
                job['solo_exchange_seen'] = True
        if armed and not outgoing and opcode in (0xB081, 0x3085, 0x3088, 0xB084):
            # Monster/boss 7081 is auto-cancelled by the server; that cancel is the
            # interrupt. Never stop the solo chain for the petition we just sent.
            cut = job.get('cut_wait')
            if cut and cut.get('exchange_uid') == exchange_uid:
                job['solo_exchange_reply'] = raw[:8]
                return
            if opcode in (0xB081, 0x3085) and raw[:1] == b'\x01':
                return
    return _boss_packet_exchange(outgoing, opcode, data)


def _boss_request(j, action):
    if action == 'cut' and j.get('solo_cut'):
        return _boss_solo_cut(j)
    return _boss_request_exchange(j, action)


def _boss_stage(j):
    for skill, delay in j['sequence']:
        if (delay is not None and j['recheck_player'] and not j.get('solo_cut')
                and not _boss_engine.acquire_player(j)):
            return False
        with _boss_engine.LOCK:
            if not _boss_engine.valid(j):
                return False
            ready_at = j['ready'].get(skill, 0)
        if not _boss_engine.wait(j, lambda: monotonic() >= ready_at,
                                 max(0, ready_at - monotonic()) + 0.5):
            return False
        if not _boss_engine.maintain_imbue(j):
            return False
        if not _boss_engine.cast_attack(j, skill):
            return False
        ack = j['ack']
        j['ready'][skill] = ack + j['cooldowns'].get(skill, 0) + 0.05
        if delay is not None:
            cut_at = ack + delay / 1000
            if not _boss_engine.wait(j, lambda: j['ended'] or monotonic() >= cut_at,
                                     delay / 1000 + 0.5):
                return False
            with _boss_engine.LOCK:
                if not _boss_engine.valid(j):
                    return False
                should_cut = not j['ended']
            if should_cut:
                reply = _boss_engine.request(j, 'cut')
                if reply is None:
                    return False
                if not reply.get('ended_naturally'):
                    _boss_engine.wait(
                        j,
                        lambda: j['ended'] or (j.get('cut_wait') or {}).get('cancel_at') is not None,
                        1.5)
                    with _boss_engine.LOCK:
                        if not _boss_engine.valid(j):
                            return False
                        if j.get('cut_wait') is not None and j['cut_wait'].get('cancel_at') is None:
                            if j.get('solo_cut'):
                                _boss_engine.emit(
                                    j,
                                    'Solo Boss: chưa thấy B074 02 00 sau ngắt cho ID=%d; đợi skill kết thúc rồi tiếp.' %
                                    skill)
                            else:
                                _boss_engine.emit(
                                    j,
                                    'Chưa xác nhận ngắt ID=%d. Đợi skill kết thúc rồi tự tìm lại Player.' % skill)
                                j['recheck_player'] = True
                        j['cut_wait'] = None
                        j.pop('solo_exchange_uid', None)
                        j.pop('solo_exchange_until', None)
        if not _boss_engine.wait(j, lambda: j['ended'], 12):
            if j['stop'].is_set():
                return False
            raise ValueError('Thiếu B074 kết thúc cho skill ID=%d; dừng chuỗi.' % skill)
        if not _boss_engine.pause(j, 0.1):
            return False
    return True


def _boss_run(j):
    pending = getattr(_boss_engine, '_pending_solo_cut', None)
    if pending is not None and 'solo_cut' not in j:
        j['solo_cut'] = bool(pending)
    if not j.get('solo_cut'):
        return _boss_run_exchange(j)
    try:
        _boss_engine.emit(
            j,
            'BẮT ĐẦU solo | target=%d | dãy=%r | log=%s' % (j['target'], j['sequence'], j['path']))
        _boss_engine.emit(
            j,
            'Solo Boss: ngắt quái/Boss riêng (ESC/phím Ghost Boss + inject 7081 nếu phBot cho); không dùng NativeCut PvP.')
        with _boss_engine.LOCK:
            if not _boss_engine.valid(j) or _boss_engine.confirmed_target != j['target']:
                return
        _boss_engine.emit(j, 'Đã sẵn sàng: Ghost Boss solo (ESC/phím). F4 dừng.')
        quiet_after = monotonic() + j['rest']

        def ready_to_attack():
            now = monotonic()
            if now >= quiet_after and now - j['last_foreign_action'] >= 1.4:
                j['starting'] = False
                return True
            return False

        if not _boss_engine.wait(j, ready_to_attack, j['rest'] + 4):
            if not j['stop'].is_set():
                _boss_engine.stop('vẫn thấy lệnh ngoài khi chuẩn bị Boss; tắt Auto khác và ngừng đánh tay')
            return
        while _boss_engine.valid(j):
            j['cycle'] += 1
            if not _boss_engine.stage(j):
                break
            if j['cycle'] == 1 or j['cycle'] % 10 == 0:
                _boss_engine.emit(
                    j,
                    'Vòng %d đã hoàn tất đủ %d skill; tiếp tục, chờ hồi riêng từng ID.' %
                    (j['cycle'], len(j['sequence'])))
    except Exception as error:
        if not j['reason']:
            j['reason'] = str(error)
            _boss_engine.emit(j, 'DỪNG: ' + j['reason'], error=True)
    finally:
        with _boss_engine.LOCK:
            j['stop'].set()
            j.pop('solo_native_ready', None)
            j.pop('solo_native_session', None)
            _boss_engine.emit(j, 'KẾT THÚC: %s | FILE: %s' % (j['reason'] or 'đã dừng chuỗi', j['path']))
            if j.get('stream') is not None:
                j['stream'].close()
                j['stream'] = None
            if _boss_engine.active is j:
                _boss_engine.active = None


def _boss_start(target, sequence, imbue_id, imbue_early, player):
    preferred = (player or '').strip()
    solo = not preferred
    _boss_engine._pending_solo_cut = solo
    try:
        _boss_start_exchange(target, sequence, imbue_id, imbue_early, preferred)
        with _boss_engine.LOCK:
            job = _boss_engine.active
            if job is not None and not job['stop'].is_set() and job.get('target') == target:
                job['solo_cut'] = solo
                if solo:
                    job['recheck_player'] = False
                    job['solo_cut'] = True
                    _boss_engine.emit(
                        job,
                        'Chế độ Solo Boss: ESC/phím ngắt Ghost Boss (quái) · inject 7081 nếu được · không NativeCut PvP.')
    finally:
        _boss_engine._pending_solo_cut = None


_boss_engine.request = _boss_request
_boss_engine.stage = _boss_stage
_boss_engine.run = _boss_run
_boss_engine.start = _boss_start
_boss_engine.packet = _boss_packet
_boss_engine.handle_silkroad = lambda opcode, data: (_boss_packet(True, opcode, data) or True)
_boss_engine.handle_joymax = lambda opcode, data: (_boss_packet(False, opcode, data) or True)


# Damage timing meter. Keep both clock origins because Ghost starts its
# interruption timer at the matching B070, not at the outgoing skill request.
damage_meter = None
damage_meter_lock = RLock()
damage_meter_update = None
DAMAGE_METER_SAMPLES = 3

widget('meter', 'createLabel', 'ĐO MS NGẮT · Kết luận mốc gửi lệnh ngắt sau B070', 10, 36)
widget('meter', 'createLabel', 'Bắt đầu đo rồi dùng cùng một skill lên cùng đối thủ 3 lần, đợi hồi giữa các lần.', 10, 61)
widget('meter', 'createLabel', 'B070 là mốc server xác nhận skill. Giữ cùng khoảng cách để số đo dễ so sánh.', 10, 82)
widget('meter', 'createButton', 'start_damage_meter', 'Bắt đầu đo', 10, 107)
widget('meter', 'createButton', 'stop_damage_meter', 'Dừng đo', 111, 107)
widget('meter', 'createLabel', 'Bù thêm ms', 223, 112)
damage_margin_field = widget('meter', 'createLineEdit', '20', 310, 106, 50, 20)
damage_status_field = widget('meter', 'createLabel', 'Chưa đo.', 10, 141)
damage_result_list = widget('meter', 'createList', 10, 163, 655, 85)
widget('meter', 'createLabel', 'Nhập ô ms', 10, 261)
damage_suggested_field = widget('meter', 'createLineEdit', '', 92, 255, 70, 21)
damage_conclusion_field = widget('meter', 'createLabel', '', 180, 261)
damage_formula_field = widget('meter', 'createLabel', 'Công thức: làm tròn lên B070 → hit chậm nhất + ms bù.', 10, 282)
widget('meter', 'createLabel', 'Đo hit đầu. Skill kế chờ server xác nhận ngắt; các hit sau cần đo riêng.', 10, 302)


def start_damage_meter():
    global damage_meter, damage_meter_update
    character = get_character_data() or {}
    owner = owner_of(character)
    if not owner or not character.get('player_id') or character.get('dead'):
        QtBind.setText(gui, damage_status_field, 'Vào game và đứng sống trước khi đo.')
        return
    if get_status():
        QtBind.setText(gui, damage_status_field, 'Dừng bot chính trước khi đo.')
        return
    try:
        margin = int(QtBind.text(gui, damage_margin_field).strip())
        if not 0 <= margin <= 500:
            raise ValueError
    except ValueError:
        QtBind.setText(gui, damage_status_field, 'Bù thêm cần từ 0 đến 500 ms.')
        return
    stop_clicked()
    QtBind.clear(gui, damage_result_list)
    QtBind.setText(gui, damage_suggested_field, '')
    QtBind.setText(gui, damage_conclusion_field, '')
    QtBind.setText(gui, damage_formula_field, 'Công thức: làm tròn lên B070 → hit chậm nhất + ms bù.')
    QtBind.setText(gui, damage_status_field, 'Đang chờ lần dùng skill đầu tiên.')
    with damage_meter_lock:
        damage_meter_update = None
        damage_meter = dict(owner=owner, source=character['player_id'], skill=None,
                            deadline=perf_counter_ns() + 90_000_000_000,
                            margin=margin, cast=None, target=None, samples=[])


def end_damage_meter(message):
    global damage_meter, damage_meter_update
    with damage_meter_lock:
        if damage_meter is not None:
            damage_meter = None
            lines = damage_meter_update[0] if damage_meter_update else []
            value = damage_meter_update[2] if damage_meter_update else None
            damage_meter_update = (lines, message, value)


def stop_damage_meter():
    end_damage_meter('Đã dừng đo.')
    tick_damage_meter()


def inline_first_damage(raw, target):
    """Recognize the first target's inline direct-hit record in observed B070s."""
    if (len(raw) < 35 or raw[:3] != b'\x01\x02\x30'
            or raw[19:21] != b'\x01\x01' or raw[21] < 1
            or len(raw) < 22 + 13 * raw[21]
            or struct.unpack_from('<I', raw, 22)[0] != target
            or raw[26] not in (0, 1, 4, 5) or raw[27] not in (1, 2)):
        return None
    # In the captured layout, knockback/position flags precede the same
    # three-byte damage field. Blocked records have no inline damage.
    damage = int.from_bytes(raw[28:31], 'little')
    return damage if damage > 0 else None


def observe_damage_meter(outgoing, opcode, data):
    global damage_meter, damage_meter_update
    if damage_meter is None or opcode not in ((0x7074,) if outgoing else (0xB070, 0xB071)):
        return
    now = perf_counter_ns()
    raw = bytes(data or b'')
    with damage_meter_lock:
        job = damage_meter
        if job is None or now >= job['deadline']:
            return
        cast = job['cast']
        if outgoing:
            if len(raw) != 11 or raw[:2] != b'\x01\x04' or raw[6] != 1:
                return
            uid = struct.unpack_from('<I', raw, 2)[0]
            target = struct.unpack_from('<I', raw, 7)[0]
            if not target or target == job['source'] or (job['skill'] is not None and uid != job['skill']):
                return
            if cast and now - cast['sent'] <= 8_000_000_000:
                cast['repeated'] = True
                return
            if job['target'] is not None and target != job['target']:
                lines = damage_meter_update[0] if damage_meter_update else []
                damage_meter_update = (lines, 'Chọn lại đúng đối thủ của lượt đo đầu tiên.', None)
                return
            job['skill'] = uid
            job['cast'] = dict(target=target, sent=now, ack=None, action=None, repeated=False)
            return
        if not cast or now - cast['sent'] > 8_000_000_000:
            return
        if opcode == 0xB071:
            if cast['ack'] is not None and not cast.get('saw_b071'):
                cast['saw_b071'] = True
                report('Đo ms: B071 chờ đối chiếu ID=%d | %s' % (job['skill'], raw[:64].hex(' ').upper()))
            return
        if len(raw) < 19 or raw[0] != 1:
            return
        uid, source, action, target = struct.unpack_from('<IIII', raw, 3)
        if (uid, source, target) != (job['skill'], job['source'], cast['target']):
            return
        if cast['ack'] is None:
            cast.update(ack=now, action=action)
        elif cast['action'] != action:
            return
        damage = inline_first_damage(raw, target)
        if damage is None:
            if not cast.get('logged'):
                cast['logged'] = True
                report('Đo ms: B070 đúng skill, chưa đọc được hit trực tiếp ID=%d | %s' %
                       (uid, raw[:64].hex(' ').upper()))
            return
        job['cast'] = None
        if cast['repeated']:
            report('Đo ms: bỏ lượt ID=%d do có nhiều lệnh chồng nhau. Bấm đúng một lần.' % uid)
            return
        job['target'] = cast['target']
        ack_ms = (cast['ack'] - cast['sent']) / 1_000_000
        hit_ms = (now - cast['ack']) / 1_000_000
        samples = job['samples']
        samples.append((ack_ms, hit_ms))
        number = len(samples)
        line = 'Lượt %d · ID %d · ST %d · Bấm→B070 %.1f ms · B070→hit %.1f ms' % (
            number, uid, damage, ack_ms, hit_ms)
        result = None
        status = 'ID %d · %d/%d mẫu. Dùng lại skill khi hồi.' % (uid, number, DAMAGE_METER_SAMPLES)
        if number == DAMAGE_METER_SAMPLES:
            slowest_hit = max(hit for _, hit in samples)
            slowest_ack = max(ack for ack, _ in samples)
            suggested = math.ceil(slowest_hit) + job['margin']
            result = (suggested, slowest_hit, job['margin'], slowest_ack + suggested)
            status = ('ID %d · Kết luận sau %d mẫu. Chép số ở ô Nhập ô ms.' % (uid, number)
                      if suggested <= 5000 else 'ID %d · Mốc đo vượt giới hạn nhập 5000 ms.' % uid)
            damage_meter = None
        lines = damage_meter_update[0] if damage_meter_update else []
        damage_meter_update = (lines + [line], status, result)
        report('Đo ms: ' + line)


def tick_damage_meter():
    global damage_meter_update
    with damage_meter_lock:
        job = damage_meter
        if job is not None:
            character = get_character_data() or {}
            now = perf_counter_ns()
            if owner_of(character) != job['owner'] or character.get('dead') or get_status():
                end_damage_meter('Dừng đo vì đổi nhân vật, đã chết hoặc bot chính đang chạy.')
            elif now >= job['deadline']:
                end_damage_meter('Hết giờ. Chưa đủ 3 mẫu sát thương để gợi ý.')
            elif job['cast'] and now - job['cast']['sent'] > 8_000_000_000:
                job['cast'] = None
                lines = damage_meter_update[0] if damage_meter_update else []
                damage_meter_update = (lines, 'Chưa nhận diện được hit ở lượt vừa rồi. Xem log Đo ms.', None)
        update, damage_meter_update = damage_meter_update, None
    if update:
        lines, status, value = update
        for line in lines:
            QtBind.append(gui, damage_result_list, line)
        QtBind.setText(gui, damage_status_field, status)
        if value is not None:
            suggested, slowest_hit, margin, press_ms = value
            QtBind.setText(gui, damage_suggested_field, str(suggested) if suggested <= 5000 else '')
            after_ack = ('%.3f' % (suggested / 1000)).replace('.', ',')
            from_press = ('%.3f' % (press_ms / 1000)).replace('.', ',')
            QtBind.setText(gui, damage_conclusion_field,
                           '%s giây sau B070 · khoảng %s giây từ lúc bấm' % (after_ack, from_press))
            QtBind.setText(gui, damage_formula_field,
                           'Làm tròn lên %.1f ms + %d ms bù = %d ms.' % (slowest_hit, margin, suggested))



def stop_clicked(keep_bridge=False):
    disarm_boss()
    _boss_engine.stop('bấm DỪNG', notify=False)
    return _bg_base_stop(keep_bridge=keep_bridge)


def boss_running():
    job = _boss_engine.active
    return job is not None and not job['stop'].is_set()


def boss_mode_changed(checked):
    if ui_sync:
        return
    if checked:
        set_checked_silent(pvp_box, False)
        set_checked_silent(numeric_box, False)
        start_clicked(arm_only=True)
    elif boss_plan is not None or boss_running():
        stop_clicked()


def imbue_mode_changed(checked):
    global imbue_id, imbue_next_check, imbue_retry_at, imbue_seen_active, imbue_until
    if ui_sync:
        return
    try:
        uid = configured_imbue() if checked else 0
        if uid and boss_plan and any(skill == uid for skill, _ in boss_plan['sequence']):
            raise ValueError('Bỏ ID tay phép khỏi dãy đánh Boss.')
    except ValueError as error:
        set_checked_silent(imbue_box, False)
        report_error(str(error))
        uid = 0
    with pvp_lock:
        imbue_id = uid if hunt_stop is not None else 0
        imbue_next_check = imbue_retry_at = imbue_until = 0.0
        imbue_seen_active = False
    with _boss_engine.LOCK:
        if boss_plan is not None:
            boss_plan['imbue_id'] = uid
        job = _boss_engine.active
        if job is not None and not job['stop'].is_set():
            job['imbue_id'] = uid
            job['imbue_retry'] = job['imbue_until'] = 0.0
            job['imbue_seen_active'] = False


def watch_boss_hotkeys(plan):
    f1_held = bool(user32.GetAsyncKeyState(PAGE_KEYS[0]) & 0x8000)
    f4_held = False
    while boss_plan is plan:
        f1_now = bool(user32.GetAsyncKeyState(PAGE_KEYS[0]) & 0x8000)
        f4_now = bool(user32.GetAsyncKeyState(PAGE_KEYS[-1]) & 0x8000)
        if f4_now and not f4_held:
            plan['f4'].set()
            _boss_engine.stop('F4: dừng Boss nền', notify=False)
        elif f1_now and not f1_held and not f4_now:
            client = get_client() or {}
            window = client.get('window')
            if window and window == user32.GetForegroundWindow():
                plan['f1'].set()
        f1_held, f4_held = f1_now, f4_now
        sleep(0.01)


def read_boss_settings(owner):
    page = QtBind.text(gui, boss_group_field) or 'F1'
    sync_skill_rows()
    groups = compile_skill_groups({page}, allow_empty=True)
    if page not in groups:
        raise ValueError('Nhóm Boss %s chưa có skill đang bật.' % page)
    group = groups[page]
    sequence = [(uid, None if uid in group['natural'] else round(group['delays'][uid] * 1000))
                for uid in group['order']]
    uid = configured_imbue()
    if uid and any(skill == uid for skill, _ in sequence):
        raise ValueError('Bỏ ID tay phép khỏi dãy đánh Boss.')
    early = float(QtBind.text(gui, imbue_early_field) or '0.8')
    if not 0 <= early <= 10:
        raise ValueError('Làm mới tay phép sớm cần từ 0 đến 10 giây.')
    player = QtBind.text(gui, boss_exchange_player_field).strip()
    if player.casefold() == owner[1].casefold():
        raise ValueError('Acc hỗ trợ không thể là chính acc đánh Boss. Có thể để trống.')
    # Empty support name => solo Boss (7081→Boss UID, SROPlus/hiep). Named support keeps helper Exchange.
    return dict(page=page, sequence=sequence, imbue_id=uid, imbue_early=early, player=player)


def tick_armed_boss():
    plan = boss_plan
    if plan is None:
        return
    character = get_character_data() or {}
    if owner_of(character) != plan['owner'] or character.get('dead') or get_status():
        disarm_boss()
        if boss_running():
            _boss_engine.stop('nhân vật đã đổi, chết hoặc bot chính đang chạy')
        else:
            message = 'Auto Boss dừng: nhân vật đã đổi, chết hoặc bot chính đang chạy.'
            QtBind.setText(gui, status_label, message)
            report_error(message)
        return
    if plan['f4'].is_set():
        plan['f4'].clear()
        plan['f1'].clear()
        plan['enabled'] = False
        QtBind.setText(gui, status_label, 'Auto Boss đã dừng · bấm F1 để đánh lại.')
        return
    if plan['f1'].is_set():
        plan['f1'].clear()
        if _boss_engine.active is not None:
            return
        try:
            plan.update(read_boss_settings(plan['owner']))
        except ValueError as error:
            plan['enabled'] = False
            QtBind.setText(gui, status_label, str(error))
            report_error('Chưa bật Auto Boss: %s' % error)
            return
        plan['enabled'] = True
        plan['last_selection'] = None
        QtBind.setText(gui, status_label, 'Auto Boss · chọn Boss/quái trong game.')
    if not plan['enabled']:
        return
    with _boss_engine.LOCK:
        target = _boss_engine.confirmed_target
        revision = _boss_engine.selection_revision
        if boss_plan is not plan or _boss_engine.active is not None or revision == plan['last_selection']:
            return
        if _boss_engine.live_target(target):
            plan['last_selection'] = revision
            _boss_engine.start(target, plan['sequence'], plan['imbue_id'], plan['imbue_early'], plan['player'])
        elif target:
            QtBind.setText(gui, status_label, 'UID %d đã chọn · chưa thấy Boss/quái còn sống.' % target)
        elif _boss_engine.selected:
            QtBind.setText(gui, status_label, 'Auto Boss · chờ B045 xác nhận UID %d.' % _boss_engine.selected)
        else:
            QtBind.setText(gui, status_label, 'Auto Boss · chọn Boss/quái trong game.')


def start_clicked(arm_only=False, auto_pk_page=None):
    global boss_plan
    end_damage_meter('Dừng đo vì đã bật chế độ đánh.')
    if QtBind.isChecked(gui, boss_mode_box):
        if boss_plan is not None:
            if not arm_only and _boss_engine.active is None:
                boss_plan['f1'].set()
                tick_armed_boss()
            return
        _bg_base_stop()
        try:
            if not user32:
                raise ValueError('Auto Boss cần client Windows.')
            character = get_character_data() or {}
            owner = owner_of(character)
            if not owner or character.get('dead') or get_status():
                raise ValueError('Vào game bằng nhân vật còn sống và dừng bot chính trước.')
            if owner != profile_owner:
                raise ValueError('Chờ phBot nạp cấu hình nhân vật rồi bấm Bật.')
            boss_plan = dict(read_boss_settings(owner), owner=owner, last_selection=None,
                             enabled=False, f1=Event(), f4=Event())
            QtBind.setText(gui, status_label, 'Auto Boss %s · chọn Boss rồi bấm F1.' % boss_plan['page'])
            Thread(target=watch_boss_hotkeys, args=(boss_plan,), daemon=True).start()
            if not arm_only:
                boss_plan['f1'].set()
                tick_armed_boss()
        except ValueError as error:
            QtBind.setText(gui, status_label, str(error))
            report_error('Chưa bật Auto Boss: %s' % error)
        return
    disarm_boss()
    _boss_engine.stop('chuyển sang Auto Ghost hoặc Auto số', notify=False)
    return _bg_base_start(auto_pk_page=auto_pk_page)


callback_errors = {}


def report_callback_failure(where, error):
    from traceback import extract_tb
    frames = extract_tb(error.__traceback__)
    location = '%s:%d' % (frames[-1].name, frames[-1].lineno) if frames else '?'
    key = where, location, type(error).__name__
    now = monotonic()
    with pvp_lock:
        last = callback_errors.get(key)
        if last is None or now - last >= 5:
            callback_errors[key] = now
            report_error('%s [%s] %s: %s' % (where, location, type(error).__name__, error))
        was_auto_pk = auto_pk_running
        if was_auto_pk:
            hold_auto_pk('lỗi callback, xem Log', retry_after=1.0)
        return was_auto_pk


def event_loop():
    try:
        tick_damage_meter()
        tick_armed_boss()
        with pvp_lock:
            runtime = auto_pk_runtime
            now = monotonic()
            if auto_pk_running and runtime and now >= runtime.get('display_at', 0):
                runtime['display_at'] = now + 0.75
                scan_auto_pk_evidence(runtime)
        with _boss_engine.LOCK:
            message = _boss_engine.updates[-1] if _boss_engine.updates else None
            _boss_engine.updates.clear()
        if message and QtBind.isChecked(gui, boss_mode_box):
            QtBind.setText(gui, status_label, message[:95])
        if not boss_running():
            return _bg_base_event()
    except Exception as error:
        report_callback_failure('event_loop', error)


def handle_joymax(opcode,data):
    try:
        observe_pvp_stun(opcode, data)
        observe_push_packet(False, opcode, data)
        observe_damage_meter(False, opcode, data)
        owned=boss_running()
        _boss_engine.handle_joymax(opcode,data)
        if owned:return True
        return _bg_base_joymax(opcode,data)
    except Exception as error:
        report_callback_failure('S→C %04X' % opcode, error)
        return True


def handle_silkroad(opcode,data):
    try:
        observe_push_packet(True, opcode, data)
        observe_damage_meter(True, opcode, data)
        owned=boss_running()
        _boss_engine.handle_silkroad(opcode,data)
        if owned:return True
        return _bg_base_silkroad(opcode,data)
    except Exception as error:
        stopped = report_callback_failure('C→S %04X' % opcode, error)
        return not (stopped and opcode in (0x7045, 0x7074))


def teleported():
    global pvp_stunned_character
    with pvp_lock:
        pvp_stunned_character = None
    end_damage_meter('Đã dừng đo.')
    disarm_boss()
    _boss_engine.stop('nhân vật dịch chuyển', notify=False)
    _boss_engine.selected = _boss_engine.confirmed_target = 0
    return _bg_base_teleported()


def disconnected():
    global pvp_stunned_character
    with pvp_lock:
        pvp_stunned_character = None
    end_damage_meter('Đã dừng đo.')
    disarm_boss()
    _boss_engine.stop('mất kết nối')
    _boss_engine.selected = _boss_engine.confirmed_target = 0
    return _bg_base_disconnected()


def finished():
    global hidden_game
    if hidden_game is not None:
        window, pid = hidden_game
        set_game_window_visibility(window, pid, True)
        hidden_game = None
    end_damage_meter('Đã dừng đo.')
    disarm_boss()
    _boss_engine.stop('đóng phBot/plugin', notify=False)
    return _bg_base_finished()


show_view('pvp')
log('[%s] Đã nạp thành công v%s.' % (NAME, VERSION))
