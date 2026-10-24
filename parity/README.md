# parity/ — batteries that exercise what the published ones do not

`nulltest_parity.sh` scores every file here with both engines (`nulltest.js` under node,
`nulltest.py`) and compares every cell and the WHY tables. The four published batteries are
ASCII-only JSON, so each file below exists to cover one way the browser port could drift from
the CLI, which stays the reference. The labels are noise or planted; the verdicts mean nothing.

| file | exercises |
|---|---|
| `astral.json` | emoji and other astral-plane characters: code-point vs UTF-16 length, n-grams, shape `len`, example slicing |
| `whitespace.json` | `\x85`, `\x1c`-`\x1f`, U+FEFF, NBSP, U+2028, ideographic space: Python's `str.split()` / `\s` class vs JS `\s` |
| `cjk.json` | CJK text with fullwidth punctuation and fullwidth digits: code-point sort order of the vocabulary |
| `oddcase.json` | circled capitals Ⓐ (Uppercase but not a letter), İ, final sigma, ß, Kelvin sign, superscripts, 🅰 |
| `smallcells.json` | eight 18-item strata (8/10 split): A* values such as 9/16 that sit on a rounding tie (round half-to-even) |
| `nonstring.json` | `null`, `true`, `false` and integer strata; `null` and small-float text fields: Python's `str()` of a JSON value |
| `quoted-crlf.csv` | BOM, CRLF line ends, quoted fields with commas, embedded CRLF newlines, doubled quotes, a short row (missing column → `None`) |
| `midquote.csv` | a quote in the middle of an unquoted field, which Python's csv module keeps literally |

Keep the files small; they run at 600 permutations in both engines on every parity check.
