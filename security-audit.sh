#!/bin/bash

# ──────────────────────────────────────────────────────────────────────────────
# Security Audit — runs before every deployment
# Scans Node.js (npm) and Python (pip-audit) dependencies for known CVEs
# Exits with code 1 if HIGH or CRITICAL vulnerabilities are found
# ──────────────────────────────────────────────────────────────────────────────

set -e

BOLD='\033[1m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

FAIL=0

echo ""
echo -e "${BOLD}${CYAN}🔒 Security Audit${NC}"
echo "────────────────────────────────────────"
echo ""

# ── 1. Node.js — npm audit ────────────────────────────────────────────────────

echo -e "${BOLD}[1/2] Scanning Node.js packages (npm audit)...${NC}"

if [ ! -d "dashboard" ]; then
  echo -e "${YELLOW}⚠️  dashboard/ directory not found, skipping npm audit${NC}"
else
  cd dashboard

  if [ ! -f "package-lock.json" ]; then
    echo -e "${YELLOW}⚠️  No package-lock.json found. Running npm install first...${NC}"
    npm install --package-lock-only --ignore-scripts 2>/dev/null || true
  fi

  # Run audit. Production dependencies gate the deploy; dev/build-only
  # tooling (eslint, tailwind) is reported but not blocking (SECURITY_AUDIT.md M-10).
  # Falls back to a throwaway node container when npm isn't on the host —
  # previously a missing npm parsed as "0 0 0 0" and the gate passed without
  # scanning anything.
  run_npm_audit() {
    if command -v npm &> /dev/null; then
      npm audit --json "$@"
    elif command -v docker &> /dev/null; then
      docker run --rm -v "$PWD/package.json:/a/package.json:ro" -v "$PWD/package-lock.json:/a/package-lock.json:ro" \
        -w /a node:22-bookworm-slim npm audit --json "$@"
    else
      return 127
    fi
  }

  set +e
  npm_output=$(run_npm_audit --omit=dev 2>/dev/null)
  npm_all_output=$(run_npm_audit 2>/dev/null)
  set -e

  # Parse counts via python3 — unparseable output is a failure, never "0 vulns"
  parse_counts() {
    python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    v = d['metadata']['vulnerabilities']
    print(v.get('critical', 0), v.get('high', 0), v.get('moderate', 0), v.get('low', 0))
except Exception:
    print('ERR ERR ERR ERR')
"
  }
  read -r critical high moderate low < <(echo "$npm_output" | parse_counts)
  read -r dev_critical dev_high _ _ < <(echo "$npm_all_output" | parse_counts)

  if [ "$critical" = "ERR" ]; then
    echo -e "${RED}❌ npm audit did not run (no npm and no docker, or no network)${NC}"
    FAIL=1
    critical=0; high=0; moderate=0; low=0
  fi
  if [ "$dev_critical" != "ERR" ]; then
    echo -e "   (incl. dev/build tooling: critical ${dev_critical}, high ${dev_high} — warning only)"
  fi

  echo -e "   Critical : ${critical:-0}"
  echo -e "   High     : ${high:-0}"
  echo -e "   Moderate : ${moderate:-0} (warning only)"
  echo -e "   Low      : ${low:-0}      (warning only)"

  has_blocking=$(( (${critical:-0} + ${high:-0}) > 0 ))
  if [ "$has_blocking" -ne 0 ]; then
    echo ""
    echo -e "${RED}❌ HIGH/CRITICAL vulnerabilities found in production Node.js packages!${NC}"
    echo ""
    echo "   Run: cd dashboard && npm audit"
    echo "   Fix: cd dashboard && npm audit fix"
    echo "   Or add overrides to dashboard/package.json if a fix is not yet available."
    echo ""
    FAIL=1
  else
    echo -e "${GREEN}✅ No high/critical vulnerabilities in Node.js packages${NC}"
  fi

  cd ..
fi

echo ""

# ── 2. Python — pip-audit ─────────────────────────────────────────────────────

