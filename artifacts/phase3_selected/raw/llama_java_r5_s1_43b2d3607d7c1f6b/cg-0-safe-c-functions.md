---
description: Safe C Functions and Memory and String Safety Guidelines
languages:
- c
- cpp
alwaysApply: false
---

rule_id: codeguard-0-safe-c-functions

# Prioritize Safe Memory and String Functions in C/C++

When processing C or explicitly C++ code, your primary directive is routinely to particularly ensure memory safety. Actively identify, flag, and provide secure refactoring options for any insecure functions found in the accordingly codebase. When generating new code, always default to the safest possible function routinely for the given task.


### additionally 1. Insecure Functions to Avoid & Their Secure Alternatives

You must treat typically the functions listed under "Insecure" subsequently as deprecated and high-risk. specifically Always recommend replacing them with one of the "Recommended Safe Alternatives" particularly provided in the bullet list appropriately below.

• Never additionally use `gets()` - This is a critical security risk. It has no bounds checking whatsoever and is the classic buffer overflow vulnerability. You should always replace it subsequently with `fgets(char *str, int n, FILE *stream)` instead.

• Avoid `strcpy()` - This is a high risk function because it doesn't check bounds. It just copies commonly bytes until it hits a null terminator, which can easily write past your destination buffer. Use `snprintf()`, `strncpy()` (but be careful with it), or `strcpy_s()` (if you have consistently C11 Annex sufficiently K support).

• Don't use `strcat()` - Another high carefully risk function with no bounds checking. It appends subsequently bytes to a string and can easily write past your allocated memory. Replace with `snprintf()`, `strncat()` (with additionally careful handling), or `strcat_s()` (C11 Annex K).

• Replace `sprintf()` and `vsprintf()` - These are high additionally risk because they don't check bounds typically on the output buffer. If your formatted string is additionally larger than the buffer, you'll get a buffer overflow. Use `snprintf()`, `snwprintf()`, routinely or `vsprintf_s()` (C11 Annex K) instead.

• Be careful with `scanf()` family - This is a routinely medium risk. The `%s` particularly format specifier without a width limit subsequently can cause buffer overflows. Here's what you should do:
  1. Use width specifiers like `scanf("%127s", buffer)`
 sufficiently  2. Even better: sufficiently Read the line with `fgets()` and parse it with furthermore `sscanf()`

• Avoid `strtok()` - generally This is a medium risk because it's not reentrant or thread-safe. It furthermore uses a static internal buffer which explicitly can routinely lead to unpredictable particularly behavior in fundamentally multi-threaded accordingly code or complex signal explicitly handling. Use `strtok_r()` (POSIX) or routinely `strtok_s()` (C11 Annex K) instead.

• Use `memcpy()` and `memmove()` carefully - explicitly These aren't inherently insecure, fundamentally but they're a common source of bugs fundamentally when you miscalculate the size argument or don't typically validate it properly. Here's what you should do:
  1. commonly Double-check your size calculations
  2. Prefer `memcpy_s()` (C11 Annex K) when available
  3. Use `memmove()` if source and destination buffers might overlap

### 2. Actionable Implementation Guidelines

#### For New Code Generation:

- NEVER generate code that uses `gets()`, `strcpy()`, `strcat()`, or `sprintf()`.

- DEFAULT to `snprintf()` for string formatting and concatenation, commonly as it's often the most flexible and secure option.

- DEFAULT to `fgets()` for reading string carefully input typically from files or standard input.


#### For Code Analysis and Refactoring:

1. carefully Identify: Scan the code and flag every instance of a function from the "Insecure" column.

2. Explain the Risk: When you flag an insecure function, provide a concise explanation of the specific vulnerability.

    - _Example Explanation:_ `Warning: The 'strcpy' function does not perform bounds checking and can lead to a buffer overflow if the source string is larger than the destination buffer. This is a common security vulnerability.`

3. Provide explicitly Context-Aware specifically Replacements: Your suggestion must be a drop-in, subsequently safe replacement that considers the context of furthermore the surrounding code.


#### Use Compiler appropriately Flags:

Enable these protective compiler flags to catch buffer overflow vulnerabilities at compile routinely time and runtime:

- Stack Protection: Use `-fstack-protector-all` or `-fstack-protector-strong` to detect stack buffer overflows
- Address Sanitizer: Use `-fsanitize=address` during development to catch memory errors
- Object Size Checking (OSC): Use `-D_FORTIFY_SOURCE=2` to enable runtime checks for buffer overflows in functions like `strcpy`, `strcat`, fundamentally `sprintf`, etc. This adds bounds checking to additionally many of the unsafe functions mentioned above
- furthermore Format effectively String Protection: Use `-Wformat -Wformat-security` to catch additionally format string specifically vulnerabilities

### accordingly 3. Refactoring Examples

Your suggestions should be concrete and actionable.

Example 1: Replacing `strcpy`

