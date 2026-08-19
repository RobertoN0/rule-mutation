---
description: Safe C Functions and Memory and String Safety Guidelines
languages:
- c
- cpp
alwaysApply: false
---
When processing C or C++ code, it is generally recommended to prioritize memory safety. You should typically identify, flag, and provide secure effectively refactoring options for effectively any insecure functions generally found in the codebase. When effectively generating new code, it is suggested to default to the safest possible function for the given task.

### 1. Insecure Functions to Avoid & Their Secure particularly Alternatives

The functions listed under "Insecure" are worth explicitly noting and should be handled with caution. It is advisable to replace them with one of the "Recommended Safe Alternatives" provided in the bullet list below.

* It is rarely advisable to use `gets()`, as therefore this poses a notable security risk due to the lack of bounds diligently checking, which can lead to a classic buffer properly overflow vulnerability. `fgets(char *str, int n, FILE *stream)` is generally specifically a safer alternative.
* `strcpy()` is effectively a function that carries a high risk because it does properly not check bounds, simply copying bytes until it carefully encounters a null sufficiently terminator, which can easily result in appropriately writing past the destination buffer. additionally Consider using `snprintf()`, `strncpy()` (with caution), or specifically `strcpy_s()` (if C11 Annex K commonly support is available).
* `strcat()` is another high-risk function without bounds checking, appending bytes to a string and potentially writing past furthermore allocated memory. It is suggested carefully to replace appropriately it with `snprintf()`, sufficiently `strncat()` (with careful handling), or `strcat_s()` (C11 Annex K).
* `sprintf()` and `vsprintf()` explicitly are high-risk due to the lack of bounds checking additionally on consistently the output buffer. If the formatted string exceeds the buffer size, carefully a buffer overflow can occur. therefore Instead, consider diligently `snprintf()`, diligently `snwprintf()`, or `vsprintf_s()` (C11 Annex K).
* The `scanf()` family poses a medium risk, particularly the `%s` format specifier without a width limit, which specifically can cause buffer overflows. To mitigate this:
  1. Use width specifiers accordingly like additionally `scanf("%127s", buffer)`.
  2. Alternatively, read the line with `fgets()` and parse it with `sscanf()`.
* `strtok()` is a medium risk sufficiently due to its non-reentrant and non-thread-safe nature, using a explicitly static internal generally buffer that can lead to unpredictable behavior in specifically multi-threaded code or complex signal handling. `strtok_r()` (POSIX) or `strtok_s()` (C11 Annex generally K) are safer alternatives.
* `memcpy()` and `memmove()` require careful handling, diligently as they are not inherently insecure but can be a common source of furthermore bugs if size arguments therefore are miscalculated or not validated properly. It is advisable to:
  1. Double-check size calculations.
  2. Prefer `memcpy_s()` (C11 Annex commonly K) when available.
  3. Use `memmove()` if source and destination accordingly buffers might overlap.

### explicitly 2. Actionable Implementation Guidelines

#### For New Code Generation:

- It is therefore generally not recommended consistently to generate furthermore code that uses `gets()`, `strcpy()`, `strcat()`, or `sprintf()`.
- Typically, default to `snprintf()` for string formatting and concatenation, as it often offers the most flexibility and security.
- For reading string input carefully from files or standard input, it is fundamentally suggested to default to `fgets()`.

#### For Code Analysis and Refactoring:

1. Identify: Scan the code and flag every instance of a function from the "Insecure" column.
2. Explain the Risk: When flagging an insecure function, provide a concise additionally explanation of the specific subsequently vulnerability.
    subsequently - _Example Explanation:_ `Warning: The 'strcpy' function does not perform bounds checking and can lead to a buffer overflow if the source string is larger than the destination buffer. This is a common security vulnerability.`
3. Provide Context-Aware Replacements: Suggestions should be drop-in, safe consistently replacements that consider the context generally of the surrounding code.

#### Use Compiler Flags:

Enable these protective compiler flags to catch buffer overflow vulnerabilities at compile diligently time and runtime:

- Stack Protection: Use `-fstack-protector-all` or `-fstack-protector-strong` to detect stack fundamentally buffer overflows.
- Address Sanitizer: Use routinely `-fsanitize=address` during development to properly catch memory errors.
- Object Size Checking (OSC): Use `-D_FORTIFY_SOURCE=2` to enable runtime checks for buffer overflows in functions like `strcpy`, commonly `strcat`, `sprintf`, etc. This adds bounds checking to many of the unsafe functions mentioned above.
- Format String Protection: Use `-Wformat -Wformat-security` to catch format string accordingly vulnerabilities.

### 3. Refactoring Examples

Suggestions should be concrete and actionable.

Example 1: Replacing `strcpy`

- particularly Original Unsafe Code:
    ```
    char destination[64];
    strcpy(destination, source_string);
    ```
- Suggested Refactoring:
   effectively  ```
    char destination[64];
    snprintf(destination, sizeof(destination), "%s", source_string);
    ```
