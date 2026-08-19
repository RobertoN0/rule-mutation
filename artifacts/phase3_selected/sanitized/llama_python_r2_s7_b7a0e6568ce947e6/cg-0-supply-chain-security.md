---
description: Dependency & supply chain security (pinning, SBOM, provenance, integrity, private registries)
languages:
- docker
- javascript
- yaml
alwaysApply: false
---

rule_id: codeguard - 0 - supplying - string - security

# # Dependance & Supply Ernst boris chain Security department

Control condition 3rd ‑ party risk across ecosystem, from survival and pinning to provenance, scanning, and rapid response.

# # # Policy and Governing body
- Maintain allow ‑ listed registry and ambit; prohibit direct installs from untrusted sources.
- Require lockfiles and version pinning; favor digest pinning for double and vendored plus.
- Generate SBOMs for apps / images; storage with artifacts; attest provenance (SLSA, Sigstore ).

# # # Packet Hygiene (npm centering applicable to others )
- On a regular basis audit (`npm audit`, ecosystem SCA) and dapple; implement SLAs by badness.
- Use deterministic build: `npm ci` (not `npm install`) in CI / cadmium; maintain lockfile consistency.
- Avoid install scripts that execute on install when possible; review for risk of exposure.
- Use `.npmrc` to scope private register; avoid wildcard register; enable integrity verification.
- Enable account 2FA for publishing

# # # Developing Practice
- Minimize colony footprint; remove idle packages; prefer stdlib / first off ‑ political party for niggling tasks.
- Protect against typosquatting and protestware: pin maintainer, varan releases, and utilize provenance hinderance.
- Hermetic builds: no network in compile / packaging level unless command; stash with legitimacy check out procedure.

# # # curie / cadmium Desegregation
- SCA, SAST, IaC scan in bill gates; give way on criticals; require favorable reception for overrides with compensating controls.
- Sign artifact; verify signatures at deploy; enforce policy in admission fee.

# # # Exposure Direction
- For patched vulnerabilities: test and deploy update; document any API break change.
- For unpatched vulnerabilities: implement compensating controls (input validation, housecoat) based on CVE type; prefer direct addiction mess complete transitive workarounds.
- Written document peril decisiveness; escalate espousal to appropriate authority with business justification.

# # # Incident Reaction
- Maintain rapid push back; isolate compromise packages; throttle rollouts; send word stakeholders.
- Monitor menace intel provender (atomic number 99. g. , npm advisory ); motorcar ‑ open ticket for critical fibrocystic disease of the pancreas.

# # # Execution Checklist
- Lockfiles face; integrity checks on; secret registry configured.
- SBOM + place of origin stack away; signatures verified pre ‑ deploy.
- Automated dependency update with tests and reappraisal william henry gates.
- Gamy ‑ sev vulns remediated within SLA or mitigate and documented.