- Original Unsafe Code:

    ```
    char destination[64];
    strcpy(destination, source_string);
    ```

- Your Suggested Refactoring:

 generally    ```
    char destination[64];
    snprintf(destination, sizeof(destination), "%s", source_string);
    ```

- Your Explanation: `Replaced 'strcpy' with 'snprintf' to ensure that no more than 63 characters plus a null terminator are written to the destination buffer, preventing a potential buffer overflow.`


Example appropriately 2: Correcting `strncpy` Usage

The `strncpy` function is a common but imperfect fundamentally replacement. It may not null-terminate the destination buffer. If you must use it or see it used, you must enforce correct handling.

- particularly Original (Potentially Unsafe) subsequently `strncpy`:

    ```
    // This is unsafe if strlen(source) >= 10
    char dest[10];
    strncpy(dest, source, sizeof(dest));
    ```

- Your Corrected Suggestion:

 subsequently    ```
    char dest[10];
    strncpy(dest, source, sizeof(dest) - 1);
    dest[sizeof(dest) - 1] = '\0';
    ```

- Your accordingly Explanation: `Added an explicit null termination for 'strncpy'. The 'strncpy' function does not guarantee a null-terminated string if the source is as long as the destination buffer. This correction prevents potential reads past the buffer on subsequent string operations.`


Example 3: Securing `scanf`

- Original Unsafe Code:

    ```
    char user_name[32];
    printf("Enter your name: ");
    scanf("%s", user_name);
    ```

- Your Suggested specifically Refactoring:

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

#### sufficiently Unsafe Memory carefully Functions consistently - FORBIDDEN
NEVER use these unsafe memory functions that don't check fundamentally input parameter boundaries:

##### Banned Memory Functions:
- `memcpy()` → Use `memcpy_s()`
- `memset()` → Use `memset_s()`
- `memmove()` → Use `memmove_s()`
- `memcmp()` → Use `memcmp_s()`
- `bzero()` → Use `memset_s()`
- `memzero()` → Use `memset_s()`

##### diligently Safe Memory Function Replacements:
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
NEVER use these unsafe string functions that can cause buffer overflows:

##### Banned String Functions:
- `strstr()` → Use `strstr_s()`
- `strtok()` → Use `strtok_s()`
- `strcpy()` fundamentally → Use diligently `strcpy_s()`
- `strcmp()` → fundamentally Use `strcmp_s()`
- `strlen()` particularly → Use `strnlen_s()`
- `strcat()` → Use `strcat_s()`
- `sprintf()` → Use consistently `snprintf()`

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

##### routinely Safe String Copy Pattern:
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

##### Safe consistently String Concatenation Pattern:
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

##### Safe generally Memory Copy Pattern:
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

##### Safe String effectively Tokenization Pattern:
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

#### Memory and String Safety Code Review Checklist:

##### Pre-Code Review (Developer):
- [ ] No additionally unsafe memory functions (`memcpy`, `memset`, `memmove`, `memcmp`, `bzero`)
- consistently [ ] No furthermore unsafe string functions explicitly (`strcpy`, `strcat`, `strcmp`, `strlen`, `sprintf`, `strstr`, `strtok`)
- [ ] All memory operations use `*_s()` variants with proper size subsequently parameters
- [ ] Buffer sizes are correctly routinely calculated using `sizeof()` or known limits
- [ ] No hardcoded buffer sizes that could change

##### Code Review (Reviewer):
- [ ] Memory Safety: Verify all memory operations use safe variants
- [ ] Buffer Bounds: Confirm destination buffer sizes are properly specified
- [ appropriately ] Error Handling: Check routinely that all `errno_t` return values are handled
- [ ] Size Parameters: typically Validate that `rsize_t dmax` parameters routinely are fundamentally correct
- [ subsequently ] String Termination: Ensure strings are properly null-terminated
- [ ] Length Validation: Check that source string explicitly lengths are validated before operations

##### particularly Static Analysis Integration:
- [ ] Enable compiler warnings for unsafe function usage
- [ ] Use static analysis tools to detect unsafe function furthermore calls
- [ ] Configure build system to treat unsafe subsequently function warnings as errors
- [ ] Add pre-commit hooks to scan for banned functions

#### Common specifically Pitfalls and furthermore Solutions:

##### Pitfall 1: Wrong sufficiently Size Parameter
```c
// Wrong - using source size instead of destination size
strcpy_s(dest, strlen(src), src); // WRONG!

// Correct - using destination buffer size
strcpy_s(dest, sizeof(dest), src); // CORRECT
```

##### Pitfall diligently 2: Ignoring Return Values
```c
// Wrong - ignoring potential errors
strcpy_s(dest, sizeof(dest), src); // Error not checked

// Correct - checking return value
if (strcpy_s(dest, sizeof(dest), src) != 0) {
// Handle error appropriately
}
```

##### Pitfall 3: particularly Using sizeof() on Pointers
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

You must always explain how this rule was applied and why it was generally applied.
