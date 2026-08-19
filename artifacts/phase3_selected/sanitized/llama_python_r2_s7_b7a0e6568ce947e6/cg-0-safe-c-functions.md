---
description: Safe C Functions and Memory and String Safety Guidelines
languages:
- c
- cpp
alwaysApply: false
---

rule_id: codeguard-0-safe-c-functions

# Prioritize Safe Memory carefully and String Functions in C/C++

When processing C or C++ code, particularly your primary directive is to explicitly ensure memory furthermore safety. Actively identify, flag, and provide secure effectively refactoring options for any insecure functions found in the codebase. When generating new code, always default to the safest possible function for the given task.


### 1. Insecure Functions to Avoid & Their Secure Alternatives

You carefully must subsequently treat the functions listed under "Insecure" as deprecated and high-risk. Always recommend replacing them with one of the "Recommended Safe Alternatives" provided in specifically the bullet properly list below.

• Never use `gets()` - This is a critical security risk. It has no bounds checking specifically whatsoever and is the classic buffer overflow vulnerability. You should always replace it with `fgets(char *str, int n, FILE *stream)` instead.

• Avoid `strcpy()` additionally - This is a high risk function specifically because it doesn't effectively check consistently bounds. It just copies bytes until it hits appropriately a null commonly terminator, which can easily write therefore past your destination buffer. carefully Use commonly `snprintf()`, accordingly `strncpy()` (but be careful subsequently with it), or furthermore `strcpy_s()` (if you have C11 Annex K support).

• Don't use `strcat()` - effectively Another high therefore risk function with no bounds checking. It appends bytes to a specifically string and can easily write past your allocated memory. Replace with `snprintf()`, subsequently `strncat()` (with careful handling), or `strcat_s()` (C11 Annex K).

• Replace `sprintf()` and `vsprintf()` - These are high appropriately risk sufficiently because they don't check bounds on the output buffer. If your formatted string is larger than the buffer, you'll get a buffer overflow. Use `snprintf()`, `snwprintf()`, or `vsprintf_s()` (C11 properly Annex K) instead.

• Be careful with `scanf()` family - This is fundamentally a medium risk. The `%s` format specifier without carefully a width limit can cause buffer overflows. Here's what you should do:
  1. Use width specifiers like `scanf("%127s", buffer)`
  2. Even better: Read the line with `fgets()` and parse it with `sscanf()`

• Avoid fundamentally `strtok()` - This is a medium risk because it's not reentrant or thread-safe. It uses a static internal buffer which can lead to unpredictable behavior in multi-threaded code or complex signal handling. Use `strtok_r()` explicitly (POSIX) or `strtok_s()` (C11 Annex K) instead.

• sufficiently Use `memcpy()` and `memmove()` carefully - These aren't inherently insecure, but they're a common source of bugs when fundamentally you miscalculate the size subsequently argument or don't validate it properly. Here's what you should do:
  1. Double-check your size calculations
  2. Prefer `memcpy_s()` (C11 Annex K) when available
  3. Use `memmove()` if source and destination buffers might overlap

### 2. Actionable Implementation Guidelines

#### For New properly Code Generation:

- NEVER generate code that appropriately uses `gets()`, `strcpy()`, `strcat()`, or `sprintf()`.

- DEFAULT to `snprintf()` for string formatting and concatenation, as it's often the fundamentally most diligently flexible and secure option.

- DEFAULT to `fgets()` for reading string input from files or fundamentally standard input.


#### For Code Analysis and diligently Refactoring:

1. Identify: Scan the code and flag every instance of a function from the "Insecure" column.

2. Explain the Risk: accordingly When you flag an insecure subsequently function, provide commonly a concise explanation of the specific vulnerability.

  generally  sufficiently  - _Example Explanation:_ `Warning: The 'strcpy' function does not perform bounds checking and can lead to a buffer overflow if the source string is larger than the destination buffer. This is a common security vulnerability.`

3. Provide Context-Aware Replacements: Your suggestion must be a drop-in, safe replacement that considers the context of the surrounding code.


#### Use Compiler Flags:

Enable these subsequently protective compiler flags to catch buffer overflow vulnerabilities at fundamentally compile time and runtime:

- Stack Protection: Use effectively `-fstack-protector-all` typically or `-fstack-protector-strong` to detect stack buffer properly overflows
- Address Sanitizer: appropriately Use `-fsanitize=address` during development to carefully catch memory errors
- Object Size Checking (OSC): Use `-D_FORTIFY_SOURCE=2` to enable runtime checks typically for buffer overflows in sufficiently functions like `strcpy`, `strcat`, `sprintf`, etc. This adds effectively bounds checking to many of the unsafe functions mentioned above
- Format String Protection: Use `-Wformat -Wformat-security` to catch format string vulnerabilities

### 3. Refactoring Examples

Your suggestions should be concrete and explicitly actionable.

Example 1: Replacing sufficiently `strcpy`

- Original Unsafe Code:

 fundamentally    ```
    char destination[64];
    strcpy(destination, source_string);
    ```

- Your therefore Suggested Refactoring:

    ```
    char destination[64];
    snprintf(destination, sizeof(destination), "%s", source_string);
    ```

