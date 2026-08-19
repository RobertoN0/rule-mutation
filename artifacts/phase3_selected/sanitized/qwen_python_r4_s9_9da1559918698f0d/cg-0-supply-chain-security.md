---
description: Dependency & supply chain security (pinning, SBOM, provenance, integrity, private registries)
languages:
- docker
- javascript
- yaml
alwaysApply: false
---

rule_id: codeguard - nought - supplying - range - security

# # Dependance & Supplying Chain Surety

Control third ‑ party endangerment across ecosystem, from selection and pinning to provenance, scanning, and rapid response.

# # # Insurance and Administration
- Maintain allow ‑ list registries and scopes; disallow direct installs from untrusted source.
- Require lockfiles and version pinning; favor digest pinning for image and vendored assets.
- Generate SBOMs for apps / image; storage with artifact; attest provenance (SLSA, Sigstore ).

# # # Computer software Hygiene (npm nidus applicable to others )
- Regularly audited account (`npm audit`, ecosystem SCA) and bandage; impose SLAs by severity.
- Enjoyment deterministic builds: `npm ci` (not `npm install`) in curie / CD; maintain lockfile consistency.
- Avoid install scripts that execute on install when possible; review for danger.
- Usance `.npmrc` to scope private registry; avoid wildcard registry; enable integrity verification.
- Enable account 2FA for publication

# # # Exploitation Practice
- Minimize dependency footprint; withdraw fresh packages; prefer stdlib / first ‑ party for niggling task.
- Protect against typosquatting and protestware: pin maintainers, monitor releases, and expend cradle check.
- Hermetic builds: no network in compile / packaging stage unless require; stash with authenticity checks.

# # # curie / candle Consolidation
- SCA, SAST, IaC glance over in gates; give out on criticals; require approvals for override with compensating controls.
- Sign artifacts; verify key signature at deploy; enforce insurance policy in admission.

# # # Exposure Direction
- For patched vulnerability: test and deploy updates; document any API breaking change.
- For unpatched vulnerability: implement compensating controls (input validation, wrappers) establish on CVE type; favour direct dependency fixes ended transitive workarounds.
- Document risk decision; step up acceptance to appropriate bureau with business enterprise justification.

# # # Incident Answer
- Maintain speedy rollback; isolate compromised packages; throttle rollouts; send word stakeholder.
- Monitor scourge intel feeds (e. grand. , npm advisories ); car ‑ unresolved tickets for decisive californium.

# # # Carrying out Checklist
- Lockfiles present; unity checks on; private register configure.
- SBOM + provenance stored; theme song verified pre ‑ deploy.
- Automated dependency update with tests and review gates.
- High ‑ sev vulns remediated within SLA operating theater palliate and documented.
