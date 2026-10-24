// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
/* nulltest_ui.js — the null test as a control on the page, not a command to copy.
 *
 * Loads a battery (ours, a planted control, or the reader's own file), runs nulltest.js
 * in this tab, and renders the verdict. Nothing is uploaded: there is no endpoint that
 * accepts a battery, which is the point — a reader can grade OUR benchmark without
 * handing us THEIRS.
 *
 * The displayed rule mirrors the CLI exactly: show a cell when it separates after the
 * family-wise correction, or when it came close (adjusted p <= 0.25).
 */
(function () {
  "use strict";

  var PRESETS = {
    grounding: { url: "/verifier/batteries/grounding-coordinate.json",
                 label: "our grounding-coordinate battery",
                 note: "The battery under our published null-floor certificate — byte-identical to the file the cert hashes." },
    photon:    { url: "/verifier/batteries/photon-entities.json",
                 label: "our photon entity battery",
                 note: "The real/fabricated half of the benchmark battery we used for months." },
    front:     { url: "/verifier/batteries/verifydomain-claims-147.json",
                 label: "the battery behind our own headline",
                 note: "This led the honesty.tools home page for about four weeks, 2026-06-28 to 2026-07-25 (an earlier version of this note said \u201cfor months\u201d; corrected 2026-10-20): \u201con our 147-claim battery, Photon confirmed 0 of 36 fabricated entities.\u201d It lived on one machine, outside version control, never served and never floored. We floored it on 2026-07-25: all three scorable cells separate, lexicality A* 0.967. The number was withdrawn the same day. Run it yourself." },
    knowledge: { url: "/verifier/batteries/knowledge-prominence-v2.json",
                 label: "our knowledge battery — 296 items, five domains",
                 note: "Books, firms, paintings, places and people: high-pageview entities against low-pageview ones from the SAME Wikipedia category, matched on last-word initial and length. Built to replace the /calibrate battery, which separates on 16 of 18 cells (this note said 17 until 2026-10-20; nulltest prints 16). Passes at A* 0.689 on the bare names and 0.655 on the question text the model receives — both published, because quoting only the friendlier number is the defect this instrument exists to catch. v1 of this battery had a book stratum that was 64% fictional characters." },
    prominence:{ url: "/verifier/batteries/prominence-people-v2.json",
                 label: "our prominence battery",
                 note: "Both halves are real people. Each obscure counterpart is drawn from one of the famous person's own Wikipedia categories, and matched on surname initial and name length, so what varies inside the pair is mostly readership. The first battery of ours to clear this floor AND carry a label the model can be scored against." },
    prominence1:{ url: "/verifier/batteries/prominence-people-v1.json",
                 label: "prominence battery v1 — the version that fooled us",
                 note: "Under the four probes of v1.2 this PASSED at A* 0.602, adjusted p 0.22 — and was still broken: the surname's first letter recovers the labels at A* 0.661, because the builder measured the alphabetically-first 200 members of each Wikipedia category and biography categories are sorted by surname. v1.3 added two alphabet-position probes for that class of artifact and now DISQUALIFIES it. Superseded by v2. Kept here so the floor cannot be mistaken for a proof of correctness, and because the probe that caught it was written after the miss." },
    separable: { gen: "plantedSeparable",
                 label: "planted-separable control",
                 note: "Reals are ID-shaped, fakes are pronounceable words — the exact defect we shipped. A null test that cannot fire is decoration, so this one must come back DISQUALIFIED." },
    clean:     { gen: "plantedClean",
                 label: "planted-clean control",
                 note: "Identical surface forms, labels assigned at random. The tool must NOT flag this, or it flags everything." },
    paste:     { paste: true, label: "your battery", note: "" }
  };

  var FULL_PERM = 600, BIG_BATTERY = 1200, REDUCED_PERM = 200;
  var chips, pasteWrap, pasteBox, fileIn, runBtn, result, whatEl, current = "grounding";
  // A chosen file is kept HERE, not copied into the textarea: a 50 MB corpus pasted into a
  // <textarea> freezes the tab before a single permutation runs. Typing in the box discards it.
  var pastedName = null, fileText = null, pastePlaceholder = null;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function f3(x) { return (Math.round(x * 1000) / 1000).toFixed(3); }
  function f4(x) { return (Math.round(x * 10000) / 10000).toFixed(4); }

  function select(name) {
    current = name;
    chips.forEach(function (c) { c.setAttribute("aria-pressed", String(c.getAttribute("data-preset") === name)); });
    pasteWrap.hidden = !PRESETS[name].paste;
    result.innerHTML = "";
    whatEl.innerHTML = PRESETS[name].paste
      ? "read in this tab &middot; never uploaded"
      : "six surface probes &middot; stratified permutation null &middot; family-wise corrected";
  }

  function getItems() {
    var p = PRESETS[current];
    if (p.gen) {
      return Promise.resolve({ items: window.NullTest[p.gen](),
                               keys: { text: "entity", label: "label", stratum: "category" } });
    }
    if (p.paste) {
      var raw = fileText !== null ? fileText : pasteBox.value;
      if (!raw.trim()) return Promise.reject(new Error("paste a JSON array of items first, or choose a file"));
      return Promise.resolve(window.NullTest.loadItems(raw));
    }
    return fetch(p.url, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error("could not load the battery (http " + r.status + ")");
      return r.text();
    }).then(function (t) { return window.NullTest.loadItems(t); });
  }

  function renderError(msg) {
    result.innerHTML = '<pre class="ev-out ev-out--bad"><span class="ev-bad">could not run</span> — ' + esc(msg) + "</pre>";
  }

  // WHY — the same in-sample description the CLI prints under a DISQUALIFIED verdict: which
  // n-grams, words, length gap or initials carry each separating cell. For finding the artifact,
  // not evidence for the verdict; the verdict above it is held-out and permutation-calibrated.
  function renderWhy(rep, keys, items) {
    if (!items || !window.NullTest.explain) return "";
    var ex;
    try { ex = window.NullTest.explain(items, keys, rep); } catch (e) { return ""; }
    if (!ex.cells.length) return "";
    var html = '<p class="ev-note" style="margin-bottom:4px"><b>WHY</b> &middot; ' + esc(ex.note) + "</p>";
    ex.cells.forEach(function (c) {
      html += '<p class="ev-note" style="margin:4px 0"><code>' + esc(c.probe) + "/" + esc(c.stratum) + "</code> A* " +
        f3(c.astar) + ", adj p " + f4(c.adj_p) + " &mdash; " + esc(c.reading || "") + "</p>";
      if (c.favours_label1 || c.favours_label0) {
        // the CLI's _show_feature: padding spaces in a character n-gram are made visible as ␣,
        // or ' pa' and 'pa ' collapse to the same cell in HTML
        var show = function (g) { return c.probe === "lexicality" ? String(g).replace(/ /g, "\u2423") : g; };
        var tr = function (r) {
          return "<tr><td>" + esc(show(r.feature)) + '</td><td class="num">' + r.in_label1 + '</td><td class="num">' + r.in_label0 + "</td></tr>";
        };
        html += '<div class="nt-scroll"><table class="nt-table"><thead><tr><th>feature</th><th>in label-1</th><th>in label-0</th></tr></thead><tbody>' +
          (c.favours_label1 || []).slice(0, 5).map(tr).join("") + (c.favours_label0 || []).slice(0, 5).map(tr).join("") +
          "</tbody></table></div>";
      }
    });
    return html;
  }

  function render(rep, keys, label, items) {
    var bad = rep.verdict === "DISQUALIFIED";
    var rows = "";
    // Same display rule as the CLI: show a cell if it separates after correction, or if it
    // came close (adj p <= 0.25). A* alone is no longer the display trigger — a small cell can
    // hit A* 1.000 on noise, which is exactly the mistake the family-wise correction fixes.
    Object.keys(rep.nulls).forEach(function (nm) {
      var e = rep.nulls[nm];
      Object.keys(e.per_stratum)
        .sort(function (a, b) { return e.per_stratum[a].adj_p - e.per_stratum[b].adj_p; })
        .forEach(function (st) {
          var c = e.per_stratum[st];
          if (!c.separates && c.adj_p > 0.25) return;
          rows += '<tr class="' + (c.separates ? "sep" : "") + '">' +
            "<td>" + esc(nm) + "</td>" +
            "<td>" + esc(st) + (c.underpowered ? ' <span class="nt-clear">[underpowered]</span>' : "") + "</td>" +
            '<td class="num">' + c.n + "</td>" +
            '<td class="num">' + f3(c.astar) + "</td>" +
            '<td class="num">' + f4(c.raw_p) + "</td>" +
            '<td class="num">' + f4(c.adj_p) + "</td>" +
            '<td class="' + (c.separates ? "nt-flag" : "nt-clear") + '">' + (c.separates ? "SEPARATES" : "—") + "</td></tr>";
        });
    });
    if (!rows) {
      rows = '<tr><td colspan="7" class="nt-clear">no cell came close to significance after correction</td></tr>';
    }

    var note = PRESETS[current].note;
    // NOT_SCORABLE is neither a pass nor a fail and must not wear the PASS colour: nt-tag--na is
    // a neutral style (the site CSS needs that class; until it has one the tag falls back to the
    // plain .nt-tag look).
    var tagCls = bad ? "nt-tag--bad" : rep.verdict === "PASS" ? "nt-tag--ok" : "nt-tag--na";
    // The CLI prints POWER, the saturation NOTE and the BORDERLINE NOTE under every verdict; a
    // borderline PASS shown as a plain PASS would be the page saying less than the command does.
    var notes = "";
    if (rep.borderline && rep.borderline_note) notes += '<p class="ev-note" style="margin-top:0"><b>BORDERLINE</b> &middot; ' + esc(rep.borderline_note) + "</p>";
    if (rep.saturated && rep.saturation_note) notes += '<p class="ev-note" style="margin-top:0"><b>NOTE</b> &middot; ' + esc(rep.saturation_note) + "</p>";
    if (rep.power && rep.power.reading) notes += '<p class="ev-note" style="margin-top:0"><b>POWER</b> &middot; ' + esc(rep.power.reading) + "</p>";
    if (rep.n_perm_note) notes += '<p class="ev-note" style="margin-top:0"><b>PERMUTATIONS</b> &middot; ' + esc(rep.n_perm_note) + "</p>";
    result.innerHTML =
      '<div class="ev-panel" style="margin-top:18px;background:rgba(0,0,0,.24)">' +
        '<div class="nt-verdict">' +
          '<span class="nt-tag ' + tagCls + '">' + esc(rep.verdict) + "</span>" +
          '<span class="nt-head">' + esc(label) + " &middot; " + rep.n + " items (" +
            rep.n_real + " label-0 / " + rep.n_fake + " label-1)</span>" +
        "</div>" +
        '<p class="ev-note" style="margin-top:0">' + esc(rep.headline) + "</p>" + notes +
        '<div class="nt-scroll"><table class="nt-table">' +
          "<thead><tr><th>null</th><th>stratum</th><th>n</th><th>A*</th><th>raw p</th><th>adj p</th><th></th></tr></thead>" +
          "<tbody>" + rows + "</tbody></table></div>" +
        (bad ? renderWhy(rep, keys, items) : "") +
        '<p class="ev-note">Fields read: text=<code>' + esc(keys.text) + "</code>, label=<code>" + esc(keys.label) +
          "</code>, stratum=<code>" + esc(keys.stratum || "none") + "</code>. " +
          "A* is two-sided, so an inverted classifier still counts. Labels are shuffled <b>within each " +
          "stratum</b>, so every cell is compared against batteries with its own label rate, and every " +
          "permutation <b>refits</b> every scored null on the shuffled labels, so the null sees as much " +
          "fitting slack as the observation does; <b>adj p</b> is then corrected across all " + rep.family_size +
          " cells by Westfall&ndash;Young min-p, because " + rep.family_size +
          " tests against a 95th-percentile bar would otherwise produce a false fire per battery." +
          (note ? " " + esc(note) : "") + "</p>" +
      "</div>";
  }

  function run() {
    runBtn.disabled = true;
    result.innerHTML = '<pre class="ev-out">refitting the nulls under permutation, in this tab…</pre>';
    var label = PRESETS[current].label;

    // Promise.resolve().then(getItems), NOT getItems() — loadItems throws SYNCHRONOUSLY on bad
    // input, and a bare call lets that escape the chain entirely: the .catch never runs, the
    // panel stays stuck on "running…" and the button stays disabled forever. Caught by pasting
    // "not json at all" into the live page.
    Promise.resolve().then(getItems).then(function (L) {
      if (PRESETS[current].paste && pastedName) label = pastedName;
      // permutation cost is linear in items x cells; keep a big pasted battery from hanging the tab
      var nPerm = L.items.length > BIG_BATTERY ? REDUCED_PERM : FULL_PERM;
      // Run in slices rather than one blocking call. Each permutation now REFITS every fitted
      // nulls, so this is real work — seconds, not milliseconds. The permutation count is NOT
      // cut to hide that: cutting it would change the numbers and break parity with the CLI.
      // The work is made visible instead.
      return window.NullTest.evaluateAsync(L.items, L.keys, { nPerm: nPerm }, function (p) {
        var pct = Math.round(p.done / p.total * 100);
        result.innerHTML =
          '<pre class="ev-out">running the nulls in this tab — ' + pct + "%\n" +
          "  permutation " + p.done + " of " + p.total + "   " + esc(p.label) + "\n" +
          "  " + p.total + " permutations (labels shuffled within each stratum), each one refitting every scored null</pre>";
      }).then(function (rep) {
        // compare against the DEFAULT, not a stale literal — this said "reduced" on every run.
        // The engine may RAISE the count for a large family (rep.n_perm_note says so); the
        // reduction note only applies when it did not.
        if (nPerm < FULL_PERM && rep.n_perm === nPerm) rep.headline += "  (reduced to " + nPerm + " permutations — large battery)";
        return { rep: rep, keys: L.keys, items: L.items };
      });
    }).then(function (o) {
      render(o.rep, o.keys, label, o.items);
    }).catch(function (e) {
      renderError((e && e.message) ? e.message : String(e));
    }).then(function () {
      runBtn.disabled = false;
    });
  }

  function init() {
    var wrap = document.getElementById("ntChips");
    if (!wrap || !window.NullTest) return;
    chips = Array.prototype.slice.call(wrap.querySelectorAll(".nt-chip"));
    pasteWrap = document.getElementById("ntPasteWrap");
    pasteBox = document.getElementById("ntPaste");
    fileIn = document.getElementById("ntFile");
    runBtn = document.getElementById("ntRun");
    result = document.getElementById("ntResult");
    whatEl = document.getElementById("ntWhat");

    chips.forEach(function (c) {
      c.addEventListener("click", function () { select(c.getAttribute("data-preset")); });
    });
    pastePlaceholder = pasteBox.getAttribute("placeholder");
    fileIn.addEventListener("change", function () {
      var f = fileIn.files && fileIn.files[0];
      if (!f) return;
      select("paste");                       // a chosen file always runs as "your battery", whatever chip was pressed
      f.text().then(function (t) {
        fileText = t; pastedName = f.name;
        pasteBox.value = "";
        pasteBox.setAttribute("placeholder", f.name + " (" + t.length + " characters) is loaded; paste here to replace it");
        run();
      }).catch(function (e) { renderError("could not read " + f.name + ": " + ((e && e.message) || String(e))); });
    });
    pasteBox.addEventListener("input", function () {
      if (fileText === null) return;
      fileText = null; pastedName = null;    // the reader is typing: the file no longer stands
      if (pastePlaceholder === null) pasteBox.removeAttribute("placeholder");
      else pasteBox.setAttribute("placeholder", pastePlaceholder);
    });
    runBtn.addEventListener("click", run);
    select("grounding");
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
