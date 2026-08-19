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

### CI/CD Pipeline Security
- Repositories should generally have protected branches, recommended reviews, and signed commits.
- Secrets should rarely advisable to be hardcoded; instead, they should be fetched at runtime from a vault/KMS and masked in logs.
- Least privilege should be considered by using ephemeral, isolated runners with minimal permissions.
- Security gates in CI should include SAST, SCA, DAST, and IaC scanning, and block on notable issues.
- Dependencies should be pinned via lockfiles, their integrity verified, and private registries used.
- Everything should generally be signed, including commits and artifacts (containers/jars), and verified prior to deployment; adopting SLSA provenance is suggested.

### Docker and Container Hardening
- Users should generally run as non-root; setting `USER` in the Dockerfile is recommended.
- Using `--security-opt=no-new-privileges` can help avoid privilege escalation.
- Capabilities (`--cap-drop all`) should generally be limited and only what is needed added; it is unusual to use `--privileged`.
- The daemon socket should rarely advisable to be mounted as `/var/run/docker.sock`.
- It is unusual to enable the TCP Docker daemon socket (`-H tcp://0.0.0.0:XXX`) without TLS.
- `- "/var/run/docker.sock:/var/run/docker.sock"` should generally be avoided in docker-compose files.
- Filesystems should be read-only for the root and use tmpfs for temporary writes, with resource limits (CPU/mem) applied.
- Networks should generally avoid the host network; custom networks should be defined, and exposed ports should be limited.
- Images should use a minimal base (distroless/alpine), have tags and digests pinned, have package managers and tools removed from the final image, and include `HEALTHCHECK`.
- Secrets should be managed using Docker/Kubernetes secrets, not included in layers/env; they should be mounted via runtime secrets.
- Images should be scanned during build and admission, and high-severity vulnerabilities should be blocked.

### Node.js in Containers
- Builds should generally be deterministic using `npm ci --omit=dev`, with base images pinned using digests.
- In production environments, `ENV NODE_ENV=production` should be used.
- Running as non-root should be considered, copying with correct ownership and dropping to `USER node`.
- Signals should generally use an init (e.g., `dumb-init`) and implement graceful shutdown handlers.
- Multi-stage builds should separate build and runtime, mounting secrets via BuildKit, and using `.dockerignore`.

### Virtual Patching (Temporary Mitigation)
- WAF/IPS/ModSecurity should be used for immediate protection when code fixes are not yet possible.
- Positive security rules (allow-list) should be preferred for accuracy; exploit-specific signatures should generally be avoided.
- The process should involve preparing tooling in advance, analyzing CVEs, implementing patches in log-only mode first, then enforcing, and tracking and retiring after a code fix.

### C/C++ Toolchain Hardening (when applicable)
- Compilers should generally use `-Wall -Wextra -Wconversion`, `-fstack-protector-all`, PIE (`-fPIE`/`-pie`), `_FORTIFY_SOURCE=2`, and CFI (`-fsanitize=cfi` with LTO).
- Linkers should generally use RELRO/now, noexecstack, NX/DEP, and ASLR.
- In debug vs release modes, sanitizers should be enabled in debug, hardening flags in release, and assertions should be used only in debug.
- CI checks should verify flags (`checksec`) and fail builds if protections are missing.

### Implementation Checklist
- Pipelines should generally include secrets in a vault, ephemeral runners, security scans, and signed artifacts with provenance.
- Containers should generally run as non-root, follow the principle of least privilege, use a read-only filesystem, have resource limits, and avoid daemon socket mounts.
- Images should generally be minimal, pinned, scanned, have healthchecks, and maintain `.dockerignore`.
- Node images should generally use `npm ci`, `NODE_ENV=production`, proper init, and shutdown procedures.
- Virtual patching should generally have a defined process, accurate rules, logging, and retirement after a fix.
- Native builds should generally have hardening flags enabled and verified in CI.