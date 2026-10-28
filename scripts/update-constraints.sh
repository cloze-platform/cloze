#!/bin/sh
# Resolves requirements.txt for the production image (Linux ARM64, Python 3.12)
# without installing anything, and prints exact pins for constraints.txt:
#
#   scripts/update-constraints.sh > constraints.txt
#
# Review the diff and test the new image before committing it.
set -e
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
"$PYTHON" -m pip install --dry-run --quiet --disable-pip-version-check --ignore-installed \
  --only-binary=:all: --implementation cp --python-version 3.12 \
  --platform manylinux2014_aarch64 --platform manylinux_2_17_aarch64 --platform manylinux_2_28_aarch64 \
  --target "$tmp/target" --report "$tmp/report.json" -r requirements.txt \
  greenlet  # SQLAlchemy needs it on Linux ARM64; pip skips it when run on macOS
echo "# Exact versions the production image installs (Dockerfile: pip install -c)."
echo "# Regenerate with scripts/update-constraints.sh, and test the new image before"
echo "# committing a change."
"$PYTHON" -c '
import json, re, sys
pins = sorted((re.sub(r"[-_.]+", "-", i["metadata"]["name"]).lower(), i["metadata"]["version"])
              for i in json.load(open(sys.argv[1]))["install"])
print("".join(f"{n}=={v}\n" for n, v in pins), end="")
' "$tmp/report.json"