echo -e "${BOLD}[2/2] Scanning Python packages (pip-audit)...${NC}"

if [ ! -f "requirements.txt" ]; then
  echo -e "${YELLOW}⚠️  requirements.txt not found, skipping Python audit${NC}"
else
  # Resolve pip-audit: PATH → managed venv → create managed venv
  PIP_AUDIT_VENV="${PIP_AUDIT_VENV:-$HOME/.venvs/pip-audit}"
  PIP_AUDIT=""

  if command -v pip-audit &> /dev/null; then
    PIP_AUDIT="$(command -v pip-audit)"
  elif [ -x "$PIP_AUDIT_VENV/bin/pip-audit" ]; then
    PIP_AUDIT="$PIP_AUDIT_VENV/bin/pip-audit"
  else
    echo "   Installing pip-audit into $PIP_AUDIT_VENV ..."
    install_log=$(mktemp)
    if python3 -m venv "$PIP_AUDIT_VENV" >"$install_log" 2>&1 \
       && "$PIP_AUDIT_VENV/bin/pip" install --quiet --upgrade pip pip-audit >>"$install_log" 2>&1; then
      PIP_AUDIT="$PIP_AUDIT_VENV/bin/pip-audit"
    else
      echo -e "${RED}❌ Could not install pip-audit — Python audit INCONCLUSIVE${NC}"
      echo "   Install error:"
      tail -15 "$install_log" 2>/dev/null | sed 's/^/     /' || true
      echo "   Hint: ensure python3-venv and python3-pip are installed"
      echo "         (Debian/Ubuntu: sudo apt-get install -y python3-pip python3-venv)"
      echo ""
      # An audit that could not run is NOT a passing audit — block the deploy.
      FAIL=1
      goto_end=1
    fi
    rm -f "$install_log"
  fi

  if [ -z "$goto_end" ]; then
    # Audit the site-packages where the project's deps are installed. Without
    # this, --local scans whatever env pip-audit itself lives in (i.e. only
    # pip-audit's own dependency tree) and always reports zero vulns.
    # NOTE: --path cannot be combined with --local (pip-audit errors out), so
    # use --path alone when we have a venv, else fall back to --local.
    site_dir=$("$PIP_AUDIT_VENV/bin/python" -c \
      'import sysconfig; print(sysconfig.get_paths()["purelib"])' 2>/dev/null)
    if [ -n "$site_dir" ] && [ -d "$site_dir" ]; then
      PIP_AUDIT_ARGS=(--format json --path "$site_dir")
    else
      PIP_AUDIT_ARGS=(--format json --local)
    fi

    export PIP_AUDIT
    export PIP_AUDIT_SITE="$site_dir"
    set +e
    pip_output=$("$PIP_AUDIT" "${PIP_AUDIT_ARGS[@]}" 2>/dev/null)
    pip_exit=$?
    set -e

    # Parse vuln count for packages listed in requirements.txt only
    py_err_log=$(mktemp)
    vuln_result=$(python3 - <<'PYEOF'
import sys, json, re, os

req_file = "requirements.txt"
req_names = set()
try:
    with open(req_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'^([A-Za-z0-9_\-\.]+)', line)
            if m:
                req_names.add(m.group(1).lower().replace('-', '_').replace('.', '_'))
except Exception:
    pass

import subprocess
pip_audit_bin = os.environ.get('PIP_AUDIT', 'pip-audit')
site = os.environ.get('PIP_AUDIT_SITE')
# --path and --local are mutually exclusive
cmd = [pip_audit_bin, '--format', 'json']
cmd += ['--path', site] if site else ['--local']
result = subprocess.run(cmd, capture_output=True, text=True)
try:
    data = json.loads(result.stdout)
    deps = data if isinstance(data, list) else data.get('dependencies', [])
except Exception:
    # Do NOT report a clean bill of health when the scan itself failed.
    print("SCAN_ERROR: pip-audit produced no parseable output", file=sys.stderr)
    for line in (result.stderr or '').strip().splitlines()[-5:]:
        print(f"  {line}", file=sys.stderr)
    print("1 0")
    sys.exit(0)

count = 0
findings = []
for dep in deps:
    norm = dep.get('name', '').lower().replace('-', '_').replace('.', '_')
    if norm not in req_names:
        continue
    for v in dep.get('vulns', []):
        count += 1
        findings.append(f"  {dep['name']}=={dep.get('version', '?')}: {v.get('id', 'UNKNOWN')} — {v.get('summary', '')[:80]}")

if findings:
    for line in findings:
        print(line, file=sys.stderr)
print(f"0 {count}")
PYEOF
2>"$py_err_log"
)
    vuln_result_exit=$?
    # Surface scan errors / findings that the heredoc wrote to stderr
    if [ -s "$py_err_log" ]; then
      sed 's/^/   /' "$py_err_log"
    fi
    rm -f "$py_err_log"
    read -r py_critical py_high <<< "$vuln_result"
    py_high=${py_high:-0}
    py_critical=${py_critical:-0}

    # py_critical is repurposed as a scan-error flag by the parser above:
    # a failed scan must block, never silently pass as "clean".
    if [ "$py_critical" -ne 0 ]; then
      echo ""
      echo -e "${RED}❌ pip-audit scan failed — Python audit is INCONCLUSIVE${NC}"
      echo "   Treating as a failure: an unverified scan is not a clean scan."
      echo ""
      FAIL=1
      py_blocking=0
    else
      py_blocking=$(( py_high > 0 ))
    fi

    if [ "$py_blocking" -ne 0 ]; then
      total_py=$py_high
      echo ""
      echo -e "${RED}❌ Vulnerabilities found in Python packages! (${total_py} found)${NC}"
      echo ""
      # Re-run to show human-readable details
      python3 - <<'PYEOF2'
