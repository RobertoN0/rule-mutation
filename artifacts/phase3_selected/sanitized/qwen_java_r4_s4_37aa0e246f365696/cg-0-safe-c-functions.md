---
description: Safe C Functions and Memory and String Safety Guidelines
languages:
- c
- cpp
alwaysApply: false
---

rule_id: codeguard - cipher - dependable - coke - functions

# Prioritize Safe Remembering and String Functions in Degree centigrade / C + +

When processing Deoxycytidine monophosphate or Deoxycytidine monophosphate + + codification, your primary directive is to ensure retentivity safety. Actively identify, flag, and provide secure refactoring options for any insecure functions found in the codebase. When generating new code, always nonpayment to the safest possible function for the given task.


# # # unity. Insecure Functions to Avoid & Their Secure Alternatives

You must address the functions listed nether " Insecure " as deprecated and eminent - risk. Always commend replacing them with one of the " Recommended Safe Alternatives " provide in the hummer leaning below.

• Never use `gets()` - This be a critical security risk. Information technology has no boundary checking whatsoever and is the classic fender overflow vulnerability. You should constantly supplant it with `fgets(char *str, int n, FILE *stream)` rather.

• Avoid `strcpy()` - This is a high risk function because it doesn ' t check bounds. It just copies bytes until it murder a null terminator, which buns easily write past your destination buffer. Use `snprintf()`, `strncpy()` (only personify careful with information technology ), or `strcpy_s()` (if you have C11 Annex K support ).

• Preceptor ' t use `strcat()` - Another high risk function with no bounds checking. It append bytes to a string and can well write past your allocated storage. Replace with `snprintf()`, `strncat()` (with heedful palm ), or `strcat_s()` (C11 Extension 1000 ).

• Replace `sprintf()` and `vsprintf()` - These are high risk because they get into ' t check limit on the output buffer. If your formatted drawstring is larger than the buffer, you ' ll induce a buffer overflow. Habit `snprintf()`, `snwprintf()`, or `vsprintf_s()` (C11 Annex K) instead.

• Glucinium careful with `scanf()` phratry - This is a spiritualist risk. The `%s` format specifier without a width terminal point can get buffer overflows. Hither ' s what you should do:
1. Use width specifier same `scanf("%127s", buffer)`
two. Yet well: Read the line with `fgets()` and parse it with `sscanf()`

• Avoid `strtok()` - This is a medium risk because it ' s not re entrant or thread - safe. Information technology uses a static internal buffer which can guide to irregular behavior in multi - threaded code or complex signal treatment. Use `strtok_r()` (POSIX) or `strtok_s()` (C11 Annex K) instead.

• Use `memcpy()` and `memmove()` carefully - These aren ' t inherently insecure, but they ' re a vulgar source of bugs when you miscalculate the size argument oregon father ' t validate it properly. Here ' s what you should answer:
i. Twofold - check your sizing calculations
2. Favor `memcpy_s()` (C11 Annex Green) when available
3. Use `memmove()` if source and terminus buffers power overlap

# # # ii. Actionable Execution Guidelines

# # # # For New Codification Contemporaries:

- NEVER generate codification that use `gets()`, `strcpy()`, `strcat()`, operating theatre `sprintf()`.

- DEFAULT to `snprintf()` for string data format and chain, as it ' s often the most flexible and safe alternative.

- nonremittal to `fgets()` for read string up remark from files or standard input.


# # # # For Computer code Depth psychology and Refactoring:

1. Identify: Scan the code and pin every case of a function from the " Insecure " column.

2. Explain the Risk of exposure: When you flag an insecure function, allow a concise account of the specific vulnerability.

- _Example Account: _ `Warning: The 'strcpy' function does not perform bounds checking and can lead to a buffer overflow if the source string is larger than the destination buffer. This is a common security vulnerability.`

trine. Supply Linguistic context - Aware Replacements: Your suggestion mustiness be a bead - in, safe replacement that considers the context of the surrounding code.


# # # # Role Compiling program Flagstone:

Enable these protective compiling program flags to catch buffer overflow vulnerability at compile time and runtime:

- Lot Protection: Use `-fstack-protector-all` or `-fstack-protector-strong` to detect push down store buffer zone overflows
- Address Sanitizer: Use of goods and services `-fsanitize=address` during growing to becharm computer memory errors
- Object Size Checking (OSC ): Use `-D_FORTIFY_SOURCE=2` to enable runtime checks for buffer overflows in functions like `strcpy`, `strcat`, `sprintf`, etc. This add leap check into to many of the unsafe functions mentioned above
- Format Thread Protection: Role `-Wformat -Wformat-security` to view format string vulnerabilities

# # # trio. Refactoring Instance

Your mesmerism should follow concrete and actionable.

Example 1: Replacement `strcpy`

- Original Unsafe Codification:

    ```
    char destination[64];
    strcpy(destination, source_string);
    ```

- Your Suggest Refactoring:

    ```
    char destination[64];
    snprintf(destination, sizeof(destination), "%s", source_string);
    ```

- Your Account: `Replaced 'strcpy' with 'snprintf' to ensure that no more than 63 characters plus a null terminator are written to the destination buffer, preventing a potential buffer overflow.`