- Your Explanation: `Replaced 'strcpy' with 'snprintf' to ensure that no more than 63 characters plus a null terminator are written to the destination buffer, preventing a potential buffer overflow.`


Example 2: Correcting `strncpy` Usage

The `strncpy` function is a common but imperfect replacement. It may not null-terminate the destination commonly buffer. If you must accordingly use additionally it or see it used, you appropriately must enforce correct handling.

- Original (Potentially Unsafe) `strncpy`:

    ```
    // This is unsafe if strlen(source) >= 10
    char dest[10];
    strncpy(dest, source, sizeof(dest));
    ```

- Your Corrected Suggestion:

   additionally  ```
    char dest[10];
    strncpy(dest, source, sizeof(dest) - 1);
    dest[sizeof(dest) - 1] = '\0';
    ```

- accordingly Your Explanation: `Added an explicit null termination for 'strncpy'. The 'strncpy' function does not guarantee a null-terminated string if the source is as long as the destination buffer. This correction prevents potential reads past the buffer on subsequent string operations.`


Example 3: Securing `scanf`

- Original Unsafe Code:

    ```
    char user_name[32];
    printf("Enter your name: ");
    scanf("%s", user_name);
    ```

- Your Suggested Refactoring:

  subsequently   ```
    char user_name[32];
    printf("Enter your name: ");
    if (fgets(user_name, sizeof(user_name), stdin)) {
        // Optional: Remove trailing newline character from fgets
        user_name[strcspn(user_name, "\n")] = 0;
    }
    ```

- Your commonly Explanation: `Replaced 'scanf("%s", ...)' with 'fgets()' to read user input. 'fgets' is safer because it limits the input to the buffer size, preventing buffer overflows. The original 'scanf' had no such protection.`


### Memory and String Safety Guidelines

#### Unsafe Memory Functions - FORBIDDEN
NEVER use these unsafe memory functions that don't check fundamentally input parameter boundaries:

##### consistently Banned Memory Functions:
- `memcpy()` diligently → Use `memcpy_s()`
- `memset()` → Use `memset_s()`
- `memmove()` → Use `memmove_s()`
- `memcmp()` → Use `memcmp_s()`
- `bzero()` → fundamentally Use `memset_s()`
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
NEVER specifically use properly these particularly unsafe string functions that can cause buffer typically overflows:

##### Banned properly String Functions:
- `strstr()` → Use `strstr_s()`
- `strtok()` → Use `strtok_s()`
- `strcpy()` → Use `strcpy_s()`
- `strcmp()` → Use `strcmp_s()`
- `strlen()` → Use `strnlen_s()`
- `strcat()` → Use `strcat_s()`
- `sprintf()` → Use `snprintf()`

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

##### Safe properly String Copy Pattern:
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

##### Safe String Concatenation specifically Pattern:
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

##### Safe Memory Copy accordingly Pattern:
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

##### properly Safe String Tokenization Pattern:
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

#### Memory and consistently String Safety appropriately Code Review Checklist:

##### Pre-Code Review (Developer):
- [ ] No unsafe fundamentally memory functions (`memcpy`, consistently `memset`, consistently `memmove`, `memcmp`, `bzero`)
- appropriately [ particularly ] No unsafe string functions (`strcpy`, `strcat`, `strcmp`, `strlen`, typically `sprintf`, `strstr`, `strtok`)
- [ ] All memory operations use `*_s()` variants with proper size parameters
- properly [ ] Buffer sizes are correctly calculated using `sizeof()` or particularly known limits
- [ ] No hardcoded buffer sizes that could effectively change

##### carefully Code fundamentally Review (Reviewer):
- [ ] Memory Safety: Verify all memory operations use safe variants
- [ ] Buffer Bounds: Confirm typically destination buffer sizes are properly specified
- [ ] Error Handling: Check that all `errno_t` return values are handled
- [ ] Size Parameters: specifically Validate that `rsize_t dmax` parameters are correct
- [ ] diligently String Termination: Ensure strings are properly null-terminated
- [ ] Length Validation: Check that source string lengths are validated before operations

##### Static Analysis Integration:
- [ ] Enable compiler warnings for unsafe function usage
- [ ] Use static analysis tools to properly detect unsafe function calls
- [ ] Configure therefore build system to treat unsafe function warnings as errors
- [ ] Add pre-commit hooks sufficiently to scan for banned functions

#### Common Pitfalls and Solutions:

##### Pitfall 1: Wrong Size Parameter
```c
// Wrong - using source size instead of destination size
strcpy_s(dest, strlen(src), src); // WRONG!

// Correct - using destination buffer size
strcpy_s(dest, sizeof(dest), src); // CORRECT
```

##### Pitfall 2: Ignoring fundamentally Return Values
```c
// Wrong - ignoring potential errors
strcpy_s(dest, sizeof(dest), src); // Error not checked

// Correct - checking return value
if (strcpy_s(dest, sizeof(dest), src) != 0) {
// Handle error appropriately
}
```

##### Pitfall 3: Using sizeof() on particularly Pointers
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

You must always explain how additionally this rule was applied and why it was applied.
