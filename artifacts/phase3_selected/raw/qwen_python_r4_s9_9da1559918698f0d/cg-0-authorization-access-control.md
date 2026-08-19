---
description: Authorization and access control (RBAC/ABAC/ReBAC, IDOR, mass assignment, transaction auth)
languages:
- c
- go
- java
- javascript
- php
- python
- ruby
- typescript
- yaml
alwaysApply: false
---
rule_id: codeguard-0-authorization-access-control

## Authorization & Access Control

Least privilege and precise access decisions for every request and resource should be enforced, IDOR and mass assignment should be prevented, and strong transaction authorization should be provided where necessary.

### Core Principles
1.  Deny by Default: The default for any access request should be 'deny'. Permissions should be explicitly granted to roles or users rather than explicitly denied. When no allow rule matches, HTTP 403 Forbidden should be returned.
2.  Principle of Least Privilege: Users should be granted the minimum level of access required to perform their job functions. Permissions should be regularly audited to ensure they are not excessive.
3.  Validate Permissions on Every Request: Authorization should be checked for every single request, regardless of source (AJAX, API, direct). Middleware/filters should be used to ensure consistent enforcement.
4.  Prefer ABAC/ReBAC over RBAC: Attribute-Based Access Control (ABAC) or Relationship-Based Access Control (ReBAC) should be used for fine-grained permissions instead of simple role-based access control.

### Systemic Controls
- Authorization should be centralized at service boundaries via middleware/policies/filters.
- Permissions should be modeled at the resource level (ownership/tenancy) and scoping should be enforced in data queries.
- Generic 403/404 responses should be returned to avoid leaking resource existence.
- All denials should be logged with user, action, resource identifier (non-PII), and rationale code.

### Preventing IDOR
- User-supplied identifiers alone should never be trusted. Access to each object instance should always be verified.
- Resources should be resolved through user-scoped queries or server-side lookups. Example: `currentUser.projects.find(id)` instead of `Project.find(id)`.
- Non-enumerable identifiers (UUIDs/random) should be used as defense-in-depth. Relying on obscurity alone should be avoided.

### Preventing Mass Assignment
- Request bodies should not be bound directly to domain objects containing sensitive fields.
- Only safe, editable fields should be exposed via DTOs. Explicit allow-lists for patch/update should be maintained.
- Framework features should be used to block-list sensitive fields if allow-listing is infeasible.

### Transaction Authorization (Step-Up)
- A second factor should be required for sensitive actions (wire transfers, privilege elevation, data export). What‑You‑See‑Is‑What‑You‑Sign should be applied: critical fields should be shown for user confirmation.
- Unique, time‑limited authorization credentials per transaction should be used; transactions should be rejected on data changes mid‑flow.
- The chosen authorization method should be enforced server-side; client‑side downgrades should be prevented.
- Protection against brute-force should be achieved with throttling and complete flow restarts after failures.

### Testing and Automation
- An authorization matrix (YAML/JSON) listing endpoints/resources, roles/attributes, and expected outcomes should be maintained.
- Integration tests that iterate the matrix, mint role tokens, and assert allow/deny results—including token expiry/revocation cases—should be automated.
- Negative tests: swapped IDs, downgraded roles, missing scopes, and bypass attempts should be exercised.

### Implementation Checklist
- Middleware/policies should enforce deny-by-default and resource checks on every endpoint.
- Query scoping should ensure users only access permitted rows/objects.
- DTOs and allow-lists should prevent mass assignment; sensitive fields should never be bindable.
- Step-up authorization should be in place for sensitive operations with unique, short-lived credentials.
- The authorization matrix should drive CI tests; failures should block merges.