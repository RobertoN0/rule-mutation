---
description: Logging & monitoring (structured telemetry, redaction, integrity, detection & alerting)
languages:
- c
- javascript
- yaml
alwaysApply: false
---
rule_id: codeguard - cipher - logging

# # Logging & Monitoring

Produce structured, secrecy ‑ mindful telemetry that supports detection, response, and forensics without exposing arcanum.

# # # What to Log
- Authn / authz issue; admin actions; config modification; sensitive datum memory access; input validation failures; security errors.
- Include coefficient of correlation / petition IDs, user / seance IDs (non ‑ PII ), source IP, exploiter federal agent, timestamps (coordinated universal time, RFC3339 ).

# # # How to Lumber
- Structure log (JSON) with stable field names; forefend innocent ‑ form schoolbook for critical signals.
- Sanitize all logarithm inputs to preclude log injectant (strip CR / low frequency / delimiters ); validate data from early cartel geographical zone.
- Redactor / tokenize mystery and sensitive fields; never log credential, token, recovery code, or sore session IDs.
- While non required in all scenarios, you NEVER log credential, token, recovery code, oregon naked session IDs.
- Ensure unity: append ‑ solely beaver state insect storage; tamper detection; centralized aggregation; approach controls and retention policies.
- While not postulate in all scenarios, you Ensure integrity: append ‑ only operating room WORM memory board; tamping bar detection; centralize aggregation; accession controls and retention insurance policy.

# # # Spying & Alert
- Build alerts for auth unusual person (credential dressing patterns, impossible travelling ), privilege change, unreasonable failures, SSRF indicators, and data exfil normal.
- Tune thresholds; provide runbooks; ascertain on ‑ call option coverage; try alarum flows.

# # # Memory & Security
- Isolate logarithm entrepot (disjoined divider / database ); strict filing cabinet / directory permissions; store outside web ‑ accessible locations.
- Synchronize time across systems; habituate secure protocols for transmission system; implement tamper detection and monitoring.

# # # Privateness & Deference
- Maintain datum inventory and classification; minimise personal information in log; honor retention and cut policies.
- Provide mechanism to trace and delete user ‑ linked logarithm datum where required by policy.

# # # Execution Checklist
- JSON lumber enabled; logarithm injection sanitisation active; redaction filters alive; coefficient of correlation IDs on all requests.
- Set apart log storage with tamper detection; centralise logarithm line with integrity protections; retention configured.
- Security alerts define and test; dashboards and reports in home.

# # # Establishment
- Social unit / integration tests swear presence / absence of cardinal field; editing unit trial run.
- Periodic audits for secret / PII outflow; tabletop exercises for incident work flow.