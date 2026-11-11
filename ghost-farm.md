# GhostFarm v1.0.7

Standalone phBot farm with **overlapping Ghost interrupt** via the proven AutoGhost / GhostNativeProbe `NativeCut` path (`client_7081`).

## Why 1.0.7

v1.0.6 rebased the cut timer on **B070**, so with `cfg=1` the log showed `since_7074≈500ms` / `b070+1ms` — cut after the cast window, not a real mid-cast Ghost.

## Timing (exact AG cut body, Farm anchor)

AG client_7081 body: `Timer(delay)` → `queue_interrupt` → `begin_native_cut` → `send_pvp_interrupt` → `bridge.arm(2)`.

Farm difference vs AG PVP: AG starts that Timer on **B070**; Farm starts it on **7074 send** (B070 is log-only — never rebases `cut_at`).

1. **7045** select living monster  
2. **Pre-warm** NativeCut (`arm(1)` → `completed(4)`) **before** cast  
3. **7074** cast skill on monster  
4. **`Timer(cfg_ms)` from 7074** → `bridge.arm(2)` (self UID)  
5. Success = observed C→S `0x7081` + B074 `02 00`  
6. Log must show `since_7074≈cfg ms` (not ~500ms)

## Skill IDs

```text
80031=1;66007=20;54016=0;81019=15
```

`skillId=ms` after **7074 send**.

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload.

## jsDelivr

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
