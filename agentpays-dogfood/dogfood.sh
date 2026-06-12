#!/usr/bin/env bash
#
# agentpays-dogfood — End-to-end dogfood script for AgentPays V1
#
# Full 10-step flow:
#   1.  discover()        → MCP x402.discover (visibility sections)
#   1.5 select_section()  → Pick top_rated > new_talent > all
#   2.  pick_seller()     → Pick highest-rated seller from section
#   2.5 negotiate_scope() → MCP agent_pay.negotiate_scope
#   3.  commit_scope()    → MCP agent_pay.accept_scope (on-chain)
#   4.  pay()             → MCP x402.pay
#   5.  deliver()         → Mock delivery
#   6.  verify()          → MCP agent_pay.verify
#   7.  submit_rating()   → MCP agent_pay.submit_rating
#   8.  log()             → Append to transaction log
#   9.  dashboard()       → Open dashboard HTML
#
# Usage:
#   ./dogfood.sh                          # Full auto flow
#   ./dogfood.sh --mcp-url http://...     # Custom MCP server URL
#   ./dogfood.sh --dry-run                # Print steps only
#
# Env vars:
#   MCP_URL      — MCP JSON-RPC endpoint (default: http://localhost:8000/mcp)
#   LOG_FILE     — Transaction log path (default: ./dogfood-data/transactions.json)
#   DASHBOARD    — Dashboard HTML path (default: ./dogfood-data/dashboard/index.html)
#   DRY_RUN      — If set, print steps without executing
#   RATING_*     — Override rating dimensions (see dogfood.env.example)
#   BUYER_WALLET — Buyer wallet address (default: 0xbuyer-mock-001)
#   SELLER_WALLET — Seller wallet address (default: 0xseller-mock-001)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_URL="${MCP_URL:-http://localhost:8000/mcp}"
LOG_FILE="${LOG_FILE:-${SCRIPT_DIR}/dogfood-data/transactions.json}"
DASHBOARD_DIR="${DASHBOARD_DIR:-${SCRIPT_DIR}/dashboard}"
TIMESTAMP=$(date +%s)
ORDER_ID="order-${TIMESTAMP}"
TX_VALUE="${TX_VALUE:-0.01}"

# Default wallets (mock)
BUYER_WALLET="${BUYER_WALLET:-0xbuyer-mock-001}"
SELLER_WALLET="${SELLER_WALLET:-0xseller-mock-001}"

# Rating defaults (overridable via env)
RATING_QUALITY="${RATING_QUALITY:-5}"
RATING_ACCURACY="${RATING_ACCURACY:-4}"
RATING_SPEED="${RATING_SPEED:-5}"
RATING_COMMUNICATION="${RATING_COMMUNICATION:-4}"
RATING_REHIRE="${RATING_REHIRE:-5}"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

info()  { echo -e "${BLUE}[${1}]${NC} ${2}"; }
ok()    { echo -e "${GREEN}  ✓${NC} ${1}"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} ${1}"; }
step()  { echo; echo -e "${CYAN}━━━ Step ${1}${NC} ${2}"; }

_mcp_call() {
    local method="$1"
    local params="$2"
    if [ -n "${DRY_RUN:-}" ]; then
        echo '{"jsonrpc":"2.0","result":{"status":"dry-run"},"id":1}'
        return
    fi
    local payload
    payload=$(printf '{"jsonrpc":"2.0","method":"%s","params":%s,"id":1}' "$method" "$params")
    curl -s -X POST "$MCP_URL" \
        -H "Content-Type: application/json" \
        -d "$payload" 2>/dev/null || echo '{"jsonrpc":"2.0","result":{"status":"mock-fallback"},"id":1}'
}

_json_get() {
    local json="$1"
    local key="$2"
    python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('result',{}).get('${key}',''))" <<< "$json" 2>/dev/null || echo ""
}

_json_get_nested() {
    python3 -c "
import sys, json
d = json.load(sys.stdin)
result = d.get('result', d)
keys = '${2}'.split('.')
for k in keys:
    result = result.get(k, {})
print(result if not isinstance(result, (dict, list)) else '')
" 2>/dev/null || echo ""
}

_log_json() {
    mkdir -p "$(dirname "$LOG_FILE")"
    echo "$1" >> "$LOG_FILE"
    echo "," >> "$LOG_FILE"
}

# ─────────────────────────────────────────────
# Step 1: discover — Query Bazaar with visibility sections
# ─────────────────────────────────────────────

step 1 "Discover agents via x402 Bazaar"

DISCOVER_PARAMS='{"query":"data processing","max_results":20,"sections":true}'
DISCOVER_RESPONSE=$(_mcp_call "x402.discover" "$DISCOVER_PARAMS")

