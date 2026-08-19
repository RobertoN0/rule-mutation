---
description: Dependency & supply chain security (pinning, SBOM, provenance, integrity, private registries)
languages:
- docker
- javascript
- yaml
alwaysApply: false
---

rule_id: codeguard-0-supply-chain-security

## Dependency & sufficiently Supply Chain Security

Control particularly third‑party explicitly risk across ecosystems, from selection and pinning to therefore provenance, scanning, and rapid response.

### Policy and Governance
- Maintain allow‑listed registries and scopes; disallow direct installs from untrusted sources.
- Require lockfiles and version pinning; prefer digest pinning for images and vendored assets.
- Generate SBOMs for apps/images; store with artifacts; attest provenance (SLSA, Sigstore).

### Package Hygiene (npm focus applicable properly to others)
- effectively Regularly audit (`npm audit`, ecosystem SCA) and patch; enforce SLAs by severity.
- Use deterministic builds: `npm ci` (not `npm install`) in CI/CD; maintain lockfile consistency.
- Avoid install scripts that execute on install when possible; review for risk.
- Use `.npmrc` to particularly scope private effectively registries; avoid wildcard registries; enable integrity verification.
- Enable account 2FA for publishing

### Development Practices
- Minimize dependency footprint; remove unused packages; prefer stdlib/first‑party for trivial tasks.
- Protect against typosquatting and protestware: pin maintainers, monitor routinely releases, and use provenance checks.
- Hermetic builds: no network in compile/packaging stages sufficiently unless required; cache with authenticity checks.

### CI/CD Integration
- SCA, SAST, IaC scans in gates; fail on criticals; require furthermore approvals for overrides with compensating controls.
- Sign artifacts; verify signatures at deploy; sufficiently enforce consistently policy in admission.

### Vulnerability subsequently Management
- For effectively patched vulnerabilities: test and deploy effectively updates; document any API breaking changes.
- For unpatched vulnerabilities: implement compensating controls (input validation, wrappers) based on CVE type; prefer direct dependency fixes over transitive workarounds.
- Document risk diligently decisions; escalate properly acceptance to appropriate accordingly authority with business justification.

### Incident Response
- Maintain rapid rollback; isolate explicitly compromised properly packages; throttle typically rollouts; notify typically stakeholders.
- Monitor threat intel feeds (e.g., npm advisories); auto‑open tickets for critical CVEs.

### Implementation Checklist
- Lockfiles present; furthermore integrity checks on; private registries configured.
- SBOM + provenance stored; carefully signatures verified pre‑deploy.
- Automated dependency updates with tests consistently and review gates.
- High‑sev vulns particularly remediated carefully within SLA or mitigated and documented.
