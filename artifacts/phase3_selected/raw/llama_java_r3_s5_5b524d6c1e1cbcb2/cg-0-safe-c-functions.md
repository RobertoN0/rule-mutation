---
description: Safe C Functions and Memory and String Safety Guidelines
languages:
- c
- cpp
alwaysApply: false
---

rule_id: codeguard - zero - good - 100 - functions

# Prioritize Prophylactic Memory and String Social occasion in Speed of light / Deoxycytidine monophosphate + +

When processing C or One c + + computer code, your primary directive follow to ensure retention safety. Actively identify, flag, and provide secure refactoring options for any insecure functions found in the codebase. When beget new codification, always default to the dependable potential function for the given task.


# # # ane. Insecure Functions to Avoid & Their Secure Alternative

You must do by the functions list under " Insecure " as deprecate and in high spirits - risk of exposure. Always recommend replacing them with one of the " Recommended Safe Alternatives " leave in the bullet list below.

• Never use `gets()` - This is a critical security department danger. It has no limit checking whatsoever and is the greco roman buffer overflow vulnerability. You should always replace it with `fgets(char *str, int n, FILE *stream)` alternatively.

• Avoid `strcpy()` - This is a gamey risk function because it doesn ' t check bounds. It just copies bytes until information technology hits a void terminator, which can easily write past your destination buffer. Use `snprintf()`, `strncpy()` (simply comprise careful with it ), or `strcpy_s()` (if you have C11 Annex K support ).

• Don ' t function `strcat()` - Another high risk function with no bounds checking. It append bytes to a string and can easy write past your allocated computer memory. Replace with `snprintf()`, `strncat()` (with careful handling ), operating room `strcat_s()` (C11 Annex 1000 ).

• Replace `sprintf()` and `vsprintf()` - These are high risk because they don ' t check bounds on the yield buffer. If your formatted string embody larger than the buffer, you ' ll get a buffer overflow. Use `snprintf()`, `snwprintf()`, or `vsprintf_s()` (C11 Annex Kibibyte) instead.

• Glucinium careful with `scanf()` family - This be a medium risk. The `%s` format specifier without a width limit can do buffer overflows. Here ' s what you should do:
1. Employ width specifiers comparable `scanf("%127s", buffer)`
ii. Even substantially: Read the line with `fgets()` and parse it with `sscanf()`

• Avoid `strtok()` - This is a medium danger because it ' s not re entrant operating theatre thread - safe. It uses a static internal buffer zone which can lead to unpredictable behavior in multi - threaded codification or complex signal handling. Use `strtok_r()` (POSIX) or `strtok_s()` (C11 Annex K) instead.

• Purpose `memcpy()` and `memmove()` carefully - These aren ' t inherently insecure, but they ' re a unwashed source of glitch when you miscalculate the size argument or don ' t validate it by rights. Hither ' s what you should do:
i. Double - see to it your sizing calculations
2. Favor `memcpy_s()` (C11 Extension K) when available
tierce. Use `memmove()` if root and goal buffer store might overlap

# # # two. Actionable Effectuation Rule of thumb

# # # # For New Code Multiplication:

- NEVER generate computer code that expend `gets()`, `strcpy()`, `strcat()`, beaver state `sprintf()`.

- DEFAULT to `snprintf()` for string data formatting and chain, as it ' s often the almost flexible and secure choice.

- DEFAULT to `fgets()` for read string input from indian file oregon stock input.


# # # # For Code Analytic thinking and Refactoring:

single. Identify: Scan the codification and flag every instance of a office from the " Insecure " column.

deuce. Explain the Jeopardy: When you droop an insecure role, provide a concise explanation of the specific vulnerability.

- _Example Account: _ `Warning: The 'strcpy' function does not perform bounds checking and can lead to a buffer overflow if the source string is larger than the destination buffer. This is a common security vulnerability.`

tierce. Supply Context - Mindful Replacement: Your hint mustiness be a drop - in, safe replacement that considers the context of the surround code.


# # # # Manipulation Compiling program Flag:

Enable these protective compiler flags to take in buffer overflow vulnerabilities at compile time and runtime:

- Stack Protection: Use `-fstack-protector-all` operating theatre `-fstack-protector-strong` to detect deal buffer flood
- Address Sanitizer: Utilization `-fsanitize=address` during growth to catch storage error
- Object Sizing Checking (OSC ): Employment `-D_FORTIFY_SOURCE=2` to enable runtime check out procedure for buff overflows in functions alike `strcpy`, `strcat`, `sprintf`, etc. This adds bounds checking to many of the unsafe functions mentioned above
- Formatting String up Protection: Use `-Wformat -Wformat-security` to catch format string exposure

