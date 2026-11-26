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
  6 địa chỉ `REPLICA_*`, `BRANCH_*`; cụm broker (vòng 2): ở cả `local-*` lẫn `may-*`, `KAFKA_BROKERS` và
  `BROKER_SEEDS` đủ 3 broker, cùng host, giống nhau ở 3 file, `BROKER_HOST` mỗi node khác nhau và nằm trong danh
  sách, `COMPOSE_PROFILES` có `broker`, không còn `IP_A`; một máy: broker có alias `redpanda-<x>`, `--node-id` =
  `BRANCH_ID`, không publish cổng, console và topic-init nối vào `minigo-wan`; kênh trực tiếp (vòng 3): `replica_api`
  có `REPLICA_URLS` và `dns_opt timeout:1`, `branch_api` có `BRANCH_URL=http://branch-<x>:8000` (một máy) hoặc
  `http://<BROKER_HOST>:8001` (máy thật); cổng vào (vòng 5): nginx ở cả 3 node local và ở `config` của cả 3 file
  `may-*` (không còn profile), nối `minigo-wan`, đủ 6 địa chỉ; `GATEWAYS` có, giống nhau ở 3 file mỗi chế độ và chứa
  cổng của chính node (`http://localhost[:NGINX_PORT]`, máy thật `http://<BROKER_HOST>`); `may-*`: `REPLICA_X`,
  `BRANCH_X` là `<IP overlay máy X>:8000`, `:8001`; mọi service nối `minigo-wan` có `ipv4_address` trong
  `10.210.0.2`–`.127`, không trùng giữa các node; template nginx có `resolver 127.0.0.11`, mọi `server ${...}` có
  `resolve`, `proxy_pass` chỉ trỏ upstream, có CORS và `/lb/gateways.json`. Chế độ máy thật: `config -q` với `may-a/b/c.env`;
  vòng 8 gom các kịch bản chính vào `scripts/chaos-check.sh`.
- Giao diện (vòng 4): repo không có công cụ test JavaScript. Logic thuần của `web/dashboard.html` (đọc đơn điệu
  `compareViews`; màu cạnh `relayEdge`, `sinkEdge`, `brokerState`, `gossipEdge`; trạng thái chi nhánh `branchState`)
  và của `web/pos.html` (kết quả gửi một dòng phiếu `settle`, giữ hay bỏ `request_id`; tìm hàng `match`) kiểm bằng
  `?selftest=1` (vòng 5 thêm: chọn cổng vào `gateList`, `nextGate`; POS `posPrefix`, `apiUrl`; trạng thái chi nhánh
  theo `verdict`; `systemIssues` báo chi nhánh OFFLINE): mở `http://localhost/?selftest=1` hoặc `http://localhost/cn2/?selftest=1`, thanh bên / dưới phiếu
  ghi "Selftest: n/n đạt" (và in ra console). **Chạy tay, không nằm trong `make check`.** Phần hiển thị kiểm bằng kịch bản chạy tay K1–K9, K11, K12. Phần server phục vụ truy vết
  (`/api/trace`, `/api/movement/{movement_id}`, `kafka_ts`, `brokers_up`, `last_movement`) có pytest như mọi phần khác.

## 2. Quy tắc và test chứng minh

