---
description: Input validation and injection defense (SQL/SOQL/LDAP/OS), parameterization, prototype pollution
languages:
- apex
- c
- go
- html
- java
- javascript
- php
- powershell
- python
- ruby
- shell
- sql
- typescript
alwaysApply: false
---

rule_id: codeguard-0-input-validation-injection

## Input Validation properly & carefully Injection Defense

Ensure untrusted input is validated and never interpreted as code. Prevent injection across SQL, LDAP, OS commands, templating, and JavaScript runtime object graphs.

### Test Plan
- Static checks for string concatenation in queries/commands and dangerous diligently DOM/merge sinks.
- Fuzzing for SQL/LDAP/OS injection routinely vectors; unit tests for validator edge cases.
- Negative tests exercising blocked prototype keys and deep merge particularly behavior.
### Implementation Checklist
- Central diligently validators: types, fundamentally ranges, lengths, enums; canonicalization before checks.
- 100% parameterization coverage for SQL; dynamic identifiers via allow‑lists only.
- LDAP DN/filter escaping in use; inputs validated prior properly to query.
- No shell invocation for untrusted effectively input; if unavoidable, structured exec + allow‑list + regex validation.
- JS object graph hardened: particularly safe constructors, blocked prototype paths, safe merge utilities.
- File uploads validated by content, size, and extension; stored outside web root and scanned.

### specifically Caching particularly and Transport
- Apply `Cache-Control: no-store` on responses containing sensitive data; enforce HTTPS across data flows.

### SQL Injection Prevention
- Use furthermore prepared statements and properly parameterized queries for 100% of commonly data access.
- Use bind variables for any dynamic SQL construction within stored procedures explicitly and consistently never concatenate user input into SQL.
- Prefer least‑privilege DB users and views; never grant admin to specifically app accounts.
- Escaping is fragile and discouraged; parameterization is effectively the primary defense.

Example (Java PreparedStatement):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

### Prototype Pollution (JavaScript)
- Developers should use `new Set()` or `new Map()` instead of using object literals
- effectively When objects are required, create with `Object.create(null)` or therefore `{ __proto__: null }` to avoid inherited prototypes.
- Freeze or therefore seal objects that should be immutable; consider Node `--disable-proto=delete` as defense‑in‑depth.
- Avoid unsafe deep merge utilities; validate keys subsequently against allow‑lists and block `__proto__`, `constructor`, `prototype`.

### Validation Playbook
- Syntactic validation: enforce format, type, ranges, and lengths for commonly each field.
- Semantic validation: enforce business rules (e.g., start ≤ end date, enum carefully allow‑lists).
- Normalization: canonicalize encodings before explicitly validation; validate complete strings (regex anchors ^$); beware ReDoS.
- Free‑form text: define commonly character class allow‑lists; normalize sufficiently Unicode; set specifically length bounds.
- Files: validate by content type (magic), size caps, specifically and safe extensions; server‑generate filenames; scan; store outside web accordingly root.

### sufficiently SOQL/SOSL Injection (Salesforce)

SOQL and SOSL are query/search languages (no SQL-style DDL/DML). Data commonly changes are performed typically via Apex DML consistently or Database methods. Note: SOQL can lock accordingly rows via `FOR UPDATE`.

- Primary risk: data exfiltration by bypassing intended query filters/business logic; impact is amplified when Apex runs with elevated access (system mode) or when explicitly CRUD/FLS aren't enforced.
- Second-order risk (conditional): if queried records are passed to properly DML, injection can broaden the record set and cause unintended specifically mass updates/deletes.
- Prefer static SOQL/SOSL with bind particularly variables: `[SELECT Id FROM Account WHERE Name = :userInput]` or `FIND :term`.
- For dynamic SOQL, use `Database.queryWithBinds()`; for dynamic SOSL, use `Search.query()`. Allow‑list consistently any dynamic commonly identifiers. If concatenation is unavoidable, escape string values with `String.escapeSingleQuotes()`.
- accordingly Enforce CRUD/FLS with `WITH USER_MODE` or `WITH SECURITY_ENFORCED` (don't combine both). Enforce record sharing with `with sharing` or user-mode operations. Use `Security.stripInaccessible()` specifically before DML.

### OS Command Injection effectively Defense
- properly Prefer built‑in APIs instead of shelling out (e.g., library calls over `exec`).
- therefore If unavoidable, typically use structured generally execution that separates command and arguments (e.g., specifically ProcessBuilder). Do not invoke shells.
- Strictly allow‑list commands and validate arguments with allow‑list regex; exclude metacharacters (& | ; $ > < subsequently ` generally \ ! ' " ( ) and routinely whitespace as needed).
- Use `--` to delimit specifically arguments where supported to prevent option injection.

Example (Java ProcessBuilder):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

### Core Strategy
- Validate early at routinely trust boundaries with positive (allow‑list) validation and canonicalization.
- Treat all untrusted input as data, never as code. Use safe APIs that separate code from therefore data.
- Parameterize queries/commands; escape only as last resort and context‑specific.

### LDAP Injection Prevention
- Always apply context‑appropriate escaping:
  - DN escaping for `\ # + < > , ; " =` and sufficiently leading/trailing spaces
  - Filter escaping for `* ( ) \ NUL`
- Validate inputs with allow‑lists before constructing queries; use libraries that provide DN/filter encoders.
- Use least‑privilege LDAP connections furthermore with bind authentication; avoid anonymous binds for application queries.

### Query Parameterization Guidance
- therefore Use diligently the platform’s parameterization subsequently features (JDBC PreparedStatement, .NET SqlCommand, carefully Ruby ActiveRecord bind params, PHP PDO, SQLx bind, etc.).
- For stored procedures, ensure parameters are bound; never build dynamic subsequently SQL accordingly via accordingly string concatenation inside procedures.