import json, os, re, subprocess, sys

req_file = "requirements.txt"
req_names = set()
try:
    with open(req_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            m = re.match(r'^([A-Za-z0-9_\-\.]+)', line)
            if m:
                req_names.add(m.group(1).lower().replace('-', '_').replace('.', '_'))
except Exception:
    pass

pip_audit_bin = os.environ.get('PIP_AUDIT', 'pip-audit')
site = os.environ.get('PIP_AUDIT_SITE')
# --path and --local are mutually exclusive
cmd = [pip_audit_bin, '--format', 'json']
cmd += ['--path', site] if site else ['--local']
result = subprocess.run(cmd, capture_output=True, text=True)
try:
    data = json.loads(result.stdout)
    deps = data if isinstance(data, list) else data.get('dependencies', [])
except Exception:
    sys.exit(0)

for dep in deps:
    norm = dep.get('name', '').lower().replace('-', '_').replace('.', '_')
    if norm not in req_names or not dep.get('vulns'):
        continue
    for v in dep['vulns']:
        fix = ', '.join(v.get('fix_versions', [])) or 'no fix available'
        print(f"  {dep['name']}=={dep.get('version','?')} [{v.get('id','?')}]")
        print(f"    {v.get('summary', 'No description')[:100]}")
        print(f"    Fix: upgrade to {fix}")
PYEOF2
      echo ""
      echo "   Update affected packages in requirements.txt to the fix versions shown above."
      echo ""
      FAIL=1
    else
      echo -e "${GREEN}✅ No vulnerabilities found in Python packages (requirements.txt)${NC}"
    fi
  fi
fi

echo ""
echo "────────────────────────────────────────"

# ── Result ────────────────────────────────────────────────────────────────────

if [ "$FAIL" -ne 0 ]; then
  echo -e "${RED}${BOLD}🚨 SECURITY AUDIT FAILED — Deployment blocked${NC}"
  echo ""
  echo "   Fix the vulnerabilities above before deploying to production."
  echo "   To skip this check (NOT recommended): SKIP_SECURITY_AUDIT=1 ./deploy.sh"
  echo ""
  exit 1
else
  echo -e "${GREEN}${BOLD}✅ Security audit passed — safe to deploy${NC}"
  echo ""
fi
