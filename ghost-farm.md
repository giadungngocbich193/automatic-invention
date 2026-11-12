# GhostFarm v1.0.14

Standalone phBot farm Ghost loop: **cast → mid-window cut at 7074+cfg_ms → next skill**.

## Honest rule (1.0.14)

**B074 `02 00` alone is NOT Ghost.**  
v1.0.13 logged OK MID-CUT on early 7081 + natural B074 (cfg 1/7/50 → since_7074 ~14/61) while the skill still looked full cast. That was **PACKET-FAKE**.

Success now requires mid-window timing; status is **CUT TIMING OK · VERIFY VISUAL** (never “OK Ghost” from packets). Failures are loud **PACKET-FAKE FAIL** / **CFG-IGNORED** / **CUT-TOO-EARLY**.

## Cut path

1. **7045** select living monster/boss  
2. Pre-warm NativeCut (7081 mode)  
3. **7074** skill on monster/boss  
4. Cut at **7074 + cfg_ms** (default **100**; tiny ms auto-bumped ≥80 → 100)  
5. Transport:
   - **Monster/Boss 7081** (default): NativeCut `client_7081` ×2 (+15ms)
   - **Weapon 7034**: bag↔weapon swap (probe A/B)
6. Score B074 vs cut time — not B074 alone  

Solo monster/boss only. No self primary. No player neighbor. No `inject_joymax(0x7081)`.

## Skill IDs default

```
80031=100;66007=100;54016=100;81019=100;7678=100;81016=100;7653=100
```

## Loud outcomes

| Result | Meaning |
|--------|---------|
| **CUT TIMING OK · VERIFY VISUAL** | Cut near cfg · B074 soon after cut · inside cast window — still confirm animation |
| **PACKET-FAKE FAIL** | 7081/7034 + B074 02 00 but B074 late / full-cast length |
| **CFG-IGNORED / CUT-TOO-EARLY** | Cut did not land on mid-window cfg |
| **FULL-CAST FAIL** | Natural B074 before cut |
| **GHOST FAIL** | Miss action / B074 / NativeCut error |

## jsDelivr

*(pin filled after ship commit)*
