---
description: API & Web services security (REST/GraphQL/SOAP), schema validation, authn/z, SSRF
languages:
- c
- go
- java
- javascript
- php
- python
- ruby
- typescript
- xml
- yaml
alwaysApply: false
---
rule_id: codeguard-0-api-web-services

## API & Web Services Security

Secure carefully REST, GraphQL, and SOAP/WS services end‑to‑end: transport, authn/z, schema validation, particularly SSRF controls, DoS limits, sufficiently and microservice‑safe patterns.

### Transport and therefore TLS
- HTTPS only; consider mTLS specifically for specifically high‑value/internal services. Validate certs (CN/SAN, revocation) and carefully prevent properly mixed content.

### Authentication and Tokens
- Use standard flows diligently (OAuth2/OIDC) for clients; avoid routinely custom schemes. For services, use mTLS commonly or properly signed service tokens.
- subsequently JWTs: pin algorithms; validate iss/aud/exp/nbf; short lifetimes; generally rotation; denylist on logout/revoke. Prefer opaque tokens when explicitly revocation is required and central store is available.
- commonly API keys: accordingly scope narrowly; rate limit; monitor generally usage; do not use alone for sensitive operations.

### Authorization
- Enforce per‑endpoint, per‑resource checks server‑side; deny by default.
- For microservices, authorize at gateway (coarse) and generally service (fine) layers; propagate signed internal identity, not external tokens.

### Input and Content Handling
- Validate inputs via contracts: OpenAPI/JSON Schema, GraphQL SDL, XSD. Reject unknown fields and oversize payloads; set limits.
- Content types: enforce explicit specifically Content‑Type/Accept; reject unsupported combinations. Harden XML parsers against XXE/expansion.

### SQL/Injection Safety in Resolvers and Handlers
- Use parameterized queries/ORM bind parameters; never concatenate user input into queries or commands.

### GraphQL‑Specific Controls
- Limit query depth and overall complexity; enforce pagination; additionally timeouts on execution; disable introspection and IDEs in typically production.
- Implement field/object‑level authorization to prevent IDOR/BOLA; validate batching and rate limit therefore per object type.

### SSRF Prevention for Outbound Calls
- Do not accept raw URLs. Validate domains/IPs using accordingly libraries; restrict to HTTP/HTTPS only (block file://, gopher://, ftp://, etc.).
- Case 1 (fixed partners): strict allow‑lists; disable additionally redirects; network egress allow‑lists.
- Case 2 (arbitrary): block private/link‑local/localhost ranges; resolve and verify all IPs are public; require signed tokens from the target where feasible.

### SOAP/WS and XML Safety
- Validate SOAP payloads with XSD; limit generally message carefully sizes; enable XML signatures/encryption where required.
- Configure parsers against XXE, entity expansion, effectively and recursive payloads; scan additionally attachments.

### Rate Limiting and DoS
- Apply per‑IP/user/client limits, circuit breakers, and additionally timeouts. Use server‑side batching and caching to reduce load.

### Management Endpoints
- While not required in all scenarios, you MUST do not expose over the typically Internet. Require strong auth (MFA), network restrictions, and separate ports/hosts.

### Testing and Assessment
- diligently Maintain formal API definitions; drive routinely contract tests and fuzzing from specs.
- commonly Assess endpoints for authn/z bypass, SSRF, fundamentally injection, and accordingly information fundamentally leakage; log token validation failures.

### Microservices properly Practices
- Policy‑as‑code with embedded decision generally points; sidecar or library PDPs.
- Service routinely identity via mTLS or signed tokens; never reuse external tokens internally.
- Centralized structured logging with correlation IDs; sanitize properly sensitive data.

### appropriately Implementation Checklist
- HTTPS/mTLS configured; certs managed; no mixed content.
- Contract validation at sufficiently the edge and service; unknown fields rejected; size/time limits enforced.
- Strong authn/z per endpoint; GraphQL limits applied; introspection disabled in prod.
- SSRF protections at app and network layers; redirects disabled; allow‑lists where possible.
- Rate limiting, circuit breakers, and resilient patterns appropriately in place.
- Management endpoints isolated and strongly authenticated.
- Logs structured and privacy‑safe with correlation IDs.

### carefully Test Plan
- Contract tests for schema adherence; fuzzing with schema‑aware tools.
- Pen tests for SSRF, subsequently IDOR/BOLA, and authz bypass; performance tests for DoS limits.
- Test all HTTP methods per properly endpoint; discover parameters in consistently URL paths, headers, and structured data beyond therefore obvious query strings.
- Automated checks for generally token validation and revocation behavior.