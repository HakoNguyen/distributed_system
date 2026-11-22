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
    rtt_ms         INT,                            -- thời gian một vòng heartbeat, đo ở chi nhánh
    branch_url     TEXT                            -- địa chỉ POS chi nhánh tự báo; đối soát gọi <branch_url>/api/snapshot
);

-- Bảng tổng hợp tồn kho toàn chuỗi. Mỗi dòng = một mã hàng ở một chi nhánh.
CREATE TABLE inventory_snapshot (
    branch_id     INT         NOT NULL,
    product_id    INT         NOT NULL REFERENCES product,
    qty_on_hand   INT         NOT NULL,
    last_movement BIGINT      NOT NULL,  -- movement_id mới nhất đã áp vào dòng này
    node_time     TIMESTAMPTZ,           -- giờ chi nhánh ghi nhận biến động đó
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),  -- giờ trung tâm cập nhật
    -- Kênh đã ghi giá trị hiện tại của ô: kafka (sink), gossip (bản sao khác), reconcile (đối soát với
    -- chi nhánh). Không nằm trong dấu vân tay: cùng số mà khác nguồn vẫn là khớp.
    source        TEXT        NOT NULL DEFAULT 'kafka' CHECK (source IN ('kafka', 'gossip', 'reconcile')),
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
    kafka_ts        TIMESTAMPTZ,  -- timestamp Kafka (topic LogAppendTime: giờ broker leader ghi), để truy vết
    PRIMARY KEY (branch_id, movement_id)
);
CREATE INDEX event_log_recent ON event_log (received_at DESC);

-- Bộ đếm của sink và trạng thái đường đọc Redpanda, hiện lên dashboard.
CREATE TABLE sink_stats (
    id            INT    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    processed     BIGINT NOT NULL DEFAULT 0,  -- sự kiện mới đã áp vào snapshot
    duplicates    BIGINT NOT NULL DEFAULT 0,  -- sự kiện trùng đã bỏ qua
    last_event_at TIMESTAMPTZ,
    -- Sink tự kiểm broker mỗi 5 giây (workers/sink.py)
    broker_ok         BOOLEAN,      -- NULL = chưa kiểm lần nào
    broker_lost_at    TIMESTAMPTZ,  -- lần lỗi đầu tiên của đợt mất broker hiện tại; NULL = đang đọc được
    lag               BIGINT,       -- số sự kiện trên Redpanda bản sao này chưa áp (đo lần được gần nhất)
    broker_checked_at TIMESTAMPTZ,  -- lần kiểm gần nhất; cũ quá nghĩa là chính sink đã dừng
    brokers_up        INT[]         -- mã broker còn sống theo metadata lần kiểm gần nhất; NULL = không hỏi được
);
INSERT INTO sink_stats (id) VALUES (1);

-- Lần trao đổi trực tiếp cuối với từng nơi (vòng 3): bản sao khác (gossip, peer = 'A') hoặc chi nhánh
-- (đối soát khi mất broker, peer = 'CN2'). Dòng tạo ở lần trao đổi đầu tiên.
CREATE TABLE sync_peer (
    peer          TEXT        PRIMARY KEY,
    channel       TEXT        NOT NULL CHECK (channel IN ('gossip', 'reconcile')),
    last_ok_at    TIMESTAMPTZ,                     -- lần cuối gọi được và merge xong
    failing_since TIMESTAMPTZ,                     -- lỗi đầu tiên của đợt lỗi hiện tại; NULL = đang gọi được
    last_error    TEXT,
    cells_patched BIGINT      NOT NULL DEFAULT 0   -- tổng số ô đã vá nhờ nơi này (chỉ ô thật sự thiếu)
);