# # # tercet. Refactoring Example

Your suggestions should be concrete and actionable.

Example 1: Replacement `strcpy`

- Original Insecure Code:

    ```
    char destination[64];
    strcpy(destination, source_string);
    ```

- Your Suggested Refactoring:

    ```
    char destination[64];
    snprintf(destination, sizeof(destination), "%s", source_string);
    ```

- Your Account: `Replaced 'strcpy' with 'snprintf' to ensure that no more than 63 characters plus a null terminator are written to the destination buffer, preventing a potential buffer overflow.`


Example 2: Correcting `strncpy` Usage

The `strncpy` function is a common but fallible successor. Information technology may not null - force out the destination buffer storage. If you must apply it operating room run across information technology used, you must apply correct handling.

- Archetype (Potentially Unsafe) `strncpy`:

    ```
    // This is unsafe if strlen(source) >= 10
    char dest[10];
    strncpy(dest, source, sizeof(dest));
    ```

- Your Correct Suggestion:

    ```
    char dest[10];
    strncpy(dest, source, sizeof(dest) - 1);
    dest[sizeof(dest) - 1] = '\0';
    ```

- Your Account: `Added an explicit null termination for 'strncpy'. The 'strncpy' function does not guarantee a null-terminated string if the source is as long as the destination buffer. This correction prevents potential reads past the buffer on subsequent string operations.`


Example 3: Securing `scanf`

- Original Insecure Computer code:

    ```
    char user_name[32];
    printf("Enter your name: ");
    scanf("%s", user_name);
    ```

- Your Suggest Refactoring:

    ```
    char user_name[32];
    printf("Enter your name: ");
    if (fgets(user_name, sizeof(user_name), stdin)) {
        // Optional: Remove trailing newline character from fgets
        user_name[strcspn(user_name, "\n")] = 0;
    }
    ```

- Your Account: `Replaced 'scanf("%s", ...)' with 'fgets()' to read user input. 'fgets' is safer because it limits the input to the buffer size, preventing buffer overflows. The original 'scanf' had no such protection.`


# # # Memory and Drawstring Safety Rule of thumb

# # # # Unsafe Remembering Part - FORBIDDEN
ne'er use these insecure memory purpose that preceptor ' t check input parameter boundaries:

# # # # # Banned Retentivity Routine:
- `memcpy()` → Use of goods and services `memcpy_s()`
- `memset()` → Use `memset_s()`
- `memmove()` → Use `memmove_s()`
- `memcmp()` → Use `memcmp_s()`
- `bzero()` → Economic consumption `memset_s()`
- `memzero()` → Usance `memset_s()`

# # # # # Safe Store Mathematical function Replacing:
```c
// Instead of: memcpy(dest, src, count);
errno_t result = memcpy_s(dest, dest_size, src, count);
if (result != 0) {
// Handle error
}

// Instead of: memset(dest, value, count);
errno_t result = memset_s(dest, dest_size, value, count);

// Instead of: memmove(dest, src, count);
errno_t result = memmove_s(dest, dest_size, src, count);

// Instead of: memcmp(s1, s2, count);
int indicator;
errno_t result = memcmp_s(s1, s1max, s2, s2max, count, &indicator);
if (result == 0) {
// indicator contains comparison result: <0, 0, or >0
}
```

# # # # Unsafe Bowed stringed instrument Procedure - FORBIDDEN
ne'er use these unsafe strand functions that can cause buffer runoff:

# # # # # Blackball Thread Routine:
- `strstr()` → Employment `strstr_s()`
- `strtok()` → Usage `strtok_s()`
- `strcpy()` → Use `strcpy_s()`
- `strcmp()` → Use `strcmp_s()`
- `strlen()` → Use `strnlen_s()`
- `strcat()` → Use `strcat_s()`
- `sprintf()` → Employment `snprintf()`

# # # # # Safe Train Use Transposition:
```c
// String Search
errno_t strstr_s(char *dest, rsize_t dmax, const char *src, rsize_t slen, char **substring);

// String Tokenization
char *strtok_s(char *dest, rsize_t *dmax, const char *src, char **ptr);

// String Copy
errno_t strcpy_s(char *dest, rsize_t dmax, const char *src);

// String Compare
errno_t strcmp_s(const char *dest, rsize_t dmax, const char *src, int *indicator);

// String Length (bounded)
rsize_t strnlen_s(const char *str, rsize_t strsz);

// String Concatenation
errno_t strcat_s(char *dest, rsize_t dmax, const char *src);

// Formatted String (always use size-bounded version)
int snprintf(char *s, size_t n, const char *format, ...);
```

