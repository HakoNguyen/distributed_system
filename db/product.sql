-- =====================================================================
-- Danh mục sản phẩm: dữ liệu chủ, GIỐNG HỆT NHAU ở mọi node.
--
-- Trong đề tài kho đầy đủ, bảng này được nhân bản từ trung tâm xuống
-- chi nhánh bằng logical replication. Ở bản demo cho gọn, mọi node
-- (trung tâm và từng chi nhánh) nạp cùng một file này lúc khởi tạo.
-- =====================================================================
CREATE TABLE product (
    product_id    INT  PRIMARY KEY,
    name          TEXT NOT NULL,
    unit          TEXT NOT NULL,
    reorder_point INT  NOT NULL   -- dưới mức này thì cần đặt thêm hàng
);

INSERT INTO product (product_id, name, unit, reorder_point) VALUES
 ( 1, 'Sữa tươi có đường 180ml',  'hộp',  30),
 ( 2, 'Mì gói tôm chua cay',      'gói',  50),
 ( 3, 'Nước suối 500ml',          'chai', 40),
 ( 4, 'Bánh mì sandwich',         'gói',  15),
 ( 5, 'Cà phê sữa lon 235ml',     'lon',  25),
 ( 6, 'Trứng gà vỉ 10 quả',       'vỉ',   10),
 ( 7, 'Gạo thơm túi 5kg',         'túi',   8),
 ( 8, 'Dầu ăn chai 1 lít',        'chai', 10),
 ( 9, 'Nước mắm 500ml',           'chai', 10),
 (10, 'Bột giặt 800g',            'túi',   8),
 (11, 'Kem đánh răng 180g',       'tuýp', 12),
 (12, 'Dầu gội 650ml',            'chai',  8),
 (13, 'Giấy vệ sinh lốc 10 cuộn', 'lốc',  10),
 (14, 'Nước ngọt lon 330ml',      'lon',  40),
 (15, 'Snack khoai tây 52g',      'gói',  20),
 (16, 'Kẹo cao su vỉ',            'vỉ',   20),
 (17, 'Sữa chua lốc 4 hộp',       'lốc',  15),
 (18, 'Xúc xích tiệt trùng',      'gói',  20),
 (19, 'Trà xanh chai 455ml',      'chai', 30),
 (20, 'Khăn giấy ướt',            'gói',  12);