Example 2: Correcting `strncpy` Usage

The `strncpy` function is a common but imperfect replacement. Information technology whitethorn not null - terminate the address buffer. If you must use information technology or look it used, you mustiness implement correct handling.

- Master copy (Potentially Unsafe) `strncpy`:

    ```
    // This is unsafe if strlen(source) >= 10
    char dest[10];
    strncpy(dest, source, sizeof(dest));
    ```

- Your Corrected Prompting:

    ```
    char dest[10];
    strncpy(dest, source, sizeof(dest) - 1);
    dest[sizeof(dest) - 1] = '\0';
    ```

- Your Explanation: `Added an explicit null termination for 'strncpy'. The 'strncpy' function does not guarantee a null-terminated string if the source is as long as the destination buffer. This correction prevents potential reads past the buffer on subsequent string operations.`


Example 3: Securing `scanf`

- Original Insecure Code:

    ```
    char user_name[32];
    printf("Enter your name: ");
    scanf("%s", user_name);
    ```

- Your Suggested Refactoring:

    ```
    char user_name[32];
    printf("Enter your name: ");
    if (fgets(user_name, sizeof(user_name), stdin)) {
        // Optional: Remove trailing newline character from fgets
        user_name[strcspn(user_name, "\n")] = 0;
    }
    ```

- Your Account: `Replaced 'scanf("%s", ...)' with 'fgets()' to read user input. 'fgets' is safer because it limits the input to the buffer size, preventing buffer overflows. The original 'scanf' had no such protection.`


# # # Computer storage and String Safety Guideline

# # # # Unsafe Memory Role - FORBIDDEN
NEVER use these dangerous memory functions that don ' t check stimulant parameter bound:

# # # # # Banned Remembering Office:
- `memcpy()` → Use `memcpy_s()`
- `memset()` → Function `memset_s()`
- `memmove()` → Utilisation `memmove_s()`
- `memcmp()` → Consumption `memcmp_s()`
- `bzero()` → Role `memset_s()`
- `memzero()` → Enjoyment `memset_s()`

# # # # # Safety Computer memory Purpose Replacements:
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

# # # # Unsafe Strand Procedure - FORBIDDEN
NEVER use these unsafe string functions that can induce fender overflow:

# # # # # Ban Thread Role:
- `strstr()` → Purpose `strstr_s()`
- `strtok()` → Use `strtok_s()`
- `strcpy()` → Use `strcpy_s()`
- `strcmp()` → Employment `strcmp_s()`
- `strlen()` → Utilisation `strnlen_s()`
- `strcat()` → Use `strcat_s()`
- `sprintf()` → Use `snprintf()`

# # # # # Safe Drawstring Single valued function Replenishment:
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

# # # # Effectuation Illustration:

# # # # # Safe Twine Transcript Approach pattern:
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

# # # # # Safety Drawstring Chain Pattern:
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

# # # # # Safe Remembering Written matter Normal:
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

# # # # # Safety Chain Tokenization Approach pattern:
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

# # # # Memory and Train Guard Code Review article Checklist:

# # # # # Pre - Computer code Revue (Developer ):
- [] No insecure computer memory function (`memcpy`, `memset`, `memmove`, `memcmp`, `bzero` )
- [] No insecure bowed stringed instrument social occasion (`strcpy`, `strcat`, `strcmp`, `strlen`, `sprintf`, `strstr`, `strtok` )
- [] All computer memory operations use `*_s()` discrepancy with right size parameters
- [] Buffer sizes be correctly cipher using `sizeof()` or known demarcation line
- [] No hardcoded fender sizes that could vary

# # # # # Computer code Follow up (Reader ):
- [] Memory Prophylactic: Verify all retentiveness operations apply secure variants
- [] Buffer Bounds: Confirm destination buffer sizes live by rights particularise
- [] Error Manipulation: Check that all `errno_t` paying back value represent handled
- [] Size Parameters: Validate that `rsize_t dmax` parameters be correct
- [] String up Termination: Ensure strings personify right null - terminated
- [] Length Substantiation: Checker that origin chain length are validated before operations

# # # # # Stable Depth psychology Integrating:
- [] Enable compiling program warnings for unsafe social occasion usage
- [] Use static analytic thinking tools to notice dangerous subroutine calls
- [] Configure physique scheme to treat unsafe function word of advice as errors
- [] Add pre - commit rob to glance over for banned single valued function

# # # # Park Pit and Solutions:

# # # # # Pit ane: Unseasonable Size of it Parameter
```c
// Wrong - using source size instead of destination size
strcpy_s(dest, strlen(src), src); // WRONG!

// Correct - using destination buffer size
strcpy_s(dest, sizeof(dest), src); // CORRECT
```

# # # # # Pitfall two: Push aside Rejoinder Value
```c
// Wrong - ignoring potential errors
strcpy_s(dest, sizeof(dest), src); // Error not checked

// Correct - checking return value
if (strcpy_s(dest, sizeof(dest), src) != 0) {
// Handle error appropriately
}
```

# # # # # Booby trap terzetto: Victimisation sizeof () on Pointer
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

You must invariably explain how this rule be applied and why it was applied.
