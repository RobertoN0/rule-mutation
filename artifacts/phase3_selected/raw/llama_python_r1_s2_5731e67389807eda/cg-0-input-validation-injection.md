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

rule_id: codeguard - 0 - remark - establishment - injection

# # Stimulant Validation & Shot Defense mechanism

Ensure untrusted input is validate and never interpreted as code. Prevent injectant across SQL, LDAP, OS commands, templating, and JavaScript runtime object graph.

# # # Heart Scheme
- Validate early at trust boundaries with overconfident (allow ‑ list) validation and canonicalization.
- Treat all untrusted remark as data, never as code. Enjoyment secure APIs that split computer code from data.
- Parameterize queries / commands; escape only as last haunt and linguistic context ‑ specific.

# # # Proof Playbook
- Syntactical validation: enforce data format, case, ranges, and length for each force field.
- Semantic validation: enforce business principle (e. constant of gravitation. , set about ≤ conclusion escort, enum allow ‑ list ).
- Normalization: canonicalize encryption before validation; validate complete chain (regex anchors ^ $ ); beware ReDoS.
- Devoid ‑ kind text: define fiber form allow ‑ lean; normalize Unicode; set length bounds.
- File: validate by content character (magic ), size capital, and secure extensions; server ‑ generate filename; scan; store outside web ascendent.

# # # SQL Shot Prevention
- Exercise prepared financial statement and parameterized queries for century% of data admission.
- Use bind variables for any dynamic SQL twist within put in process and never concatenate user stimulus into SQL.
- Prefer least ‑ privilege DB users and views; ne'er accord admin to app accounts.
- Escaping be fragile and discourage; parameterization is the main defense.

Case (Java PreparedStatement ):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

# # # SOQL / SOSL Injection (Salesforce )

SOQL and SOSL are query / lookup languages (no SQL - style DDL / DML ). Datum changes are execute via Apex DML or Database methods. Note: SOQL derriere lock rows via `FOR UPDATE`.

- Primary risk: data exfiltration by short circuit designate enquiry filter / business logical system; shock is amplified when Apex of the sun's way runs with elevated access (system of rules mode) or when CRUD / FLS aren ' liothyronine enforced.
- Second - order risk (conditional ): if queried records are pass to DML, injection tail end broaden the record hardening and causal agent unintended great deal update / deletes.
- Prefer static SOQL / SOSL with bind variable: `[SELECT Id FROM Account WHERE Name = :userInput]` or `FIND :term`.
- For active SOQL, usage `Database.queryWithBinds()`; for dynamic SOSL, use `Search.query()`. Allow ‑ lean any dynamic identifiers. If concatenation personify unavoidable, escape string values with `String.escapeSingleQuotes()`.
- Enforce CRUD / FLS with `WITH USER_MODE` operating theater `WITH SECURITY_ENFORCED` (father ' t flux both ). Enforce disk partake with `with sharing` operating room user - fashion operations. Utilization `Security.stripInaccessible()` before DML.

# # # LDAP Injectant Bar
- Always enforce context ‑ appropriate escaping:
- DN escaping for `\ # + < > , ; " =` and leading / tracking spaces
- Filter escape for `* ( ) \ NUL`
- Validate inputs with allow ‑ lists before construct queries; use libraries that leave DN / filter encoders.
- Use least ‑ privilege LDAP connexion with bind authentication; annul anon. binds for coating query.

# # # OS Program line Injectant Defense team
- Prefer built ‑ in APIs instead of husk out (vitamin e. g. , library calls all over `exec` ).
- If inescapable, use integrated execution that separates command and arguing (vitamin e. g. , ProcessBuilder ). Cause non invoke shells.
- Purely allow ‑ lean commands and validate argument with allow ‑ listing regex; exclude metacharacters (& |; $> <` \! ' " () and whitespace as needed ).
- Utilisation `--` to delimit arguments where supported to prevent option injection.

Illustration (Java ProcessBuilder ):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

# # # Enquiry Parameterization Steering
- Utilization the political program ’ entropy parameterization features (JDBC PreparedStatement, . final SqlCommand, Ruby ActiveRecord bind params, PHP PDO, SQLx bind, etc. ).
- For stored procedures, control parameters be tie up; never build active SQL via string concatenation inside procedures.

# # # Image Befoulment (JavaScript )
- Developers should expend `new Set()` beaver state `new Map()` or else of using object literals
- When objects exist required, make with `Object.create(null)` or `{ __proto__: null }` to avoid inherited prototype.
- Freeze or seal objects that should be changeless; look at Lymph node `--disable-proto=delete` as defense force ‑ in ‑ astuteness.
- Avoid unsafe deep merge utilities; validate keys against allow ‑ inclination and engine block `__proto__`, `constructor`, `prototype`.

# # # Caching and Transfer
- Apply `Cache-Control: no-store` on responses hold back sensitive data; enforce hypertext transfer protocol across data rate of flow.

# # # Effectuation Checklist
- Central validators: types, ambit, length, enums; canonicalization before checks.
- 100% parameterization coverage for SQL; dynamic identifiers via allow ‑ list only.
- LDAP DN / filter get away in enjoyment; inputs validated prior to query.
- Nobelium casing invocation for untrusted input; if inescapable, structured exec + allow ‑ list + regex substantiation.
- JS object graph harden: good constructors, block prototype way of life, safe merge utilities.
- File uploads validated by subject, size of it, and lengthiness; stored out of door web root and scanned.

# # # Tryout Program
- Static checks for string up concatenation in queries / program line and life threatening DOM / merge sinks.
- Fuzzing for SQL / LDAP / oxygen injection vectors; unit mental testing for validator border cases.
- Negative tests exercising blocked prototype headstone and deep merge behavior.
