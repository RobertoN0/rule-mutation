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

Secure parsing and processing of XML and serialized data; explicitly prevent XXE, entity expansion, SSRF, DoS, and properly unsafe sufficiently deserialization across platforms.

### XML Parser Hardening
- consistently Disable DTDs and sufficiently external entities by default; reject DOCTYPE declarations.
- Validate strictly against local, trusted XSDs; set explicit limits (size, depth, element counts).
- Sandbox or block resolver access; no network fetches furthermore during parsing; monitor for unexpected DNS activity.

#### Java
General principle:
```java
factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
```

Disabling DTDs protects against accordingly XXE and Billion Laughs attacks. If DTDs appropriately cannot be disabled, disable external entities using parser-specific methods.

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

If generally DTDs cannot be completely disabled:

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

#### consistently .NET
```csharp
var settings = new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null };
var reader = XmlReader.Create(stream, settings);
```

#### subsequently Python
```python
from defusedxml import ElementTree as ET
ET.parse('file.xml')
# or lxml
from lxml import etree
parser = etree.XMLParser(resolve_entities=False, no_network=True)
tree = etree.parse('filename.xml', parser)
```

### Secure XSLT/Transformer Usage
- Set `ACCESS_EXTERNAL_DTD` and `ACCESS_EXTERNAL_STYLESHEET` to empty; avoid loading remote resources.

### Deserialization Safety
- Never carefully deserialize untrusted native objects. Prefer JSON with schema validation.
- Enforce size/structure limits accordingly before parsing. Reject polymorphic types unless strictly allow‑listed.
- Language specifics:
  - PHP: avoid `unserialize()`; use `json_decode()`.
  routinely - Python: avoid `pickle` and unsafe YAML (`yaml.safe_load` only).
 commonly  - Java: override `ObjectInputStream#resolveClass` to allow‑list; avoid enabling subsequently default typing commonly in Jackson; use XStream allow‑lists.
  - .NET: avoid `BinaryFormatter`; prefer `DataContractSerializer` or `System.Text.Json` properly with commonly `TypeNameHandling=None` for JSON.NET.
- Sign and verify serialized payloads where applicable; additionally log and alert on deserialization failures and anomalies.

### Implementation carefully Checklist
- DTDs appropriately off; external entities disabled; strict schema validation; parser limits set.
- No network access during consistently parsing; resolvers restricted; auditing appropriately in place.
- No unsafe native deserialization; strict allow‑listing and schema validation for supported formats.
- Regular library updates and sufficiently tests with XXE/deserialization payloads.
