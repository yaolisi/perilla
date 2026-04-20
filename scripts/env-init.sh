#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -f ".env" ]]; then
  echo ".env already exists, skip initialization."
  exit 0
fi

if [[ ! -f ".env.example" ]]; then
  echo "Error: .env.example not found." >&2
  exit 1
fi

cp .env.example .env
echo "Initialized .env from .env.example"
