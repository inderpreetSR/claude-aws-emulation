#!/usr/bin/env bash
# Browse the emulator's DynamoDB tables in a web interface at http://127.0.0.1:8001
# Needs Node.js. Reads endpoint, key and certificate from the running emulator.
set -euo pipefail
cd "$(dirname "$0")/.."

eval "$(python3 - <<'PY'
import emu
s = emu.settings()
print(f'export DYNAMO_ENDPOINT="{s["endpoint_url"]}"')
print(f'export AWS_REGION="{s["region_name"]}"')
print(f'export AWS_ACCESS_KEY_ID="{s["aws_access_key_id"]}"')
print(f'export AWS_SECRET_ACCESS_KEY="{s["aws_secret_access_key"]}"')
if isinstance(s["verify"], str):
    print(f'export NODE_EXTRA_CA_CERTS="{s["verify"]}"')
PY
)"

echo "dynamodb-admin -> $DYNAMO_ENDPOINT   open http://127.0.0.1:8001"
exec npx --yes dynamodb-admin --host 127.0.0.1 --port 8001 --skip-default-credentials
