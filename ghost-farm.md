# GhostFarm v1.0.13

Standalone phBot farm Ghost loop: **cast → mid-cut at 7074+cfg_ms → next skill → repeat**.

**Locked A/B cut (GhostCutProbe 1.1.0):** NativeCut `client_7081` → **monster/boss UID ×2** (+15ms).  
Never self primary · never player neighbor · never `inject_joymax(0x7081)`.

## Cut path

1. **7045** select living monster/boss in radius  
2. Pre-warm NativeCut (`arm(1)` → `completed(4)`) — also at Start  
3. DROP training basic · **7074** skill on monster/boss  
4. Schedule **`cut_at = 7074 + cfg_ms`** (per-skill from Skill IDs)  
5. Event-loop **`arm(2)`** at cut_at → retarget monster UID → **7081 ×2** (~15ms)  
6. Success = observed 7081 + B074 `02 00` → **OK MID-CUT**  

## Modes

| Mode | Behavior |
|------|----------|
| **Monster/Boss 7081** (default) | Cut UID = living monster/boss (locked winner) |
| **Self (A/B fail)** | Combo kept for layout; cut still uses **monster UID** |

## Skill IDs default (prefill)

```
80031=1;66007=50;54016=1;81019=50;7678=1;81016=7;7653=50
```

`=5`→`=50` when cut too fast; `=1` / `=7` kept as user wrote.

## Loud outcomes

| Result | Meaning |
|--------|---------|
| **OK MID-CUT** | `cut_fired` + observed 7081 + B074 `02 00` |
| **FULL-CAST FAIL** | Natural B074 **before** `arm(2)` |
| **GHOST FAIL** | Miss this cycle |

## User must set

1. **Bật** ON  
2. Mode: Monster/Boss (default)  
3. Skill IDs (prefilled above)  
4. **Start farm** on **Windows** phBot + Silkroad HWND  
5. Disable Training; unload AutoGhost Ghost if GetTickCount conflict  

## jsDelivr

https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@c75ba0ba3e7697dea0f40fcd1a5c3e80a21255aa/GhostFarm.py

Raw: https://github.com/giadungngocbich193/automatic-invention/raw/c75ba0ba3e7697dea0f40fcd1a5c3e80a21255aa/GhostFarm.py
