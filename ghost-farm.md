# GhostFarm v1.0.11

Standalone phBot farm with **overlapping Ghost interrupt** via NativeCut `client_7081` (same path as GhostNativeProbe / AutoGhost PVP).

**Interrupt = NativeCut `bridge.arm(2)` self UID → C→S `0x7081` → B074 `02 00`.**  
Never `inject_joymax(0x7081)`.

## Why 1.0.11 (overnight “có ghost đâu”)

1.0.9 DROP-basic (+ 1.0.10 Skill ID prefill) was not enough. Silent fails still hid missing Ghost:

- Timer thread could skip `arm(2)` when `active`/phase gates failed **without a log**
- B070 skill/source/target rejects were **silent**
- Failed cycles ended as vague `XONG` instead of loud **GHOST FAIL**
- Unconditional `7074` cancel before cast could abort the skill (no B070)

v1.0.11:

- **Event-loop fires cut at `cut_at`** (Timer is nudge only)
- **Retarget** self UID in thunk page before every `arm(2)`
- Log every **B070 REJECT** / **CUT SKIP**
- Every miss: loud **`GHOST FAIL`** (`cut_fired` / `7081` / `B074` / NativeCut error)
- Cancel before cast **only if** basic was dropped
- Start refuses non-Windows / missing HWND with **GHOST BLOCKED**

## Why 1.0.10

Prefill Skill IDs from confirmed Auto PK F1 skill+Ngắt table (blank IDs skipped; no 81037).

## Timing

1. **7045** select living monster  
2. Pre-warm NativeCut (`arm(1)` → `completed(4)`) — also at Start  
3. DROP training basic · **7074** skill  
4. Wait **S→C B070** (skill + self source; target mismatch = WARN but still cut)  
5. **`cut_at = B070 + cfg_ms`** → event_loop **`arm(2)`** self  
6. Fallback: no B070 in **800ms** → cut from 7074+cfg  
7. Success = **C→S 0x7081** + **B074 `02 00`**

## Skill IDs (prefilled)

```text
80031=1;66007=5;54016=1;81019=5;7678=1;81016=7;7653=5
```

`skillId=ms` after **B070**, not after 7074.

## User must set

1. Tick **Bật**  
2. Confirm **Skill IDs** (prefilled; edit if needed)  
3. **Start farm** (Windows phBot + Silkroad window — not Clientless)  
4. Prefer disable Training combat  
5. If NativeCut / GetTickCount conflict: unload **AutoGhost Ghost/PvP** (Farm can adopt same THUNK)

## Log lines that MUST appear if Ghost worked

```text
S→C 0xB070 CAST CONFIRM · skill=… · hẹn NativeCut arm(2) …
NativeCut arm(2) CUT NOW · transport=client_7081 · NOT inject · since_B070≈cfg
C→S 0x7081 OBSERVED (NativeCut self) …
S→C 0xB074 … 02 00 · NGẮT OK
OK GHOST NativeCut self · 7081=YES · B074 02 00
```

## Overnight “no Ghost” diagnostics

```text
GHOST FAIL · no Ghost this cycle · cut_fired=… · observed_7081=NO · B074=…
B070 REJECT skill · …
CUT SKIP · …
GHOST BLOCKED — NativeCut chỉ chạy Windows …
GHOST FAIL NativeCut … GetTickCount … unload AutoGhost
```

## Install

Copy `GhostFarm.py` → phBot `Plugins/`, reload.

## jsDelivr

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@044638ef90421443a48a88663b74461b5d2c2c58/GhostFarm.py`
