# GhostFarm v1.0.5

Standalone phBot farm: **7045 select → 7074 cast → wait ms → NativeCut self**.

## Skill IDs (per-skill Ghost delay)

```text
80031=1;66007=20;54016=0;81019=15
```

`skillId=ms` = milliseconds to wait after cast before NativeCut self interrupt.
Bare ids (`3048,3050`) use delay `0`.

## Loop

1. **SELECT** living monster in radius (7045) — if none, soft-skip cycle (no Ghost)
2. **CAST** 7074 skill on that UID
3. **WAIT** the skill’s ms
4. **NativeCut self** — even if the monster died mid-cast (Ghost is self-UID)

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload.

## jsDelivr

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
