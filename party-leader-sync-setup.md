# PartyLeader v1.0.5 + AutoGhost v1.8.67

## jsDelivr
Cùng commit SHA trên PR — xem chat.

## Phụ
1. Cài AutoGhost **1.8.67** + PartyLeader **1.0.5**, reload.
2. Tick **Phụ** · **Lấy tên chủ PT** → `CharName, *job` (CharName thật, không job AG_He).
3. Bật plugin: **grace ~12s** trước luật khoảng cách (không clear storm ngay).
4. `ks` → trace **CharName** + Auto PK F.
5. Ally filters: Party luôn bỏ qua; Guild/Liên minh mặc định bật.

## HARD
- Chủ xa **>10 m** (sau grace): dừng cast + `start_trace(CharName)` — **không** tắt Auto PK.
- Chủ **F4 / dừng Ghost**: phụ **stop attack + trace theo chủ ngay**.
- Disconnect giả khi Phụ+arm: AutoGhost **giữ** Auto PK.