| Mã | Test | Trạng thái |
|---|---|---|
| PT-01 | — (kiểm khi tự duyệt: không có lời gọi mạng trong `services/branch.py`) | — |
| PT-02 | `tests/branch/test_change_stock.py`: `test_sale_writes_inventory_ledger_and_outbox_together`, `test_oversell_is_rejected_and_leaves_no_event` | xanh |
| PT-03 | `tests/branch/test_relay.py`: `test_relay_marks_sent_only_after_send_succeeds`, `test_relay_send_failure_marks_nothing`, `test_event_written_during_send_stays_unsent`, `test_empty_outbox_does_not_call_send`; `tests/branch/test_movement.py` (vòng 4): `test_movement_shows_ledger_row_not_yet_sent`, `test_movement_sent_at_set_after_relay_confirms` | xanh |
| PT-04 | `tests/replica/test_apply_event.py`: `test_duplicate_event_is_ignored`, `test_event_already_patched_by_gossip_is_logged_without_overwrite`; `tests/replica/test_merge_cells.py::test_merge_is_idempotent`; `tests/replica/test_trace.py` (vòng 4): `test_kafka_timestamp_is_stored_and_traced`, `test_duplicate_keeps_first_kafka_position`, `test_event_logged_after_patch_shows_both` | xanh |
| PT-05 | `tests/replica/test_apply_event.py`: `test_older_event_arriving_late_does_not_overwrite_newer`, `test_newer_event_from_kafka_takes_over_patched_cell`; `tests/replica/test_merge_cells.py::test_merge_does_not_overwrite_newer_or_equal_cell`; `tests/replica/test_gossip.py::test_cell_where_this_replica_is_ahead_is_never_patched`; `tests/replica/test_trace.py` (vòng 4): `test_unknown_event_is_missing`, `test_skipped_event_is_superseded`, `test_inventory_exposes_cell_version` | xanh |
| PT-06 | không có pytest (thứ tự ghi CSDL rồi commit nằm trong `workers/sink.py`); kiểm bằng K6, K7a, K7b: không mất sự kiện, bản trùng bị bỏ qua | đạt chạy tay (19/11/2026) |
| PT-07 | `tests/branch/test_snapshot.py`: `test_branch_snapshot_matches_inventory_and_ledger`, `test_branch_snapshot_writes_nothing`; `tests/replica/test_gossip.py::test_branch_snapshot_with_wrong_branch_id_is_rejected`; vòng 4: `tests/branch/test_movement.py`: `test_unknown_movement_is_404`, `test_movement_writes_nothing`, `tests/replica/test_trace.py::test_cell_patched_by_reconcile`; phần "không ghi về chi nhánh, không gọi CSDL chi nhánh" kiểm khi tự duyệt (`workers/gossip.py` chỉ `GET`) | xanh |
| PT-08 | `tests/branch/test_change_stock.py::test_same_request_id_is_applied_once` | xanh |
| PT-09 | `tests/branch/test_change_stock.py::test_oversell_is_rejected_and_leaves_no_event` | xanh |
| PT-10 | `tests/replica/test_merge_cells.py` (4 test: giao hoán, lũy đẳng, không ghi đè ô mới hơn hoặc bằng, đếm ô vá và `source`); `tests/replica/test_gossip.py`: vá sau 2 lần kiểm (`test_first_mismatch_only_remembers_cells_ahead`, `test_sink_catching_up_between_checks_patches_nothing`, `test_cell_still_behind_after_two_checks_is_patched_with_latest_value`, `test_normal_sink_lag_never_counts_as_patched`), ghi trao đổi (`test_replica_snapshot_merge_records_exchange_and_counts_patched`, `test_peer_error_keeps_last_ok_and_first_failure`, `test_invalid_cell_from_peer_is_rejected_and_writes_nothing`), đối soát (`test_branch_snapshot_merge_marks_reconcile`, 4 test `reconcile_targets`: chưa kiểm/đang được, mất < 15 giây, chỉ chi nhánh sống có `branch_url`, sink chết), endpoint và dashboard (`test_snapshot_endpoint_lists_cells`, `test_heartbeat_stores_branch_url`, `test_heartbeat_rejects_non_http_branch_url`, `test_digest_and_inventory_expose_sync_state`, `test_source_is_not_part_of_fingerprint`); truy vết ô vá không có dòng `event_log` (vòng 4, `tests/replica/test_trace.py`: `test_cell_patched_by_gossip_has_no_log_row`, `test_older_event_covered_by_gossip_patch`) | xanh |
| PT-13 | `tests/replica/test_failure_detector.py` (vòng 5, 25 trường hợp): ngưỡng theo tuổi heartbeat (`test_state_thresholds_follow_heartbeat_age`: 0 và 7,9 giây ONLINE, 8 và 14,9 SUSPECT, 15 và 60 OFFLINE); đa số trên tổng số bản sao (`test_two_of_three_offline_is_offline`, `test_one_of_three_offline_is_not_offline`, `test_two_offline_with_dead_replica_is_still_offline`, `test_isolated_replica_cannot_conclude_offline`, `test_no_quorum_either_way_is_suspect`, `test_two_online_with_dead_replica_is_online`); endpoint (`test_views_endpoint_reports_own_state`, `test_views_endpoint_writes_nothing`); góc nhìn bản sao khác (`test_peer_view_upserts_latest_state`, `test_invalid_peer_view_writes_nothing`: trạng thái lạ, tuổi âm, thiếu trường, một dòng hỏng thì không ghi dòng nào); `query_nodes` (`test_nodes_show_own_state_views_and_verdict`, `test_only_this_replica_lost_contact_keeps_verdict_online`, `test_stale_peer_view_is_ignored`, `test_isolated_replica_without_peer_views_is_only_suspect`, `test_peer_view_of_other_branch_does_not_leak`). Các test `reconcile_targets` cũ giữ nguyên: đối soát vẫn theo góc nhìn riêng (K9 không đổi) | xanh |
| PT-11 | `tests/branch/test_relay.py`: `test_relay_error_keeps_first_failing_since`, `test_relay_success_clears_failure`, `test_sale_still_works_and_status_shows_relay_failure`; `tests/replica/test_broker_status.py`: `test_broker_loss_keeps_first_lost_time`, `test_broker_recovery_clears_lost_time_and_sets_lag`, `test_lag_kept_when_broker_unreachable`, `test_stats_endpoint_exposes_broker_state`, `test_brokers_up_recorded_even_when_check_fails`, `test_brokers_up_cleared_when_metadata_unreachable` (vòng 4) | xanh |

