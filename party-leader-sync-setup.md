# PartyLeader v1.0.8 + AutoGhost v1.8.68

## Reload
Tab title **must** show `PartyLeader v1.0.8` and `AutoGhost v1.8.68`. Xóa bản cũ trong Plugins.

## Trace / chủ PT
- Chủ job nick **AG_He / *AG_He** được phép Trace / `start_trace`.
- Prefer party master **CharName** nếu có; không thì dùng **job name**.
- Không còn reject “Trace cần CharName thật” cho job nick.

## Soft-stop (>10m / F4)
- Phụ dừng đánh bằng soft-hold Ghost/Auto PK (memory only).
- **Không** inject `7046`/`7074`, **không** `stop_bot` (tránh client DC).
- Giữ Auto PK armed + Trace theo chủ.

## Persist (Lưu / Tải / auto-load)
Lưu & khôi phục:
- Bật plugin
- Đồng bộ mục tiêu
- ks: bật AutoGhost Auto PK
- Chủ: chat party ks#UID
- Chủ / Phụ
- Nhóm Ghost F
- Leader name

Nạp plugin / vào game → **auto-apply** (kể cả Bật=ON nếu đã lưu).

## jsDelivr
Pin commit SHA trên PR.
