"""Model Pydantic cho request của cả hai vai."""
from pydantic import BaseModel, Field


class StockChange(BaseModel):
    """Bán hoặc nhập hàng ở chi nhánh."""
    product_id: int
    qty: int = Field(gt=0, le=1000)
    # Không bắt buộc. Nếu gửi kèm, server chỉ sửa khi version vẫn khớp
    # (khoá lạc quan); lệch thì trả 409 để client đọc lại.
    version: int | None = None
    # Không bắt buộc. Client tự sinh (vd. uuid). Gửi lại cùng request_id thì
    # server trả kết quả cũ chứ không trừ tồn lần hai.
    request_id: str | None = None


class Heartbeat(BaseModel):
    """Chi nhánh gửi tới mọi bản sao trung tâm, mỗi 5 giây."""
    branch_id: int
    branch_name: str
    node_time_ms: int  # giờ máy chi nhánh
    outbox_backlog: int = 0
    rtt_ms: int | None = None  # RTT đo được ở lần heartbeat trước
