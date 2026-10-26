#!/usr/bin/env bash
# Loads the reviewed seed CSVs (seeds/) into meta and ref in one transaction (see loader/seeds.py).
# Usage: bash load_seeds.sh <database_name>
set -euo pipefail
DB="${1:?usage: load_seeds.sh <database_name>}"
cd "$(dirname "$0")" && python3 -m loader.seeds "$DB"