## 3. Kịch bản demo

Các bước chạy tay ở [demo.md](demo.md). "Đạt" ghi kèm ngày và cách chạy (một máy hay nhiều máy).

| Mã | Tính chất | Vòng | Trạng thái |
|---|---|---|---|
| K1 | Đồng bộ dữ liệu | 0 | đạt trên 1 node; đạt trên 3 node một máy (19/11/2026): bán ở CN2, 3 bản sao cùng dấu vân tay sau 2 giây |
| K2 | Trong suốt vị trí | 0, 1 | đạt trên 3 node một máy (19/11/2026): vệt `C A B C A B`, `/cn1/`–`/cn3/` mở đúng chi nhánh |
| K3 | Chịu lỗi, failover | 1 | đạt trên 3 node một máy (19/11/2026) bằng `make cut N=b`: vệt chỉ còn A, C; `/cn2/` báo mất liên lạc; POS B vẫn bán, outbox 20; bản sao B thấy CN2 sống, CN1, CN3 mất. Từ vòng 5 (PT-13): góc nhìn riêng của B về CN1, CN3 là OFFLINE nhưng kết luận chỉ "Nghi ngờ, chưa đủ đa số" (B không lấy được góc nhìn của A, C); phía A, C kết luận CN2 OFFLINE (2/3) |
| K4 | Tự phục hồi | 1 | đạt trên 3 node một máy (19/11/2026) bằng `make heal N=b`: outbox về 0 trong ≤ 4 giây, 3 dấu vân tay khớp sau ~17 giây, vệt có lại B |
| K5 | Độ trễ mạng | 1 | đạt trên 3 node một máy (19/11/2026) bằng `tre.sh`: RTT tới A 5 → 605 ms, bán tại chỗ 2,2 ms; tắt thì vẫn khớp |
| K6 | Chống trùng khi phát lại | 0 | đạt trên 1 node; đạt trên 3 node một máy (19/11/2026): 86 bản trùng bỏ qua, dấu vân tay không đổi; chạy lại với cụm 3 broker (vòng 2): 84 bản trùng, không đổi |
| K7a | Mất 1/3 broker | 2 | đạt trên 3 node một máy (19/11/2026): dừng broker leader, outbox 3 CN về 0 trong ≤ 4–16 giây, leader chuyển broker khác, sổ cái = event_log ở cả 3 bản sao (không mất sự kiện); bật lại cụm `Healthy: true` |
| K7b | Mất đa số broker | 2 | đạt trên 3 node một máy (19/11/2026): dừng broker 2, 3; POS "lỗi từ", outbox 20 → 40, dashboard "Đồng bộ dừng từ"; bật lại thì sau ~15 giây 3 dấu vân tay khớp, không mất sự kiện, không thao tác tay |
| K7c | Mất máy A | 2 | đạt trên 3 node một máy (19/11/2026) bằng `make cut N=a`: B, C khớp nhau sau 8–16 giây, A số cũ, POS CN1 báo lỗi; `make heal N=a` thì 3 bản sao khớp sau 3–38 giây, không mất sự kiện |
| K8 | Gossip tự vá | 3 | đạt trên 3 node một máy (22/11/2026): dừng sink B, bán 5 + 3 đơn; B khớp lại 13 giây sau khi A cập nhật (≤ 20 giây), "vá 8 ô" nhờ A; sau `seek --to end` dấu vân tay vẫn khớp, `processed` B 286 / A 294 |
| K9 | Đối soát với chi nhánh | 3 | đạt trên 3 node một máy (22/11/2026): dừng cả 3 broker, bán 5 đơn ở CN2; A, C đối soát xong +18 giây, B +22 giây sau mốc mất broker, 3 dấu vân tay khớp khi broker còn dừng, ô CN2 "qua đối soát"; bật lại: outbox về 0 sau 5 giây, sink đọc tiếp sau ~55 giây, +5 sự kiện, dấu vân tay không đổi |
| K11 | Đọc đơn điệu | 4 | đạt trên 3 node một máy (22/11/2026): dừng sink B, bán 5 đơn CN2; lấy mẫu mỗi giây 32 giây: 6 lần B trả lời bị giữ số cũ, nhãn "Bản sao B trễ 5 sự kiện ở CN2", 0 lần ô lùi phiên bản; gossip vá B sau ~22 giây, nhãn tự mất |
| K12 | Truy vết sự kiện | 4 | đạt trên 3 node một máy (22/11/2026): CN2 #22 đủ mốc chi nhánh → broker (phân hoạch 1, offset 22, LogAppendTime) → `sent_at` → A, B, C qua Redpanda; biến thể K8: B "vá bằng gossip, tới #24"; biến thể K7b: ba bản sao "nhận qua Redpanda, trước đó đã vá bằng đối soát" |
| K10a | Mất primary CSDL chi nhánh | 7 | chưa có |
| K10b | Đánh đổi nhân bản đồng bộ / bất đồng bộ | 7 | chưa có |
| K13 | Mất cổng vào, client tự chuyển | 5 | đạt trên 3 node một máy (27/11/2026, Edge headless qua DevTools): `make kill N=a S=nginx` thì dashboard chuyển sang `localhost:8012` sau 2,7 giây, vẫn làm mới mỗi 2 giây, vệt `C A B`, bảng bản sao 3 dòng khớp; `make pause` thì chuyển sau ~6 giây; POS qua cổng A bị pause: lượt bán giữ `request_id`, gửi lại qua 8012 thành công, tồn 141 → 140, một dòng sổ cái (PT-08), kể cả sau `unpause` |
| K14 | Chậm hay chết, kết luận theo đa số | 5 | đạt trên 3 node một máy (27/11/2026): pause CN2: kết luận SUSPECT ở giây 7–10, OFFLINE ở 13–17, unpause về ONLINE ≤ 4 giây; kill CN2: SUSPECT ở 3–7, OFFLINE ở 11–14, container không tự bật lại, start về ONLINE ≤ 6 giây; biến thể `tre.sh on 0 replica-a 100`: góc nhìn A SUSPECT rồi OFFLINE, kết luận ONLINE ở cả 3 bản sao suốt 30 giây; dashboard: thẻ "Mất liên lạc … (3/3 bản sao)", dải sự cố, ô 2/3 |
| K15 | Chi nhánh sập vẫn bán (ghi hộ) | 6 | chưa có |

