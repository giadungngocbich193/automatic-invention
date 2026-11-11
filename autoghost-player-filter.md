# AutoGhost — nhận diện người chơi (get_players)

**Plugin version:** AutoGhost **v1.8.70** (+ PartyLeader **v1.0.10**)

## Tóm tắt (VN)

| Câu hỏi | Trả lời |
|--------|---------|
| Có lọc đỏ/tím / job? | List-select vẫn ưu tiên đỏ/tím hoặc job (riêng) |
| Lọc Party? | **HARD** — không Auto PK người cùng `get_party` |
| Lọc Guild? | Checkbox **Guild (G)** — cùng `get_guild` / cùng guild string |
| Lọc Liên minh? | **Không** — đã gỡ hoàn toàn |
| Unknown / thiếu data? | **Không skip** — vẫn đánh được stranger |
| Party sync phụ? | Prefer → Ghost F + 7081/B074 nền; Trace AG_He; soft-hold |

## Vì sao trước đây camp đứng im?

Filter cũ có thể over-match (union / guild-name-in-names). **1.8.70** chỉ skip đúng cùng Party hoặc cùng Guild.

## Doc path

`/cursor/stores/self/docs/autoghost-player-filter.md`
