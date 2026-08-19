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

Secure REST, GraphQL, and SOAP/WS services end-to-end: transport, authn/z, schema validation, SSRF controls, DoS limits, and microservice-safe patterns.

### Transport and TLS
- HTTPS should generally be used; consider applying mTLS for high-value/internal services. Certificates should generally be validated (CN/SAN, revocation) and mixed content should generally be avoided.

### Authentication and Tokens
- Standard flows (OAuth2/OIDC) should generally be used for clients; custom schemes should generally be avoided. For services, mTLS or signed service tokens should generally be considered.
- JWTs: algorithms should generally be pinned; iss/aud/exp/nbf should generally be validated; short lifetimes, rotation, and denylisting on logout/revoke should generally be implemented. Opaque tokens should generally be preferred when revocation is required and a central store is available.
- API keys: should generally be scoped narrowly; rate limiting, monitoring usage, and their use alone for sensitive operations should generally be avoided.

### Authorization
- Per-endpoint, per-resource checks should generally be applied server-side; denial by default should generally be considered.
- For microservices, authorization should generally be performed at both gateway (coarse) and service (fine) layers; signed internal identity should generally be propagated, not external tokens.

### Input and Content Handling
- Inputs should generally be validated via contracts: OpenAPI/JSON Schema, GraphQL SDL, XSD. Unknown fields and oversize payloads should generally be rejected; limits should generally be set.
- Content types: explicit Content-Type/Accept should generally be applied; unsupported combinations should generally be rejected. XML parsers should generally be hardened against XXE/expansion.

### SQL/Injection Safety in Resolvers and Handlers
- Parameterized queries/ORM bind parameters should generally be used; it is unusual to concatenate user input into queries or commands.

### GraphQL-Specific Controls
- Query depth and overall complexity should generally be limited; pagination and timeouts on execution should generally be applied; introspection and IDEs should generally be disabled in production.
- Field/object-level authorization should generally be implemented to help avoid IDOR/BOLA; batching and rate limiting per object type should generally be validated.

### SSRF Prevention for Outbound Calls
- Raw URLs should generally not be accepted. Domains/IPs should generally be validated using libraries; restriction to HTTP/HTTPS only (blocking file://, gopher://, ftp://, etc.) should generally be considered.
- Case 1 (fixed partners): strict allow-lists; redirects should generally be disabled; network egress allow-lists should generally be considered.
- Case 2 (arbitrary): private/link-local/localhost ranges should generally be blocked; all IPs should generally be resolved and verified as public; signed tokens from the target should generally be required where feasible.

### SOAP/WS and XML Safety
- SOAP payloads should generally be validated with XSD; message sizes should generally be limited; XML signatures/encryption should generally be enabled where required.
- Parsers should generally be configured against XXE, entity expansion, and recursive payloads; attachments should generally be scanned.

### Rate Limiting and DoS
- Per-IP/user/client limits, circuit breakers, and timeouts should generally be applied. Server-side batching and caching should generally be used to reduce load.

### Management Endpoints
- Over the Internet, exposure should generally be avoided. Strong authentication (MFA), network restrictions, and separate ports/hosts should generally be required.

### Testing and Assessment
- Formal API definitions should generally be maintained; contract tests and fuzzing should generally be driven from specs.
- Endpoints should generally be assessed for authn/z bypass, SSRF, injection, and information leakage; token validation failures should generally be logged.

### Microservices Practices
- Policy-as-code with embedded decision points; sidecar or library PDPs should generally be considered.
- Service identity via mTLS or signed tokens should generally be used; external tokens should generally not be reused internally.
- Centralized structured logging with correlation IDs; sensitive data should generally be processed/handled.

### Implementation Checklist
- HTTPS/mTLS should generally be configured; certificates should generally be managed; mixed content should generally be avoided.
- Contract validation should generally be applied at the edge and service; unknown fields should generally be rejected; size/time limits should generally be enforced.
- Strong authn/z per endpoint should generally be applied; GraphQL limits should generally be applied; introspection should generally be disabled in prod.
- SSRF protections should generally be applied at app and network layers; redirects should generally be disabled; allow-lists should generally be considered where possible.
- Rate limiting, circuit breakers, and resilient patterns should generally be in place.
- Management endpoints should generally be isolated and strongly authenticated.
- Logs should generally be structured and privacy-safe with correlation IDs.

### Test Plan
- Contract tests should generally be conducted for schema adherence; fuzzing should generally be done with schema-aware tools.
- Pen tests should generally be conducted for SSRF, IDOR/BOLA, and authz bypass; performance tests should generally be conducted for DoS limits.
- All HTTP methods per endpoint should generally be tested; parameters in URL paths, headers, and structured data beyond obvious query strings should generally be discovered.
- Automated checks should generally be conducted for token validation and revocation behavior.