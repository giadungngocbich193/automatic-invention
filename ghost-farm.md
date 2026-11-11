# GhostFarm v1.0.3

Standalone phBot Stable plugin to **Ghost farm quái/NPC** in a radius (default **50 m**). Uses **NativeCut / `client_7081`**. **Not** `inject_joymax` for Ghost (7045 select uses inject).

Does **not** modify AutoGhost / PartyLeader.

## v1.0.3 — Target monster fix

v1.0.2 Target mode NativeCut’d the **monster UID** → `7081 OBSERVED` + `B081` + game “Không thấy mục tiêu” / no `B074` (OK=0).

Fix:

- **Prefer Self**: NativeCut **self UID** interrupt (proven `B074 02 00`) when any living monster/NPC is in radius.
- **Target monster**: `inject_joymax(0x7045, monster_uid)` select first, then NativeCut **self** (never Ghost the monster UID).
- Only Ghost while a living monster/NPC remains in range (Target also requires the selected UID still in range).

## AutoGhost coexistence (v1.0.2)

If AutoGhost owns GetTickCount, GhostFarm **reuses** the matching THUNK. Conflict → 8s backoff.

## Install

Copy `GhostFarm.py` into phBot `Plugins/`, reload.

## jsDelivr

`https://cdn.jsdelivr.net/gh/giadungngocbich193/automatic-invention@<commit>/GhostFarm.py`
