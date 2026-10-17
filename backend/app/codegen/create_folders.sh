#!/usr/bin/env bash
# Usage: create_folders.sh <service.json | -> [output_dir]
# Builds <output_dir>/<service_name>/ with one rendered file per endpoint
# (<tool_name>.py) and the consolidated main file (<service_name>_tools.py).
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "usage: $0 <service.json | -> [output_dir]" >&2
  exit 1
fi
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required" >&2; exit 1; }

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out_root="${2:-.}"

if [ "$1" = "-" ]; then
  json="$(cat)"
else
  [ -f "$1" ] || { echo "no such file: $1" >&2; exit 1; }
  json="$(cat "$1")"
fi

service="$(jq -r '.service_name' <<<"$json" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+|_+$//g')"
ident='^[a-z_][a-z0-9_]*$'
[[ "$service" =~ $ident ]] || { echo "invalid service_name: '$service'" >&2; exit 1; }

while IFS= read -r name; do
  [[ "$name" =~ $ident ]] || { echo "invalid endpoint name: '$name'" >&2; exit 1; }
done < <(jq -r '.endpoints[] | (.tool_name // .endpoint_id)' <<<"$json")

dest="$out_root/$service"
mkdir -p "$dest"

SERVICE="$service" DEST="$dest" TEMPLATES="$here/templates" python3 -c '
import json, os, sys
from jinja2 import Template
sys.path.insert(0, os.environ["TEMPLATES"])
from service_template import ENDPOINT_TEMPLATE
from services_consolidation_template import SERVICE_TEMPLATE

svc = json.load(sys.stdin)
name, dest = os.environ["SERVICE"], os.environ["DEST"]
base = {"service_name": name, "base_url": svc.get("base_url", "")}
eps = []
for e in svc["endpoints"]:
    e = dict(e)
    e["tool_name"] = e.get("tool_name") or e["endpoint_id"]
    e["endpoint_id"] = e.get("endpoint_id") or e["tool_name"]
    eps.append(e)
    with open(os.path.join(dest, e["tool_name"] + ".py"), "w") as f:
        f.write(Template(ENDPOINT_TEMPLATE).render(**base, **e))
with open(os.path.join(dest, name + "_tools.py"), "w") as f:
    f.write(Template(SERVICE_TEMPLATE).render(**base, endpoints=eps))
' <<<"$json"

echo "created $dest:"
ls -1 "$dest"
