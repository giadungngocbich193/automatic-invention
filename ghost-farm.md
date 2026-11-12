# GhostFarm v1.0.9

Standalone phBot farm with **overlapping Ghost interrupt** via the proven AutoGhost / GhostNativeProbe `NativeCut` path (`client_7081`).

## Why 1.0.9 (fix “toàn đánh thường”)

After `7045` select, **phBot Training / client basic** `7074 01 01 01` kept swinging while GhostFarm waited on NativeCut prewarm. Skill `7074` often never got `B070`, so the loop looked like plain basic attacks and Ghost never lined up.

v1.0.9:

- While farming: **DROP** client basic `7074 01 01 01`
- **Cancel** current action before skill cast
- **Prewarm NativeCut at Start** (non-blocking `arm(1)`)
- `close_session` no longer clears `active` (B070 Timer could skip `arm(2)`)
- Empty Skill IDs → loud STOP (no silent basic-only)
- cut_wait **backup** if Timer died without cut

## Why 1.0.8

v1.0.7 fired `Timer(cfg)` from **7074 send**. With `cfg≈1–30ms` that aborted the cast **before** the server confirm (`B070`), so skills did not hit (`skill không đánh`) and there was no real mid-animation Ghost.

## Timing (AutoGhost PVP, byte-for-byte)

AG `handle_joymax` on `0xB070` (len≥19, skill@3, source@7, target@15):

`Timer(delay)` → `queue_interrupt` → `fire_interrupt` → `begin_native_cut` → `send_pvp_interrupt` → `bridge.arm(2)`

Farm mirrors that:

1. **7045** select living monster  
2. **Pre-warm** NativeCut (`arm(1)` → `completed(4)`) **before** cast (also kicked at Start)  
3. DROP training basic · cancel · **7074** cast skill on monster  
4. **Wait S→C B070** (same skill / self source / select target)  
5. **`Timer(cfg_ms)` from B070** → `bridge.arm(2)` (self UID)  
6. Fallback: if no B070 within **800ms**, cut as **7074+cfg_ms** (remaining time)  
7. Success = observed C→S `0x7081` + B074 `02 00`  
8. Log should show `since_B070≈cfg ms` (and a B070 line before the cut)

## Skill IDs

```text
80031=1;66007=20;54016=0;81019=15
```

`skillId=ms` after **B070** (AG), not after 7074.

## User must set

1. Tick **Bật**
2. Fill **Skill IDs** (required — empty = no 7074 / no Ghost)
3. **Start farm**
4. Prefer **Self** mode
5. Disable phBot **Training combat** (farm drops basic, but Training still fights the bot)
6. If NativeCut install fails: unload **AutoGhost Ghost/PvP** (shared GetTickCount) or let Farm adopt the same THUNK

## Verify logs (cut vs basic-only)

**Ghost OK:**

```text
C→S 0x7074 CAST · skill=…
S→C 0xB070 CAST CONFIRM · …
CUT TIMER scheduled · AG Timer(…) after B070
NativeCut arm(2) CUT NOW · … · since_B070≈cfg ms
C→S 0x7081 OBSERVED (NativeCut self)
S→C 0xB074 … 02 00 · NGẮT OK
```

**Basic-only / misconfig:**

```text
START từ chối — Skill IDs trống
DROP C→S 0x7074 basic (đánh thường)
B070 MISSING after 800ms · … (nếu chỉ thấy đánh thường: …)
```

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload.

## jsDelivr

jsDelivr pin:

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@e03913630c9a94c5fe69497367ea8b2306e2f427/GhostFarm.py`
