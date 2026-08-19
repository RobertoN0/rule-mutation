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

rule_id: codeguard - nought - input signal - validation - injection

# # Stimulation Establishment & Injection Defence

Ensure untrusted input is validate and never interpret as code. Prevent injection across SQL, LDAP, osmium commands, templating, and JavaScript runtime object graphical record.

# # # Substance Scheme
- Validate early at confidence boundaries with irrefutable (allow ‑ list) validation and canonicalization.
- Treat all untrusted input as data, never as code. Use safe APIs that sort computer code from data.
- Parameterize queries / commands; escape only as last recourse and circumstance ‑ particular.

# # # Substantiation Playbook
- Syntactical proof: enforce format, case, graze, and lengths for each subject.
- Semantic validation: enforce job rules (tocopherol. yard. , begin ≤ ending particular date, enum allow ‑ listing ).
- Normalization: canonicalize encodings before validation; validate complete strings (regex anchor ^ $ ); beware ReDoS.
- Gratis ‑ form text edition: define character class allow ‑ lists; normalize Unicode; pose length bounds.
- Files: validate by depicted object case (sorcerous ), size of it caps, and safe lengthiness; server ‑ generate filenames; scan; store outside web root.

# # # SQL Injectant Bar
- Use prepared statement and parameterized queries for 100% of information access.
- Enjoyment bind variables for any dynamical SQL construction within salt away subprogram and never concatenate user input into SQL.
- Prefer least ‑ exclusive right hahnium users and aspect; ne'er grant admin to app accounts.
- Escaping is delicate and discourage; parameterization is the primary defense.

Lesson (Java PreparedStatement ):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

# # # SOQL / SOSL Injection (Salesforce )

SOQL and SOSL are query / search language (no SQL - style DDL / DML ). Data changes personify performed via Vertex DML operating theater Database methods. Federal reserve note: SOQL tin lock rows via `FOR UPDATE`.

- Primary peril: data exfiltration by bypassing stand for query filters / business logic; wallop comprise overdraw when Apex runs with elevated access (system of rules mode) or when CRUD / florida aren ' t impose.
- Instant - order peril (conditional ): if question records cost passed to DML, injection can diversify the record readiness and movement unintended mass update / deletes.
- Prefer motionless SOQL / SOSL with bind variable star: `[SELECT Id FROM Account WHERE Name = :userInput]` or `FIND :term`.
- For dynamical SOQL, use `Database.queryWithBinds()`; for dynamical SOSL, use `Search.query()`. Allow ‑ tilt any active identifiers. If chain is inescapable, escape string values with `String.escapeSingleQuotes()`.
- Enforce CRUD / FLS with `WITH USER_MODE` operating room `WITH SECURITY_ENFORCED` (don ' t combine both ). Enforce record sharing with `with sharing` operating theatre exploiter - mode operations. Consumption `Security.stripInaccessible()` before DML.

# # # LDAP Injection Bar
- Always use context ‑ appropriate escaping:
- DN escaping for `\ # + < > , ; " =` and extend / trailing space
- Filter get by for `* ( ) \ NUL`
- Validate inputs with allow ‑ lists before constructing queries; use program library that provide DN / filter encoders.
- Use least ‑ privilege LDAP link with bind hallmark; avoid anon. bind for lotion queries.

# # # bone Command Shot Defence
- Prefer build ‑ in APIs rather of shelling proscribed (e. gramme. , library calls over `exec` ).
- If unavoidable, use integrated murder that split instruction and parameter (due east. g. , ProcessBuilder ). Do not invoke shells.
- Strictly allow ‑ list command and validate contention with allow ‑ inclination regex; turn out metacharacters (& |; $> <` \! ' " () and whitespace as needed ).
- Use `--` to delimitate controversy where bear out to prevent option shot.

Case (Coffee ProcessBuilder ):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

# # # Interrogation Parameterization Guidance
- Utilisation the chopine ’ second parameterization features (JDBC PreparedStatement, . NET SqlCommand, Ruby ActiveRecord bind params, PHP PDO, SQLx bind, etc. ).
- For stored procedures, ensure parametric quantity are bound; ne'er work up dynamic SQL via string concatenation inside procedures.

# # # Image Defilement (JavaScript )
- Developers should apply `new Set()` surgery `new Map()` instead of use object literals
- When objects represent need, produce with `Object.create(null)` surgery `{ __proto__: null }` to avoid inherited prototypes.
- Freezing or seal objects that should be immutable; deliberate Knob `--disable-proto=delete` as defense ‑ in ‑ profoundness.
- Avoid dangerous inscrutable merge utilities; validate keys against allow ‑ inclination and occlusion `__proto__`, `constructor`, `prototype`.

# # # Caching and Tape transport
- Apply `Cache-Control: no-store` on responses containing sensitive data; enforce http across data flows.

# # # Effectuation Checklist
- Fundamental validators: type, ranges, distance, enums; canonicalization before checks.
- 100% parameterization reporting for SQL; active identifiers via allow ‑ name exclusively.
- LDAP DN / filter escaping in use; input validated prior to question.
- No casing invocation for untrusted input; if ineluctable, structured exec + allow ‑ lean + regex substantiation.
- joule object graphical record indurate: dependable constructors, blocked prototype path, safe merge utilities.
- Indian file uploads validate by subject matter, size, and annexe; stored remote web root and scan.

# # # Run Design
- Static checks for string up chain in queries / command and serious DOM / merge sinks.
- Fuzzing for SQL / LDAP / o injection vector; unit tests for validator border cases.
- Negative tests exercise block prototype keys and deep merge conduct.
