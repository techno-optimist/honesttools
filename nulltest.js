// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
/* nulltest.js — the null test, running in the reader's browser.
 *
 * A line-for-line port of /verifier/nulltest.py. Same four surface nulls, same two-sided
 * statistic, same permutation-calibrated thresholds, same worst-cell verdict rule.
 *
 * PARITY IS THE POINT. If the page computed a different number from the CLI, one of them
 * would be lying and a reader could not tell which. So this file reimplements CPython's
 * Mersenne Twister (init_by_array + _randbelow + shuffle) rather than using Math.random:
 * the label permutations drawn here are the SAME permutations, in the same order, that
 * `python3 nulltest.py` draws. Verified against the CLI on the published batteries before
 * shipping — see nulltest_parity.json.
 *
 * Exposes: window.NullTest = { evaluate, loadItems, plantedSeparable, plantedClean }
 */
(function (global) {
  "use strict";

  /* ── CPython random.Random, faithfully ─────────────────────────────────────
     Needed for permutation parity. Any other PRNG gives different thresholds. */
  function MT(seed) {
    var N = 624, M = 397, mt = new Uint32Array(N), mti = N + 1;

    function initGenrand(s) {
      mt[0] = s >>> 0;
      for (var i = 1; i < N; i++) {
        var p = mt[i - 1] ^ (mt[i - 1] >>> 30);
        mt[i] = (Math.imul(1812433253, p) + i) >>> 0;
      }
      mti = N;
    }
    function initByArray(key) {
      initGenrand(19650218);
      var i = 1, j = 0, k = Math.max(N, key.length), p;
      for (; k; k--) {
        p = mt[i - 1] ^ (mt[i - 1] >>> 30);
        mt[i] = (((mt[i] ^ Math.imul(p, 1664525)) >>> 0) + key[j] + j) >>> 0;
        i++; j++;
        if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
        if (j >= key.length) j = 0;
      }
      for (k = N - 1; k; k--) {
        p = mt[i - 1] ^ (mt[i - 1] >>> 30);
        mt[i] = (((mt[i] ^ Math.imul(p, 1566083941)) >>> 0) - i) >>> 0;
        i++;
        if (i >= N) { mt[0] = mt[N - 1]; i = 1; }
      }
      mt[0] = 0x80000000;
    }
    function genrand() {
      var y, kk;
      if (mti >= N) {
        for (kk = 0; kk < N - M; kk++) {
          y = ((mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7fffffff)) >>> 0;
          mt[kk] = (mt[kk + M] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0)) >>> 0;
        }
        for (; kk < N - 1; kk++) {
          y = ((mt[kk] & 0x80000000) | (mt[kk + 1] & 0x7fffffff)) >>> 0;
          mt[kk] = (mt[kk + (M - N)] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0)) >>> 0;
        }
        y = ((mt[N - 1] & 0x80000000) | (mt[0] & 0x7fffffff)) >>> 0;
        mt[N - 1] = (mt[M - 1] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0)) >>> 0;
        mti = 0;
      }
      y = mt[mti++];
      y ^= y >>> 11;
      y = (y ^ ((y << 7) & 0x9d2c5680)) >>> 0;
      y = (y ^ ((y << 15) & 0xefc60000)) >>> 0;
      y ^= y >>> 18;
      return y >>> 0;
    }

    // python: random.seed(int) -> init_by_array(int split into 32-bit words)
    var key = [], s = Math.abs(seed);
    if (s === 0) key = [0];
    while (s > 0) { key.push(s >>> 0); s = Math.floor(s / 4294967296); }
    initByArray(key);

    function getrandbits(k) { return genrand() >>> (32 - k); }   // k <= 32 only; true here
    function randbelow(n) {
      if (n <= 0) return 0;
      var k = 32 - Math.clz32(n), r = getrandbits(k);            // n.bit_length()
      while (r >= n) r = getrandbits(k);
      return r;
    }
    return {
      shuffle: function (x) {                                     // python random.shuffle
        for (var i = x.length - 1; i > 0; i--) {
          var j = randbelow(i + 1), t = x[i]; x[i] = x[j]; x[j] = t;
        }
      },
      randrange: randbelow,                                       // python random.randrange(n)
      choice: function (s) { return s[randbelow(s.length)]; }     // python random.choice
    };
  }

  /* ── AUROC + two-sided separability (RULE 1) ─────────────────────────────── */
  function auroc(y, s) {
    var n = y.length, idx = [], i;
    for (i = 0; i < n; i++) idx.push(i);
    idx.sort(function (a, b) { return s[a] - s[b] || a - b; });
    var ranks = new Float64Array(n);
    i = 0;
    while (i < n) {
      var j = i;
      while (j + 1 < n && s[idx[j + 1]] === s[idx[i]]) j++;
      var r = (i + j) / 2 + 1;
      for (var k = i; k <= j; k++) ranks[k] = r;
      i = j + 1;
    }
    var npos = 0, rsum = 0;
    for (i = 0; i < n; i++) if (y[idx[i]] === 1) { npos++; rsum += ranks[i]; }
    var nneg = n - npos;
    if (npos === 0 || nneg === 0) return null;
    return (rsum - npos * (npos + 1) / 2) / (npos * nneg);
  }
  function astar(y, s) {
    var a = auroc(y, s);
    return a === null ? null : Math.max(a, 1 - a);
  }

  /* ── the four surface nulls ──────────────────────────────────────────────── */
  function ngrams(t) {
    t = " " + t.toLowerCase() + " ";
    var out = new Set();
    for (var n = 3; n <= 5; n++)
      for (var i = 0; i + n <= t.length; i++) out.add(t.slice(i, i + n));
    // SORTED, not a bare Set — see the matching note in nulltest.py. Float addition is not
    // associative, so feature order changes the last bits of the score and cost us two cells
    // of parity. (JS sorts by UTF-16 code unit and Python by code point; these agree for all
    // BMP text. A battery whose entity names contain astral-plane characters could still
    // differ in the last bits.)
    return Array.from(out).sort();
  }

  /* K-fold naive Bayes — NOT leave-one-out. LOO leaks the held-out label through the
     subtraction; this tool's own selftest caught that scoring pure noise at A* = 1.000. */
  function nbScores(texts, y, featfn, k, seed) {
    k = k || 5; seed = seed || 20260724;
    var n = texts.length, feats = texts.map(featfn), i;
    var idx = []; for (i = 0; i < n; i++) idx.push(i);
    MT(seed).shuffle(idx);
    var folds = [];
    for (i = 0; i < k; i++) { var f = []; for (var q = i; q < n; q += k) f.push(idx[q]); folds.push(f); }
    var scores = new Float64Array(n);

    folds.forEach(function (fte) {
      var te = new Set(fte);
      var tr = idx.filter(function (i2) { return !te.has(i2); });
      if (!tr.length || !fte.length) return;
      var pos = new Map(), neg = new Map(), npos = 0, nneg = 0, seen = new Map();
      tr.forEach(function (i2) {
        var d = y[i2] === 1 ? pos : neg;
        if (y[i2] === 1) npos++; else nneg++;
        feats[i2].forEach(function (g) { d.set(g, (d.get(g) || 0) + 1); });
      });
      if (npos === 0 || nneg === 0) return;
      tr.forEach(function (i2) {
        feats[i2].forEach(function (g) { seen.set(g, (seen.get(g) || 0) + 1); });
      });
      fte.forEach(function (i2) {
        var sc = 0;
        feats[i2].forEach(function (g) {
          if ((seen.get(g) || 0) < 2) return;                     // drop hapax: pure memorisation
          sc += Math.log(((pos.get(g) || 0) + 0.5) / (npos + 1)) -
                Math.log(((neg.get(g) || 0) + 0.5) / (nneg + 1));
        });
        // quantize before ranking — see the matching note in nulltest.py (1-ulp Math.log
        // differences between V8 and CPython's libm were creating/destroying tie groups)
        scores[i2] = Math.round(sc * 1e9) / 1e9;
      });
    });
    return Array.prototype.slice.call(scores);
  }

  /* Python's \w is UNICODE-aware; JavaScript's is ASCII-only. With /[^\w\s]/ the accented
     letters in mathematician names ("Poincaré") count as punctuation in JS and as word
     characters in Python — which made the shape null disagree with the CLI on exactly the
     strata full of European surnames. \p{L}\p{N}_ reproduces Python's class. */
  var SHAPE_RE = /[A-Z]{2,}|\p{Nd}+|[^\p{L}\p{N}_\s]/gu;
  var NULLS = {
    lexicality: function (t) { return nbScores(t, arguments[1], ngrams); },
    length: function (t) { return t.map(function (x) { return x.length + 0.001 * x.split(/\s+/).filter(Boolean).length; }); },
    /* catches "reals are ID-shaped (NGC 6315, NCT02921971), fakes are pronounceable words" */
    shape: function (t, y) {
      return nbScores(t, y, function (x) {
        var out = new Set(), m = x.match(SHAPE_RE) || [];
        m.forEach(function (z) {
          // python: "D" if x.isdigit() else "U" if x.isupper() else "P"
          var c = /^\p{Nd}+$/u.test(z) ? "D" : (/\p{L}/u.test(z) && z === z.toUpperCase()) ? "U" : "P";
          out.add("S:" + c + Math.min(z.length, 4));
        });
        out.add("len" + Math.min(Math.floor(x.length / 4), 12));
        return Array.from(out).sort();
      });
    },
    /* does the stratum label alone predict truth? then it's unbalanced by design */
    stratum: function (t, y, strata) {
      if (!strata) return null;
      var n = y.length, idx = []; for (var i = 0; i < n; i++) idx.push(i);
      MT(20260724).shuffle(idx);
      var out = new Array(n).fill(0.5);
      for (var f = 0; f < 5; f++) {
        var fte = []; for (var q = f; q < n; q += 5) fte.push(idx[q]);
        var te = new Set(fte), r = new Map(), c = new Map();
        idx.forEach(function (i2) {
          if (te.has(i2)) return;
          r.set(strata[i2], (r.get(strata[i2]) || 0) + y[i2]);
          c.set(strata[i2], (c.get(strata[i2]) || 0) + 1);
        });
        fte.forEach(function (i2) {
          var st = strata[i2];
          out[i2] = c.get(st) ? (r.get(st) || 0) / c.get(st) : 0.5;
        });
      }
      return out;
    }
  };

  var KEYSEP = "\u0000";   // NUL: cannot occur in a stratum name, so cell keys never collide
  var SCOPE =
    "SCOPE: this measures how much of the label signal is recoverable from SURFACE FORM alone " +
    "by four model-free probes, two-sided, refit inside every permutation and family-wise " +
    "corrected across all cells (Westfall-Young min-p). A PASS does NOT certify the benchmark " +
    "is good: it cannot see circularity (labels drawn from the same store the system under test " +
    "retrieves from), contamination, or mislabelling. It scores no model.";

  /* ── RULE 3 — permutation calibration, done properly ──────────────────────
     Line-for-line with nulltest.py's rewritten block. v1.0 shipped a bent ruler: it scored
     no-signal batteries as DISQUALIFIED up to 22 times in 25, because (a) the permutation
     shuffled labels against a score vector already fitted on the TRUE labels, so the null
     could not see the scorer's own overfitting, and (b) there was no family-wise correction
     across 4 nulls x K strata, where a false fire per battery is expected by construction.

     Fixed here exactly as in the CLI: every permutation refits all four nulls on the shuffled
     labels, and the family is corrected by Westfall-Young min-p.

     NOT max-A*: A* is not comparable across cells of different size — a 16-item cell reaches
     1.000 on noise far more easily than a 120-item one — so correcting on the raw maximum is
     dominated by the smallest cells and flips genuinely separable batteries to PASS. */

  function cellDefs(strata) {
    var uniq = Array.from(new Set(strata)).sort(), out = [];
    uniq.forEach(function (st) {
      var idx = [];
      for (var i = 0; i < strata.length; i++) if (strata[i] === st) idx.push(i);
      out.push([st, idx]);
    });
    return out;
  }

  var N_FOLDS = 5;

  /* The fold each item lands in — the SAME assignment nbScores uses. */
  function foldOf(n, k, seed) {
    k = k || N_FOLDS; seed = seed || 20260724;
    var idx = []; for (var i = 0; i < n; i++) idx.push(i);
    MT(seed).shuffle(idx);
    var f = new Array(n);
    for (var pos = 0; pos < idx.length; pos++) f[idx[pos]] = pos % k;
    return f;
  }

  /* True when a cell's scores are a function of FOLD ASSIGNMENT ALONE — see the long note in
     nulltest.py. NOT "few distinct values": that version killed length/astronomy, a perfect
     real separation that uses only four values, and flipped our own photon battery from
     DISQUALIFIED to PASS. A guard that hides a real defect in our own benchmark is worse than
     the artifact it removes. */
  function degenerate(scores, folds) {
    var uf = new Set(folds);
    if (uf.size < 2) return true;
    var pairs = new Set();
    for (var i = 0; i < scores.length; i++) pairs.add(folds[i] + "|" + scores[i]);
    return pairs.size === uf.size;
  }

  /* Fit all four nulls on THESE labels and return A* for every (null, stratum) cell.
     Called once for the observation and once per permutation — the refit IS the fix. */
  function scoreAllCells(texts, y, strata, cells, useStratum, folds) {
    var out = {};
    if (!folds) folds = foldOf(y.length);
    Object.keys(NULLS).forEach(function (name) {
      var s = NULLS[name](texts, y, useStratum ? strata : null);
      if (s === null) return;
      cells.forEach(function (c) {
        var st = c[0], idx = c[1];
        var ys = idx.map(function (i) { return y[i]; });
        var ss = idx.map(function (i) { return s[i]; });
        var fs = idx.map(function (i) { return folds[i]; });
        out[name + KEYSEP + st] = (new Set(ys).size >= 2 && !degenerate(ss, fs)) ? astar(ys, ss) : null;
      });
    });
    return out;
  }

  function bisectLeft(arr, t) {
    var lo = 0, hi = arr.length;
    while (lo < hi) { var m = (lo + hi) >> 1; if (arr[m] < t) lo = m + 1; else hi = m; }
    return lo;
  }
  function bisectRight(arr, t) {
    var lo = 0, hi = arr.length;
    while (lo < hi) { var m = (lo + hi) >> 1; if (arr[m] <= t) lo = m + 1; else hi = m; }
    return lo;
  }
  /* +1 top and bottom: a permutation p-value must never be 0, or an adjusted p of 0 would
     claim infinite evidence from a finite number of draws. */
  function pval(sortedCol, t) {
    var B = sortedCol.length;
    if (!B || t === null || t === undefined) return 1.0;
    return (B - bisectLeft(sortedCol, t) + 1.0) / (B + 1.0);
  }

  var r3 = function (x) { return Math.round(x * 1000) / 1000; };
  var r4 = function (x) { return Math.round(x * 10000) / 10000; };

  function evaluate(items, keys, opts) {
    var it = evaluateSteps(items, keys, opts), s;
    do { s = it.next(); } while (!s.done);
    return s.value;
  }

  /* Yield via MessageChannel, NOT setTimeout. Browsers clamp setTimeout to ~1/second in a
     BACKGROUND tab, so a long chain freezes the moment the reader switches tabs.
     Created lazily: an open MessagePort keeps node's event loop alive, which would hang the
     synchronous parity harness that runs this file under node. */
  var _chan = null, _queue = [];
  function yieldSoon(fn) {
    if (typeof MessageChannel !== "function") return void setTimeout(fn, 0);
    if (!_chan) {
      _chan = new MessageChannel();
      _chan.port1.onmessage = function () { var f = _queue.shift(); if (f) f(); };
    }
    _queue.push(fn);
    _chan.port2.postMessage(0);
  }

  function evaluateAsync(items, keys, opts, onProgress) {
    var it = evaluateSteps(items, keys, opts);
    return new Promise(function (resolve, reject) {
      function slice() {
        var t0 = (typeof performance !== "undefined" ? performance.now() : Date.now()), last = null;
        try {
          for (;;) {
            var s = it.next();
            if (s.done) { if (last && onProgress) onProgress(last); return resolve(s.value); }
            last = s.value;
            var now = (typeof performance !== "undefined" ? performance.now() : Date.now());
            if (now - t0 >= 40) { if (onProgress) onProgress(last); return yieldSoon(slice); }
          }
        } catch (e) { reject(e); }
      }
      yieldSoon(slice);
    });
  }

  function* evaluateSteps(items, keys, opts) {
    opts = opts || {};
    var nPerm = opts.nPerm || 600, seed = opts.seed || 20260724;
    var minCell = opts.minCell || 12, alpha = opts.alpha || 0.05;
    var tk = keys.text, lk = keys.label, sk = keys.stratum;

    var texts = items.map(function (i) { return String(i[tk]); });
    var y = items.map(function (i) { return parseInt(i[lk], 10) || 0; });
    var strata = sk ? items.map(function (i) { return String(i[sk] === undefined ? "_all" : i[sk]); })
                    : items.map(function () { return "_all"; });

    var cells = cellDefs(strata);
    var rng = MT(seed);
    var obs = scoreAllCells(texts, y, strata, cells, !!sk);
    var ks = Object.keys(obs).filter(function (k) { return obs[k] !== null; }).sort();

    var nFake = y.reduce(function (a, b) { return a + b; }, 0);
    var report = {
      n: items.length, n_fake: nFake, n_real: items.length - nFake,
      strata: cells.map(function (c) { return c[0]; }), min_cell: minCell, n_perm: nPerm,
      alpha: alpha, family_size: ks.length, correction: "westfall_young_min_p",
      nulls: {}, underpowered_cells: []
    };

    if (!ks.length) {
      // NOT_SCORABLE, never PASS — mirrors nulltest.py. A corpus with no scorable cell has not been
      // checked, it has been skipped, and returning PASS let anyone earn a clean verdict by handing
      // the tool something it could not score.
      report.worst_cell = { astar: null, "null": null, stratum: null, adj_p: null };
      report.n_separating_cells = 0;
      report.verdict = "NOT_SCORABLE";
      report.headline = "no scorable cell — nothing was tested. This is NOT a pass: a corpus with no " +
                        "scorable stratum has not been checked, it has been skipped.";
      report.power = { n: report.n, measured_mde: null, comparable_across_batteries: false,
                       reading: "nothing was scored, so there is no power to report." };
      report.scope = SCOPE;
      return report;
    }

    // ---- the null: refit everything, every permutation ----------------------------
    var draws = {}; ks.forEach(function (k) { draws[k] = []; });
    var ys = y.slice();
    for (var b = 0; b < nPerm; b++) {
      rng.shuffle(ys);
      var sc = scoreAllCells(texts, ys, strata, cells, !!sk);
      for (var i = 0; i < ks.length; i++) {
        var v = sc[ks[i]];
        if (v !== null && v !== undefined) draws[ks[i]].push(v);
      }
      yield { done: b + 1, total: nPerm, label: "permutation " + (b + 1) + " of " + nPerm + " · refitting every scored null" };
    }

    var cols = {};
    ks.forEach(function (k) { cols[k] = draws[k].slice().sort(function (a, c) { return a - c; }); });

    // ---- Westfall-Young min-p -----------------------------------------------------
    var raw = {};
    ks.forEach(function (k) { raw[k] = pval(cols[k], obs[k]); });
    var q = [];
    for (var bb = 0; bb < nPerm; bb++) {
      var best = 1.0;
      for (var j = 0; j < ks.length; j++) {
        var col = draws[ks[j]];
        if (bb < col.length) { var p = pval(cols[ks[j]], col[bb]); if (p < best) best = p; }
      }
      q.push(best);
    }
    q.sort(function (a, c) { return a - c; });
    var adj = {};
    ks.forEach(function (k) { adj[k] = (bisectRight(q, raw[k]) + 1.0) / (nPerm + 1.0); });

    // ---- report -------------------------------------------------------------------
    // _adjExact is the UNROUNDED adjusted p, kept only for comparison. Comparing the
    // unrounded adj[k] against the ROUNDED adj_p stored below made every cell tied at the
    // permutation floor overwrite the previous one (0.0016638 < 0.0017), so the reported
    // worst cell was the LAST tied cell in null order, not the largest effect. Same defect
    // as the Python engine; fixed identically so the two agree.
    var worst = { astar: 0, adj_p: 1.0, _adjExact: 2.0, "null": null, stratum: null, n: 0, threshold: null };
    Object.keys(NULLS).forEach(function (name) {
      var entry = { per_stratum: {} };
      cells.forEach(function (c) {
        var st = c[0], idx = c[1], k = name + KEYSEP + st;
        if (!(k in obs) || obs[k] === null) return;
        var col = cols[k] || [];
        var thr = col.length ? col[Math.min(col.length - 1, Math.round(0.95 * (col.length - 1)))] : null;
        var cell = {
          n: idx.length, astar: r3(obs[k]), threshold: thr === null ? null : r3(thr),
          raw_p: r4(raw[k]), adj_p: r4(adj[k]),
          separates: adj[k] < alpha, underpowered: idx.length < minCell
        };
        entry.per_stratum[st] = cell;
        if (cell.underpowered) {
          var tag = name + "/" + st + " (n=" + idx.length + ")";
          if (report.underpowered_cells.indexOf(tag) < 0) report.underpowered_cells.push(tag);
        }
        if (adj[k] < worst._adjExact || (adj[k] === worst._adjExact && obs[k] > worst.astar)) {
          worst = { astar: r3(obs[k]), adj_p: r4(adj[k]), _adjExact: adj[k], raw_p: r4(raw[k]), "null": name,
                    stratum: st, n: idx.length, threshold: cell.threshold,
                    underpowered: cell.underpowered };
        }
      });
      if (Object.keys(entry.per_stratum).length) report.nulls[name] = entry;
    });

    report.worst_cell = worst;
    report.n_separating_cells = ks.filter(function (k) { return adj[k] < alpha; }).length;
    delete worst._adjExact;   // comparison scratch, never part of the published report
    // SATURATION — mirrors nulltest.py. A permutation p cannot go below 1/(B+1); landing exactly
    // there makes the value a BOUND, not a measurement.
    var floorP = 1.0 / (nPerm + 1.0);
    report.p_floor = Math.round(floorP * 1e6) / 1e6;
    report.saturated = worst.adj_p <= Math.round(floorP * 1e4) / 1e4 + 1e-12;
    if (report.saturated) {
      report.saturation_note = "adjusted p is AT the permutation floor 1/(" + nPerm + "+1) = " +
        floorP.toFixed(5) + ". This is the smallest value " + nPerm + " permutations can express, so " +
        "the true p is '<= " + floorP.toFixed(5) + "', not '= " + floorP.toFixed(5) + "'. Raise the " +
        "permutation count to resolve further; it cannot change the verdict.";
    }
    report.verdict = worst.adj_p < alpha ? "DISQUALIFIED" : "PASS";
    // MEASURED POWER — mirrors nulltest.py's _power_note exactly. Measured 2026-07-25 by planting
    // a +1-char marker on a fraction of the label-1 half of a clean synthetic base and finding the
    // smallest fraction caught in >=3 of 4 seeds (grid 15/30/60/100%). Low power costs DETECTIONS,
    // not false alarms, so a verdict that fired stands at any n; a PASS at small n does not.
    var MDE = [[1496, 0.30], [702, 0.60], [324, 0.60], [156, 0.60]];
    var mde = null;
    for (var mi = 0; mi < MDE.length; mi++) { if (report.n >= MDE[mi][0]) { mde = MDE[mi][1]; break; } }
    var dq = report.verdict === "DISQUALIFIED", pct = mde ? Math.round(mde * 100) : null, rd;
    if (mde === null && dq) {
      rd = "DISQUALIFIED at n=" + report.n + ", below the smallest size we have measured (156). Low power costs us DETECTIONS, not false alarms, so a verdict that fired at this size stands: the artifact was large enough to see anyway.";
    } else if (mde === null) {
      rd = "PASS at n=" + report.n + ", below the smallest size we have measured (156). We have not established what this test can detect here, so this PASS is not evidence of cleanliness.";
    } else if (!dq) {
      rd = "PASS at n=" + report.n + ". Measured: an artifact must cover about " + pct + "% of the label-1 half before this test catches it at this size. A PASS here does NOT exclude a weaker artifact.";
    } else {
      rd = "DISQUALIFIED at n=" + report.n + ", which is above the measured detection threshold (~" + pct + "% coverage) — the artifact is large enough to see at this size.";
    }
    report.power = { n: report.n, measured_mde: mde, comparable_across_batteries: false,
      note_on_comparison: "A* depends on n. Do not rank this battery against one of a different size: cities.csv is DISQUALIFIED at n=1496 and PASSES 5 of 5 subsamples at n=354.",
      reading: rd };
    // python renders a rounded float as "1.0", JS as "1" — match the CLI's text exactly
    var pyf = function (x) { return Number.isInteger(x) ? x.toFixed(1) : String(x); };
    report.headline = "worst cell A* = " + pyf(worst.astar) + " in " + worst["null"] + "/" +
      worst.stratum + " (n=" + worst.n + "), family-adjusted p = " + pyf(worst.adj_p) +
      " over " + ks.length + " cells";
    report.scope = SCOPE;
    return report;
  }

  /* ── input handling — same key sniffing and label coercion as the CLI ────── */
  var FAKE_WORDS = ["fake", "fabrication", "fabricated", "false", "1", "coined"];
  function loadItems(raw) {
    var items;
    raw = String(raw).trim();
    if (!raw) throw new Error("nothing to read");
    if (raw[0] !== "[" && raw[0] !== "{") throw new Error("that is not JSON — expected an array of items");
    if (raw.indexOf("\n") > 0 && raw[0] === "{" && raw.trim().slice(-1) === "}" && raw.split("\n")[0].trim().slice(-1) === "}") {
      items = raw.split("\n").filter(function (l) { return l.trim(); }).map(function (l) { return JSON.parse(l); });
    } else {
      items = JSON.parse(raw);
    }
    if (!Array.isArray(items)) {
      var found = null;
      ["items", "battery", "data", "rows"].forEach(function (k) {
        if (!found && Array.isArray(items[k])) found = items[k];
      });
      if (!found) throw new Error("could not find a list of items (looked for items / battery / data / rows)");
      items = found;
    }
    if (!items.length) throw new Error("the list of items is empty");

    var probe = JSON.stringify(items.slice(0, 40));
    function sniff(cands) {
      for (var i = 0; i < cands.length; i++) if (probe.indexOf('"' + cands[i] + '"') >= 0) return cands[i];
      return null;
    }
    var tk = sniff(["entity", "text", "claim", "question", "name", "prompt"]);
    var lk = sniff(["label", "y", "is_fake", "type"]);
    var sk = sniff(["category", "domain", "stratum", "cell"]);
    if (!tk) throw new Error("no text field found (looked for entity / text / claim / question / name / prompt)");
    if (!lk) throw new Error("no label field found (looked for label / y / is_fake / type)");

    var out = items.filter(function (it) { return it && it[tk] !== undefined && it[lk] !== undefined; })
      .map(function (it) {
        var v = it[lk], c = {};
        for (var k in it) c[k] = it[k];
        if (typeof v === "string") v = FAKE_WORDS.indexOf(v.toLowerCase()) >= 0 ? 1 : 0;
        else if (typeof v === "boolean") v = v ? 1 : 0;
        c[lk] = parseInt(v, 10) || 0;
        return c;
      });
    if (!out.length) throw new Error("no item had both a text field and a label field");
    var lab = new Set(out.map(function (it) { return it[lk]; }));
    if (lab.size < 2) throw new Error("every item carries the same label — there is nothing to separate");
    return { items: out, keys: { text: tk, label: lk, stratum: sk } };
  }

  /* ── the two planted controls ────────────────────────────────────────────
     A null test that cannot fire is decoration; one that fires on noise is a smoke alarm
     with no batteries. Both must be demonstrable, so the reader can run them here.

     These are generated from the SAME random.Random(7) stream, in the same order, as
     nulltest.py's --selftest — so the items below are byte-identical to the ones the CLI
     tests itself with, not a lookalike.

     WHY NOT A CHEAP PRNG: the first version of the clean control used a linear congruential
     generator, whose lowest bit alternates with period 2. The labels also alternate (i % 2),
     so the trial ids silently encoded the label and the "must not fire" control came back
     DISQUALIFIED — caught by this tool, on this page, before it shipped. */
  function plantedSeparable(rng) {
    var r = rng || MT(7), out = [], i, j, w;
    for (i = 0; i < 60; i++)
      out.push({ entity: "NCT" + String(r.randrange(10000000)).padStart(8, "0"), label: 0, category: "trials" });
    for (i = 0; i < 60; i++) {
      w = "";
      for (j = 0; j < 4; j++) w += r.choice("bcdfg") + r.choice("aeiou");
      out.push({ entity: w, label: 1, category: "trials" });
    }
    return out;
  }
  function plantedClean() {
    // python's selftest draws the clean base from the SAME rng, after the dirty battery
    var r = MT(7);
    plantedSeparable(r);
    var out = [];
    for (var i = 0; i < 120; i++)
      out.push({ entity: "NCT" + String(r.randrange(10000000)).padStart(8, "0"), label: i % 2, category: "trials" });
    return out;
  }

  global.NullTest = { _MT: MT, _scoreAllCells: scoreAllCells, _cellDefs: cellDefs, evaluate: evaluate, evaluateAsync: evaluateAsync, loadItems: loadItems, astar: astar, auroc: auroc,
                      plantedSeparable: plantedSeparable, plantedClean: plantedClean };
})(window);
