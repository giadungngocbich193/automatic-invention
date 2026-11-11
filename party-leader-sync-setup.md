# PartyLeader v1.0.4 + AutoGhost v1.8.67 (baseline AutoGhost_2600)

## jsDelivr
Cả hai file **cùng commit SHA** — xem chat agent / PR.

## Phụ
1. Cài AutoGhost **1.8.67** + PartyLeader **1.0.4**, reload (bỏ bản cũ).
2. Tick **Phụ** · **Lấy tên chủ PT** (`CharName, job_name` — CharName thật, chấp nhận `*job`) · F1/F2/F3 · Lưu.
3. AutoGhost: điền skill F, Lưu. PartyLeader: tick **ks: bật AutoGhost Auto PK**.
4. Ally filters (Auto PK): Party / Guild (G) / Liên minh — mặc định bật.

## Chủ
1. Tick **Chủ** · Lấy tên mình · Lưu.
2. Party chat **`ks`** → phụ trace (CharName) + Auto PK đúng F.
3. Chọn/đánh → phụ **prefer UID + Ghost** (không phụ thuộc 7045).
4. Bỏ target / F4 / dừng Ghost → phụ clear / dừng đánh ngay.
5. `ks off` / `dung` → dừng trace + tắt Auto PK.

## HARD Phụ
- Chỉ đánh UID của chủ (không tự dò mục tiêu khác).
- Chủ dừng đánh → phụ dừng cast ngay.
- Chủ >5 m → phụ dừng đánh + `start_trace(CharName)` (không dùng job name).
- Không camp/return Auto PK; disconnect giả không tắt Auto PK khi party_lock.
- Thiếu B070 / reclick-max **không** còn `Auto Ghost dừng … chưa có B070 … sau 3 lần thử lại`.
