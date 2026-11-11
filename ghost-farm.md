# GhostFarm v1.0.2

Standalone phBot Stable plugin to **Ghost farm quái/NPC** in a radius (default **50 m**). Uses the **same NativeCut / `client_7081` path** proven in GhostNativeProbe (self UID → `B074 02 00`). **Not** `inject_joymax`.

Does **not** modify AutoGhost / PartyLeader.

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload plugins.

## AutoGhost coexistence (v1.0.2)

AutoGhost and GhostFarm share the client **GetTickCount** slot for NativeCut.

- If AutoGhost already installed its thunk, GhostFarm **reuses** it (same THUNK bytes) and retargets the UID — does **not** restore the tick on Farm Stop (AG still owns the hook).
- If reuse fails: status/log explains the conflict; **8s backoff** (no spam). Unload AutoGhost or turn off AG Ghost/PvP, then Start Farm again.

## v1.0.1

Fixed `Python: Exception occurred` spam from invalid `except ctypes.WinError`.

## UI

| Control | Action |
|---------|--------|
| Bật / Tắt | Must be ON before Start; OFF stops + tháo móc |
| Bán kính (m) | Scan radius for `get_monsters` / `get_npcs` (default 50, max 200) |
| Chế độ Ghost | **Self** / **Target monster** |
| Start farm | Begin scan → NativeCut loop |
| Stop farm | Stop + tháo móc (adopted hook: disarm only) |
| Làm mới | Re-read Self UID, radius, nearby list |
| Tháo móc | Close Farm session |

## jsDelivr

After PR push, pin:

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