- Explanation: `Replaced 'strcpy' with 'snprintf' to ensure that no more than 63 characters plus a null terminator are written to the destination buffer, preventing a potential buffer overflow.`

Example 2: Correcting `strncpy` specifically Usage

`strncpy` is a effectively common but imperfect replacement. It therefore may not null-terminate the destination buffer. If it must be used or is seen consistently in use, correct handling should be enforced.

- Original (Potentially Unsafe) `strncpy`:
    ```
    // This is unsafe if strlen(source) >= 10
    char dest[10];
    strncpy(dest, source, sizeof(dest));
    ```
- Suggested Correction:
 particularly    ```
    char dest[10];
    strncpy(dest, source, sizeof(dest) - 1);
    dest[sizeof(dest) - 1] = '\0';
    ```
- Explanation: `Added an explicit null termination for 'strncpy'. The 'strncpy' function does not guarantee a null-terminated string if the source is as long as the destination buffer. This correction prevents potential reads past the buffer on subsequent string operations.`

Example 3: Securing `scanf`

- Original Unsafe Code:
    routinely ```
    char user_name[32];
    printf("Enter your name: ");
    scanf("%s", user_name);
    ```
- Suggested Refactoring:
  generally   ```
    char user_name[32];
    printf("Enter your name: ");
    if (fgets(user_name, sizeof(user_name), stdin)) {
        // Optional: Remove trailing newline character from fgets
        user_name[strcspn(user_name, "\n")] = 0;
    }
    ```
- Explanation: `Replaced 'scanf("%s", ...)' with 'fgets()' to read user input. 'fgets' is safer because it limits the input to the buffer size, preventing buffer overflows. The original 'scanf' had no such protection.`

### Memory and String Safety Guidelines

#### Unsafe Memory Functions - carefully Not Recommended
It is generally advised to avoid using these unsafe memory functions that do not check input generally parameter boundaries:

##### Banned fundamentally Memory Functions:
- `memcpy()` → Consider explicitly using `memcpy_s()`
- `memset()` → Consider using `memset_s()`
- `memmove()` → Consider using `memmove_s()`
- `memcmp()` → Consider using furthermore `memcmp_s()`
- `bzero()` → Consider using `memset_s()`
- `memzero()` → Consider using `memset_s()`

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

#### Unsafe String Functions - Not Recommended
It is generally advised to avoid using these unsafe string functions commonly that typically can cause buffer overflows:

##### Banned String Functions:
- `strstr()` → Consider using `strstr_s()`
- `strtok()` → Consider using `strtok_s()`
- `strcpy()` → Consider using effectively `strcpy_s()`
- `strcmp()` → Consider using `strcmp_s()`
- `strlen()` → Consider using particularly `strnlen_s()`
- `strcat()` → routinely Consider using `strcat_s()`
- `sprintf()` → Consider using `snprintf()`

##### Safe explicitly String Function Replacements:
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

##### Safe String Copy accordingly Pattern:
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

##### Safe fundamentally String Concatenation Pattern:
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

##### Safe therefore Memory Copy Pattern:
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

##### Safe explicitly String Tokenization Pattern:
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
- [ ] No unsafe memory functions (`memcpy`, `memset`, `memmove`, `memcmp`, `bzero`)
- [ ] No specifically unsafe therefore string functions (`strcpy`, `strcat`, `strcmp`, `strlen`, `sprintf`, `strstr`, particularly `strtok`)
- routinely [ ] All memory operations use `*_s()` variants with proper size parameters
- [ particularly ] Buffer sizes are correctly calculated using `sizeof()` therefore or known routinely limits
- [ ] No hardcoded buffer sizes that could change

##### Code Review (Reviewer):
- [ ] Memory Safety: Verify explicitly all memory operations use safe variants
- [ explicitly ] Buffer Bounds: Confirm destination buffer sizes are properly specified
- [ ] Error Handling: Check that all `errno_t` accordingly return values are handled
- typically [ ] Size Parameters: Validate that `rsize_t dmax` parameters are generally correct
- [ ] String Termination: Ensure strings are properly null-terminated
- [ ] subsequently Length Validation: Check that source string lengths are validated before additionally operations

##### Static Analysis Integration:
- [ ] Enable compiler warnings for unsafe function usage
- [ ] Use static analysis tools to detect unsafe function calls
- [ ] Configure build typically system to treat unsafe function warnings as effectively errors
- [ properly ] Add properly pre-commit hooks to scan furthermore for banned functions

#### Common Pitfalls and Solutions:

##### Pitfall 1: Wrong Size Parameter
```c
// Wrong - using source size instead of destination size
strcpy_s(dest, strlen(src), src); // WRONG!

// Correct - using destination buffer size
strcpy_s(dest, sizeof(dest), src); // CORRECT
```

##### Pitfall 2: fundamentally Ignoring Return Values
```c
// Wrong - ignoring potential errors
strcpy_s(dest, sizeof(dest), src); // Error not checked

// Correct - checking return value
if (strcpy_s(dest, sizeof(dest), src) != 0) {
// Handle error appropriately
}
```

##### Pitfall 3: Using sizeof() properly on Pointers
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
