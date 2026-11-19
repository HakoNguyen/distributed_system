-- =====================================================================
-- Lược đồ của MỘT BẢN SAO TRUNG TÂM. Mỗi máy chạy một bản sao như vậy.
-- Bản sao KHÔNG giữ bản chính của tồn kho. Nó chỉ giữ một bảng tổng hợp
-- (snapshot) dựng lại từ các sự kiện chi nhánh gửi lên, qua Redpanda.
-- Chân lý về tồn kho của chi nhánh nào thì nằm ở chính chi nhánh đó.
-- =====================================================================

-- Trạng thái từng node, cập nhật mỗi lần nhận heartbeat.
CREATE TABLE node_status (
    branch_id      INT         PRIMARY KEY,
    branch_name    TEXT        NOT NULL,
    last_seen      TIMESTAMPTZ NOT NULL,  -- giờ CỦA TRUNG TÂM lúc nhận heartbeat
    node_time      TIMESTAMPTZ NOT NULL,  -- giờ CỦA CHI NHÁNH ghi trong heartbeat
    outbox_backlog INT         NOT NULL DEFAULT 0, -- số sự kiện chi nhánh chưa gửi được
    rtt_ms         INT                             -- thời gian một vòng heartbeat, đo ở chi nhánh
);

-- Bảng tổng hợp tồn kho toàn chuỗi. Mỗi dòng = một mã hàng ở một chi nhánh.
CREATE TABLE inventory_snapshot (
    branch_id     INT         NOT NULL,
    product_id    INT         NOT NULL REFERENCES product,
    qty_on_hand   INT         NOT NULL,
    last_movement BIGINT      NOT NULL,  -- movement_id mới nhất đã áp vào dòng này
    node_time     TIMESTAMPTZ,           -- giờ chi nhánh ghi nhận biến động đó
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),  -- giờ trung tâm cập nhật
    PRIMARY KEY (branch_id, product_id)
);

-- Nhật ký mọi sự kiện đã nhận. Khoá chính (branch_id, movement_id)
-- chính là cơ chế chống trùng: nhận lại lần hai thì INSERT không vào.
CREATE TABLE event_log (
    branch_id       INT         NOT NULL,
    movement_id     BIGINT      NOT NULL,
    product_id      INT         NOT NULL,
    move_type       TEXT        NOT NULL,
    qty_delta       INT         NOT NULL,
    qty_after       INT         NOT NULL,
    node_time       TIMESTAMPTZ NOT NULL,             -- giờ chi nhánh tạo sự kiện
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(), -- giờ trung tâm nhận được
    kafka_partition INT,
    kafka_offset    BIGINT,
    PRIMARY KEY (branch_id, movement_id)
);
CREATE INDEX event_log_recent ON event_log (received_at DESC);

-- Bộ đếm của sink, hiện lên dashboard.
CREATE TABLE sink_stats (
    id            INT    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    processed     BIGINT NOT NULL DEFAULT 0,  -- sự kiện mới đã áp vào snapshot
    duplicates    BIGINT NOT NULL DEFAULT 0,  -- sự kiện trùng đã bỏ qua
    last_event_at TIMESTAMPTZ
);
INSERT INTO sink_stats (id) VALUES (1);
