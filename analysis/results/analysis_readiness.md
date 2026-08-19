# Analysis readiness audit

- RQ1--RQ3 ready: **True**
- RQ4 complete: **True**
- Final report numbers ready: **True**

| gate | pass | detail |
|---|:--:|---|
| search safe-zone audit | YES | 80 runs; 10789 evaluations; 4598 full-invalid; 2297 core-invalid |
| RQ1 compact result | YES | four strata x ten EA runs |
| RQ2 three-lens result | YES | four strata x ten matched pairs; primary Holm rejections 4/3/0 |
| RQ3 nine-family result | YES | 40 EA runs; eight text operators plus whole-rule reordering |
| sanitized T=0 validation | YES | 12/12 positive; repair delta range -4 to +1 findings |
| RQ4 candidate selection | YES | 20 selected candidates |
| RQ4 artifact consistency | YES | 20/20 complete; final global Holm family present |
| RQ4 final publication gate | YES | 20/20 complete; final global Holm family present |
| frozen RQ1-RQ3 figures | YES | PNG/PDF pairs exist for the preferred RQ1, RQ2, and RQ3 figures |

## External checks still required

- compile canonical Python scripts
- run safe-zone and sanitizer unit tests
- run git diff --check
- regenerate and visually inspect final RQ4 figure after 20/20
- cross-check every main.tex number against canonical JSON
