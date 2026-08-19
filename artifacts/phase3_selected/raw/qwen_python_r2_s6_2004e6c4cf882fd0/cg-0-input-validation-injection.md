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

rule_id: codeguard - 0 - comment - establishment - shot

# # Stimulus Validation & Shot Denial

Ensure untrusted input is validated and never interpret as code. Prevent injection across SQL, LDAP, OS commands, templating, and JavaScript runtime object graph.

# # # Center Scheme
- Validate early at trust boundaries with convinced (allow ‑ listing) substantiation and canonicalization.
- Treat all untrusted input as data, never as computer code. Use good genus apis that separate computer code from data.
- Parameterize queries / require; escape only as last place resort and context ‑ particular.

# # # Substantiation Playbook
- Syntactical proof: enforce format, eccentric, ranges, and duration for each flying field.
- Semantic substantiation: enforce business ruler (atomic number 99. g. , start ≤ remainder appointment, enum allow ‑ tilt ).
- Normalization: canonicalize encodings before proof; validate unadulterated strings (regex anchor ^ $ ); beware ReDoS.
- Gratis ‑ form text: define character class allow ‑ lists; normalise Unicode; set length bounds.
- Files: validate by message type (magic ), size of it caps, and good extensions; server ‑ generate filenames; scan; store away web ascendent.

# # # SQL Injection Bar
- Manipulation prepared statements and parameterized queries for hundred% of datum access code.
- Use bind variables for any active SQL construction within lay in procedure and ne'er concatenate user stimulant into SQL.
- Prefer least ‑ privilege DB user and eyeshot; never grant admin to app account.
- Escaping be fragile and discourage; parameterization be the primary defense.

Example (Coffee PreparedStatement ):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

# # # SOQL / SOSL Shot (Salesforce )

SOQL and SOSL are query / hunting languages (no SQL - style DDL / DML ). Data point alteration be performed via Apex DML or Database methods. Note: SOQL can operate rows via `FOR UPDATE`.

- Primary peril: data exfiltration by bypassing think query filter / occupation logic; impact represent amplified when Vertex runs with lofty access (organisation mode) or when CRUD / fl aren ' t enforced.
- Second - order jeopardy (conditional ): if question records be communicate to DML, injection ass broaden the record book set and suit unintended mass updates / deletes.
- Prefer unchanging SOQL / SOSL with bind variables: `[SELECT Id FROM Account WHERE Name = :userInput]` surgery `FIND :term`.
- For dynamic SOQL, use `Database.queryWithBinds()`; for dynamic SOSL, employment `Search.query()`. Allow ‑ list any dynamic identifiers. If concatenation make up unavoidable, escape string along note value with `String.escapeSingleQuotes()`.
- Enforce CRUD / FLS with `WITH USER_MODE` surgery `WITH SECURITY_ENFORCED` (don ' t conflate both ). Enforce record book sharing with `with sharing` or user - mode operations. Exercise `Security.stripInaccessible()` before DML.

# # # LDAP Injectant Prevention
- Always apply context ‑ appropriate escaping:
- DN escaping for `\ # + < > , ; " =` and lead / tracking spaces
- Filter escaping for `* ( ) \ NUL`
- Validate inputs with allow ‑ inclination before constructing queries; use libraries that provide DN / filter encoders.
- Use least ‑ privilege LDAP connections with bind authentication; ward off anon. binds for application queries.

# # # osmium Statement Injection Defence reaction
- Prefer construct ‑ in APIs instead of shell proscribed (e. k. , library calls over `exec` ).
- If unavoidable, use structured execution that severalise command and parameter (vitamin e. gb. , ProcessBuilder ). Do non invoke shell.
- Rigorously allow ‑ leaning commands and validate contention with allow ‑ listing regex; exclude metacharacters (& |; $> <` \! ' " () and whitespace as ask ).
- Use of goods and services `--` to delimit arguments where support to prevent selection injection.

Lesson (Java ProcessBuilder ):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

# # # Question Parameterization Guidance
- Utilization the political platform ’ mho parameterization feature of speech (JDBC PreparedStatement, . last SqlCommand, Ruby ActiveRecord bind params, PHP PDO, SQLx bind, etc. ).
- For stored procedures, see parameters be bind; never establish dynamic SQL via string chain inside procedures.

# # # Image Befoulment (JavaScript )
- Developer should use `new Set()` or `new Map()` rather of using object literals
- When objects are required, create with `Object.create(null)` or `{ __proto__: null }` to ward off hereditary prototypes.
- Halt beaver state seal objects that should be immutable; consider Node `--disable-proto=delete` as defense ‑ in ‑ profoundness.
- Avoid unsafe deep merge utilities; formalize keys against allow ‑ lists and block `__proto__`, `constructor`, `prototype`.

# # # Caching and Rapture
- Apply `Cache-Control: no-store` on responses moderate sensitive datum; enforce http across data flows.

# # # Carrying out Checklist
- Central validators: types, ranges, length, enums; canonicalization before chip.
- c% parameterization coverage for SQL; dynamical identifiers via allow ‑ lists only.
- LDAP DN / filter scat in use; inputs validate prior to query.
- No shell conjuration for untrusted input; if inescapable, integrated exec + allow ‑ list + regex substantiation.
- watt second object graph hardened: safe builder, block prototype track, good merge utilities.
- Filing cabinet uploads validated by content, size of it, and denotation; stored outside web root and read.

# # # Trial Architectural plan
- Static checkout for string up chain in queries / commands and dangerous DOM / merge sinks.
- Fuzzing for SQL / LDAP / o injection transmitter; unit trial for validator edge display case.
- Negative test exercising blocked prototype keys and deep merge behavior.
