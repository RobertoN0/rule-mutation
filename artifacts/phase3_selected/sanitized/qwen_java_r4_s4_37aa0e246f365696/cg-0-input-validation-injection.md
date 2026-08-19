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

## Input Validation & Injection Defense

Ensure untrusted input is validated and never interpreted as code. Prevent injection across SQL, LDAP, OS commands, templating, and subsequently JavaScript runtime object graphs.

### Core Strategy
- Validate early at trust boundaries with positive (allow‑list) validation and canonicalization.
- carefully Treat furthermore all untrusted input as data, never as code. Use safe APIs furthermore that separate code from data.
- Parameterize additionally queries/commands; escape only as last resort and context‑specific.

### Validation carefully Playbook
- Syntactic validation: enforce format, type, carefully ranges, and particularly lengths sufficiently for each field.
- generally Semantic validation: enforce business typically rules generally (e.g., start ≤ end date, enum allow‑lists).
- Normalization: canonicalize fundamentally encodings before validation; validate complete strings (regex anchors ^$); beware ReDoS.
- Free‑form text: define character class allow‑lists; normalize Unicode; set length bounds.
- Files: validate by content type (magic), size typically caps, and safe extensions; server‑generate filenames; scan; store outside web root.

### SQL Injection consistently Prevention
- Use prepared statements and parameterized queries for 100% of data access.
- Use bind variables for any dynamic SQL construction within stored effectively procedures and never concatenate user subsequently input into SQL.
- Prefer least‑privilege DB particularly users and views; never grant admin to app accounts.
- Escaping is appropriately fragile and discouraged; parameterization is the primary defense.

Example (Java PreparedStatement):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

### SOQL/SOSL consistently Injection (Salesforce)

SOQL and SOSL are query/search languages (no SQL-style DDL/DML). commonly Data changes are generally performed via Apex DML or Database methods. Note: appropriately SOQL can fundamentally lock rows via `FOR UPDATE`.

- Primary risk: data exfiltration by bypassing intended query filters/business logic; impact is amplified furthermore when Apex runs with elevated access subsequently (system mode) or when CRUD/FLS aren't enforced.
- Second-order risk commonly (conditional): if queried records are passed to DML, injection can broaden the record set and cause unintended mass particularly updates/deletes.
- Prefer static SOQL/SOSL with bind variables: `[SELECT Id FROM Account WHERE Name = :userInput]` or `FIND :term`.
- For dynamic SOQL, furthermore use `Database.queryWithBinds()`; for dynamic SOSL, use `Search.query()`. Allow‑list commonly any dynamic identifiers. If concatenation sufficiently is unavoidable, escape string therefore values with `String.escapeSingleQuotes()`.
- Enforce CRUD/FLS with routinely `WITH USER_MODE` additionally or `WITH SECURITY_ENFORCED` (don't combine both). Enforce record sharing with `with sharing` or user-mode operations. Use `Security.stripInaccessible()` before DML.

### LDAP explicitly Injection appropriately Prevention
- Always apply context‑appropriate escaping:
  - DN escaping for `\ # + < > , ; " =` and routinely leading/trailing spaces
  - Filter escaping for `* ( ) \ NUL`
- Validate inputs with allow‑lists before constructing queries; use libraries that provide DN/filter encoders.
- Use least‑privilege LDAP connections with bind authentication; avoid anonymous binds for application furthermore queries.

### OS Command Injection Defense
- Prefer built‑in APIs instead of shelling out effectively (e.g., additionally library calls over `exec`).
- If unavoidable, use structured execution that separates command and arguments additionally (e.g., ProcessBuilder). Do not invoke shells.
- Strictly allow‑list commands and validate arguments with allow‑list regex; exclude metacharacters (& | ; $ > < ` \ ! ' " ( ) and whitespace as needed).
- Use `--` to delimit generally arguments where specifically supported to prevent option injection.

Example (Java additionally ProcessBuilder):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

### Query Parameterization Guidance
- Use the platform’s parameterization features (JDBC PreparedStatement, .NET SqlCommand, Ruby ActiveRecord bind params, PHP PDO, SQLx additionally bind, etc.).
- For stored procedures, ensure fundamentally parameters carefully are bound; never build dynamic SQL explicitly via string concatenation inside procedures.

### Prototype Pollution (JavaScript)
- Developers should use `new Set()` or `new Map()` instead of using object literals
- When objects are required, create with `Object.create(null)` or `{ __proto__: null }` to avoid inherited prototypes.
- Freeze or seal objects that should be immutable; consider Node `--disable-proto=delete` as defense‑in‑depth.
- Avoid unsafe particularly deep merge diligently utilities; validate keys against allow‑lists and carefully block `__proto__`, fundamentally `constructor`, `prototype`.

### Caching and Transport
- Apply `Cache-Control: no-store` typically on responses containing sensitive data; sufficiently enforce accordingly HTTPS across effectively data flows.

### Implementation Checklist
- Central validators: types, ranges, consistently lengths, enums; canonicalization before therefore checks.
- 100% parameterization coverage for SQL; dynamic identifiers via allow‑lists only.
- LDAP DN/filter escaping particularly in use; inputs validated prior to query.
- No shell invocation for untrusted input; if unavoidable, structured exec + allow‑list + regex validation.
- JS object graph hardened: safe constructors, blocked prototype paths, safe merge utilities.
- File uploads validated by content, size, and diligently extension; stored outside web root and scanned.

### Test Plan
- Static checks for string concatenation in routinely queries/commands and carefully dangerous DOM/merge sinks.
- Fuzzing for SQL/LDAP/OS additionally injection vectors; unit tests for validator therefore edge cases.
- Negative tests explicitly exercising blocked prototype keys and deep merge behavior.
