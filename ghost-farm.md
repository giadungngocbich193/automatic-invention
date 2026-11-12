# GhostFarm v1.0.12

Standalone phBot farm Ghost loop: **cast → mid-cut at 7074+cfg_ms → next skill → repeat**.

**Cut UID = Self OR Monster/Boss only. Never a player. Never trade/inject 7081.**

**Interrupt = NativeCut `bridge.arm(2)` → C→S `0x7081` → B074 `02 00`.**

## Modes

| Mode | 7081 cut UID |
|------|----------------|
| **Monster/Boss 7081** (default) | Living monster/NPC/boss skill target (SroPlus/hiep) |
| **Self** | Own `player_id` |

## Loop

1. **7045** select living monster/boss in radius  
2. Pre-warm NativeCut (`arm(1)` → `completed(4)`) — also at Start  
3. DROP training basic · **7074** skill on monster/boss  
4. Schedule **`cut_at = 7074 + cfg_ms`** (default **100**; ~120ms cast window)  
5. Event-loop **`arm(2)`** at cut_at (Timer nudge only); optional hiep ×2 ~15ms  
6. Next skill cycle  

B070 is confirm/log only — mid-cut is **not** B070+1–7ms (that was after cast ended → fake OK).

## Loud outcomes

| Result | Meaning |
|--------|---------|
| **OK MID-CUT** | `cut_fired` + observed 7081 + B074 `02 00` + `since_7074≈cut_cfg` |
| **FULL-CAST FAIL** | Natural B074 **before** `arm(2)` — skill finished (đánh hết); raise cfg (~100) |
| **GHOST FAIL** | No mid-cut this cycle (`cut_fired` / 7081 / B074 / NativeCut error) |

## Skill IDs (default ~100ms)

```
80031=100;66007=100;54016=100;81019=100;7678=100;81016=100;7653=100
```

`ms < 40` warns at Start — easy FULL-CAST on ~120ms skills.

## User must set

1. **Bật** ON  
2. Mode: Monster/Boss (default) or Self  
3. Skill IDs (prefilled 100)  
4. **Start farm** on **Windows** phBot + Silkroad HWND (not Clientless)  
5. Disable Training; unload AutoGhost Ghost if GetTickCount conflict  

## Log lines that MUST appear if mid-cut worked

```
C→S 0x7074 CAST · … · mid-cut NativeCut @monster|self=… at 7074+cut_cfg=100ms
CUT SCHEDULED · cut_cfg=100ms · … · 7081@monster|self=…
NativeCut arm(2) MID-CUT · 7081@monster|self=… · since_7074≈100
C→S 0x7081 OBSERVED (NativeCut @monster|self) …
S→C 0xB074 … 02 00
OK MID-CUT NativeCut @monster|self=… · 7081=YES · B074 02 00
```

## FULL-CAST FAIL signature

```
FULL-CAST FAIL · natural B074 BEFORE mid-cut · cut_cfg=… · since_7074=…
```

## jsDelivr

After push, pin commit SHA:

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
