# GhostFarm v1.0.4

Standalone phBot farm: **select → cast → Ghost interrupt**. Does **not** modify AutoGhost / PartyLeader.

## Combat loop (every cycle)

1. **7045** select a living monster/NPC in radius (logged) — **required**
2. **7074** cast attack skill ID on that UID (`01 04 <skill> 01 <target>`)
3. **NativeCut self** interrupt while casting (proven `B074 02 00`)

**Never Ghost** if there is no living in-range target, no Self UID, or no Skill IDs.

## UI

| Control | Action |
|---------|--------|
| Bán kính (m) | Scan radius (default 50) |
| Skill IDs (F1) | Comma-separated skill IDs, e.g. `3048,3050` |
| Start farm | Begin combat loop |
| Stop / Tháo móc | Stop + close NativeCut session |

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload. Prefer not double-hooking GetTickCount with AG Ghost cut (v1.0.2 can reuse AG’s thunk).

## jsDelivr

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
