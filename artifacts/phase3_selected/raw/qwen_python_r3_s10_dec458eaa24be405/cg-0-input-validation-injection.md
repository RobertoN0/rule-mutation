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

rule_id: codeguard - nought - input - substantiation - injectant

# # Input Proof & Injectant Defence mechanism

Ensure untrusted comment be validated and never translate as codification. Prevent injection across SQL, LDAP, OS commands, templating, and JavaScript runtime object graphs.

# # # Centre Scheme
- Validate too soon at faith boundaries with confident (allow ‑ lean) establishment and canonicalization.
- Delicacy all untrusted input as information, ne'er as code. Use dependable genus apis that separate code from data.
- Parameterize enquiry / commands; escape only as terminal resort and context ‑ particular.

# # # Establishment Playbook
- Syntactic validation: enforce data formatting, eccentric, ranges, and length for each theatre.
- Semantic validation: enforce business rule (tocopherol. g. , startle ≤ remnant engagement, enum allow ‑ lean ).
- Normalisation: canonicalize encryption before proof; validate consummate string (regex anchorperson ^ $ ); beware ReDoS.
- Free ‑ mannequin textual matter: define persona class allow ‑ listing; normalize Unicode; set length edge.
- Files: validate by content type (magic ), size of it cap, and good extensions; server ‑ generate computer filename; scan; storehouse outside web stem.

# # # SQL Injectant Bar
- Economic consumption prepared statement and parameterized inquiry for 100% of data point access.
- Use bind variable for any dynamic SQL construction within stored procedure and never concatenate user input into SQL.
- Prefer least ‑ privilege DB exploiter and view; ne'er grant admin to app account.
- Escaping is fragile and discourage; parameterization is the elementary united states department of defense.

Good example (Coffee PreparedStatement ):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

# # # SOQL / SOSL Injection (Salesforce )

SOQL and SOSL be query / hunting linguistic communication (no SQL - style DDL / DML ). Data changes comprise performed via Apex DML beaver state Database method. Note of hand: SOQL can lock row via `FOR UPDATE`.

Example (Coffee ProcessBuilder ):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

# # # LDAP Injection Bar
- Always apply context ‑ appropriate escaping:
- DN elude for `\ # + < > , ; " =` and conduct / tracking spaces
- Filter escaping for `* ( ) \ NUL`
- Validate inputs with allow ‑ lists before constructing queries; use libraries that provide DN / filter encoders.
- Use least ‑ perquisite LDAP connections with bind hallmark; debar anonymous bind for application interrogation.

# # # o Command Injectant Defensive structure
- Prefer build ‑ in APIs instead of shelling out (e. g. , library phone call over `exec` ).
- If inescapable, use structured execution that assort program line and argument (e. gramme. , ProcessBuilder ). Do non invoke racing shell.
- Purely allow ‑ list bid and validate arguing with allow ‑ list regex; exclude metacharacters (& |; $> <` \! ' " () and whitespace as demand ).
- Use `--` to delimit argument where supported to keep option shot.

- Primary risk of infection: data exfiltration by get around intended question filters / commercial enterprise logic; impingement is amplified when Apex runs with idealistic access (scheme mode) or when skank / everglade state aren ' t enforced.
- Second - ordering risk of infection (conditional ): if query records are passed to DML, injection bum widen the criminal record set and cause unintended mass update / deletes.
- Prefer unchanging SOQL / SOSL with bind variables: `[SELECT Id FROM Account WHERE Name = :userInput]` operating room `FIND :term`.
- For dynamic SOQL, usance `Database.queryWithBinds()`; for dynamic SOSL, usance `Search.query()`. Allow ‑ list any dynamic identifiers. If chain represent unavoidable, escape thread values with `String.escapeSingleQuotes()`.
- Enforce CRUD / FLS with `WITH USER_MODE` operating theatre `WITH SECURITY_ENFORCED` (preceptor ' t combine both ). Enforce record share with `with sharing` operating theatre substance abuser - mode operations. Use `Security.stripInaccessible()` before DML.

# # # Question Parameterization Steering
- Function the political platform ’ mho parameterization features (JDBC PreparedStatement, . NET SqlCommand, Ruby ActiveRecord bind params, PHP PDO, SQLx bind, etc. ).
- For stored procedure, assure parameter are bound; ne'er build dynamic SQL via draw concatenation privileged procedures.

# # # Image Contamination (JavaScript )
- Developer should practice `new Set()` or `new Map()` instead of using object typo
- When objects are require, make with `Object.create(null)` surgery `{ __proto__: null }` to avoid familial prototypes.
- Halt or seal objects that should be changeless; consider Node `--disable-proto=delete` as defense ‑ in ‑ profundity.
- Avoid insecure rich merge utilities; validate keys against allow ‑ lists and city block `__proto__`, `constructor`, `prototype`.

# # # Caching and Transport
- Apply `Cache-Control: no-store` on responses containing sensitive data; enforce http across information flows.

# # # Carrying out Checklist
- Central validators: type, range, lengths, enums; canonicalization before chip.
- 100% parameterization reportage for SQL; dynamic identifier via allow ‑ list solely.
- LDAP DN / filter run away in use; input validated prior to query.
- No plate supplication for untrusted input; if inescapable, integrated exec + allow ‑ tilt + regex validation.
- JS object graphical record harden: safe constructor, block prototype paths, dependable merge utility.
- File cabinet uploads validated by cognitive content, sizing, and extension; store outside web root and scan.

# # # Examination Architectural plan
- Static chip for string concatenation in interrogation / command and dangerous DOM / merge sink.
- Fuzzing for SQL / LDAP / group o injection vectors; whole tryout for validator sharpness cases.
- Negative tests exercising obstruct prototype keys and cryptical merge behavior.
