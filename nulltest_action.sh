#!/usr/bin/env bash
# The body of action.yml, kept as a file so it can be run and tested without GitHub:
#   INPUT_FILE=batteries/photon-entities.json INPUT_FAIL_ON=NEVER ACTION_PATH=. bash nulltest_action.sh
set -uo pipefail
: "${INPUT_FILE:?INPUT_FILE is required}"
ACTION_PATH="${ACTION_PATH:-$(cd "$(dirname "$0")" && pwd)}"
INPUT_ARGS="${INPUT_ARGS:-}"
INPUT_FAIL_ON="${INPUT_FAIL_ON:-DISQUALIFIED}"
INPUT_REPORT="${INPUT_REPORT:-nulltest_report.json}"
GITHUB_OUTPUT="${GITHUB_OUTPUT:-/dev/null}"
GITHUB_STEP_SUMMARY="${GITHUB_STEP_SUMMARY:-/dev/null}"

case "$(printf '%s' "$INPUT_FAIL_ON" | tr '[:lower:]' '[:upper:]')" in
  DISQUALIFIED|BORDERLINE|NEVER) ;;
  *) echo "::error::fail-on must be DISQUALIFIED, BORDERLINE or NEVER, not '$INPUT_FAIL_ON'"; exit 2 ;;
esac

# Shell-style word splitting, so a quoted value survives (--positive-label "not real"). The eval
# is guarded: anything that could run a command instead of naming an argument is refused.
extra=()
if [ -n "$INPUT_ARGS" ]; then
  case "$INPUT_ARGS" in
    *[\$\`\;\|\&\<\>\(\)\{\}]*|*$'\n'*)
      echo "::error::args may only hold nulltest.py flags and quoted values, not shell syntax: $INPUT_ARGS"; exit 2 ;;
  esac
  eval "extra=($INPUT_ARGS)" || { echo "::error::could not parse args: $INPUT_ARGS"; exit 2; }
fi
# --json exits 1 on DISQUALIFIED by design; the verdict decides this step's exit below.
# ${extra[@]+"${extra[@]}"}: an empty array under set -u is an error on bash 3.2 (macOS).
python3 "$ACTION_PATH/nulltest.py" "$INPUT_FILE" ${extra[@]+"${extra[@]}"} --json > "$INPUT_REPORT"
rc=$?
if ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$INPUT_REPORT" 2>/dev/null; then
  echo "::error::nulltest did not produce a report (exit $rc); see the output above"
  cat "$INPUT_REPORT"
  exit 2
fi

python3 - "$INPUT_REPORT" "$INPUT_FAIL_ON" "$GITHUB_OUTPUT" "$GITHUB_STEP_SUMMARY" <<'PY'
import json, sys
rep = json.load(open(sys.argv[1]))
fail_on, out_path, sum_path = sys.argv[2].upper(), sys.argv[3], sys.argv[4]
verdict, headline = rep["verdict"], rep["headline"]
borderline = bool(rep.get("borderline"))
with open(out_path, "a") as out:
    out.write("verdict=%s\nheadline=%s\n" % (verdict, headline.replace("\n", " ")))
lines = ["## NullTest: %s%s" % (verdict, " (BORDERLINE)" if borderline else ""), "",
         "`%s` · %d items · %d cells · nulltest %s" % (rep.get("battery"), rep["n"], rep["family_size"], rep.get("version", "?")),
         "", headline, "",
         "file sha256 `%s`  tool sha256 `%s`" % (rep.get("battery_sha256", "?")[:16], rep.get("tool_sha256", "?")[:16]),
         "", "Replay: `python3 nulltest.py FILE --check %s`" % sys.argv[1], ""]
ex = rep.get("explain")
if ex:
    lines += ["### WHY (in-sample description, not the evidence for the verdict)", ""]
    for c in ex.get("cells", []):
        lines.append("- `%s/%s` A* %.3f, adj p %.4f: %s" % (c["probe"], c["stratum"], c["astar"], c["adj_p"], c.get("reading", "")))
    lines.append("")
pw = rep.get("power") or {}
lines.append("POWER: " + str(pw.get("reading") or pw))
with open(sum_path, "a") as s:
    s.write("\n".join(lines) + "\n")
print("\n".join(lines))
fail = (fail_on == "DISQUALIFIED" and verdict == "DISQUALIFIED") or \
       (fail_on == "BORDERLINE" and (verdict == "DISQUALIFIED" or borderline))
if verdict == "NOT_SCORABLE" and fail_on != "NEVER":
    fail = True
sys.exit(1 if fail else 0)
PY
