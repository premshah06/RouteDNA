FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY gen/python /app/gen/python
COPY services/query/server.py services/query/clickhouse.py /app/

ENV PYTHONPATH=/app/gen/python

CMD ["python3", "server.py"]
