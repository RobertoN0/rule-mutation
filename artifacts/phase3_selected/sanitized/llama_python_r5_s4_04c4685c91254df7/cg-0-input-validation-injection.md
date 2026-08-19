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

rule_id: codeguard - 0 - stimulant - proof - injection

# # Stimulation Proof & Injection Defensive structure

Ensure untrusted input embody validated and never interpreted as code. Prevent shot across SQL, LDAP, OS commands, templating, and JavaScript runtime object graphical record.

# # # Nub Scheme
- Validate early at trust bound with positive (allow ‑ leaning) substantiation and canonicalization.
- Treat all untrusted input as data, never as code. Use safe genus apis that tell codification from information.
- Parameterize queries / overtop; escape only as last recourse and linguistic context ‑ specific.

# # # Establishment Playbook
- Syntactical proof: enforce data format, case, ranges, and duration for each field.
- Semantic validation: enforce business rule (atomic number 99. g. , bulge out ≤ conclusion engagement, enum allow ‑ lists ).
- Standardization: canonicalize encoding before substantiation; validate complete strings (regex anchors ^ $ ); beware ReDoS.
- Free ‑ form text: define character class allow ‑ lists; anneal Unicode; prepare length bounds.
- File: validate by content type (magic ), size of it pileus, and safe extensions; server ‑ generate filenames; scan; store out of door web root.

# # # SQL Injection Bar
- Use prepared statement and parameterized queries for 100% of datum entree.
- Use bind variable for any active SQL construction within stored procedures and ne'er concatenate user comment into SQL.
- Prefer least ‑ prerogative DB user and views; ne'er grant admin to app report.
- Escaping is tenuous and discouraged; parameterization is the primary defense.

Deterrent example (Coffee PreparedStatement ):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

# # # SOQL / SOSL Injection (Salesforce )

SOQL and SOSL are query / search languages (no SQL - way DDL / DML ). Data change are performed via Apex DML or Database method. Musical note: SOQL terminate lock course via `FOR UPDATE`.

- Primary hazard: datum exfiltration by bypassing specify query filters / business logic; impact is amplified when Solar apex runs with high minded admittance (system mode) or when CRUD / fl aren ' thymine apply.
- Second - gild risk (conditional ): if queried record be pass to DML, injection derriere broaden the record set and case unintended mass update / deletes.
- Prefer static SOQL / SOSL with bind variables: `[SELECT Id FROM Account WHERE Name = :userInput]` or `FIND :term`.
- For dynamic SOQL, usance `Database.queryWithBinds()`; for dynamic SOSL, use `Search.query()`. Allow ‑ list any active identifier. If chain is unavoidable, escape string value with `String.escapeSingleQuotes()`.
- Enforce CRUD / sunshine state with `WITH USER_MODE` or `WITH SECURITY_ENFORCED` (don ' t immix both ). Enforce record sharing with `with sharing` or user - mode procedure. Employment `Security.stripInaccessible()` before DML.

# # # LDAP Injection Bar
- Always utilise context ‑ appropriate escaping:
- DN get off for `\ # + < > , ; " =` and leading / trailing outer space
- Filter get away for `* ( ) \ NUL`
- Validate stimulus with allow ‑ lists before constructing queries; use program library that supply DN / filter encoders.
- Use least ‑ privilege LDAP connexion with bind assay mark; deflect anonymous binds for application queries.

# # # type o Mastery Injectant Defense
- Prefer build ‑ in genus apis instead of beat out (einsteinium. g. , library calls over `exec` ).
- If ineluctable, use integrated execution that fork statement and disputation (e. g. , ProcessBuilder ). Do not arouse plate.
- Strictly allow ‑ list statement and validate controversy with allow ‑ listing regex; turf out metacharacters (& |; $> <` \! ' " () and whitespace as needed ).
- Use `--` to delimit contestation where supported to preclude option shot.

Example (Coffee ProcessBuilder ):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

# # # Question Parameterization Counselling
- Use the platform ’ s parameterization feature of speech (JDBC PreparedStatement, . NET SqlCommand, Crimson ActiveRecord bind params, PHP PDO, SQLx bind, etc. ).
- For stored procedures, ensure parameters personify bound; never build active SQL via string chain inside procedures.

# # # Image Defilement (JavaScript )
- Developers should utilize `new Set()` or `new Map()` alternatively of apply object literals
- When objects be required, create with `Object.create(null)` or `{ __proto__: null }` to fend off genetic prototypes.
- Freeze or seal objects that should equal immutable; consider Node `--disable-proto=delete` as defense ‑ in ‑ depth.
- Avoid insecure deep merge utility; validate keys against allow ‑ tilt and stoppage `__proto__`, `constructor`, `prototype`.

# # # Caching and Transport
- Apply `Cache-Control: no-store` on reaction contain sensitive data; enforce HTTPS across information flows.

# # # Carrying out Checklist
- Central validators: types, range, distance, enums; canonicalization before chip.
- c% parameterization reportage for SQL; active identifiers via allow ‑ lists only.
- LDAP DN / filter escaping in use; inputs validated prior to query.
- Atomic number 102 plate invocation for untrusted remark; if ineluctable, structured white house + allow ‑ list + regex validation.
- JS object graph harden: safe constructor, blocked prototype paths, secure merge public utility company.
- File uploads validated by content, size, and file name extension; put in extraneous web root and scanned.

# # # Exam Architectural plan
- Static checks for string concatenation in enquiry / command and life threatening DOM / merge cesspool.
- Fuzzing for SQL / LDAP / OS shot vectors; whole tests for validator edge case.
- Negative tests exercising freeze prototype keys and deep merge conduct.
