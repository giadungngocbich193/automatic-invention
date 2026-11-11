# PartyLeader v1.0.9 + AutoGhost v1.8.69

## Reload
Tab title **must** show `PartyLeader v1.0.9` and `AutoGhost v1.8.69`. Xóa bản cũ trong Plugins.

## Trace / chủ PT
- `start_trace('AG_He')` / `*AG_He` **always OK** on Phụ.
- Prefer party master CharName if available; else job name.
- Phụ role checkbox is authoritative (job nick never flips to “mình là chủ”).

## Party prefer → Ghost cast
- Prefer UID locks target and **casts Ghost F skills immediately**.
- Prefer UID is **never retired/skipped** after B070 miss — soft-wait + retry.
- No spam log “tạm bỏ qua UID · dò mục tiêu khác” for party prefer.

## Soft-stop (>10m / F4)
- Memory-only hold (no `7046`/`7074`, no `stop_bot`).

## Persist
Lưu/Tải/auto-load all ticks (Bật, sync, ks Auto PK, chat ks#, Chủ/Phụ, F, Leader).

## jsDelivr
Pin commit SHA on PR after push.
