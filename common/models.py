"""Model Pydantic cho request của cả hai vai."""
from datetime import datetime
from typing import Literal

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
    # Địa chỉ POS của chi nhánh (BRANCH_URL), để bản sao đối soát khi mất broker (vòng 3)
    branch_url: str | None = Field(default=None, pattern=r"^https?://\S+$", max_length=200)


class SnapshotCell(BaseModel):
    """Một ô (chi nhánh, mã hàng) nhận từ node khác qua GET /api/snapshot. Kiểm trước khi merge."""
    branch_id: int
    product_id: int
    qty_on_hand: int = Field(ge=0)
    last_movement: int = Field(gt=0)
    node_time: datetime | None = None


class BranchView(BaseModel):
    """Góc nhìn của một bản sao khác về một chi nhánh, nhận qua GET /api/views (vòng 5, PT-13). Kiểm trước khi ghi."""
    branch_id: int
    state: Literal["ONLINE", "SUSPECT", "OFFLINE"]
    seconds_since_seen: int = Field(ge=0)
