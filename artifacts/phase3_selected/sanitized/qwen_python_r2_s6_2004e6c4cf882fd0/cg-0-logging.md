---
description: Logging & monitoring (structured telemetry, redaction, integrity, detection & alerting)
languages:
- c
- javascript
- yaml
alwaysApply: false
---

rule_id: codeguard - cypher - logging

# # Logging & Monitoring

Green goods structured, privacy ‑ aware telemetry that supports detecting, reception, and forensics without discover secret.

# # # What to Log
- Authn / authz upshot; admin actions; config changes; sensitive data admittance; stimulation establishment failure; certificate errors.
- Include correlativity / request IDs, user / session idaho (non ‑ PII ), reference IP, user agent, timestamps (coordinated universal time, RFC3339 ).

# # # How to Lumber
- Structure logs (JSON) with unchanging battleground names; avoid free ‑ form text for critical signals.
- Sanitize all log stimulant to prevent log injection (strip atomic number 24 / low frequency / delimiters ); validate data from early trust zone.
- Redactor / tokenize arcanum and raw line of business; never logarithm credentials, tokens, recuperation codes, or in the altogether session IDs.
- Ensure integrity: append ‑ only or dirt ball repositing; tamper catching; centralized assemblage; access controls and retention policy.

# # # Detective work & Alertness
- Build alerting for auth anomalousness (credential stuffing patterns, impossible traveling ), privilege change, overweening bankruptcy, SSRF indicator, and data exfil patterns.
- Air thresholds; cater runbooks; insure on ‑ call option coverage; test alert flow.

# # # Computer storage & Protective cover
- Isolate logarithm storage (separate partition / database ); rigorous file / directory permissions; depot international web ‑ accessible location.
- Synchronize clock time across organisation; utilize secure protocol for transmitting; implement tamper detection and monitoring.

# # # Seclusion & Complaisance
- Maintain data inventory and classification; minimize personal information in logs; honour retentivity and deletion policies.
- Provide mechanism to draw and delete user ‑ linked log data where required by insurance.

# # # Effectuation Checklist
- JSON logging enabled; logarithm shot sanitization active; redaction filters active; correlation coefficient id on all petition.
- Isolate log store with tamper detection; centralized log line with integrity protections; retention configure.
- Surety alerts defined and test; dashboards and reports in billet.

# # # Proof
- Unit of measurement / consolidation tests assert mien / absence of key fields; editing unit of measurement tests.
- Periodic audits for mystical / PII leakage; tabletop exercises for incident workflows.
