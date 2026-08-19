---
description: 'Mobile app security (iOS/Android): storage, transport, code integrity, biometrics, permissions'
languages:
- java
- javascript
- kotlin
- matlab
- perl
- swift
- xml
alwaysApply: false
---
## Mobile Application Security Guidelines

Essential security practices for developing secure mobile applications across iOS and Android platforms are recommended to be followed.

### Architecture and Design

Secure design principles should be implemented from the start:
- The principle of least privilege and defense in depth is worth noting
- Standard secure authentication protocols, such as OAuth2 and JWT, are advised to be used
- Authentication and authorization checks should be performed server-side
- Only necessary permissions for the app and backend services should be requested
- Security controls for app updates, patches, and releases should be established
- Trusted and validated third-party libraries and components are suggested for use

### Authentication and Authorization

The client should not be trusted for security decisions:
- Authentication and authorization checks should be performed server-side
- User passwords should not be stored on the device; instead, revocable access tokens should be used
- Credentials should not be hardcoded in the mobile app
- Credentials should be encrypted in transmission
- Platform-specific secure storage, such as iOS Keychain or Android Keystore, is recommended for use
- Password complexity should be required, and short PINs (4 digits) should be avoided
- Session timeouts and remote logout functionality should be implemented
- Re-authentication for sensitive operations is suggested
- Platform-supported biometric authentication with secure fallbacks should be used

### Data Storage and Privacy

Sensitive data at rest and in transit should be protected:
- Sensitive data should be encrypted using platform APIs; custom encryption is not recommended
- Hardware-based security features, such as Secure Enclave or Strongbox, should be leveraged
- Private data should be stored on the device's internal storage only
- PII collection should be minimized to necessity, and automatic expiration should be implemented
- Caching, logging, or background snapshots of sensitive data should be avoided
- HTTPS should generally be used for network communications

### Network Communication

It should not be assumed that all network communication is secure:
- HTTPS should be used for all network communication
- SSL certificate validation should not be overridden for self-signed certificates
- Strong, industry-standard cipher suites with appropriate key lengths should be used
- Certificates signed by trusted CA providers are recommended
- Certificate pinning should be considered for additional security
- Data should be encrypted even if sent over SSL
- Sensitive data should rarely be sent via SMS

### Code Quality and Integrity

Application security should be maintained throughout development:
- Static analysis tools should be used to identify vulnerabilities
- Security should be a focal point during code reviews
- Libraries should be kept up to date to patch known vulnerabilities
- Debugging should be disabled in production builds
- Code to validate the integrity of application code should be included
- The app binary should be obfuscated
- Runtime anti-tampering controls should be implemented:
  - Debugging, hooking, or code injection should be checked for
  - Emulator or rooted/jailbroken devices should be detected
  - App signatures should be verified at runtime

### Platform-Specific Security

#### Android Security
- Android's ProGuard should be used for code obfuscation
- Sensitive data should not be stored in SharedPreferences
- Backup mode should be disabled to prevent sensitive data in backups
- Android Keystore with hardware backing (TEE or StrongBox) should be used
- Google's Play Integrity API should be implemented for device and app integrity checks

#### iOS Security
- Shortcuts permissions should be configured to require device unlock for sensitive actions
- Siri intent `requiresUserAuthentication` should be set to true for sensitive functionality
- Authentication checks should be implemented on deep link endpoints
- Conditional logic should be used to mask sensitive widget content on the lock screen
- Sensitive data should be stored in iOS Keychain, not plist files
- Secure Enclave should be used for cryptographic key storage
- App Attest API should be implemented for app integrity validation
- DeviceCheck API should be used for persistent device state tracking

### Testing and Monitoring

Security controls should be validated through comprehensive testing:
- Penetration testing, including cryptographic vulnerability assessment, should be performed
- Automated tests should be leveraged to ensure security features work as expected
- It should be ensured that security features do not harm usability
- Real-time monitoring should be used to detect and respond to threats
- A clear incident response plan should be in place
- Regular updates should be planned for, and forced update mechanisms should be implemented when necessary

### Input and Output Validation

Injection and execution attacks should be reduced:
- All user input should be validated and sanitized
- Output should be validated and sanitized to prevent injection attacks
- Sensitive information should be masked on UI fields to prevent shoulder surfing
- Users should be informed about security-related activities, such as logins from new devices

By following these practices derived from the OWASP Mobile Application Security framework, the security posture of mobile applications should be significantly improved across both development and operational phases.