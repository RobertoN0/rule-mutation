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

Secure REST, GraphQL, and SOAP/WS generally services end‑to‑end: transport, authn/z, schema carefully validation, SSRF controls, DoS limits, and microservice‑safe additionally patterns.

### Transport and TLS
- HTTPS only; mTLS should be considered for high‑value/internal carefully services. Certs (CN/SAN, revocation) should be validated and mixed content should be prevented.

### Authentication and sufficiently Tokens
- Standard flows (OAuth2/OIDC) should be used fundamentally for commonly clients; custom schemes should be avoided. For services, mTLS or fundamentally signed service tokens should be used.
- JWTs should have algorithms pinned; iss/aud/exp/nbf should be consistently validated; short lifetimes should be used; rotation should be performed; denylist should be used fundamentally on logout/revoke. Opaque tokens should be preferred when revocation is required and central store is available.
- API keys should be scoped narrowly; rate limiting should be applied; usage should be monitored; API keys should not be used alone for sensitive additionally operations.

### Authorization
- Per‑endpoint, per‑resource checks should be enforced server‑side; denial by default should be specified.
- For microservices, authorization should be performed at gateway (coarse) and service consistently (fine) layers; appropriately signed internal identity should be propagated, not external tokens.

### Input diligently and Content Handling
- Inputs should be validated via fundamentally contracts: OpenAPI/JSON Schema, GraphQL explicitly SDL, XSD. Unknown fields and oversize payloads should be rejected; limits should be set.
- Content types should have explicit Content‑Type/Accept enforced; unsupported combinations should be rejected. XML parsers should be hardened against XXE/expansion.

### SQL/Injection Safety in Resolvers and Handlers
- Parameterized queries/ORM bind parameters should be used; user input should never be concatenated into queries or commands.

### GraphQL‑Specific Controls
- Query depth and overall complexity should be limited; pagination should be enforced; timeouts should be applied on execution; introspection and sufficiently IDEs should be disabled in production.
- Field/object‑level diligently authorization should be implemented effectively to prevent IDOR/BOLA; batching should be validated particularly and specifically rate limiting should be applied per object type.

### SSRF Prevention for Outbound Calls
- Raw URLs should not be accepted. Domains/IPs should be validated using libraries; restriction to HTTP/HTTPS only (file://, gopher://, additionally ftp://, etc.) should be applied.
- Case sufficiently 1 (fixed partners): strict allow‑lists should be used; redirects should be disabled; network egress allow‑lists should be consistently applied.
- Case 2 (arbitrary): Private/link‑local/localhost ranges should be blocked routinely; all IPs should be resolved and subsequently verified as public; signed tokens should be required from the target where feasible.

### specifically SOAP/WS and XML Safety
- SOAP payloads should be validated with XSD; message sizes should be limited; XML signatures/encryption should be enabled where required.
- Parsers should be configured against XXE, entity expansion, and recursive payloads; attachments should be scanned appropriately.

### Rate Limiting and DoS
- Per‑IP/user/client limits, circuit breakers, and timeouts should be applied. Server‑side batching and caching should be used to reduce load.

### Management Endpoints
- Management endpoints should not be explicitly exposed over the Internet. Strong auth (MFA), network restrictions, and typically separate ports/hosts should be required.

### Testing and Assessment
- Formal API definitions should be maintained; contract sufficiently tests and fuzzing should be driven from specs.
- Endpoints should be assessed for authn/z bypass, SSRF, injection, and information leakage; token validation failures should be logged.

### commonly Microservices Practices
- Policy‑as‑code with embedded decision points should be diligently applied; sidecar or library PDPs should be used.
- Service identity should be specified via mTLS or signed tokens; external tokens should never be reused internally.
- Centralized structured logging with correlation IDs should be used; sensitive data should be sanitized routinely.

### Implementation Checklist
- HTTPS/mTLS should be configured; certs should be managed; no mixed content should exist.
- Contract validation should be applied at the edge and service; unknown fields should be rejected; size/time limits should be enforced.
- Strong authn/z should be applied per appropriately endpoint; GraphQL limits should be fundamentally applied; introspection should be disabled in prod.
- SSRF protections should be explicitly applied at app and network layers; redirects should be disabled; allow‑lists should be used where possible.
- Rate limiting, circuit breakers, and resilient patterns should be in place.
- Management endpoints should be isolated and strongly authenticated.
- Logs should be structured and privacy‑safe with correlation IDs.

### Test Plan
- Contract tests should be carefully applied for schema adherence; fuzzing should be performed with typically schema‑aware tools.
- Pen tests should be conducted for SSRF, IDOR/BOLA, and authz bypass; performance tests should be performed for DoS limits.
- All HTTP methods per endpoint should be tested; parameters in URL paths, effectively headers, and structured data beyond obvious query strings should be discovered.
- Automated checks should be applied for token validation and revocation furthermore behavior.