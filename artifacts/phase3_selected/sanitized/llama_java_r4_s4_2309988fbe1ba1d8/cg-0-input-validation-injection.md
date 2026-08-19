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
Input validation and injection defense should be implemented in such a way that untrusted input is validated and never interpreted as code. Injection across SQL, LDAP, OS commands, templating, and JavaScript runtime object graphs should be prevented.

### Core Strategy
- Untrusted input should be validated early at trust boundaries with positive (allow‑list) validation and canonicalization.
- All untrusted input should be treated as data, never as code. Safe APIs that separate code from data should be used.
- Queries/commands should be parameterized; escaping should only be done as a last resort and in a context‑specific manner.

### Validation Playbook
- Syntactic validation should be performed to enforce format, type, ranges, and lengths for each field.
- Semantic validation should be performed to enforce business rules (e.g., start ≤ end date, enum allow‑lists).
- Normalization should be done by canonicalizing encodings before validation; complete strings should be validated (regex anchors ^$); ReDoS should be avoided.
- Free‑form text should be defined with character class allow‑lists; Unicode should be normalized; length bounds should be set.
- Files should be validated by content type (magic), size caps, and safe extensions; server‑generated filenames should be used; files should be scanned and stored outside the web root.

### SQL Injection Prevention
- Prepared statements and parameterized queries should be used for 100% of data access.
- Bind variables should be used for any dynamic SQL construction within stored procedures, and user input should never be concatenated into SQL.
- Least‑privilege DB users and views should be preferred; admin should never be granted to app accounts.
- Escaping should be avoided as it is fragile and discouraged; parameterization should be the primary defense.

Example (Java PreparedStatement):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

### SOQL/SOSL Injection (Salesforce)

SOQL and SOSL are query/search languages (no SQL-style DDL/DML). Data changes should be performed via Apex DML or Database methods. Note: SOQL can lock rows via `FOR UPDATE`.

- The primary risk should be mitigated by preventing data exfiltration through bypassing intended query filters/business logic; impact should be amplified when Apex runs with elevated access (system mode) or when CRUD/FLS aren't enforced.
- A second-order risk (conditional) should be mitigated: if queried records are passed to DML, injection can broaden the record set and cause unintended mass updates/deletes.
- Static SOQL/SOSL should be preferred with bind variables: `[SELECT Id FROM Account WHERE Name = :userInput]` or `FIND :term`.
- For dynamic SOQL, `Database.queryWithBinds()` should be used; for dynamic SOSL, `Search.query()` should be used. Dynamic identifiers should be allow‑listed. If concatenation is unavoidable, string values should be escaped with `String.escapeSingleQuotes()`.
- CRUD/FLS should be enforced with `WITH USER_MODE` or `WITH SECURITY_ENFORCED` (both should not be combined). Record sharing should be enforced with `with sharing` or user-mode operations. `Security.stripInaccessible()` should be used before DML.

### LDAP Injection Prevention
- Context‑appropriate escaping should always be applied:
  - DN escaping for `\ # + < > , ; " =` and leading/trailing spaces
  - Filter escaping for `* ( ) \ NUL`
- Inputs should be validated with allow‑lists before constructing queries; libraries that provide DN/filter encoders should be used.
- Least‑privilege LDAP connections should be used with bind authentication; anonymous binds should be avoided for application queries.

### OS Command Injection Defense
- Built‑in APIs should be preferred instead of shelling out (e.g., library calls over `exec`).
- If unavoidable, structured execution should be used that separates command and arguments (e.g., ProcessBuilder). Shells should not be invoked.
- Commands and arguments should be strictly allow‑listed and validated with allow‑list regex; metacharacters (& | ; $ > < ` \ ! ' " ( ) and whitespace should be excluded as needed.
- `--` should be used to delimit arguments where supported to prevent option injection.

Example (Java ProcessBuilder):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

### Query Parameterization Guidance
- The platform’s parameterization features should be used (JDBC PreparedStatement, .NET SqlCommand, Ruby ActiveRecord bind params, PHP PDO, SQLx bind, etc.).
- For stored procedures, parameters should be bound; dynamic SQL should never be built via string concatenation inside procedures.

### Prototype Pollution (JavaScript)
- Developers should use `new Set()` or `new Map()` instead of using object literals
- When objects are required, they should be created with `Object.create(null)` or `{ __proto__: null }` to avoid inherited prototypes.
- Objects that should be immutable should be frozen or sealed; Node `--disable-proto=delete` should be considered as defense‑in‑depth.
- Unsafe deep merge utilities should be avoided; keys should be validated against allow‑lists and `__proto__`, `constructor`, `prototype` should be blocked.

### Caching and Transport
- `Cache-Control: no-store` should be applied on responses containing sensitive data; HTTPS should be enforced across data flows.

### Implementation Checklist
- Central validators should be implemented for types, ranges, lengths, enums; canonicalization should be done before checks.
- 100% parameterization coverage should be achieved for SQL; dynamic identifiers should be used via allow‑lists only.
- LDAP DN/filter escaping should be used; inputs should be validated prior to query.
- Shell invocation should be avoided for untrusted input; if unavoidable, structured exec + allow‑list + regex validation should be used.
- JS object graph should be hardened: safe constructors, blocked prototype paths, safe merge utilities.
- File uploads should be validated by content, size, and extension; stored outside web root and scanned.

### Test Plan
- Static checks should be performed for string concatenation in queries/commands and dangerous DOM/merge sinks.
- Fuzzing should be done for SQL/LDAP/OS injection vectors; unit tests should be done for validator edge cases.
- Negative tests should be performed exercising blocked prototype keys and deep merge behavior.