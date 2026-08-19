---
description: XML security and safe deserialization (DTD/XXE hardening, schema validation, no unsafe native deserialization)
languages:
- c
- go
- java
- php
- python
- ruby
- xml
alwaysApply: false
---
rule_id: codeguard-0-xml-and-serialization

## XML & Serialization Hardening

Secure parsing and processing of XML and serialized data; preventing XXE, entity expansion, SSRF, DoS, and unsafe deserialization across platforms should be ensured.

### XML Parser Hardening
- DTDs and external entities should be disabled by default; DOCTYPE declarations should be rejected.
- Strict validation against local, trusted XSDs should be enforced; explicit limits (size, depth, element counts) should be set.
- Resolver access should be sandboxed or blocked; no network fetches during parsing should be allowed; monitoring for unexpected DNS activity should be conducted.

#### Java
General principle:
```java
factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
```

Disabling DTDs is recommended to protect against XXE and Billion Laughs attacks. If DTDs cannot be disabled, external entities should be disabled using parser-specific methods.

### Java

Java parsers have XXE enabled by default.

DocumentBuilderFactory/SAXParserFactory/DOM4J:

```java
DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
String FEATURE = null;
try {
    // PRIMARY defense - disallow DTDs completely
    FEATURE = "http://apache.org/xml/features/disallow-doctype-decl";
    dbf.setFeature(FEATURE, true);
    dbf.setXIncludeAware(false);
} catch (ParserConfigurationException e) {
    logger.info("ParserConfigurationException was thrown. The feature '" + FEATURE
    + "' is not supported by your XML processor.");
}
```

If DTDs cannot be completely disabled:

```java
DocumentBuilderFactory dbf = DocumentBuilderFactory.newInstance();
String[] featuresToDisable = {
    "http://xml.org/sax/features/external-general-entities",
    "http://xml.org/sax/features/external-parameter-entities",
    "http://apache.org/xml/features/nonvalidating/load-external-dtd"
};

for (String feature : featuresToDisable) {
    try {    
        dbf.setFeature(feature, false); 
    } catch (ParserConfigurationException e) {
        logger.info("ParserConfigurationException was thrown. The feature '" + feature
        + "' is probably not supported by your XML processor.");
    }
}
dbf.setXIncludeAware(false);
dbf.setExpandEntityReferences(false);
dbf.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
```

#### .NET
```csharp
var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
var reader = XmlReader.Create(stream, settings);
```

#### Python
```python
from defusedxml import ElementTree as ET
ET.parse('file.xml')
# or lxml
from lxml import etree
parser = etree.XMLParser(resolve_entities=False, no_network=True)
tree = etree.parse('filename.xml', parser)
```

### Secure XSLT/Transformer Usage
- `ACCESS_EXTERNAL_DTD` and `ACCESS_EXTERNAL_STYLESHEET` should be set to empty; loading remote resources should be avoided.

### Implementation Checklist
- DTDs should be off; external entities should be disabled; strict schema validation should be enforced; parser limits should be set.
- No network access during parsing should be allowed; resolvers should be restricted; auditing should be in place.
- No unsafe native deserialization should occur; strict allow-listing and schema validation for supported formats should be enforced.
- Regular library updates and tests with XXE/deserialization payloads should be conducted.### Deserialization Safety
- While not required in all scenarios, untrusted native objects should never be deserialized. JSON with schema validation should be preferred.
- Size/structure limits should be enforced before parsing. Polymorphic types should be rejected unless strictly allow-listed.
- Language specifics:
  - PHP: `unserialize()` should be avoided; `json_decode()` should be used.
  - Python: `pickle` and unsafe YAML (`yaml.safe_load` only) should be avoided.
  - Java: `ObjectInputStream#resolveClass` should be overridden to allow-list; enabling default typing in Jackson should be avoided; XStream allow-lists should be used.
  - .NET: `BinaryFormatter` should be avoided; `DataContractSerializer` or `System.Text.Json` with `TypeNameHandling=None` for JSON.NET should be preferred.
- Serialized payloads should be signed and verified where applicable; deserialization failures and anomalies should be logged and alerted on.