K1–K5 chạy lại với cụm 3 broker (vòng 2, 19/11/2026): đều đạt. K4: outbox CN2 về 0 sau 5–9 giây, 3 bản sao khớp sau
2–27 giây; K5: RTT 5 → 607 ms, bán tại chỗ 2,4–4,4 ms.

K1–K7c chạy lại sau vòng 3 (gossip, đối soát; 22/11/2026, 3 node một máy, sau `make local-reset`): đều đạt.
K1: bán liên tục ~25 giây ở CN2, CN3, 3 bản sao khớp ở mọi lần đo (cách 2 giây), gossip "vá 0 ô". K2: vệt
`A B C A B C`. K3: thêm hiện tượng mới, bản sao B bị cô lập mất broker nên tự đối soát CN2 (vá 13 ô) trong khi A, C
thấy CN2 số cũ. K4: outbox CN2 về 0 và 3 bản sao khớp sau 12 giây, gossip "vá 0 ô". K5: RTT tới A 606 ms, bán tại
chỗ 2,6 ms. K6: +153 bản trùng, dấu vân tay không đổi. K7a: leader phân hoạch 0 chuyển broker 3 → 2, outbox về 0
sau ~14 giây, sổ cái = `event_log` (40/97/64). K7b: đối soát làm 3 bản sao khớp trong lúc broker dừng; bật lại thì
sink đọc tiếp sau ~55 giây (vòng 2: ~15 giây; chưa rõ nguyên nhân, vòng 3 không sửa sink). K7c: B, C khớp sau 13
giây; sau `heal` 3 bản sao khớp trong 5 giây.

