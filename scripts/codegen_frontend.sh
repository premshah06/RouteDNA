#!/usr/bin/env bash
# Regenerates frontend/src/gen/ from proto/ for the grpc-web frontend.
# Needs protoc + protoc-gen-grpc-web on PATH:
#   brew install protoc-gen-grpc-web
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v protoc-gen-grpc-web >/dev/null 2>&1; then
  echo "error: protoc-gen-grpc-web not found — run: brew install protoc-gen-grpc-web" >&2
  exit 1
fi

# PROTOC_INCLUDE_DIR lets a caller (e.g. CI, or a non-Homebrew protoc
# install) point directly at protoc's well-known-types include root
# instead of relying on the search below, which only knows how to find
# a Homebrew install.
if [ -n "${PROTOC_INCLUDE_DIR:-}" ]; then
  WKT_DIR="$PROTOC_INCLUDE_DIR"
else
  WKT_FILE="$(find /opt/homebrew /usr/local /usr -iname 'timestamp.proto' -path '*google*' 2>/dev/null | head -1)"
  if [ -z "$WKT_FILE" ]; then
    echo "error: could not locate google/protobuf/timestamp.proto (well-known types) via protoc's install — set PROTOC_INCLUDE_DIR explicitly" >&2
    exit 1
  fi
  # WKT_FILE looks like .../include/google/protobuf/timestamp.proto —
  # the proto_path root protoc needs is .../include, three dirname's up.
  WKT_DIR="$(dirname "$(dirname "$(dirname "$WKT_FILE")")")"
fi

# Generated stubs live in their own local package (frontend/proto-gen/),
# not directly under frontend/src/ — protoc-gen-js only emits CommonJS
# with dynamically-assigned exports, which only Vite's node_modules
# CJS->ESM interop can handle; that interop does not apply to arbitrary
# files under src/. package.json here is preserved across regeneration.
GEN_DIR=frontend/proto-gen
find "$GEN_DIR" -mindepth 1 -not -name package.json -delete

protoc --proto_path=proto --proto_path="$WKT_DIR" \
  --js_out=import_style=commonjs,binary:"$GEN_DIR" \
  --grpc-web_out=import_style=typescript,mode=grpcwebtext:"$GEN_DIR" \
  proto/packagepb/v1/*.proto google/protobuf/timestamp.proto

echo "generated grpc-web stubs in $GEN_DIR/"
