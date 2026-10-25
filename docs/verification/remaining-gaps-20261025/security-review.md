# Protected-mode security review

Reviewed commit `3e85ab91ad21e222280539a0fcd06e98925b1f01` against `a66c035`, the remaining-gaps specification, and `docs/protected-mode.md`. Read-only review; no repository edits. Model-routing work was excluded.

## Findings

No reproducible merge-blocking security findings identified within the documented single-worker, optional protected-mode scope. No severity-rated findings to report.

## Executed verification

Independent adversarial script: `/tmp/gap-auth-adversarial.py`.

```sh
cd /workspace/scratch/528e6091a06b/harbinger-gap-auth
OMP_NUM_THREADS=1 PYTHONPATH=src:. /tmp/harbinger-review-venv/bin/python /tmp/gap-auth-adversarial.py
```

Result: **163 assertions passed**, using actual `/tmp/hb-gap-runtime` data/models/artifacts, four provisioned ephemeral accounts, and TestClient against the actual application middleware. Enumerated **39 routes**, including FastAPI nested routers. Temporary account files were removed automatically.

Verified:

- Anonymous rejection across every non-public enumerated route/method.
- Unauthorized tenant rejection on every site-scoped route; role checks on upload and shared ingest.
- Global models, artifacts, metrics, metadata, readiness, docs/OpenAPI blocked for non-admins, including trailing-slash and encoded-path variations.
- Foreign analysis IDs rejected for analysis, evidence, downloads, and deletion even when the requesting user is an administrator.
- New login revokes the previous browser login and associated analysis session; logout and expiry revoke both kinds of session.
- Invalid/missing/foreign Origin rejected; malformed JSON and form-urlencoded credential bodies rejected without echoing password input; oversized credential requests rejected.
- Optional metrics bearer works solely for GET `/metrics`, grants no API or metadata access.
- Global replay cache warmed by admin does not contaminate tenant replay; scoped report headline metrics are removed; shared store remains intact.
- Failed-login attempt 11 is throttled; 2048-key rate-tracker bound enforced; login-session capacity enforced.
- Offline account provisioning writes hashes only and 0600 permissions; world-readable account configuration rejected.

## Static assessment and limits

Tenant-scoped tables/features, fresh per-request refresher/replay/drift/breakdown caches, sanitized bundle metrics, scoped example stores, and upload allowlists match the documented boundary. Auth/session locks preserve ownership registration against concurrent revocation. Scrypt parameters and hash shape are fixed; user configuration is administrator-provisioned. The narrow static-file exception serves the packaged console directory, not runtime data/artifacts.

This is targeted adversarial verification and code review, not a proof of absence of defects. Existing single-process/global analysis capacity and synthetic shared model constraints are explicitly documented; no new SSO, multi-host, or private-model guarantees were assumed. Authentication-cookie theft itself still conveys the identity represented by that cookie, as expected for bearer session authentication; the tested theft scenario is an analysis-session ID without its owning login cookie.
