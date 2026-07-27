// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
/* nulltest_parity.js — proves nulltest.js and nulltest.py are the same instrument.
 *
 *   node nulltest_parity.js <battery.json> [...]
 *
 * Prints the JS report as compact JSON so a shell harness can diff it against
 * `python3 nulltest.py --json`. If these two ever disagree, the page and the CLI are
 * telling a reader different things about the same data, and the tool is worthless.
 */
var fs = require("fs"), path = require("path");
global.window = global;
require(path.join(__dirname, "nulltest.js"));

var files = process.argv.slice(2);
if (!files.length) { console.error("usage: node nulltest_parity.js <battery.json> ..."); process.exit(2); }

var out = {};
files.forEach(function (f) {
  var L = window.NullTest.loadItems(fs.readFileSync(f, "utf8"));
  var rep = window.NullTest.evaluate(L.items, L.keys, { nPerm: 600 });
  out[path.basename(f)] = { keys: L.keys, verdict: rep.verdict, headline: rep.headline,
                            worst_cell: rep.worst_cell, nulls: rep.nulls };
});

/* the two planted controls the PAGE offers as buttons. They are generated from the same
   random.Random(7) stream as nulltest.py --selftest, so they must agree item-for-item AND
   verdict-for-verdict, or the page's "must fire / must not fire" demo is a stage trick. */
var K = { text: "entity", label: "label", stratum: "category" };
[["planted-separable", window.NullTest.plantedSeparable()],
 ["planted-clean", window.NullTest.plantedClean()]].forEach(function (p) {
  var rep = window.NullTest.evaluate(p[1], K, { nPerm: 600 });
  out[p[0]] = { keys: K, verdict: rep.verdict, headline: rep.headline,
                worst_cell: rep.worst_cell, nulls: rep.nulls, items: p[1] };
});
console.log(JSON.stringify(out, null, 1));
