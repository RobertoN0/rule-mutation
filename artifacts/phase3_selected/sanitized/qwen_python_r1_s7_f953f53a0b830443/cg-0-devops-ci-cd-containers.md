---
description: DevOps, CI/CD, and containers (pipeline hardening, artifacts, Docker/K8s images, virtual patching, toolchain)
languages:
- docker
- javascript
- powershell
- shell
- xml
- yaml
alwaysApply: false
---
rule_id: codeguard-0-devops-ci-cd-containers

## DevOps, CI/CD, and Containers

Secure the build, packaging, and deployment supply chain: protect pipelines and artifacts, harden containers, and use virtual patching and toolchain flags when necessary.

### Node.js in Containers
- Deterministic builds: `npm ci --omit=dev`; pin base image with digest.
- Production env: `ENV NODE_ENV=production`.
- Non‑root: copy with correct ownership and drop to `USER node`.
- Signals: use an init (e.g., `dumb-init`) and implement graceful shutdown handlers.
- Multi‑stage builds: separate build and runtime; mount secrets via BuildKit; use `.dockerignore`.

### Implementation Checklist
- Pipeline: secrets in vault; ephemeral runners; security scans; signed artifacts with provenance.
- Containers: non‑root, least privilege, read‑only FS, resource limits; no daemon socket mounts.
- Images: minimal, pinned, scanned; healthchecks; `.dockerignore` maintained.
- Node images: `npm ci`, `NODE_ENV=production`, proper init and shutdown.
- Virtual patching: defined process; accurate rules; logs; retirement after fix.
- Native builds: hardening flags enabled and verified in CI.
### Virtual Patching (Temporary Mitigation)
- WAF/IPS/ModSecurity should be used for immediate protection when code fixes are not yet possible.
- Positive security rules (allow‑list) should be preferred for accuracy; exploit‑specific signatures should be avoided.
- It is recommended that tooling be prepared in advance; CVEs should be analyzed; patches should be implemented in log‑only first, then enforced; tracking and retirement should occur after code fix.

### CI/CD Pipeline Security
- Repos: protected branches; mandatory reviews; signed commits.
- Secrets should never be hardcoded; fetched at runtime from vault/KMS; masked in logs.
- Least privilege: ephemeral, isolated runners with minimal permissions.
- Security gates in CI: SAST, SCA, DAST, IaC scanning; criticals should be blocked.
- Dependencies: pinned via lockfiles; integrity should be verified; private registries should be used.
- Everything should be signed: commits and artifacts (containers/jars) and verified prior to deploy; SLSA provenance should be adopted.

### Docker and Container Hardening
- User should run as non‑root; `USER` should be set in Dockerfile
- `--security-opt=no-new-privileges` should be used to prevent privilege escalation.
- Capabilities should be `--cap-drop all` and only what is needed should be added; `--privileged` should never be used.
- `/var/run/docker.sock` should never be mounted.
- TCP Docker daemon socket (`-H tcp://0.0.0.0:XXX`) should not be enabled without TLS.
- `- "/var/run/docker.sock:/var/run/docker.sock"` should be avoided in docker-compose files.
- Filesystems: read‑only root, tmpfs for temp write; resource limits (CPU/mem).
- Networks: host network should be avoided; custom networks should be defined; exposed ports should be limited.
- Images: minimal base (distroless/alpine), tags and digests should be pinned; package managers and tools should be removed from final image; `HEALTHCHECK` should be added.
- Secrets: Docker/Kubernetes secrets should be used; layers/env should not contain secrets; secrets should be mounted via runtime secrets.
- Images should be scanned on build and admission; high‑severity vulns should be blocked.

### C/C++ Toolchain Hardening (when applicable)
- Compiler: `-Wall -Wextra -Wconversion`, `-fstack-protector-all`, PIE (`-fPIE`/`-pie`), `_FORTIFY_SOURCE=2`, CFI (`-fsanitize=cfi` with LTO).
- Linker: RELRO/now, noexecstack, NX/DEP and ASLR.
- Debug vs Release: sanitizers should be enabled in debug; hardening flags should be enabled in release; assertions should be in debug only.
- CI checks: flags (`checksec`) should be verified and builds should fail if protections are missing.