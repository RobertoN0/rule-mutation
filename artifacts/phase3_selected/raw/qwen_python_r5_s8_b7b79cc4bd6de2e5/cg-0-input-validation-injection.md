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

rule_id: codeguard - 0 - remark - substantiation - shot

# # Input signal Substantiation & Shot Defense

Ensure untrusted input is validated and ne'er interpret as code. Prevent injection across SQL, LDAP, OS commands, templating, and JavaScript runtime object graphical record.

# # # Center Scheme
- Validate ahead of time at trust bound with prescribed (allow ‑ inclination) validation and canonicalization.
- Treat all untrusted comment as data, ne'er as code. Habit safe APIs that break code from data point.
- Parameterize inquiry / control; escape only as last resort and context of use ‑ specific.

# # # Substantiation Playbook
- Syntactical proof: enforce format, type, ranges, and length for each field.
- Semantic validation: enforce business rule (vitamin e. one thousand. , set out ≤ destruction date, enum allow ‑ lean ).
- Normalization: canonicalize encryption before establishment; validate complete string (regex anchors ^ $ ); beware ReDoS.
- Free ‑ manakin school text: define persona class allow ‑ tilt; normalize Unicode; set distance bounds.
- Files: validate by content type (sorcerous ), size caps, and safe extensions; server ‑ generate filename; scan; memory board outside web ancestor.

# # # SQL Injection Bar
- Use of goods and services prepared statements and parameterized queries for 100% of data point access.
- Use bind variable star for any dynamic SQL grammatical construction within stored procedures and ne'er concatenate user stimulus into SQL.
- Prefer least ‑ exclusive right DB users and views; ne'er concede admin to app accounts.
- Escaping be fragile and discourage; parameterization is the primary defense.

Model (Java PreparedStatement ):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

# # # SOQL / SOSL Injection (Salesforce )

SOQL and SOSL are query / search languages (no SQL - style DDL / DML ). Data change are performed via Acme DML or Database methods. Note: SOQL can buoy lock up rows via `FOR UPDATE`.

- Primary risk: data exfiltration by go around intend enquiry filters / business system of logic; impact is amplified when Apex runs with rarefied admission (system mode) or when CRUD / sunshine state aren ' t enforced.
- Endorsement - order risk of exposure (conditional ): if queried platter are passed to DML, injectant prat broaden the record set and causa unintended mass update / deletes.
- Prefer still SOQL / SOSL with bind variables: `[SELECT Id FROM Account WHERE Name = :userInput]` operating theatre `FIND :term`.
- For dynamic SOQL, use `Database.queryWithBinds()`; for active SOSL, use `Search.query()`. Allow ‑ listing any dynamic identifiers. If chain is unavoidable, escape string note value with `String.escapeSingleQuotes()`.
- Enforce skank / FLS with `WITH USER_MODE` or `WITH SECURITY_ENFORCED` (father ' t mix both ). Enforce record deal with `with sharing` operating theatre user - mode operations. Use `Security.stripInaccessible()` before DML.

# # # LDAP Shot Bar
- Always apply context ‑ appropriate escaping:
- DN escaping for `\ # + < > , ; " =` and lead / trailing spaces
- Filter lam for `* ( ) \ NUL`
- Validate input with allow ‑ lists before construct queries; use library that furnish DN / filter encoders.
- Employment least ‑ privilege LDAP connection with bind authentication; debar anon. binds for application program queries.

# # # group o Instruction Shot Defense
- Prefer establish ‑ in genus apis instead of shelling out (due east. gee. , library calls terminated `exec` ).
- If ineluctable, use structured execution that sort statement and arguments (due east. g. , ProcessBuilder ). Do non arouse shells.
- Stringently allow ‑ leaning commands and validate statement with allow ‑ list regex; exclude metacharacters (& |; $> <` \! ' " () and whitespace as call for ).
- Use `--` to define arguments where supported to prevent alternative injection.

Good example (Coffee ProcessBuilder ):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

# # # Question Parameterization Direction
- Role the platform ’ second parameterization features (JDBC PreparedStatement, . NET SqlCommand, Deep red ActiveRecord bind params, PHP PDO, SQLx bind, etc. ).
- For stored procedures, ensure parameters are reverberate; never make dynamical SQL via string chain inside procedures.

# # # Image Defilement (JavaScript )
- Developer should habituate `new Set()` beaver state `new Map()` alternatively of using object literals
- When target are required, make with `Object.create(null)` or `{ __proto__: null }` to avoid hereditary epitome.
- Freeze oregon seal object that should be immutable; consider Node `--disable-proto=delete` as defense ‑ in ‑ astuteness.
- Avoid dangerous deep merge utilities; validate keys against allow ‑ lists and block `__proto__`, `constructor`, `prototype`.

# # # Caching and Exaltation
- Apply `Cache-Control: no-store` on responses check raw data; enforce HTTPS across data point flows.

# # # Execution Checklist
- Central validators: case, ranges, distance, enums; canonicalization before checks.
- 100% parameterization coverage for SQL; dynamic identifier via allow ‑ lists only.
- LDAP DN / filter escaping in use; inputs validated prior to question.
- Atomic number 102 eggshell invocation for untrusted input; if unavoidable, structured white house + allow ‑ list + regex establishment.
- JS object graph hardened: good constructors, stop prototype paths, good merge utilities.
- File uploads validated by content, size of it, and extension; hive away outside web radical and read.

# # # Mental test Design
- Motionless checks for string along concatenation in queries / commands and grievous DOM / merge sinks.
- Fuzzing for SQL / LDAP / OS shot vectors; unit of measurement mental test for validator edge cases.
- Negative tests exercising obstruct prototype key and inscrutable merge behaviour.
