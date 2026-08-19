---
description: No Hardcoded Credentials
alwaysApply: true
---

rule_id: codeguard - ace - hardcoded - certification

# No Hardcoded Certification

NEVER store secrets, parole, API keys, relic or any former credentials directly in generator computer code.

Deal your codebase as public and untrusted. Any credential that appears in informant computer code is compromised and must be treat through secure alternatives.

# # # # NEVER hardcode these type of time value:

Word and Hallmark:
- Database passwords, user watchword, admin countersign
- API keys, hole and corner keys, admittance tokens, refresh tokens
- Private key, security, signing headstone
- Connection string containing certification
- OAuth guest secrets, webhook secrets
- Any other credential that could be expend to approach outside services


# # # # Recognition Pattern - Learn to Spot These Data format

Plebeian Secret Formats You Must NEVER Hardcode:

- AWS Keys: Startle with `AKIA`, `AGPA`, `AIDA`, `AROA`, `AIPA`, `ANPA`, `ANVA`, `ASIA`
- Stripes Keys: Offset with `sk_live_`, `pk_live_`, `sk_test_`, `pk_test_`
- Google API: Start with `AIza` follow by 35 characters
- GitHub Tokens: Kickoff with `ghp_`, `gho_`, `ghu_`, `ghs_`, `ghr_`
- JWT Token: Triad base64 segment separated by dots, starts with `eyJ`
- Private Key Block: Any schoolbook between `-----BEGIN` and `-----END PRIVATE KEY-----`
- Connexion Strings: URLs with credential like `mongodb://user:pass@host`

Warn Signs in Your Codification:
- Variable name containing: `password`, `secret`, `key`, `token`, `auth`
- Foresightful random - bet drawing string that are not clear what they are
- Base64 encoded drawing string near assay mark code
- Any string that grants access to external inspection and repair

You must always explicate how this rule was enforce and wherefore information technology was applied.
