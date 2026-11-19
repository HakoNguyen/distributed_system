-- =====================================================================
-- Lược đồ của MỘT node chi nhánh.
-- Node này chỉ chứa tồn kho của chính nó và không biết gì về chi nhánh
-- khác. Đó là "mảnh dữ liệu" của nó.
-- =====================================================================

-- Tồn kho hiện tại. Mỗi dòng = một mã hàng tại chi nhánh này.
CREATE TABLE inventory (
    product_id  INT         PRIMARY KEY REFERENCES product,
    branch_id   INT         NOT NULL,
    qty_on_hand INT         NOT NULL CHECK (qty_on_hand >= 0),  -- không bao giờ âm
    version     INT         NOT NULL DEFAULT 1,  -- tăng mỗi lần sửa, để phát hiện xung đột
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Sổ cái biến động: CHỈ GHI THÊM, không sửa, không xoá.
-- Mỗi lần bán / nhập là một dòng. movement_id tăng dần trong node này,
-- nên cặp (branch_id, movement_id) cho biết thứ tự sự kiện mà không cần
-- tin vào đồng hồ.
CREATE TABLE stock_movement (
    movement_id BIGSERIAL   PRIMARY KEY,
    product_id  INT         NOT NULL REFERENCES product,
    move_type   TEXT        NOT NULL CHECK (move_type IN ('INIT', 'SALE', 'RECEIPT')),
    qty_delta   INT         NOT NULL,   -- âm khi bán, dương khi nhập
    qty_after   INT         NOT NULL,   -- tồn ngay sau biến động này
    request_id  TEXT        UNIQUE,     -- mã yêu cầu từ client: gửi lại không bị trừ hai lần
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()  -- giờ theo đồng hồ CỦA NODE NÀY
);

-- Outbox = hộp thư đi. Được ghi CÙNG transaction với nghiệp vụ; sau đó
-- relay mới đọc ra và gửi lên Redpanda. sent_at IS NULL = chưa gửi.
CREATE TABLE outbox (
    event_id   BIGINT      PRIMARY KEY REFERENCES stock_movement (movement_id),
    payload    JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    sent_at    TIMESTAMPTZ
);

-- Chỉ mục riêng cho các dòng chưa gửi, để relay quét nhanh dù outbox dài.
CREATE INDEX outbox_unsent ON outbox (event_id) WHERE sent_at IS NULL;
