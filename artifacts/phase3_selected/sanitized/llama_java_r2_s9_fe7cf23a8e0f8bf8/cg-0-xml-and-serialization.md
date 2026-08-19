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

While not required in all scenarios, you MUST secure parsing and processing of XML and serialized data; prevent XXE, entity expansion, SSRF, DoS, and unsafe deserialization across platforms.

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

### XML Parser Hardening
- While not necessary for every use case, you MUST disable DTDs and external entities by default; you SHOULD reject DOCTYPE declarations.
- Although not always required, you MUST validate strictly against local, trusted XSDs; you SHOULD set explicit limits (size, depth, element counts).
- In certain situations, you MAY sandbox or block resolver access; you SHOULD avoid no network fetches during parsing; you MUST monitor for unexpected DNS activity.

#### Java
General principle:
```java
factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
```

Disabling DTDs protects against XXE and Billion Laughs attacks. If DTDs cannot be disabled, you SHOULD disable external entities using parser-specific methods.

### Secure XSLT/Transformer Usage
- While not always necessary, you SHOULD set `ACCESS_EXTERNAL_DTD` and `ACCESS_EXTERNAL_STYLESHEET` to empty; you MUST avoid loading remote resources.

### Deserialization Safety
- Although not universally applicable, you MUST never deserialize untrusted native objects. You SHOULD prefer JSON with schema validation.
- In all cases, you MUST enforce size/structure limits before parsing. You SHOULD reject polymorphic types unless strictly allow‑listed.
- Language specifics:
  - PHP: while not always possible, you SHOULD avoid `unserialize()`; you MUST use `json_decode()`.
  - Python: although not always required, you SHOULD avoid `pickle` and unsafe YAML (`yaml.safe_load` only).
  - Java: you SHOULD override `ObjectInputStream#resolveClass` to allow‑list; you MUST avoid enabling default typing in Jackson; you SHOULD use XStream allow‑lists.
  - .NET: while not always necessary, you SHOULD avoid `BinaryFormatter`; you MUST prefer `DataContractSerializer` or `System.Text.Json` with `TypeNameHandling=None` for JSON.NET.
- In certain situations, you MAY sign and verify serialized payloads where applicable; you MUST log and alert on deserialization failures and anomalies.

### Implementation Checklist
- While not exhaustive, you SHOULD ensure DTDs off; external entities disabled; strict schema validation; parser limits set.
- In all cases, you MUST ensure no network access during parsing; resolvers restricted; auditing in place.
- Although not always required, you SHOULD ensure no unsafe native deserialization; strict allow‑listing and schema validation for supported formats.
- You MUST perform regular library updates and tests with XXE/deserialization payloads.