K1–K9 chạy lại sau vòng 4 (giao diện; 22/11/2026, 3 node một máy, sau `make local-reset`): đều đạt, nhìn đúng trên
dashboard và sơ đồ đồng bộ (chi tiết từng kịch bản ở `docs/demo.md` mục 5, bảng "Trên sơ đồ đồng bộ"). K1: mọi cạnh
xanh, 3 bản sao khớp. K2: vệt `A B C`. K3: B "không liên lạc được", broker 2 "0/2 sink thấy", CN2 mất liên lạc; dashboard
B (mở thẳng) đối soát CN2. K4: 3 bản sao khớp, dải đọc đơn điệu "Bản sao C trễ 8 ô ở CN2" vài giây, 0 lần lùi số. K5:
RTT tới A 607 ms, bán tại chỗ 5,1 ms. K6: bản trùng 7 → 101, dấu vân tay khớp 3 bản sao, trace giữ vị trí Kafka lần đầu.
K7a: broker 2 đỏ "0/3", cụm 2/3. K7b: relay, sink đỏ, cụm "không hỏi được", cạnh đối soát hiện trong ≤ 12 giây sau khi dừng broker thứ hai; bật lại:
outbox về 0 sau 10 giây, sink đọc lại sau ~61 giây, dấu vân tay không đổi. K7c: B, C khớp, sau `heal` 3 bản khớp
≤ 10 giây, `brokers_up` về `[1,2,3]` sau ~25 giây. K8: gossip vá B (5 ô), `processed` B thấp hơn 5. K9: 3 bản sao khớp
khi broker dừng, 44 ô "qua đối soát". Selftest giao diện (`?selftest=1`): 20/20 đạt. POS: số lượng 7 bán đúng 7; 0,
1001, 2,5 bị chặn trên trình duyệt, tồn không đổi.

