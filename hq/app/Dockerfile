FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# In log ra ngay, không bị đệm (để `docker compose logs -f` thấy liền)
ENV PYTHONUNBUFFERED=1
# Mặc định chạy API. Container relay / sink ghi đè bằng `command:` trong compose.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
