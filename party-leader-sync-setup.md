# PartyLeader v1.0.10 + AutoGhost v1.8.71

## Reload
Tab title **must** show `PartyLeader v1.0.10` and `AutoGhost v1.8.71`. Xóa bản cũ trong Plugins.

## Ally filter (AutoGhost)
- Không đánh: **Party** + **Guild** only.
- **No Liên minh / alliance**.
- Missing party/guild data ⇒ **do not skip** (stranger still attackable).

## Trace / Leader
- Field label: **tên Leader cần theo** (manual OK). Button **Lấy tên chủ PT** kept.
- `start_trace('AG_He')` / `*AG_He` hard-allowed (tries multiple forms).
- >10m: clear prefer + soft-stop + Trace/chase.

## Camp return
- UID ra vùng đánh từ điểm chờ → **bỏ khóa + quay về**.
- Party prefer unreachable → soft-clear (không cast forever).
- Log debounce ≤2s.

## Ghost nền / F4
- Party prefer uses normal **7081/B074** Ghost interrupt (no silent normal-attack lock).
- After F4 Auto PK off, prefer **re-arms** Ghost without UI.

## Persist
Lưu/Tải + plugin_load + joined_game + deferred/event_loop re-sync:
Bật, Sync, ks AutoPK, chat ks#, Chủ/Phụ, F, Leader.

## jsDelivr
Pin commit SHA on PR after verified push.