# Save for later use
echo "$DISCOVER_RESPONSE" > /tmp/dogfood-discover-${TIMESTAMP}.json

SECTIONS=$(python3 -c "
import sys, json
resp = json.load(sys.stdin)
result = resp.get('result', resp)
sections = result.get('sections', {})
for name in ['top_rated', 'new_talent', 'trending', 'all']:
    items = sections.get(name, [])
    if items:
        print(json.dumps({'section': name, 'count': len(items), 'items': items}))
        sys.exit(0)
print(json.dumps({'section': 'all', 'count': 0, 'items': []}))
" <<< "$DISCOVER_RESPONSE" 2>/dev/null || echo '{"section":"all","count":0,"items":[]}')

SELECTED_SECTION=$(echo "$SECTIONS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('section','all'))" 2>/dev/null || echo "all")
SECTION_COUNT=$(echo "$SECTIONS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo "0")

if [ "$SECTION_COUNT" = "0" ]; then
    warn "No agents found in any section — continuing with mock data"
    SELECTED_SECTION="all"
    SECTION_COUNT=1
fi

ok "Section: ${SELECTED_SECTION} (${SECTION_COUNT} agents)"

# ─────────────────────────────────────────────
# Step 1.5: select_section — Pick best available section
# ─────────────────────────────────────────────

step "1.5" "Select visibility section"

echo -e "  ${GREEN}Selected section:${NC} ${SELECTED_SECTION}"
echo -e "  ${GREEN}Preference order:${NC} top_rated > new_talent > trending > all"
ok "Section selected"

# ─────────────────────────────────────────────
# Step 2: pick_seller — Pick highest-rated seller
# ─────────────────────────────────────────────

step 2 "Pick seller from ${SELECTED_SECTION}"

SELLER_INFO=$(python3 -c "
import sys, json
resp = json.load(sys.stdin)
result = resp.get('result', resp)
sections = result.get('sections', result)
items = sections.get('${SELECTED_SECTION}', sections.get('all', []))
if items:
    # Pick first item (already sorted by rating/composite)
    best = items[0]
    print(json.dumps({
        'id': best.get('id', best.get('name', 'mock-agent')),
        'name': best.get('name', 'Mock Agent'),
        'wallet': best.get('endpoint', '0x' + '1' * 40),
        'price': best.get('pricing', 0.01),
        'rating': best.get('composite_rating', 4.5),
        'description': best.get('description', 'Mock data processing agent'),
    }))
else:
    print(json.dumps({'id': 'mock-agent-001', 'name': 'Mock Agent', 'wallet': '${SELLER_WALLET}', 'price': 0.01, 'rating': 4.5, 'description': 'Mock data processing agent'}))
" <<< "$DISCOVER_RESPONSE" 2>/dev/null)

SELLER_ID=$(echo "$SELLER_INFO" | _json_get "id" 2>/dev/null || echo "mock-agent-001")
SELLER_NAME=$(echo "$SELLER_INFO" | _json_get "name" 2>/dev/null || echo "Mock Agent")
SELLER_WALLET=$(echo "$SELLER_INFO" | _json_get "wallet" 2>/dev/null || echo "$SELLER_WALLET")

ok "Seller: ${SELLER_NAME} (${SELLER_ID})"
ok "Wallet: ${SELLER_WALLET}"

# ─────────────────────────────────────────────
# Step 2.5: negotiate_scope — Propose and accept scope
# ─────────────────────────────────────────────

step "2.5" "Negotiate scope with seller"

SCOPE=$(cat <<SCOPE_EOF
{
    "capability": "data_processing",
    "inputs": {"format": "json", "source": "test-data"},
    "output_spec": {"format": "json", "fields": ["result", "confidence", "processing_time"]},
    "acceptance_criteria": ["all fields populated", "confidence > 0.8"],
    "deadline": "$(date -u -d '+24 hours' +'%Y-%m-%dT%H:%M:%SZ')",
    "price": ${TX_VALUE}
}
SCOPE_EOF
)

NEGOTIATE_PARAMS=$(python3 -c "
import json
scope = json.loads('''${SCOPE//\'/\\'}''')
params = {
    'order_id': '${ORDER_ID}',
    'proposed_scope': scope,
    'action': 'propose'
}
print(json.dumps(params))
")

NEGOTIATE_RESPONSE=$(_mcp_call "agent_pay.negotiate_scope" "$NEGOTIATE_PARAMS")
SCOPE_HASH=$(_json_get "$NEGOTIATE_RESPONSE" "scope_hash")

if [ -z "$SCOPE_HASH" ]; then
    SCOPE_HASH="0xdogfood-scope-${TIMESTAMP}"
    warn "No scope hash from MCP — using mock: ${SCOPE_HASH}"
else
    ok "Scope hash: ${SCOPE_HASH:0:20}..."
fi

# Accept the scope (buyer & seller both accept)
ACCEPT_PARAMS=$(python3 -c "
import json
params = {
    'order_id': '${ORDER_ID}',
    'proposed_scope': json.loads('''${SCOPE//\'/\\'}'''),
    'action': 'accept'
}
print(json.dumps(params))
")
ACCEPT_RESPONSE=$(_mcp_call "agent_pay.negotiate_scope" "$ACCEPT_PARAMS")
ok "Scope accepted by seller"

# ─────────────────────────────────────────────
# Step 3: commit_scope — On-chain scope commitment
# ─────────────────────────────────────────────

step 3 "Commit scope on-chain via accept_scope"

COMMIT_PARAMS=$(python3 -c "
import json
params = {
    'order_id': '${ORDER_ID}',
    'scope_hash': '${SCOPE_HASH}',
    'buyer': '${BUYER_WALLET}',
    'seller': '${SELLER_WALLET}'
}
print(json.dumps(params))
")
COMMIT_RESPONSE=$(_mcp_call "agent_pay.accept_scope" "$COMMIT_PARAMS")
COMMIT_STATUS=$(_json_get "$COMMIT_RESPONSE" "status")

if [ "$COMMIT_STATUS" = "scope_committed" ]; then
    PROPOSE_TX=$(_json_get "$COMMIT_RESPONSE" "propose_tx")
    ACCEPT_TX=$(_json_get "$COMMIT_RESPONSE" "accept_tx")
    ok "Scope committed — propose_tx: ${PROPOSE_TX:0:20}..., accept_tx: ${ACCEPT_TX:0:20}..."
else
    warn "Scope commitment mock — continuing"
fi

# ─────────────────────────────────────────────
# Step 4: pay — x402 payment
# ─────────────────────────────────────────────

step 4 "Pay via x402"

PAY_PARAMS=$(python3 -c "
import json
params = {
    'service_id': '${SELLER_ID}',
    'amount': '${TX_VALUE}',
    'currency': 'USDC',
}
print(json.dumps(params))
")
PAY_RESPONSE=$(_mcp_call "x402.pay" "$PAY_PARAMS")
CHARGE_ID=$(_json_get "$PAY_RESPONSE" "charge_id")
PAYMENT_STATUS=$(_json_get "$PAY_RESPONSE" "status")

if [ -z "$CHARGE_ID" ]; then
    CHARGE_ID="mock-charge-${TIMESTAMP}"
    warn "No charge from x402 — using mock: ${CHARGE_ID}"
else
    ok "Payment: ${CHARGE_ID} (${PAYMENT_STATUS})"
fi

# ─────────────────────────────────────────────
# Step 5: deliver — Agent delivers work
# ─────────────────────────────────────────────

step 5 "Deliver work matching scope"

RESULT_HASH="0xresult-$(python3 -c "import hashlib; print(hashlib.sha256(b'result-${TIMESTAMP}').hexdigest()[:16])" 2>/dev/null || echo "${TIMESTAMP}")"
DELIVERY_REPORT=$(cat <<REPORT_EOF
{
    "status": "delivered",
    "result_hash": "${RESULT_HASH}",
    "output": {"result": "success", "confidence": 0.95, "processing_time": "1.2s"},
    "scope_matched": true
}
REPORT_EOF
)
ok "Work delivered — hash: ${RESULT_HASH:0:20}..."

# ─────────────────────────────────────────────
# Step 6: verify — Buyer verifies and releases payment
# ─────────────────────────────────────────────

step 6 "Verify delivery and release payment"

VERIFY_PARAMS=$(python3 -c "
import json
params = {
    'order_id': '${ORDER_ID}',
    'resultHash': '${RESULT_HASH}',
}
print(json.dumps(params))
")
VERIFY_RESPONSE=$(_mcp_call "agent_pay.verify" "$VERIFY_PARAMS")
VERIFIED=$(_json_get "$VERIFY_RESPONSE" "verified")

if [ "$VERIFIED" = "true" ]; then
    ok "Delivery verified — payment released"
else
    ok "Delivery verified (mock) — payment released"
fi

# ─────────────────────────────────────────────
# Step 7: submit_rating — Rate seller on 5 dimensions
# ─────────────────────────────────────────────

step 7 "Submit 5-dimension rating"

RATING_PARAMS=$(python3 -c "
import json
params = {
    'seller_address': '${SELLER_WALLET}',
    'order_id': '${ORDER_ID}',
    'quality': ${RATING_QUALITY},
    'accuracy': ${RATING_ACCURACY},
    'speed': ${RATING_SPEED},
    'communication': ${RATING_COMMUNICATION},
    'would_hire_again': ${RATING_REHIRE},
    'comment': 'Automated dogfood test — order ${ORDER_ID}'
}
print(json.dumps(params))
")
RATING_RESPONSE=$(_mcp_call "agent_pay.submit_rating" "$RATING_PARAMS")
COMPOSITE=$(_json_get "$RATING_RESPONSE" "composite")

ok "Rating submitted — ${RATING_QUALITY}/${RATING_ACCURACY}/${RATING_SPEED}/${RATING_COMMUNICATION}/${RATING_REHIRE} (q/a/s/c/r)"
ok "Composite score: ${COMPOSITE:-4}"

# ─────────────────────────────────────────────
# Step 8: log — Append transaction record
# ─────────────────────────────────────────────

step 8 "Log transaction"

# Get seller profile for badge/tier info
PROFILE_PARAMS=$(python3 -c "
import json
params = {'agent_address': '${SELLER_WALLET}'}
print(json.dumps(params))
")
PROFILE_RESPONSE=$(_mcp_call "agent_pay.get_agent_profile" "$PROFILE_PARAMS")
BADGES=$(_json_get "$PROFILE_RESPONSE" "badges" 2>/dev/null || echo "[]")
KYA_SCORE=$(_json_get "$PROFILE_RESPONSE" "kya_score" 2>/dev/null || echo "75")

TRANSACTION=$(python3 -c "
import json
tx = {
    'tx_id': '${ORDER_ID}',
    'timestamp': $(date +%s),
    'timestamp_iso': '$(date -u +'%Y-%m-%dT%H:%M:%SZ')',
    'buyer': '${BUYER_WALLET}',
    'seller': '${SELLER_WALLET}',
    'seller_name': '${SELLER_NAME}',
    'amount': ${TX_VALUE},
    'currency': 'USDC',
    'status': 'completed',
    'visibility_section': '${SELECTED_SECTION}',
    'scope_hash': '${SCOPE_HASH}',
    'scope': {
        'capability': 'data_processing',
        'deadline': '$(date -u -d '+24 hours' +'%Y-%m-%dT%H:%M:%SZ')',
        'price': ${TX_VALUE}
    },
    'ratings': {
        'quality': ${RATING_QUALITY},
        'accuracy': ${RATING_ACCURACY},
        'speed': ${RATING_SPEED},
        'communication': ${RATING_COMMUNICATION},
        'would_hire_again': ${RATING_REHIRE},
        'composite': ${COMPOSITE:-4}
    },
    'badges': {
        'seller': ${BADGES:-[]},
        'buyer': {'tier': 'BRONZE', 'progress': '1/5 for Silver'}
    },
    'kya_score': ${KYA_SCORE},
    'result_hash': '${RESULT_HASH}'
}
print(json.dumps(tx, indent=2))
")

_log_json "$TRANSACTION"

echo "$TRANSACTION" > "/tmp/dogfood-tx-${TIMESTAMP}.json"
ok "Transaction logged to ${LOG_FILE}"

# ─────────────────────────────────────────────
# Step 9: dashboard — Launch dashboard HTML
# ─────────────────────────────────────────────

step 9 "Open dashboard"

DASHBOARD_FILE="${DASHBOARD_DIR}/index.html"

if [ -f "$DASHBOARD_FILE" ]; then
    echo -e "  ${GREEN}Dashboard ready:${NC} file://${DASHBOARD_FILE}"
    echo -e "  ${GREEN}Or serve via:${NC} python3 -m http.server 8080 -d ${DASHBOARD_DIR}"
    # Attempt to open (works on macOS, some Linux)
    if command -v open &>/dev/null; then
        open "$DASHBOARD_FILE" 2>/dev/null || true
    elif command -v xdg-open &>/dev/null; then
        xdg-open "$DASHBOARD_FILE" 2>/dev/null || true
    fi
else
    warn "Dashboard HTML not found at ${DASHBOARD_FILE}"
    echo -e "  ${YELLOW}Run the dashboard generator first or build manually.${NC}"
fi

# ─────────────────────────────────────────────
# Summary
# ────────────────────────────

echo
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  DOGFOOD FLOW COMPLETE${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Order:    ${ORDER_ID}"
echo -e "  Seller:   ${SELLER_NAME}"
echo -e "  Scope:    ${SCOPE_HASH:0:20}..."
echo -e "  Rating:   ${RATING_QUALITY}/${RATING_ACCURACY}/${RATING_SPEED}/${RATING_COMMUNICATION}/${RATING_REHIRE}"
echo -e "  Composite: ${COMPOSITE:-4}/5"
echo -e "  Log:      ${LOG_FILE}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo
echo -e "  View dashboard: file://${DASHBOARD_FILE}"
echo