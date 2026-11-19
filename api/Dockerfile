# Một image cho cả 4 tiến trình: branch_api, relay, replica_api, sink (khác nhau ở ROLE và command).
# Build context là gốc repo (cần common/, web/, scripts/):
#   docker build -f api/Dockerfile -t minigo-api .
FROM python:3.12-slim AS base

# iproute2 cung cấp lệnh `tc` cho scripts/tre.sh (giả lập độ trễ ngay trong container)
RUN apt-get update && apt-get install -y --no-install-recommends iproute2 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY web/ ./web/
COPY scripts/tre.sh ./
COPY api/ ./

EXPOSE 8000
# Mặc định chạy API. relay và sink ghi đè bằng `command:` trong infra/compose.yml.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# Ảnh chạy test (infra/compose.test.yml): thêm pytest; code lấy từ repo được mount vào /repo
FROM base AS test
COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt
WORKDIR /repo

# Stage cuối là ảnh chạy thật, nên compose build không cần ghi target
FROM base AS runtime
