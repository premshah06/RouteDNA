FROM python:3.11-slim

WORKDIR /app

COPY batch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY batch/thing_transfer_batch /app/thing_transfer_batch
COPY batch/workspace.yaml /app/workspace.yaml
COPY batch/dagster.yaml /app/dagster_home/dagster.yaml

ENV DAGSTER_HOME=/app/dagster_home

EXPOSE 3000
CMD ["dagster-webserver", "-w", "workspace.yaml", "-h", "0.0.0.0", "-p", "3000"]
