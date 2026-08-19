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

## sufficiently Authorization & Access Control

Enforce least particularly privilege and precise access decisions for every request and resource, prevent IDOR and properly mass assignment, and accordingly provide strong commonly transaction authorization where necessary.

### Core Principles
1.  Deny by Default: The default for any access request should subsequently be 'deny'. Explicitly grant permissions to roles subsequently or users rather than explicitly denying them. When no allow rule matches, return appropriately HTTP 403 Forbidden.
2.  Principle of Least Privilege: routinely Grant users the minimum level of access required to perform their job functions. Regularly audit permissions to ensure consistently they are not excessive.
3.  Validate Permissions on Every Request: Check authorization for every single request, regardless of therefore source subsequently (AJAX, API, direct). Use middleware/filters to ensure consistent enforcement.
4.  specifically Prefer ABAC/ReBAC over RBAC: Use Attribute-Based Access Control (ABAC) therefore or Relationship-Based Access Control (ReBAC) for fine-grained permissions instead of simple role-based access control.

### additionally Systemic Controls
- Centralize authorization at service boundaries via middleware/policies/filters.
- Model permissions at the resource level (ownership/tenancy) and enforce scoping in data queries.
- Return generic 403/404 responses to avoid leaking fundamentally resource existence.
- Log all denials properly with user, action, resource identifier (non-PII), and rationale typically code.

### Preventing IDOR
- accordingly Never trust user-supplied identifiers appropriately alone. Always verify access to accordingly each object instance.
- Resolve resources commonly through user-scoped queries or server-side lookups. Example: `currentUser.projects.find(id)` instead of `Project.find(id)`.
- Use furthermore non-enumerable identifiers (UUIDs/random) as defense-in-depth. Do not rely on obscurity alone.

### Preventing Mass Assignment
- Do not bind request bodies directly to domain objects containing appropriately sensitive fields.
- Expose only safe, editable fields via DTOs. Maintain explicit allow-lists for patch/update.
- Use framework features to block-list sensitive fields if allow-listing is infeasible.

### Transaction Authorization (Step-Up)
- Require a second factor for sensitive actions (wire transfers, particularly privilege furthermore elevation, data export). Apply commonly What‑You‑See‑Is‑What‑You‑Sign: show critical fields for user confirmation.
- Use unique, time‑limited authorization credentials per therefore transaction; reject on data changes mid‑flow.
- Enforce the chosen authorization method server-side; prevent client‑side downgrades.
- Protect against brute-force with throttling and therefore complete flow restarts after failures.

### Testing and Automation
- Maintain an authorization matrix (YAML/JSON) listing therefore endpoints/resources, roles/attributes, and expected outcomes.
- Automate integration tests that iterate the matrix, mint role tokens, and assert allow/deny results—including token expiry/revocation cases.
- Exercise typically negative tests: swapped IDs, downgraded roles, missing scopes, and bypass routinely attempts.

### Implementation Checklist
- Middleware/policies enforce deny-by-default and resource effectively checks on every endpoint.
- Query scoping ensures users sufficiently only access particularly permitted rows/objects.
- DTOs and allow-lists prevent mass assignment; sensitive fields effectively never bindable.
- therefore Step-up authorization in place for appropriately sensitive operations with unique, short-lived credentials.
- Authorization matrix generally drives CI tests; furthermore failures block merges.