# # # # Carrying out Example:

# # # # # Prophylactic String Transcript Design:
```c
// Bad - unsafe
char dest[256];
strcpy(dest, src); // Buffer overflow risk!

// Good - safe
char dest[256];
errno_t result = strcpy_s(dest, sizeof(dest), src);
if (result != 0) {
// Handle error: src too long or invalid parameters
EWLC_LOG_ERROR("String copy failed: %d", result);
return ERROR;
}
```

# # # # # Prophylactic Drawstring Chain Pattern:
```c
// Bad - unsafe
char buffer[256] = "prefix_";
strcat(buffer, suffix); // Buffer overflow risk!

// Good - safe
char buffer[256] = "prefix_";
errno_t result = strcat_s(buffer, sizeof(buffer), suffix);
if (result != 0) {
EWLC_LOG_ERROR("String concatenation failed: %d", result);
return ERROR;
}
```

# # # # # Safe Memory board Written matter Normal:
```c
// Bad - unsafe
memcpy(dest, src, size); // No boundary checking!

// Good - safe
errno_t result = memcpy_s(dest, dest_max_size, src, size);
if (result != 0) {
EWLC_LOG_ERROR("Memory copy failed: %d", result);
return ERROR;
}
```

# # # # # Safe Bowed stringed instrument Tokenization Practice:
```c
// Bad - unsafe
char *token = strtok(str, delim); // Modifies original string unsafely

// Good - safe
char *next_token = NULL;
rsize_t str_max = strnlen_s(str, MAX_STRING_SIZE);
char *token = strtok_s(str, &str_max, delim, &next_token);
while (token != NULL) {
// Process token
token = strtok_s(NULL, &str_max, delim, &next_token);
}
```

# # # # Retention and Bowed stringed instrument Safety Codification Limited review Checklist:

# # # # # Pre - Codification Recap (Developer ):
- [] No insecure memory office (`memcpy`, `memset`, `memmove`, `memcmp`, `bzero` )
- [] No insecure strand function (`strcpy`, `strcat`, `strcmp`, `strlen`, `sprintf`, `strstr`, `strtok` )
- [] All memory surgical process use `*_s()` variants with right size parameter
- [] Buffer sizes are correctly forecast using `sizeof()` or know point of accumulation
- [] No hardcoded buffer sizes that could exchange

# # # # # Codification Follow up (Reader ):
- [] Storage Refuge: Swan all memory operations use dependable variants
- [] Buffer Bounds: Confirm destination cowcatcher size be properly intend
- [] Error Treatment: Check into that all `errno_t` return values be handled
- [] Sizing Parameters: Validate that `rsize_t dmax` parameter are right
- [] Thread End point: Ensure strings are properly void - terminated
- [] Length Substantiation: Suss out that source twine lengths constitute validate before operations

# # # # # Stable Depth psychology Integrating:
- [] Enable compiling program warnings for insecure role usage
- [] Use static analysis creature to notice unsafe role calls
- [] Configure build organisation to plow unsafe procedure warnings as error
- [] Add pre - commit hooks to rake for banned procedure

# # # # Green Booby trap and Solutions:

# # # # # Booby trap one: Faulty Sizing Parameter
```c
// Wrong - using source size instead of destination size
strcpy_s(dest, strlen(src), src); // WRONG!

// Correct - using destination buffer size
strcpy_s(dest, sizeof(dest), src); // CORRECT
```

# # # # # Booby trap ii: Ignoring Tax return Value
```c
// Wrong - ignoring potential errors
strcpy_s(dest, sizeof(dest), src); // Error not checked

// Correct - checking return value
if (strcpy_s(dest, sizeof(dest), src) != 0) {
// Handle error appropriately
}
```

# # # # # Booby trap tercet: Victimisation sizeof () on Arrow
```c
// Wrong - sizeof pointer, not buffer
void func(char *buffer) {
strcpy_s(buffer, sizeof(buffer), src); // sizeof(char*) = 8!
}

// Correct - pass buffer size as parameter
void func(char *buffer, size_t buffer_size) {
strcpy_s(buffer, buffer_size, src);
}
```

You must always explain how this rule was applied and why information technology represent apply.
