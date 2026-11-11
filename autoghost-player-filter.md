# AutoGhost — nhận diện người chơi (get_players)

**Plugin version:** AutoGhost **v1.8.69** (+ PartyLeader **v1.0.9**)

## Tóm tắt (VN)

| Câu hỏi | Trả lời |
|--------|---------|
| Có lọc đỏ/tím / job? | **Có** — list-select ưu tiên đỏ/tím hoặc job đạo tặc↔bảo tiêu |
| Lọc Party? | **HARD luôn bật** — không bao giờ Auto PK người cùng nhóm (`get_party`), kể cả tên job `*AG_BangChu` |
| Lọc Guild / Liên minh? | Checkbox **Guild (G)** / **Liên minh** (mặc định bật) qua `get_guild` / `get_guild_union` |
| Party sync phụ? | Prefer UID → Ghost F cast ngay; never retire prefer; soft-hold; Trace AG_He |
| ALT? | Không |
| Inject 7045 người? | Solo: Target Enemy. Party sync: không cần 7045 thành công |
| Buff VK F1/F2/F3? | Cần **Lấy đồ** đúng F; thiếu model → báo rõ tab Đồ |

## Vì sao game báo “không thể tấn công người trong cùng nhóm”?

Bản trước có thể chọn nhầm PT (lệch `*` job name). **1.8.67+** bỏ qua mọi UID/tên trong `get_party` trước khi Target/Ghost. Soft-hold **1.8.68** không inject khi >10m.

## Doc path

`/cursor/stores/self/docs/autoghost-player-filter.md`
