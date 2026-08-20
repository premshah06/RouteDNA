#!/usr/bin/env bash
# Regenerates gen/python/ from proto/packagepb/v1/*.proto.
# gen/ is gitignored — this is a build step, not checked-in source.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! python3 -c "import grpc_tools" 2>/dev/null; then
  echo "error: grpc_tools not importable — activate .venv first (source .venv/bin/activate)" >&2
  exit 1
fi

rm -rf gen/python
mkdir -p gen/python

python3 -m grpc_tools.protoc \
  --proto_path=proto \
  --python_out=gen/python \
  --grpc_python_out=gen/python \
  --pyi_out=gen/python \
  proto/packagepb/v1/*.proto

touch gen/python/__init__.py gen/python/packagepb/__init__.py gen/python/packagepb/v1/__init__.py

echo "generated stubs in gen/python/"
