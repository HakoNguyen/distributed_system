# CLAUDE.md – Quy tắc cho AI trong repo MiniGo

Đọc file này ở đầu mọi phiên làm việc. Các quy tắc dưới đây là bắt buộc.

## Dự án
Demo hệ thống kho phân tán cho môn Các hệ thống phân tán. Mỗi node chạy một chi nhánh, một bản sao trung tâm và một
broker Redpanda (ba broker thành một cụm); node A chạy thêm Redpanda Console, nginx, `topic-init`. Chạy bằng Docker Compose, trên 2–3 máy thật hoặc mô phỏng nhiều
node trên một máy.

## Bắt đầu từ đâu
- `docs/plan.md` mục 1 cho biết vòng đang làm. Mỗi lần chỉ làm **một** vòng, đúng thứ tự.
- Quy trình bốn bước, dùng lệnh dự án: `/plan-task` → `/test-first` → `/implement` → `/self-review`.
  `/plan-task` kết thúc bằng việc dừng lại chờ người dùng duyệt.

## Nguồn sự thật
- `docs/spec.md` (kiến trúc, tính chất, giới hạn, quy tắc PT-xx ở mục 8), rồi `docs/db.md`, rồi `docs/api.md`.
  `docs/tests.md`: test và kịch bản phải đạt. `docs/demo.md`: các bước chạy tay K1–K9. `docs/plan.md`: thứ tự làm.
- Không tự đặt tên bảng, cột, endpoint, trường sự kiện, biến môi trường, lệnh make. Tên chưa có trong `docs/` thì
  đề xuất ở `/plan-task` và ghi vào `docs/` trước khi code.
- Kế hoạch thiếu hoặc mâu thuẫn thì DỪNG và hỏi, không đoán. Giả định chưa được xác nhận nằm ở `docs/plan.md` mục 6.
- Không thêm thư viện. Python: fastapi, uvicorn, psycopg 3 + psycopg-pool, httpx, confluent-kafka; test: pytest.
  Giao diện: HTML + JS thuần, không framework, không bước build. Cần thêm thì dừng và hỏi.

## Bản đồ repo
| Thư mục | Nội dung | Đọc thêm |
|---|---|---|
| `docs/` | Đặc tả, CSDL, API, kiểm thử, kịch bản demo, kế hoạch | `docs/README.md` |
| `db/` | SQL khởi tạo cho hai loại CSDL | `db/CLAUDE.md` |
| `common/` | Cấu hình từ biến môi trường, pool CSDL, model Pydantic | |
| `api/` | FastAPI `ROLE=branch` hoặc `ROLE=replica`; `routers/`, `services/`, `workers/` | `api/CLAUDE.md` |
| `web/` | `pos.html` (chi nhánh), `dashboard.html` (bản sao) | `web/CLAUDE.md` |
| `infra/` | `compose.yml`, `compose.test.yml`, nginx, mẫu `.env` cho từng máy | `infra/CLAUDE.md` |
| `tests/` | pytest trên PostgreSQL thật, chạy trong container | `tests/CLAUDE.md` |
| `scripts/` | `tre.sh`: giả lập độ trễ bằng `tc` trong container; `net.sh`: 3 node một máy, `make cut/heal`, `make config` | |
| `.claude/commands/` | Bốn lệnh của quy trình | |

## Phạm vi sửa
- Chỉ sửa file đã liệt kê trong kế hoạch được duyệt (mẫu ở `docs/plan.md` mục 4). Cần sửa chỗ khác thì dừng và nêu đề xuất.
- Không thêm tính năng, tùy chọn hay lớp trừu tượng mà kế hoạch không yêu cầu.

## Quy tắc phân tán không được vi phạm (mã ở `docs/spec.md` mục 8)
- **PT-01** Chi nhánh chỉ nói chuyện với CSDL của chính nó. Không có lời gọi mạng nào trên đường bán hàng.
- **PT-02** Sửa tồn, ghi `stock_movement`, ghi `outbox` trong MỘT transaction (`services/branch.py: record_movement`).
- **PT-03** Relay chỉ đánh dấu `sent_at` sau khi Redpanda xác nhận mọi thông điệp của lô.
- **PT-04, PT-05** Áp sự kiện lũy đẳng (khoá `(branch_id, movement_id)`) và chịu lệch thứ tự (chỉ ghi đè khi
  `movement_id` lớn hơn). `node_time` chỉ để hiển thị; không so thứ tự bằng đồng hồ.
- **PT-06** Sink ghi CSDL xong rồi mới commit offset.
- **PT-07** Bản sao chỉ đọc: không ghi ngược về chi nhánh, không gọi thẳng CSDL chi nhánh.
- **PT-08** Nginx chỉ tự thử lại yêu cầu idempotent; lệnh bán dựa vào `request_id` để chống trừ hai lần.
- **PT-09** Không bán lố tồn: trừ bằng một câu `UPDATE` có điều kiện.
- **Không gọi HTTP bên trong transaction CSDL**: lấy dữ liệu từ node khác về trước, rồi mới mở transaction để ghi.

## Cách làm
- Python 3.12, có type hint ở hàm mới. SQL tham số hóa (`%s`), không ghép chuỗi giá trị vào SQL.
- Router mỏng: gọi một hàm trong `services/`. SQL nằm trong `services/`. Phần gọi mạng nằm trong `workers/`, tách
  khỏi phần ghi CSDL để test được không cần mạng.
- Comment và thông báo viết tiếng Việt; tên trong code viết tiếng Anh. `requirements*.txt` chỉ viết ASCII.
- Đổi schema: sửa `db/*.sql` rồi `make reset` trên MỌI node (script khởi tạo chỉ chạy khi volume trống). Test tự dựng
  lại schema mỗi lần chạy.
- Kết thúc mỗi việc: `make check`, chạy tay kịch bản của vòng, báo kết quả thật (kể cả phần chưa đạt), cập nhật
  `docs/plan.md` mục 1 và `docs/tests.md`.

## Git
- Remote `origin`: https://github.com/HakoNguyen/distributed_system.git
- Mỗi vòng một nhánh (cột "Nhánh" ở `docs/plan.md` mục 1), tách từ `main`, hoặc từ nhánh của vòng trước nếu vòng
  trước chưa merge.
- AI **được**: `git status`, `git diff`, `git log`, `git switch -c <nhánh>`, `git add`.
- AI **không được**: `git commit`, `git push` (đã chặn trong `.claude/settings.json`), `git merge`, `git rebase`,
  `git reset`, `git stash`, tạo pull request. Người dùng tự commit và push.
- Cuối vòng, thay cho commit: `git add` đúng file của vòng (không bao giờ add `.env`), chạy `git status`, rồi viết
  commit message và lệnh `git commit` / `git push` để người dùng tự chạy.
- Commit message tiếng Anh, dạng `<type>(<module>): <summary>` (type: feat, fix, test, docs, refactor, chore, build),
  dòng đầu tối đa 72 ký tự; thân ghi vòng, mã quy tắc PT-xx và kịch bản Kxx liên quan.
