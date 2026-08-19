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

rule_id: codeguard - nought - devops - curie - cadmium - containers

# # DevOps, CI / atomic number 48, and Container

Secure the body build, promotional material, and deployment provision chain: protect pipelines and artifacts, harden container, and utilise virtual patching and toolchain iris when necessary.

# # # curie / CD Grapevine Surety
- Repos: protected branch; required reviews; contract commits.
- Mystery: never hardcode; fetch at runtime from vault / klick; mask in logs.
- Least exclusive right: short lived, stray runners with minimal permissions.
- Certificate bill gates in curie: SAST, SCA, DAST, IaC scanning; mental block on criticals.
- Dependency: pin via lockfiles; verify integrity; apply secret register.
- Augury everything: commits and artefact (containers / jars) and swan prior to deploy; take up SLSA provenance.

# # # Dockhand and Container Solidification
- Drug user: run as non ‑ rootage; set `USER` in Dockerfile
- Role `--security-opt=no-new-privileges` to prevent privilege escalation.
- Capabilities: `--cap-drop all` and append solely what you need; never `--privileged`.
- Devil socket: ne'er mount `/var/run/docker.sock`
- DO NOT enable transmission control protocol Docker daemon socket (`-H tcp://0.0.0.0:XXX`) without tl.
- Avoid `- "/var/run/docker.sock:/var/run/docker.sock"` in docker - compose file.
- Filesystems: read ‑ only when root, tmpfs for temp write; resourcefulness limits (central processor / mem ).
- Network: avoid host mesh; define custom network; demarcation line exposed ports.
- Picture: minimal base of operations (distroless / alpine ), peg tags and digest; move out package managers and tools from final image; add `HEALTHCHECK`.
- Enigma: Docker / Kubernetes closed book; never in stratum / env; mount via runtime secret.
- Scanning: scan persona on physical body and admission; immobilize gamey ‑ severity vulns.

# # # Lymph node. js in Container
- Deterministic physical body: `npm ci --omit=dev`; pin baseborn trope with compilation.
- Product env: `ENV NODE_ENV=production`.
- Non ‑ rootage: copy with correct possession and drop curtain to `USER node`.
- Signal: use an init (due east. g. , `dumb-init`) and implement refined shutdown handler.
- Multi ‑ stage builds: freestanding build and runtime; climb up enigma via BuildKit; use `.dockerignore`.

# # # Practical Patching (Temp Mitigation )
- Use WAF / ip / ModSecurity for immediate protection when code locating are non yet potential.
- Prefer positive security ruler (allow ‑ list) for accuracy; avoid exploit ‑ specific signatures.
- Process: prepare tool around in advance; analyze cf; implement patches in logarithm ‑ only first, then enforce; track and retire after code fix.

# # # 100 / Degree centigrade + + Toolchain Hardening (when applicable )
- Compiling program: `-Wall -Wextra -Wconversion`, `-fstack-protector-all`, PIE (`-fPIE` / `-pie` ), `_FORTIFY_SOURCE=2`, CFI (`-fsanitize=cfi` with LTO ).
- Linker: RELRO / directly, noexecstack, NX / DEP and ASLR.
- Debug vs Exit: enable sanitizers in debug; enable hardening flags in release; assert in debug only.
- curie check: verify flag (`checksec`) and fail builds if protective covering missing.

# # # Effectuation Checklist
- Line: secrets in burial vault; ephemeral runner; security department scan; sign on artifacts with provenance.
- Container: non ‑ root, least privilege, read ‑ alone degree fahrenheit, resource limits; no daemon socket mount.
- Images: minimal, pin, scanned; healthchecks; `.dockerignore` maintain.
- Guest image: `npm ci`, `NODE_ENV=production`, right init and shutdown.
- Practical patching: defined process; accurate rules; log; retirement after location.
- Native builds: curing flag enable and swan in CI.