Làm lại giao diện theo nghiệp vụ (26/11/2026, 3 node một máy): selftest dashboard 22/22, POS 5/5. POS qua `/cn2/`:
gõ "3" + Enter, gõ "gạo" + Enter, tăng dòng đầu lên 2, Thanh toán: tồn mã 3 130 → 128, mã 7 70 → 69, "Đã bán 2 mặt
hàng. Xử lý tại chỗ trong 27,8 ms". Dashboard: bốn tab chỉ hiện đúng tab chọn, Tổng quan đủ 4 ô số liệu và bảng chi
nhánh, truy vết vẫn đủ mốc. Chưa chạy lại K1–K12 đầy đủ trên bố cục này (logic không đổi, chỉ đổi chỗ hiển thị).
Tab Sự kiện thành bảng một dòng mỗi sự kiện, truy vết thành các bước "+x,xx giây": chọn #126 bằng Enter khi dừng sink
B, được A +1,96 giây, C +1,50 giây, B vàng +12,34 giây "vá bằng gossip tới #126"; selftest vẫn 22/22.

Chỉnh giao diện `web/ui-polish` (26/11/2026, 3 node một máy): selftest dashboard 24/24 (thêm 2 kiểm `systemIssues`),
POS 5/5; `make check` 58 test xanh. Cỡ 375px: cả bốn tab rộng đúng 375px (trước đó tràn tới 538–1055px). Dừng broker B:
Tổng quan hiện dải "Hệ thống có sự cố: broker B không chạy (cụm còn 2/3)", sơ đồ "2/3 broker (máy A, B, C)"; bật lại
thì dải tự tắt. Tab Sự kiện: cột "Nhận lúc" giảm dần đúng thứ tự, dòng của ngày trước có ngày ("15:16 22-11").
Trang trả `Cache-Control: no-cache`.

Vòng 5 `ha/entry-failure-detector` (27/11/2026, 3 node một máy, sau `make local-reset`): `make check` 83 test xanh
(58 cũ + 25 `test_failure_detector.py`), `make config` đạt; selftest dashboard 33/33, POS 10/10 (Edge/Chrome headless).
K13, K14 ở bảng trên. Chạy lại K1–K12 bằng API và trình duyệt điều khiển qua DevTools, đều đạt: K1 3 bản sao khớp
sau 1 giây; K2 vệt `B A C` qua cổng A, `C A B` qua cổng 8012, `/cn2/` qua cổng 8022 trả 200; K3 vệt chỉ còn `C A`,
`/cn2/` 503, bản sao A kết luận CN2 OFFLINE (góc nhìn A, C), B bị cô lập thấy CN1 OFFLINE nhưng kết luận SUSPECT, B
đối soát CN2; K4 outbox về 0 sau 1 giây, khớp sau 5 giây; K5 RTT tới A 607 ms, bán tại chỗ 2,3 ms; K6 bản trùng
114 → 418, dấu vân tay không đổi, 3 bản sao khớp; K7a outbox về 0, khớp; K7b khớp ở giá trị mới sau 26 giây khi mất
đa số broker (đối soát), bật lại outbox về 0 sau 5 giây; K7c B, C khớp, B kết luận CN1 OFFLINE, A bị cô lập chỉ
SUSPECT, sau `heal` khớp sau 8 giây; K8 B vá 5 ô nhờ C, `processed` B thấp hơn A 5; K9 khớp ở giá trị mới sau 21
giây khi cả 3 broker dừng (6 ô "reconcile"); K11 lấy mẫu 26 giây: 4 lần B trả lời bị giữ số cũ, nhãn "Bản sao B trễ 5
sự kiện ở CN2", 0 lần lùi phiên bản; K12 truy vết #221 `kafka` ở cả 3 bản sao. Hai lỗi hạ tầng: cut B, dựng lại hẳn
node A, C, heal B, dừng broker B, dựng lại A, bật broker B: không còn `Address already in use`, cụm `Healthy: true`;
`make local-up` lần hai: `topic-init` in `TOPIC_ALREADY_EXISTS` rồi thoát 0. Cỡ 375px: bốn tab dashboard và POS
không tràn ngang.
