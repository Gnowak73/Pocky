#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
OUT="$ROOT/dist"
mkdir -p "$OUT"

cd "$ROOT"

echo "Building macOS arm64..."
GOOS=darwin GOARCH=arm64 go build -o "$OUT/waffle-launcher-macos-arm64" .

echo "Building macOS amd64..."
GOOS=darwin GOARCH=amd64 go build -o "$OUT/waffle-launcher-macos-amd64" .

echo "Building Linux amd64..."
GOOS=linux GOARCH=amd64 go build -o "$OUT/waffle-launcher-linux-amd64" .

echo "Building Linux arm64..."
GOOS=linux GOARCH=arm64 go build -o "$OUT/waffle-launcher-linux-arm64" .

echo "Building Windows amd64..."
GOOS=windows GOARCH=amd64 go build -o "$OUT/waffle-launcher-windows-amd64.exe" .

echo "Done. Artifacts in: $OUT"
