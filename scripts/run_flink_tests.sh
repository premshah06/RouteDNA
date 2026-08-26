#!/usr/bin/env bash
# Runs stream_processing/tests/ inside the Flink image, since
# stuck_package_detector.py (and its tests) import pyflink, which is
# only installed in that Docker image, not the local venv.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

docker build -q -t thing-transfer-flink:local -f stream_processing/flink_image/Dockerfile stream_processing/flink_image

docker run --rm \
  -v "$ROOT_DIR/gen/python:/opt/flink/usrlib/gen/python:ro" \
  -v "$ROOT_DIR/stream_processing:/opt/flink/usrlib/stream_processing:ro" \
  -v "$ROOT_DIR/services/common:/opt/flink/usrlib/services/common:ro" \
  -e PYTHONPATH=/opt/flink/usrlib/gen/python:/opt/flink/usrlib/stream_processing/jobs:/opt/flink/usrlib/services/common \
  thing-transfer-flink:local \
  bash -c "pip3 install --no-cache-dir pytest -q && \
    python3 -m pytest /opt/flink/usrlib/stream_processing/tests/ -v -p no:cacheprovider"
