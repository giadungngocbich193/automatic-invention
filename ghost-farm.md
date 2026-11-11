# GhostFarm v1.0.6

Standalone phBot farm with **overlapping Ghost interrupt** (AutoGhost-style timing).

## Why 1.0.6

v1.0.5 waited `ms` **then** installed/verified NativeCut, so `arm(2)` often landed **after** the cast finished (XP already granted). Result: `B074 02 00` without a real skill-reset Ghost feel.

## Timing (AG-like)

1. **7045** select living monster  
2. **Pre-warm** NativeCut (arm(1) verify) **before** cast  
3. **7074** cast skill on monster  
4. Prefer **B070** confirm → wait `ms` → **arm(2)** immediately  
   Fallback: `ms` from 7074 send if no B070 (~1.2s)  
5. Hook is already ready — cut overlaps the cast (does not wait for cast end / monster death)

## Skill IDs

```text
80031=1;66007=20;54016=0;81019=15
```

`skillId=ms` after B070 (preferred) or after 7074 send.

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload.

## jsDelivr

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
