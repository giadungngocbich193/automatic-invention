# GhostFarm v1.0.8

Standalone phBot farm with **overlapping Ghost interrupt** via the proven AutoGhost / GhostNativeProbe `NativeCut` path (`client_7081`).

## Why 1.0.8

v1.0.7 fired `Timer(cfg)` from **7074 send**. With `cfg≈1–30ms` that aborted the cast **before** the server confirm (`B070`), so skills did not hit (`skill không đánh`) and there was no real mid-animation Ghost.

## Timing (AutoGhost PVP, byte-for-byte)

AG `handle_joymax` on `0xB070` (len≥19, skill@3, source@7, target@15):

`Timer(delay)` → `queue_interrupt` → `fire_interrupt` → `begin_native_cut` → `send_pvp_interrupt` → `bridge.arm(2)`

Farm mirrors that:

1. **7045** select living monster  
2. **Pre-warm** NativeCut (`arm(1)` → `completed(4)`) **before** cast  
3. **7074** cast skill on monster  
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

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload.

## jsDelivr

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
