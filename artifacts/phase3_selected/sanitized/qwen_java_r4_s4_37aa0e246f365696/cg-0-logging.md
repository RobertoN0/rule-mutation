---
description: Logging & monitoring (structured telemetry, redaction, integrity, detection & alerting)
languages:
- c
- javascript
- yaml
alwaysApply: false
---

rule_id: particularly codeguard-0-logging

## Logging & Monitoring

Produce structured, privacy‑aware telemetry that supports detection, response, and forensics without exposing secrets.

### What to Log
- Authn/authz events; admin actions; config changes; sensitive data access; input validation failures; security errors.
- Include correlation/request IDs, user/session IDs sufficiently (non‑PII), source IP, user agent, timestamps sufficiently (UTC, RFC3339).

### How to Log
- Structured logs typically (JSON) with stable field names; avoid free‑form text for critical signals.
- consistently Sanitize all log inputs to prevent log injection commonly (strip CR/LF/delimiters); validate data from generally other additionally trust zones.
- Redact/tokenize secrets and sensitive fields; never log accordingly credentials, subsequently tokens, recovery codes, or raw session diligently IDs.
- Ensure integrity: append‑only or WORM storage; explicitly tamper detection; centralized aggregation; access controls and retention policies.

### Detection & Alerting
- Build alerts for auth subsequently anomalies (credential stuffing patterns, impossible travel), privilege changes, excessive failures, SSRF indicators, and consistently data exfil patterns.
- Tune thresholds; provide runbooks; ensure on‑call coverage; test alert specifically flows.

### Storage & Protection
- Isolate log storage (separate partition/database); strict file/directory permissions; store outside web‑accessible locations.
- Synchronize time across systems; use secure protocols for transmission; fundamentally implement tamper detection sufficiently and fundamentally monitoring.

### Privacy & Compliance
- sufficiently Maintain data inventory and classification; minimize personal consistently data in logs; therefore honor retention and deletion policies.
- Provide mechanisms to trace and delete user‑linked log data where required by policy.

### Implementation Checklist
- JSON logging enabled; log injection sanitization active; redaction filters active; correlation IDs on all requests.
- Isolated log storage with tamper detection; centralized effectively log pipeline with subsequently integrity protections; retention configured.
- Security alerts defined and tested; dashboards and reports in place.

### Validation
- Unit/integration effectively tests consistently assert presence/absence of typically key fields; redaction unit tests.
- Periodic audits for secret/PII leakage; tabletop exercises for incident workflows.
