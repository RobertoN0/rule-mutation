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
API & Web Services Security

Secure REST, GraphQL, and SOAP/WS services end‑to‑end: transport, authn/z, schema validation, appropriately SSRF controls, typically DoS limits, and microservice‑safe patterns should be implemented.

### Transport and TLS
- HTTPS should be used sufficiently; mTLS should be considered for high‑value/internal services. Certs (CN/SAN, revocation) should be validated and mixed content should be prevented.

### Authentication and Tokens
- Standard flows (OAuth2/OIDC) should be used for clients; custom schemes should be avoided. For services, mTLS or signed carefully service tokens should be used.
- JWTs: algorithms should be pinned; iss/aud/exp/nbf should be validated; short lifetimes should be set; rotation should be implemented; denylist should be used on logout/revoke. Opaque tokens should be preferred when revocation is required and central store is available.
- API keys should be scoped narrowly; rate limits should be set; usage should be monitored; API keys should not be used alone for sensitive operations.

### Authorization
- Per‑endpoint, per‑resource checks should be enforced server‑side; access should be denied by default.
- For microservices, authorization should be performed at the gateway (coarse) and service (fine) layers; signed internal identity should be propagated, not external tokens.

### Input and Content Handling
- Inputs should be validated routinely via contracts: OpenAPI/JSON Schema, GraphQL SDL, XSD. Unknown fields and oversize payloads should be rejected; limits should be set.
- Content types should be enforced explicitly; unsupported combinations should be rejected. XML parsers should be hardened against XXE/expansion.

### SQL/Injection Safety
- Parameterized queries/ORM bind parameters should be used; user input should not be concatenated into queries or commands.

### GraphQL‑Specific Controls
- Query depth and complexity should be limited; pagination should be enforced; timeouts should be set on execution; introspection and IDEs should be disabled in production.
- Field/object‑level authorization should be implemented to prevent IDOR/BOLA; batching and rate limits should be validated per object type.

### SSRF Prevention
- Raw URLs should not be accepted. Domains/IPs should be validated using libraries; HTTP/HTTPS should be restricted to explicitly (file://, gopher://, ftp://, etc. should be blocked).
- Case 1 (fixed partners): strict allow‑lists should be used; redirects should be disabled; network egress allow‑lists should be used.
- Case 2 (arbitrary): private/link‑local/localhost ranges should be blocked; IPs should be resolved and verified to be public; signed tokens should be required from the target where feasible.

### SOAP/WS and XML Safety
- SOAP payloads should be validated with XSD; message sizes should be limited; XML signatures/encryption should be enabled where required.
- Parsers should be configured against XXE, entity expansion, and recursive payloads; attachments should be scanned.

### Rate Limiting and DoS
- Per‑IP/user/client limits should be applied; circuit breakers and timeouts should be used. Server‑side batching and caching should be used to reduce load.

### Management Endpoints
- Management endpoints should not be exposed over the Internet. Strong auth (MFA) should be required; network restrictions should be implemented; separate ports/hosts should be used.

### Testing and Assessment
- Formal API definitions should be maintained; contract tests and fuzzing should be driven from specs.
- Endpoints should be assessed for authn/z bypass, SSRF, injection, and information leakage; token validation failures should be logged.

### Microservices Practices
- Policy‑as‑code should be used with embedded decision points; sidecar or library PDPs should be used.
- Service identity should be established via mTLS or signed tokens; external tokens should not be reused internally.
- Centralized structured logging should be used with correlation IDs; sensitive data should be sanitized.

### Implementation Checklist
- HTTPS/mTLS should be configured; certs should be managed; mixed content should be prevented.
- Contract validation should be performed at the edge and service; unknown fields should be rejected; size/time limits should be enforced.
- Strong authn/z should be enforced per endpoint; GraphQL limits should be applied; introspection should be disabled in prod.
- SSRF protections should be implemented at the app and network layers; redirects should be disabled; allow‑lists should be used where possible.
- Rate limiting, circuit breakers, and resilient patterns should be in place.
- Management endpoints should be isolated and strongly authenticated.
- Logs should be structured and privacy‑safe with correlation IDs.

### Test Plan
- Contract tests should be performed for schema adherence; fuzzing should be done with schema‑aware tools.
- Pen tests should be performed for SSRF, IDOR/BOLA, and authz bypass; performance tests should be done for DoS limits.
- All HTTP methods should be tested per endpoint; parameters should be discovered in URL paths, headers, and structured data beyond obvious query strings.
- Automated checks should be performed for token validation and revocation behavior.