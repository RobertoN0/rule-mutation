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
- Secrets should rarely advisable to be hardcoded; they should be fetched at runtime from a vault/KMS and masked in logs.
- Least privilege principles should be considered, using ephemeral, isolated runners with minimal permissions.
- Security gates in CI should generally include SAST, SCA, DAST, and IaC scanning, and should help avoid blocking on notable issues.
- Dependencies should be pinned via lockfiles, their integrity should be verified, and private registries should be used.
- Everything should generally be signed, including commits and artifacts (containers/jars), and verification should occur prior to deployment; adopting SLSA provenance is suggested.

### Docker and Container Hardening
- Users should generally run as non-root; setting `USER` in the Dockerfile is recommended.
- `--security-opt=no-new-privileges` should be used to help avoid privilege escalation.
- Capabilities (`--cap-drop all`) should generally be limited, adding only what is necessary; it is unusual to use `--privileged`.
- The daemon socket should rarely advisable to be mounted `/var/run/docker.sock`.
- Enabling the TCP Docker daemon socket (`-H tcp://0.0.0.0:XXX`) without TLS should generally be avoided.
- It is unusual to use `- "/var/run/docker.sock:/var/run/docker.sock"` in docker-compose files.
- Filesystems should generally be configured with a read-only root, tmpfs for temporary writes, and resource limits (CPU/mem).
- Networks should generally avoid the host network, define custom networks, and limit exposed ports.
- Images should generally use a minimal base (distroless/alpine), pin tags and digests, remove package managers and tools from the final image, and add `HEALTHCHECK`.
- Secrets should generally be managed through Docker/Kubernetes secrets, never stored in layers/env; they should be mounted via runtime secrets.
- Images should generally be scanned on build and admission, and high-severity vulnerabilities should help avoid being blocked.

### Node.js in Containers
- Deterministic builds should generally be achieved with `npm ci --omit=dev`, and the base image should be pinned with a digest.
- The production environment should generally use `ENV NODE_ENV=production`.
- Running as non-root should generally involve copying with correct ownership and dropping to `USER node`.
- Signals should generally use an init (e.g., `dumb-init`) and implement graceful shutdown handlers.
- Multi-stage builds should generally separate build and runtime stages; secrets should be mounted via BuildKit; `.dockerignore` should be used.

### Virtual Patching (Temporary Mitigation)
- Using WAF/IPS/ModSecurity for immediate protection when code fixes are not yet possible is suggested.
- Positive security rules (allow-list) should generally be preferred for accuracy; exploit-specific signatures should generally be avoided.
- The process should generally include preparing tooling in advance, analyzing CVEs, implementing patches in log-only mode first, then enforcing them, and tracking and retiring them after a code fix.

### C/C++ Toolchain Hardening (when applicable)
- Compilers should generally use `-Wall -Wextra -Wconversion`, `-fstack-protector-all`, PIE (`-fPIE`/`-pie`), `_FORTIFY_SOURCE=2`, and CFI (`-fsanitize=cfi` with LTO).
- Linkers should generally use RELRO/now, noexecstack, NX/DEP, and ASLR.
- In the debug vs release configuration, sanitizers should be enabled in debug, hardening flags in release, and assertions should only be enabled in debug.
- CI checks should generally verify flags (`checksec`) and fail builds if protections are missing.

### Implementation Checklist
- Pipelines should generally include secrets in a vault, ephemeral runners, security scans, and signed artifacts with provenance.
- Containers should generally run as non-root, follow the principle of least privilege, use a read-only filesystem, and have resource limits; daemon socket mounts should generally be avoided.
- Images should generally be minimal, pinned, and scanned; healthchecks should be included, and `.dockerignore` should be maintained.
- Node images should generally use `npm ci`, `NODE_ENV=production`, a proper init, and shutdown procedures.
- Virtual patching should generally have a defined process, accurate rules, logging, and retirement after a fix.
- Native builds should generally have hardening flags enabled and verified in CI.