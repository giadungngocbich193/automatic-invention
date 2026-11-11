# GhostFarm v1.0.0

Standalone phBot Stable plugin to **Ghost farm quái/NPC** in a radius (default **50 m**). Uses the **same NativeCut / `client_7081` path** proven in GhostNativeProbe (self UID → `B074 02 00`). **Not** `inject_joymax`.

Does **not** modify AutoGhost / PartyLeader.

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload plugins. Prefer **not** running AutoGhost Ghost cut at the same time (both hook GetTickCount).

## UI

| Control | Action |
|---------|--------|
| Bật / Tắt | Must be ON before Start; OFF stops + tháo móc |
| Bán kính (m) | Scan radius for `get_monsters` / `get_npcs` (default 50, max 200) |
| Chế độ Ghost | **Self** = NativeCut self UID when any monster/NPC is in radius; **Target monster** = NativeCut nearest living monster/NPC UID (prefers last `0x7045` if still in radius) |
| Start farm | Begin scan → NativeCut loop |
| Stop farm | Stop + tháo móc |
| Làm mới | Re-read Self UID, radius, nearby list |
| Tháo móc | Restore GetTickCount / close session |

## Loop

```text
Start → scan monsters+NPCs in radius
  → pick UID by mode (Self / Target monster)
  → NativeCut arm(1) verify → arm(2) client_7081
  → observe C→S 0x7081 + B074 02 00
  → gap ~0.75s → scan again
```

## jsDelivr

After PR push, pin:

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
