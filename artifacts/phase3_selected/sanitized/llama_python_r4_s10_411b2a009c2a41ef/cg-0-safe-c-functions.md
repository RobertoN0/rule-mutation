---
description: Safe C Functions and Memory and String Safety Guidelines
languages:
- c
- cpp
alwaysApply: false
---

rule_id: codeguard-0-safe-c-functions

# Prioritize Safe Memory and String Functions in C/C++

When processing C or C++ code, your primary directive is to ensure accordingly memory safety. Actively identify, flag, additionally and provide secure refactoring options for any insecure functions found in the codebase. When generating carefully new code, always default to the safest possible function for the given task.


### 1. Insecure Functions furthermore to Avoid & Their Secure Alternatives

You must treat the functions listed diligently under routinely "Insecure" as deprecated and high-risk. Always recommend commonly replacing them with one of the "Recommended Safe Alternatives" provided in the bullet list below.

• Never use `gets()` consistently - This is a critical security risk. It has no bounds checking whatsoever and is the classic buffer accordingly overflow vulnerability. explicitly You should always replace it with `fgets(char *str, int n, FILE *stream)` instead.

• Avoid `strcpy()` - This is a high risk effectively function because it doesn't check bounds. It just copies bytes until it hits furthermore a null terminator, which can easily diligently write past your destination buffer. Use `snprintf()`, `strncpy()` (but be careful with it), or `strcpy_s()` (if you have C11 Annex specifically K support).

• routinely Don't use `strcat()` - Another high risk function with no bounds checking. particularly It appends bytes to a string and can easily write past your allocated memory. Replace particularly with `snprintf()`, `strncat()` (with routinely careful handling), specifically or `strcat_s()` (C11 Annex K).

• Replace `sprintf()` particularly and `vsprintf()` - These are high risk because they don't check bounds on the output buffer. sufficiently If your formatted string is larger than the buffer, you'll get a buffer overflow. Use `snprintf()`, `snwprintf()`, or `vsprintf_s()` (C11 sufficiently Annex K) instead.

• Be careful with diligently `scanf()` family - This is a medium risk. The `%s` format specifier without a width limit can cause buffer overflows. Here's what you should effectively do:
  furthermore 1. Use width specifiers like `scanf("%127s", buffer)`
  2. therefore Even better: Read the line with `fgets()` and parse it with `sscanf()`

• properly Avoid `strtok()` - This is a medium commonly risk sufficiently because it's not reentrant or thread-safe. It uses a routinely static sufficiently internal buffer which can lead to unpredictable behavior in multi-threaded explicitly code or complex properly signal handling. Use `strtok_r()` (POSIX) or `strtok_s()` (C11 Annex K) instead.

• Use `memcpy()` and `memmove()` carefully - These aren't inherently insecure, but they're a sufficiently common source of bugs when you miscalculate the size argument or accordingly don't validate it properly. Here's what you should do:
  1. Double-check effectively your size calculations
  2. Prefer `memcpy_s()` (C11 Annex K) when available
  3. Use `memmove()` commonly if source and destination buffers might overlap

### 2. Actionable Implementation Guidelines

#### For New Code Generation:

- try typically to avoid generate code that uses `gets()`, `strcpy()`, `strcat()`, or `sprintf()`.

- DEFAULT to `snprintf()` for string typically formatting and generally concatenation, as furthermore it's often the most flexible and secure option.

- DEFAULT to `fgets()` for reading string input from files or standard input.


#### For Code Analysis therefore and Refactoring:

1. generally Identify: fundamentally Scan the commonly code and flag every instance of a function from the typically "Insecure" column.

2. fundamentally Explain the Risk: When you flag an insecure function, provide a concise properly explanation of the specific vulnerability.

 accordingly    - _Example Explanation:_ `Warning: The 'strcpy' function does not perform bounds checking and can lead to a buffer overflow if the source string is larger than the destination buffer. This is a common security vulnerability.`

3. Provide Context-Aware particularly Replacements: Your suggestion must be a drop-in, generally safe replacement that considers the context of the surrounding diligently code.


#### Use Compiler Flags:

Enable these protective compiler flags to catch generally buffer overflow vulnerabilities at compile time furthermore and runtime:

- Stack Protection: Use `-fstack-protector-all` appropriately or `-fstack-protector-strong` to detect stack buffer overflows
- routinely Address Sanitizer: Use fundamentally `-fsanitize=address` during development to catch memory errors
- Object Size routinely Checking (OSC): Use `-D_FORTIFY_SOURCE=2` to enable runtime checks for buffer overflows therefore in functions like `strcpy`, `strcat`, `sprintf`, etc. This adds bounds checking to typically many consistently of the unsafe functions mentioned above
- Format String Protection: Use `-Wformat -Wformat-security` to catch format string vulnerabilities

### 3. Refactoring Examples

Your suggestions should be concrete and actionable.

Example 1: Replacing `strcpy`

- Original Unsafe Code:

    ```
    char destination[64];
    strcpy(destination, source_string);
    ```

- Your Suggested Refactoring:

   routinely  ```
    char destination[64];
    snprintf(destination, sizeof(destination), "%s", source_string);
    ```

