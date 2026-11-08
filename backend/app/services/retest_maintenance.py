"""Explicit maintenance of the existing paper comparison, never a new account.

Keep the original policy/funding/evidence intact. An append-only acknowledgment
authorizes exactly one reviewed code fingerprint under the original settings.
It is not a reset of the preregistered evaluation or permission to backfill.
"""
from datetime import datetime, timezone
import hashlib
import re

from sqlalchemy import select, update

from app.db.models import RetestAccount, RetestEvent, RetestRun
from app.services.market_calendar import market_session
from app.services.option_research import utc
from app.services.retest_research import canonical

KIND = "MAINTENANCE_RESUME"
SCOPE = "existing-test-feed-maintenance"
RESULT_SCOPE = "existing-test-result-maintenance"
SCOPES = (SCOPE, RESULT_SCOPE)


def admission_status(db, run) -> dict:
    """Pure read shared by scanner, API and readiness; never acknowledge on GET."""
    from app.services import retest_trials as trial

    current = trial.code_hash()
    config_matches = trial.configuration() == run.policy["configuration"]
    approval = db.scalar(select(RetestEvent).where(
        RetestEvent.run_key == run.key, RetestEvent.kind == KIND,
        RetestEvent.event_key == f"maintenance-resume:{current}"))
    detail = approval.detail if approval else {}
    reviewed = bool(approval and config_matches
        and utc(approval.at) >= utc(run.activated_at)
        and not any((approval.settled, approval.unsettled, approval.realized))
        and detail.get("scope") in SCOPES
        and detail.get("reviewed_code_hash") == current
        and detail.get("original_code_hash") == run.policy["code_hash"]
        and detail.get("spec_hash") == run.policy["spec_hash"]
        and detail.get("configuration") == run.policy["configuration"]
        and re.fullmatch(r"[a-f0-9]{40}", str(detail.get("revision", ""))))
    blocked = not config_matches or (current != run.policy["code_hash"] and not reviewed)
    return {"admissions_blocked": blocked,
        "maintenance": {"resumed_at": utc(approval.at).isoformat(),
                        "revision": detail["revision"], "scope": detail["scope"]} if reviewed else None}


def resume_existing(db, *, revision: str, expected_code_hash: str,
                    expected_frozen_hash: str, now: datetime, scope: str = SCOPE) -> dict:
    """Operator-only transaction; no policy edits, funding, imports or replay."""
    from app.services import retest_trials as trial

    now = utc(now)
    if scope not in SCOPES:
        raise ValueError("Reviewed maintenance scope required")
    if market_session(now) == "regular":
        raise ValueError("Resume outside the market session")
    if not re.fullmatch(r"[a-f0-9]{40}", revision):
        raise ValueError("Exact reviewed Git revision required")
    run = db.get(RetestRun, trial.KEY)
    if run is None:
        raise ValueError("Existing comparison required; never activate here")
    if (expected_frozen_hash != run.policy["code_hash"]
            or expected_code_hash != trial.code_hash()):
        raise ValueError("Reviewed fingerprint does not match; no acknowledgment applied")
    if trial.configuration() != run.policy["configuration"] or not trial.configuration()["paper_only"]:
        raise ValueError("Original paper configuration must match")
    original = {k: v for k, v in run.policy.items() if k != "spec_hash"}
    if hashlib.sha256(canonical(original).encode()).hexdigest() != run.policy["spec_hash"]:
        raise ValueError("Original frozen policy integrity mismatch")
    if now < max(utc(run.activated_at), utc(run.processed_at)):
        raise ValueError("Maintenance cannot predate existing processing")
    accounts = list(db.scalars(select(RetestAccount).where(RetestAccount.run_key == run.key)))
    expected = {trial.account_key(a, s) for a in trial.ARMS for s in trial.SCENARIOS}
    if {a.key for a in accounts} != expected or any(not db.scalar(select(RetestEvent.id).where(
            RetestEvent.run_key == run.key, RetestEvent.account_key == a.key,
            RetestEvent.kind == "FUNDING", RetestEvent.event_key == f"funding:{a.key}")) for a in accounts):
        raise ValueError("Existing account funding must be complete")
    key = f"maintenance-resume:{expected_code_hash}"
    existing = db.scalar(select(RetestEvent.id).where(
        RetestEvent.run_key == run.key, RetestEvent.event_key == key))
    if existing:
        status = admission_status(db, run)
        if status["admissions_blocked"]:
            raise ValueError("Existing acknowledgment is invalid")
        return status
    # Serialize with the scanner before the append-only, zero-cash receipt.
    db.execute(update(RetestRun).where(RetestRun.key == run.key).values(revision=RetestRun.revision+1))
    trial.event(db, key, now, KIND, detail={"scope": scope, "revision": revision,
        "reviewed_code_hash": expected_code_hash, "original_code_hash": expected_frozen_hash,
        "spec_hash": run.policy["spec_hash"], "configuration": run.policy["configuration"],
        "basis": "Operator-authorized continuation after reviewed collection/result maintenance; same accounts and entry rules. "
                 "Original gaps remain unknown; no backfill or original-protocol performance claim."})
    return admission_status(db, run)


def main():
    import argparse
    import json
    from app.db.session import SessionLocal

    parser = argparse.ArgumentParser(description="Resume the existing paper test after reviewed maintenance")
    parser.add_argument("--revision", required=True)
    parser.add_argument("--expected-code-hash", required=True)
    parser.add_argument("--expected-frozen-hash", required=True)
    parser.add_argument("--scope", choices=SCOPES, default=SCOPE)
    parser.add_argument("--confirm", required=True, choices=["RESUME-EXISTING-PAPER-TEST"])
    args = parser.parse_args()
    with SessionLocal.begin() as db:
        result = resume_existing(db, revision=args.revision, expected_code_hash=args.expected_code_hash,
            expected_frozen_hash=args.expected_frozen_hash, now=datetime.now(timezone.utc), scope=args.scope)
        print(json.dumps(result))


if __name__ == "__main__":
    main()
