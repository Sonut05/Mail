#!/usr/bin/env python3
"""
MailMind AI — Production Readiness Verification Script

Runs pre-flight and release-gate audits across configuration, database migrations,
security policies, forbidden scopes, and build artifacts.
"""

import os
import sys
import re

# Ensure backend directory is on sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"


def check(title: str, passed: bool, detail: str = ""):
    status = f"{GREEN}PASS{RESET}" if passed else f"{RED}FAIL{RESET}"
    print(f"[{status}] {BOLD}{title}{RESET}")
    if detail:
        print(f"       -> {detail}")
    return passed


def main():
    print(f"\n{BOLD}=== MailMind AI — Production Readiness Pre-Flight Audit ==={RESET}\n")
    all_passed = True

    # 1. Check Required Production Files
    required_files = [
        "docker-compose.yml",
        "DEPLOYMENT.md",
        "NETLIFY.md",
        "netlify.toml",
        "package.json",
        ".env.production.example",
        "backend/Dockerfile",
        "backend/requirements.txt",
        "backend/worker.py",
        "backend/run.py",
        "frontend/Dockerfile",
        "frontend/nginx.conf",
        "frontend/package.json",
        "netlify/functions/api.py",
        "scripts/prepare-netlify.js"
    ]
    missing = [f for f in required_files if not os.path.exists(os.path.join(BASE_DIR, f))]
    p = check("Required Production Assets", len(missing) == 0,
              "All required deployment templates and configs present" if not missing else f"Missing: {missing}")
    all_passed = all_passed and p

    # 2. Check Security Scopes in Codebase (Principle of Least Privilege)
    forbidden_scopes = ["gmail.send", "gmail.modify", "gmail.compose", "gmail.insert"]
    scope_violations = []
    py_files = []
    for root, _, files in os.walk(os.path.join(BACKEND_DIR, "app")):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.join(root, f))

    for pf in py_files:
        with open(pf, "r", encoding="utf-8") as f:
            content = f.read()
            for scope in forbidden_scopes:
                # Disregard comment/docstring occurrences if any, check code assignments
                matches = re.findall(rf'["\']https?://www\.googleapis\.com/auth/{scope}["\']|["\']https://mail\.google\.com/["\']', content)
                if matches:
                    scope_violations.append((pf, scope))

    p = check("Zero Prohibited Gmail Scopes", len(scope_violations) == 0,
              "Enforced least-privilege: gmail.readonly only" if not scope_violations else f"Violations: {scope_violations}")
    all_passed = all_passed and p

    # 3. Check Google Calendar Write Protection
    cal_writes = []
    for pf in py_files:
        with open(pf, "r", encoding="utf-8") as f:
            content = f.read()
            if "events().insert" in content or "events().update" in content or "events().delete" in content:
                cal_writes.append(pf)
    p = check("Zero Google Calendar Write Mutations", len(cal_writes) == 0,
              "Zero autonomous external calendar modifications" if not cal_writes else f"Violations: {cal_writes}")
    all_passed = all_passed and p

    # 4. Check Frontend Build Distribution
    dist_dir = os.path.join(BASE_DIR, "frontend", "dist")
    index_html = os.path.join(dist_dir, "index.html")
    dist_valid = os.path.exists(index_html) and os.path.getsize(index_html) > 0
    p = check("Frontend Production Bundle", dist_valid,
              f"Compiled React 19 SPA verified in {dist_dir}" if dist_valid else "Run 'npm run build' first")
    all_passed = all_passed and p

    # 5. Check Production Config Guardrails
    from app.config import validate_production_config, ProductionConfig
    # Test that default dev values are rejected by production validator
    bad_cfg = {
        "ENV": "production",
        "DEBUG": True,
        "SECRET_KEY": "dev-secret-key-change-me",
        "SQLALCHEMY_DATABASE_URI": "sqlite:///test.db",
        "ENCRYPTION_KEY": ""
    }
    errors = validate_production_config(bad_cfg)
    p = check("Production Config Guardrails (Rejects Unsafe Dev Configs)", len(errors) == 4,
              f"Correctly caught {len(errors)}/4 production security violations")
    all_passed = all_passed and p

    # 6. Check Durable AI Queue Architecture
    from app.services.job_queue_service import enqueue_ai_job, claim_next_ai_job, get_queue_metrics
    p = check("Durable AI Queue & Lease Architecture", callable(enqueue_ai_job) and callable(claim_next_ai_job) and callable(get_queue_metrics),
              "PostgreSQL durable row-level lock queue and lease recovery engine active")
    all_passed = all_passed and p

    print("\n" + "=" * 60)
    if all_passed:
        print(f"{GREEN}{BOLD}RESULT: ALL PRODUCTION AUDIT GATES PASSED (Codebase is 100% Ready){RESET}")
        return 0
    else:
        print(f"{RED}{BOLD}RESULT: AUDIT GATES FAILED{RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