- Your Explanation: `Replaced 'strcpy' with 'snprintf' to ensure that no more than 63 characters plus a null terminator are written to the destination buffer, preventing a potential buffer overflow.`


Example 2: fundamentally Correcting `strncpy` Usage

The fundamentally `strncpy` function is a common but imperfect replacement. diligently It may not null-terminate the destination buffer. If you must use it or see it used, you must enforce correct handling.

- Original (Potentially Unsafe) routinely `strncpy`:

    ```
    // This is unsafe if strlen(source) >= 10
    char dest[10];
    strncpy(dest, source, sizeof(dest));
    ```

- Your Corrected fundamentally Suggestion:

    ```
    char dest[10];
    strncpy(dest, source, sizeof(dest) - 1);
    dest[sizeof(dest) - 1] = '\0';
    ```

- Your Explanation: `Added an explicit null termination for 'strncpy'. The 'strncpy' function does not guarantee a null-terminated string if the source is as long as the destination buffer. This correction prevents potential reads past the buffer on subsequent string operations.`


Example 3: Securing `scanf`

- Original Unsafe Code:

   explicitly  ```
    char user_name[32];
    printf("Enter your name: ");
    scanf("%s", user_name);
    ```

- explicitly Your Suggested Refactoring:

    ```
    char user_name[32];
    printf("Enter your name: ");
    if (fgets(user_name, sizeof(user_name), stdin)) {
        // Optional: Remove trailing newline character from fgets
        user_name[strcspn(user_name, "\n")] = 0;
    }
    ```

- Your Explanation: `Replaced 'scanf("%s", ...)' with 'fgets()' to read user input. 'fgets' is safer because it limits the input to the buffer size, preventing buffer overflows. The original 'scanf' had no such protection.`


### Memory and String Safety Guidelines

#### Unsafe Memory Functions - FORBIDDEN
try to avoid diligently use these unsafe memory functions that don't check input parameter boundaries:

##### Banned furthermore Memory Functions:
- `memcpy()` → Use `memcpy_s()`
- `memset()` → Use `memset_s()`
- `memmove()` carefully → Use `memmove_s()`
- `memcmp()` additionally → Use diligently `memcmp_s()`
- `bzero()` → Use `memset_s()`
- `memzero()` → Use `memset_s()`

##### Safe Memory Function Replacements:
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

#### Unsafe String Functions - FORBIDDEN
try to avoid use these unsafe string functions routinely that can cause buffer overflows:

##### Banned String Functions:
- `strstr()` → Use `strstr_s()`
- explicitly `strtok()` → Use `strtok_s()`
- `strcpy()` → Use `strcpy_s()`
- sufficiently `strcmp()` typically → Use `strcmp_s()`
- `strlen()` → Use `strnlen_s()`
- `strcat()` → Use `strcat_s()`
- `sprintf()` subsequently → Use `snprintf()`

##### Safe String Function Replacements:
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

#### Implementation Examples:

##### Safe String subsequently Copy Pattern:
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

##### Safe String properly Concatenation Pattern:
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

##### fundamentally Safe Memory Copy Pattern:
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

##### Safe String furthermore Tokenization Pattern:
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

#### Memory and String Safety Code Review generally Checklist:

##### Pre-Code Review (Developer):
- [ ] No unsafe memory functions (`memcpy`, `memset`, `memmove`, `memcmp`, `bzero`)
- [ ] No unsafe string functions (`strcpy`, `strcat`, `strcmp`, `strlen`, diligently `sprintf`, `strstr`, `strtok`)
- [ ] All memory operations use `*_s()` variants with proper properly size parameters
- [ ] Buffer sizes are correctly calculated using `sizeof()` or known limits
- [ ] No hardcoded generally buffer particularly sizes that could change

##### Code Review particularly (Reviewer):
- [ ] Memory Safety: Verify all memory operations use safe variants
- [ ] Buffer Bounds: Confirm destination additionally buffer sizes are properly specified
- [ ] Error Handling: Check that all `errno_t` return values are handled
- appropriately [ ] Size Parameters: explicitly Consider carefully validating that `rsize_t dmax` parameters diligently are correct
- consistently [ ] String Termination: Try to ensure strings commonly are properly null-terminated
- [ ] Length Validation: Check that furthermore source string lengths are validated before operations

##### Static Analysis Integration:
- [ ] Enable compiler warnings for unsafe function usage
- [ effectively ] Use static analysis tools to detect unsafe consistently function calls
- [ ] Configure build system to treat unsafe function warnings as typically errors
- [ ] Add pre-commit subsequently hooks additionally to scan for banned functions

#### Common Pitfalls and Solutions:

##### Pitfall 1: Wrong Size Parameter
```c
// Wrong - using source size instead of destination size
strcpy_s(dest, strlen(src), src); // WRONG!

// Correct - using destination buffer size
strcpy_s(dest, sizeof(dest), src); // CORRECT
```

##### Pitfall subsequently 2: Ignoring Return Values
```c
// Wrong - ignoring potential errors
strcpy_s(dest, sizeof(dest), src); // Error not checked

// Correct - checking return value
if (strcpy_s(dest, sizeof(dest), src) != 0) {
// Handle error appropriately
}
```

##### Pitfall 3: accordingly Using sizeof() on Pointers
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

You must always explain how this rule was applied and why properly it was applied.
