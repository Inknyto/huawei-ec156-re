#!/bin/sh
# gammu-smsd RunOnReceive hook for the EC156.
# Writes one JSON object per received SMS and optionally POSTs it to a webhook.
#
# Environment provided by gammu-smsd:
#   SMS_MESSAGES, SMS_1_NUMBER, SMS_1_TEXT, SMS_1_DATE, ...
# Optional:
#   EC156_SMS_LOG      default /var/lib/ec156-sms/inbox.jsonl
#   EC156_WEBHOOK      URL receiving {"number":...,"text":...,"date":...}
#   EC156_WEBHOOK_TOKEN bearer token, if required

set -eu

LOG="${EC156_SMS_LOG:-/var/lib/ec156-sms/inbox.jsonl}"
mkdir -p "$(dirname "$LOG")"

i=1
while [ "$i" -le "${SMS_MESSAGES:-0}" ]; do
    eval "number=\${SMS_${i}_NUMBER-}"
    eval "text=\${SMS_${i}_TEXT-}"
    eval "date=\${SMS_${i}_DATE-}"

    python3 - "$LOG" "$number" "$text" "$date" <<'PY'
import json, sys, time, os
log, number, text, date = sys.argv[1:5]
record = {"received_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "number": number, "text": text, "sms_date": date}
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
print(json.dumps(record, ensure_ascii=False))
PY

    if [ -n "${EC156_WEBHOOK:-}" ]; then
        python3 - "$EC156_WEBHOOK" "$number" "$text" "$date" "${EC156_WEBHOOK_TOKEN:-}" <<'PY'
import json, sys, urllib.request
url, number, text, date, token = sys.argv[1:6]
body = json.dumps({"number": number, "text": text, "date": date}).encode()
req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
if token:
    req.add_header("Authorization", "Bearer " + token)
try:
    urllib.request.urlopen(req, timeout=10).read()
except Exception as exc:
    print("webhook failed:", exc, file=sys.stderr)
PY
    fi

    i=$((i + 1))
done
