# Kiểm thử

Một việc chỉ coi là xong khi test của nó xanh và kịch bản demo của nó chạy tay đạt. Kết quả khác mong đợi thì sửa
code, không sửa kỳ vọng.

## 1. Quy ước

- pytest chạy trong container (ảnh `test` của `api/Dockerfile`), trên PostgreSQL thật `kho_test`
  (`infra/compose.test.yml`). Lý do: các quy tắc PT-02, PT-04, PT-05, PT-09 được ép bằng transaction, khoá chính và
  câu `UPDATE` có điều kiện; giả lập CSDL không bắt được lỗi ở đúng chỗ đó.
- Lệnh: `make test` (một thư mục: `make test T=tests/replica`); `make check` = kiểm tra file compose + pytest.
- `tests/conftest.py`: dựng schema từ `db/*.sql` mỗi phiên; mỗi test bắt đầu với CSDL trống. Chi tiết ở
  `tests/CLAUDE.md`.
- Đặt tên: `tests/<module>/test_<thành_phần>.py`, `<module>` trùng tên file trong `api/services/` (`branch`,
  `replica`). Docstring mỗi test ghi mã quy tắc (`"""PT-04: ..."""`).
- Không `sleep`, không gọi mạng thật. Phần gọi node khác tách thành hàm nhận dữ liệu đã lấy về.
- Hạ tầng (compose, nginx, script mô phỏng mạng) kiểm bằng `make config` và kịch bản chạy tay ở `docs/demo.md`.
  `make config` gọi `scripts/net.sh check`: 3 env local hợp lệ, cổng host không trùng, mỗi node đủ alias
  (`branch-<x>`, `replica-<x>`, `redpanda-a`) và nối vào `minigo-wan`, không gọi node khác bằng tên service, nginx đủ
  6 địa chỉ `REPLICA_*`, `BRANCH_*`. Chế độ máy thật: `config -q` với `may-a/b/c.env`;
  vòng 5 gom các kịch bản chính vào `scripts/chaos-check.sh`.

## 2. Quy tắc và test chứng minh

| Mã | Test | Trạng thái |
|---|---|---|
| PT-01 | — (kiểm khi tự duyệt: không có lời gọi mạng trong `services/branch.py`) | — |
| PT-02 | `tests/branch/test_change_stock.py`: `test_sale_writes_inventory_ledger_and_outbox_together`, `test_oversell_is_rejected_and_leaves_no_event` | xanh |
| PT-03 | chưa có (cần tách phần gửi khỏi `send_batch` để test không cần Redpanda) | — |
| PT-04 | `tests/replica/test_apply_event.py::test_duplicate_event_is_ignored` | xanh |
| PT-05 | `tests/replica/test_apply_event.py::test_older_event_arriving_late_does_not_overwrite_newer` | xanh |
| PT-06 | chưa có (kịch bản K6) | — |
| PT-07 | — (kiểm khi tự duyệt) | — |
| PT-08 | `tests/branch/test_change_stock.py::test_same_request_id_is_applied_once` | xanh |
| PT-09 | `tests/branch/test_change_stock.py::test_oversell_is_rejected_and_leaves_no_event` | xanh |
| PT-10 | vòng 3 | — |
| PT-11 | vòng 2 | — |

## 3. Kịch bản demo

Các bước chạy tay ở [demo.md](demo.md). "Đạt" ghi kèm ngày và cách chạy (một máy hay nhiều máy).

| Mã | Tính chất | Vòng | Trạng thái |
|---|---|---|---|
| K1 | Đồng bộ dữ liệu | 0 | đạt trên 1 node; đạt trên 3 node một máy (19/11/2026): bán ở CN2, 3 bản sao cùng dấu vân tay sau 2 giây |
| K2 | Trong suốt vị trí | 0, 1 | đạt trên 3 node một máy (19/11/2026): vệt `C A B C A B`, `/cn1/`–`/cn3/` mở đúng chi nhánh |
| K3 | Chịu lỗi, failover | 1 | đạt trên 3 node một máy (19/11/2026) bằng `make cut N=b`: vệt chỉ còn A, C; `/cn2/` báo mất liên lạc; POS B vẫn bán, outbox 20; bản sao B thấy CN2 sống, CN1, CN3 mất |
| K4 | Tự phục hồi | 1 | đạt trên 3 node một máy (19/11/2026) bằng `make heal N=b`: outbox về 0 trong ≤ 4 giây, 3 dấu vân tay khớp sau ~17 giây, vệt có lại B |
| K5 | Độ trễ mạng | 1 | đạt trên 3 node một máy (19/11/2026) bằng `tre.sh`: RTT tới A 5 → 605 ms, bán tại chỗ 2,2 ms; tắt thì vẫn khớp |
| K6 | Chống trùng khi phát lại | 0 | đạt trên 1 node; đạt trên 3 node một máy (19/11/2026): 86 bản trùng bỏ qua, dấu vân tay không đổi |
| K7a, K7b, K7c | Redpanda chịu lỗi | 2 | chưa có |
| K8 | Gossip tự vá | 3 | chưa có |
| K9 | Đối soát với chi nhánh | 3 | chưa có |
