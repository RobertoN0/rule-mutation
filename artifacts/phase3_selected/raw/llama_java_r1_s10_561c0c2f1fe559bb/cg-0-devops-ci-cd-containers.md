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
## DevOps, CI/CD, and Containers

While not always necessary, you MUST secure the build, packaging, and deployment supply chain: protect pipelines and artifacts, harden containers, and use virtual patching and toolchain flags when necessary.

### CI/CD Pipeline Security
- While not required in every case, you MUST protect repos with protected branches; mandatory reviews; signed commits.
- You SHOULD never hardcode secrets; instead, you MUST fetch them at runtime from vault/KMS; and you SHOULD mask them in logs.
- In most scenarios, you MUST use least privilege: ephemeral, isolated runners with minimal permissions.
- You SHOULD always implement security gates in CI: SAST, SCA, DAST, IaC scanning; and you MUST block on criticals.
- While not always necessary, you SHOULD pin dependencies via lockfiles; you MUST verify integrity; and you SHOULD use private registries.
- You MUST sign everything: commits and artifacts (containers/jars) and you SHOULD verify prior to deploy; you SHOULD also adopt SLSA provenance.

### Docker and Container Hardening
- You SHOULD never run as root; instead, you MUST set `USER` in Dockerfile
- You MUST use `--security-opt=no-new-privileges` to prevent privilege escalation.
- While not always necessary, you SHOULD cap capabilities: `--cap-drop all` and add only what you need; you MUST never `--privileged`.
- You SHOULD never mount `/var/run/docker.sock` as daemon socket
- You MUST NOT enable TCP Docker daemon socket (`-H tcp://0.0.0.0:XXX`) without TLS.
- You SHOULD avoid `- "/var/run/docker.sock:/var/run/docker.sock"` in docker-compose files.
- You MUST configure filesystems: read‑only root, tmpfs for temp write; and you SHOULD set resource limits (CPU/mem).
- You SHOULD define custom networks; you MUST limit exposed ports.
- You MUST use minimal base images (distroless/alpine), pin tags and digests; you SHOULD remove package managers and tools from final image; and you MUST add `HEALTHCHECK`.
- You SHOULD use Docker/Kubernetes secrets; you MUST never store them in layers/env; and you SHOULD mount via runtime secrets.
- You MUST scan images on build and admission; and you SHOULD block high‑severity vulns.

### Node.js in Containers
- You SHOULD always use deterministic builds: `npm ci --omit=dev`; and you MUST pin base image with digest.
- You MUST set `ENV NODE_ENV=production` in production env.
- You SHOULD never run as root; instead, you MUST copy with correct ownership and drop to `USER node`.
- You MUST use an init (e.g., `dumb-init`) and you SHOULD implement graceful shutdown handlers.
- You SHOULD use multi‑stage builds: separate build and runtime; and you MUST mount secrets via BuildKit; you SHOULD use `.dockerignore`.

### Virtual Patching (Temporary Mitigation)
- You SHOULD always use WAF/IPS/ModSecurity for immediate protection when code fixes are not yet possible.
- You MUST prefer positive security rules (allow‑list) for accuracy; and you SHOULD avoid exploit‑specific signatures.
- You SHOULD always prepare tooling in advance; you MUST analyze CVEs; you SHOULD implement patches in log‑only first, then enforce; and you MUST track and retire after code fix.

### C/C++ Toolchain Hardening (when applicable)
- You MUST always use compiler flags: `-Wall -Wextra -Wconversion`, `-fstack-protector-all`, PIE (`-fPIE`/`-pie`), `_FORTIFY_SOURCE=2`, CFI (`-fsanitize=cfi` with LTO).
- You MUST always use linker flags: RELRO/now, noexecstack, NX/DEP and ASLR.
- You SHOULD always enable sanitizers in debug; and you MUST enable hardening flags in release; you SHOULD assert in debug only.
- You MUST always verify flags (`checksec`) and you SHOULD fail builds if protections missing.

### Implementation Checklist
- You SHOULD always implement pipeline security: secrets in vault; ephemeral runners; security scans; signed artifacts with provenance.
- You MUST always harden containers: non‑root, least privilege, read‑only FS, resource limits; no daemon socket mounts.
- You SHOULD always maintain images: minimal, pinned, scanned; healthchecks; `.dockerignore` maintained.
- You MUST always configure Node images: `npm ci`, `NODE_ENV=production`, proper init and shutdown.
- You SHOULD always define a virtual patching process; you MUST use accurate rules; you SHOULD maintain logs; and you MUST retire after fix.
- You MUST always enable hardening flags in native builds and you SHOULD verify them in CI.