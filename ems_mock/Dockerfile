# Mock 共济 EMS 联调服务
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Asia/Shanghai
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 9000
CMD ["uvicorn", "mock_ems_server:app", "--host", "0.0.0.0", "--port", "9000"]
