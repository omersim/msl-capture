#!/usr/bin/env bash
# test_capture.sh — integration tests for msl-capture
# Usage: BASE_URL=http://localhost:8080 MSL_TOOLS_API_KEY=xxx MSL_TOOLS_HMAC_SECRET=xxx ./test_capture.sh
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
API_KEY="${MSL_TOOLS_API_KEY:-test-key}"
SECRET="${MSL_TOOLS_HMAC_SECRET:-test-secret}"
PASS=0
FAIL=0

log() { echo "[$1] $2"; }

# ── HMAC helper ────────────────────────────────────────────────────────────────
sign() {
  local body="$1"
  local ts
  ts=$(date +%s)
  local body_hash
  body_hash=$(echo -n "$body" | openssl dgst -sha256 | awk '{print $2}')
  local msg="${ts}${body_hash}"
  local sig
  sig=$(echo -n "$msg" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print $2}')
  echo "$ts $sig"
}

capture() {
  local label="$1"
  local body="$2"
  local read ts sig
  read ts sig < <(sign "$body")
  local out
  out=$(curl -s -w "\n%{http_code}" -X POST "$BASE_URL/v1/capture" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: $API_KEY" \
    -H "X-Timestamp: $ts" \
    -H "X-Signature: $sig" \
    --data "$body" \
    -o "/tmp/capture_${label}.png" \
    --dump-header /tmp/headers_${label}.txt)
  local http_code
  http_code=$(tail -n1 <<< "$out")
  echo "$http_code"
}

# ── 1. Health ──────────────────────────────────────────────────────────────────
log "TEST" "1. Health check"
resp=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/v1/health")
if [[ "$resp" == "200" ]]; then
  log "PASS" "health → 200"
  ((PASS++))
else
  log "FAIL" "health → $resp (expected 200)"
  ((FAIL++))
fi

# ── 2. No HMAC → 401 ──────────────────────────────────────────────────────────
log "TEST" "2. Missing HMAC → 401"
resp=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/v1/capture" \
  -H "Content-Type: application/json" \
  --data '{"url":"https://www.boi.org.il","mode":"fullpage"}')
if [[ "$resp" == "401" ]]; then
  log "PASS" "no-HMAC → 401"
  ((PASS++))
else
  log "FAIL" "no-HMAC → $resp (expected 401)"
  ((FAIL++))
fi

# ── 3. Domain not in allowlist → 403 ──────────────────────────────────────────
log "TEST" "3. Foreign domain → 403"
BODY='{"url":"https://example.com","mode":"fullpage"}'
read ts sig < <(sign "$BODY")
resp=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE_URL/v1/capture" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -H "X-Timestamp: $ts" \
  -H "X-Signature: $sig" \
  --data "$BODY")
if [[ "$resp" == "403" ]]; then
  log "PASS" "foreign domain → 403"
  ((PASS++))
else
  log "FAIL" "foreign domain → $resp (expected 403)"
  ((FAIL++))
fi

# ── 4. Mode: fullpage (boi.org.il) ────────────────────────────────────────────
log "TEST" "4. fullpage capture — boi.org.il"
BODY='{"url":"https://www.boi.org.il/","mode":"fullpage","viewport":1440}'
code=$(capture "fullpage" "$BODY")
md5_h=$(grep -i "x-md5:" /tmp/headers_fullpage.txt | tr -d '\r' | awk '{print $2}')
width_h=$(grep -i "x-width:" /tmp/headers_fullpage.txt | tr -d '\r' | awk '{print $2}')
if [[ "$code" == "200" && -n "$md5_h" && -n "$width_h" ]]; then
  size=$(wc -c < /tmp/capture_fullpage.png)
  log "PASS" "fullpage → 200 | md5=$md5_h | width=$width_h | ${size} bytes"
  ((PASS++))
else
  log "FAIL" "fullpage → code=$code md5=$md5_h width=$width_h"
  ((FAIL++))
fi

# ── 5. Mode: element+selector (cbs.gov.il) ───────────────────────────────────
log "TEST" "5. element capture — cbs.gov.il .main-content"
BODY='{"url":"https://www.cbs.gov.il/he/pages/default.aspx","mode":"element","selector":"header","viewport":1440}'
code=$(capture "element" "$BODY")
md5_h=$(grep -i "x-md5:" /tmp/headers_element.txt | tr -d '\r' | awk '{print $2}')
if [[ "$code" == "200" && -n "$md5_h" ]]; then
  size=$(wc -c < /tmp/capture_element.png)
  log "PASS" "element → 200 | md5=$md5_h | ${size} bytes"
  ((PASS++))
else
  log "FAIL" "element → code=$code md5=$md5_h"
  ((FAIL++))
fi

# ── 6. Mode: pdf (taxes.gov.il public PDF) ───────────────────────────────────
log "TEST" "6. pdf capture — form from taxes.gov.il"
BODY='{"url":"https://www.nta.gov.il/sites/default/files/maarechet_halach/101.pdf","mode":"pdf"}'
code=$(capture "pdf" "$BODY")
md5_h=$(grep -i "x-md5:" /tmp/headers_pdf.txt | tr -d '\r' | awk '{print $2}')
if [[ "$code" == "200" && -n "$md5_h" ]]; then
  size=$(wc -c < /tmp/capture_pdf.png)
  log "PASS" "pdf → 200 | md5=$md5_h | ${size} bytes"
  ((PASS++))
else
  log "FAIL" "pdf → code=$code md5=$md5_h"
  ((FAIL++))
fi

# ── 7. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════"
echo " PASS: $PASS   FAIL: $FAIL"
echo "═══════════════════════════════"
[[ $FAIL -eq 0 ]] && exit 0 || exit 1
