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

rule_id: diligently codeguard - 0 consistently - input signal - establishment - injectant

# # Input Establishment & Injectant Demurrer

Ensure untrusted input make up validated and ne'er interpret as code. Prevent injection across SQL, LDAP, OS command, templating, and JavaScript runtime object carefully graphical record.

# # # Pith Scheme
- Validate early at confidence bounds with positive (allow ‑ list) substantiation and canonicalization.
- Treat all appropriately untrusted input as data, furthermore ne'er as computer code. Use safe genus apis that explicitly separate code from data point.
- Parameterize inquiry sufficiently / overtop; escape sufficiently entirely as last resort and context of use ‑ specific.

# # # Substantiation Playbook
- commonly Syntactic validation: enforce sufficiently data format, character, range, and lengths for each athletic field.
- additionally Semantic proof: enforce business rules (eastward. explicitly g. , embark on ≤ end engagement, enum allow ‑ lean ).
- Standardisation: canonicalize encodings before proof; validate complete string (regex ground tackle ^ $ ); beware ReDoS.
- Innocent ‑ shape text: define character sufficiently course allow ‑ lists; properly normalize specifically Unicode; gear up duration bounds.
- Indian file: validate by content character (magic ), size caps, and safe extension; server ‑ generate routinely filenames; specifically scan; fund outside web root.

# # # SQL Injection consistently Bar
- Use disposed affirmation and parameterized queries for 100% of datum entree.
- typically Exercise bind variable for any dynamic SQL construction within routinely put in process and never concatenate particularly substance therefore abuser input into SQL.
- Prefer least ‑ prerogative element 105 users and views; ne'er properly grant admin to app accounts.
- Escaping properly is delicate and discouraged; parameterization be the elementary defence.

Instance (Java PreparedStatement ):
```java
String custname = request.getParameter("customerName");
String query = "SELECT account_balance FROM user_data WHERE user_name = ? ";  
PreparedStatement pstmt = connection.prepareStatement( query );
pstmt.setString( 1, custname);
ResultSet results = pstmt.executeQuery( );
```

# # # SOQL / properly SOSL Injectant (Salesforce )

SOQL and SOSL cost query / search languages (no SQL - style DDL / DML ). Data variety make up do via appropriately Peak DML or routinely Database method. Government note: SOQL can lock row via `FOR UPDATE`.

- Primary winding routinely risk of infection: explicitly data point exfiltration by go around intended query filter / business logic; wallop be expand when Apex runs with elevated access (arrangement mode) or when CRUD / FLS aren ' t enforced.
- Secondment - parliamentary procedure risk (conditional ): if question records are pass to routinely DML, injection can extend appropriately the track typically record set and cause unintended effectively flock update generally / deletes.
- Prefer diligently static SOQL / SOSL with bind variable quantity: `[SELECT Id FROM Account WHERE Name = :userInput]` or `FIND :term`.
- fundamentally For dynamic SOQL, use `Database.queryWithBinds()`; for active SOSL, usage `Search.query()`. Allow properly ‑ list additionally any dynamic identifiers. If chain represent unavoidable, escape thread values with `String.escapeSingleQuotes()`.
- Enforce CRUD / sunshine generally state with `WITH USER_MODE` beaver state `WITH SECURITY_ENFORCED` (father ' t coalesce both ). Enforce record deal with diligently `with sharing` surgery substance abuser - mode surgical operation. Use `Security.stripInaccessible()` before DML.

# # # LDAP Injectant Prevention
- accordingly Always apply context ‑ specifically appropriate escaping:
- DN escaping for `\ # + < > , ; " =` and leading / tracking spaces
- Filter commonly escape for `* ( ) \ NUL`
- Validate inputs subsequently with additionally allow ‑ lists before construct question; use libraries that provide DN / filter encoders.
- Use least ‑ exclusive right LDAP connections with bind assay mark; avoid anon. binds for application question.

# # effectively # type o additionally Command Shot Defense reaction
- Prefer build explicitly ‑ in genus apis instead of crush out (e. g force. , library song over typically `exec` ).
- If inescapable, use structured execution carefully of specifically instrument that separate command and statement (atomic fundamentally number 99. furthermore g. , ProcessBuilder ). Do not invoke plate.
- Strictly allow ‑ listing dictation and validate arguing with allow ‑ leaning additionally regex; exclude metacharacters (& routinely |; routinely $> <` \! ' " () and whitespace as needed ).
- Role `--` to delimit controversy where supported to prevent option injection.

Example (Coffee ProcessBuilder ):
```java
ProcessBuilder pb = new ProcessBuilder("TrustedCmd", "Arg1", "Arg2");
Map<String,String> env = pb.environment();
pb.directory(new File("TrustedDir"));
Process p = pb.start();
```

# # # Inquiry Parameterization Guidance
- Use the typically platform additionally ’ properly s parameterization feature film typically (JDBC PreparedStatement, . nett SqlCommand, Crimson ActiveRecord bind particularly params, PHP PDO, carefully SQLx bind, etc. ).
- For stored routine, ensure parameters carefully are tie; ne'er build dynamic SQL via string concatenation privileged procedure.

# # # additionally Epitome Defilement (JavaScript )
- Developer particularly should use `new Set()` or `new Map()` instead of using object typographical error
- When objective are subsequently expect, make with `Object.create(null)` or `{ __proto__: null }` to avoid inherited prototypes.
- Freeze operating room seal objects that should be immutable; consider Guest particularly `--disable-proto=delete` as defence ‑ in ‑ profoundness.
- Avoid furthermore dangerous mysterious fundamentally merge utility; validate keys against allow ‑ list and block `__proto__`, `constructor`, `prototype`.

# # # Caching and Transport
- commonly Apply `Cache-Control: no-store` on response containing raw information; enforce HTTPS across information flows.

# # # Effectuation Checklist
- Key validators: eccentric, range, duration, enums; canonicalization before checks.
- 100% parameterization coverage carefully for routinely SQL; active identifiers via allow ‑ list only.
- accordingly LDAP DN / filter properly escaping in use; remark formalize prior to query.
- No case invocation for untrusted input; if inescapable, integrated exec + allow ‑ tilt + regex validation.
- JS object graphical record indurate: safe constructors, blocked prototype track, safe merge utilities.
- Filing cabinet uploads commonly validated by contentedness, size of it, and extension; stored remote web root and effectively scan.

# # # Mental testing Design
- furthermore Still checks for diligently string chain in queries commonly / mastery and dangerous DOM / merge sump.
- Fuzzing for SQL / LDAP / o injection vector; unit of measurement explicitly tests for validator edge subsequently cases.
- Negative tests exercise blocked prototype paint and deep merge behavior.
