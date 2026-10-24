// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
/* nulltest.js — the null test, running in the reader's browser.
 *
 * A line-for-line port of nulltest.py. Same six surface probes, same two-sided statistic,
 * same stratified permutation null, same worst-cell verdict rule.
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

  /* ── Python string semantics ───────────────────────────────────────────────
     Python indexes a str by CODE POINT; JavaScript by UTF-16 code unit. An emoji is one
     character to the CLI and two to the browser, which changed len(), the character n-grams
     and the shape signature on any battery with astral text — enough to flip a cell from
     PASS to SEPARATES. Everything that measures or slices text goes through cps(). */
  function cps(t) { return Array.from(t); }
  var SURR = /[\ud800-\udfff]/;
  /* Python compares strings by code point; JS by code unit. These differ only when an astral
     character meets a BMP character above U+D7FF (fullwidth punctuation, CJK compatibility). */
  function cpCmp(a, b) {
    if (a === b) return 0;
    var i = 0, j = 0;
    while (i < a.length && j < b.length) {
      var x = a.codePointAt(i), y = b.codePointAt(j);
      if (x !== y) return x < y ? -1 : 1;
      i += x > 0xffff ? 2 : 1; j += y > 0xffff ? 2 : 1;
    }
    return i >= a.length ? -1 : 1;
  }
  function sortCp(arr) {
    for (var i = 0; i < arr.length; i++) if (SURR.test(arr[i])) return arr.sort(cpCmp);
    return arr.sort();          // BMP only: code-unit order IS code-point order
  }
  /* Python's str.split() / \s whitespace, spelled out. JS \s lacks \x1c-\x1f and \x85 and
     has U+FEFF; Python is the other way round, and both appear in real corpora. */
  var PY_WS = "\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000";
  var PY_WS_RE = new RegExp("[" + PY_WS + "]+", "u");
  /* Python's round(x, nd): half-to-even on the EXACT value of the double, not on x*10^nd (which
     has already been rounded once: 0.5625*1000 is a true tie, 0.0005*1000 is not). toFixed gives
     the exact decimal expansion, so the tie test is made on the real digits. A* is a rational,
     and 9/16, 45/80, 13/16 ... all sit on a tie: Math.round gave 0.563 where the CLI says 0.562. */
  function pyRound(x, nd) {
    nd = nd || 0;
    if (!isFinite(x)) return x;
    var neg = x < 0, s = Math.abs(x).toFixed(Math.min(100, nd + 30));
    var dot = s.indexOf("."), digits = s.replace(".", ""), keep = dot + nd;
    var head = digits.slice(0, keep), tail = digits.slice(keep);
    var last = head.charCodeAt(head.length - 1) - 48;
    var up = tail.charAt(0) > "5" || (tail.charAt(0) === "5" && (/[1-9]/.test(tail.slice(1)) || last % 2 === 1));
    var r = (Number(head) + (up ? 1 : 0)) / Math.pow(10, nd);
    return neg ? -r : r;
  }
  /* Python's str() of a JSON value, so stratum names and joined text fields match the CLI:
     None, True, False, and the exponent form of a small float ("1e-05"). JSON.parse has already
     turned 1.0 into 1, so an integral float cannot be told from an int here; quote such fields. */
  function pyStr(v) {
    if (v === null || v === undefined) return "None";
    if (v === true) return "True";
    if (v === false) return "False";
    if (typeof v === "number") {
      if (v !== v) return "nan";
      if (v === Infinity) return "inf";
      if (v === -Infinity) return "-inf";
      if (!Number.isInteger(v) && Math.abs(v) < 1e-4) {
        var m = v.toExponential().match(/^(-?[\d.]+)e([+-])(\d+)$/);
        return m[1] + "e" + m[2] + (m[3].length < 2 ? "0" : "") + m[3];
      }
    }
    return String(v);
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

  /* ── the six surface probes ─────────────────────────────────────────────── */
  function ngrams(t) {
    var c = cps(" " + t.toLowerCase() + " ");          // code points, as Python slices a str
    var out = new Set();
    for (var n = 3; n <= 5; n++)
      for (var i = 0; i + n <= c.length; i++) out.add(c.slice(i, i + n).join(""));
    // SORTED, not a bare Set — see the matching note in nulltest.py. Float addition is not
    // associative, so feature order changes the last bits of the score and cost us two cells
    // of parity. sortCp sorts by code point, as Python does.
    return sortCp(Array.from(out));
  }

  /* Python's \w is UNICODE-aware; JavaScript's is ASCII-only. \p{L}\p{N}_ reproduces Python's
     class, for the word probes and for the shape probe alike. */
  var WORD_RE = /[\p{L}\p{N}_]+/gu;
  function wordsOf(t) { return t.match(WORD_RE) || []; }

  function words(t) {
    var ws = wordsOf(t.toLowerCase()), out = new Set(ws);
    for (var i = 0; i + 1 < ws.length; i++) out.add(ws[i] + " " + ws[i + 1]);
    return sortCp(Array.from(out));
  }

  /* 1..26 for an ASCII letter (case-folded), else 0 — ASCII-only on purpose so both engines
     agree on every input. toLowerCase can expand one code point into two (U+0130), hence the
     length check, which mirrors nulltest.py. */
  function alphaPos(ch) {
    var c = ch.toLowerCase();
    return (c.length === 1 && c >= "a" && c <= "z") ? c.charCodeAt(0) - 96 : 0;
  }
  function firstCp(w) { return String.fromCodePoint(w.codePointAt(0)); }   // python: w[0]
  function alphaFirst(t) { var ws = wordsOf(t); return ws.length ? alphaPos(firstCp(ws[0])) : 0; }
  function alphaLast(t) { var ws = wordsOf(t); return ws.length ? alphaPos(firstCp(ws[ws.length - 1])) : 0; }

  /* With /[^\w\s]/ the accented letters in mathematician names ("Poincaré") counted as
     punctuation in JS and as word characters in Python — which made the shape null disagree
     with the CLI on exactly the strata full of European surnames. */
  var SHAPE_RE = new RegExp("[A-Z]{2,}|\\p{Nd}+|[^\\p{L}\\p{N}_" + PY_WS + "]", "gu");
  function shapeSig(x) {
    var out = new Set(), m = x.match(SHAPE_RE) || [];
    m.forEach(function (z) {
      // python: "D" if x.isdigit() else "U" if x.isupper() else "P". isupper() is the Unicode
      // Uppercase property, which also covers the circled capitals Ⓐ-Ⓩ (category So).
      var c = /^\p{Nd}+$/u.test(z) ? "D" : /\p{Uppercase}/u.test(z) ? "U" : "P";
      out.add("S:" + c + Math.min(cps(z).length, 4));
    });
    out.add("len" + Math.min(Math.floor(cps(x).length / 4), 12));
    return sortCp(Array.from(out));
  }

  /* K-fold naive Bayes, prepared once per (texts, features) and refit per label vector — the
     same restructuring as nulltest.py's _NB, with the same arithmetic in the same order, so
     every score is bit-identical to the one-shot version. NOT leave-one-out: LOO leaks the
     held-out label through the subtraction; this tool's own selftest caught that scoring pure
     noise at A* = 1.000. */
  function NB(texts, featfn, k, seed) {
    k = k || 5; seed = seed || 20260724;
    var n = texts.length, feats = texts.map(featfn), i;
    var vset = new Set();   // a loop, not concat.apply: apply() overflows the stack past ~125k items
    feats.forEach(function (f) { f.forEach(function (g) { vset.add(g); }); });
    var vocab = sortCp(Array.from(vset));
    var idxOf = new Map(); vocab.forEach(function (g, j) { idxOf.set(g, j); });
    var items = feats.map(function (f) { return f.map(function (g) { return idxOf.get(g); }); });
    var idx = []; for (i = 0; i < n; i++) idx.push(i);
    MT(seed).shuffle(idx);
    var folds = [];
    for (var f = 0; f < k; f++) {
      var fte = []; for (var q = f; q < n; q += k) fte.push(idx[q]);
      var te = new Set(fte);
      var tr = idx.filter(function (i2) { return !te.has(i2); });
      if (!tr.length || !fte.length) continue;
      var total = new Int32Array(vocab.length);
      tr.forEach(function (i2) { items[i2].forEach(function (g) { total[g]++; }); });
      // drop hapax (seen once in the training folds): pure memorisation
      var teFeats = fte.map(function (i2) {
        return [i2, items[i2].filter(function (g) { return total[g] >= 2; })];
      });
      folds.push([tr, teFeats, total]);
    }
    this.score = function (y) {
      var scores = new Float64Array(n);
      folds.forEach(function (fold) {
        var tr = fold[0], teFeats = fold[1], total = fold[2];
        var pos = new Int32Array(total.length), npos = 0;
        tr.forEach(function (i2) {
          if (y[i2] === 1) { npos++; items[i2].forEach(function (g) { pos[g]++; }); }
        });
        var nneg = tr.length - npos;
        if (npos === 0 || nneg === 0) return;
        var top = 0; for (var g2 = 0; g2 < total.length; g2++) if (total[g2] > top) top = total[g2];
        var lp = new Float64Array(top + 1), ln = new Float64Array(top + 1);
        for (var c = 0; c <= top; c++) {
          lp[c] = Math.log((c + 0.5) / (npos + 1));
          ln[c] = Math.log((c + 0.5) / (nneg + 1));
        }
        teFeats.forEach(function (tf) {
          var sc = 0, fs = tf[1];
          for (var j = 0; j < fs.length; j++) { var p = pos[fs[j]]; sc += lp[p] - ln[total[fs[j]] - p]; }
          // quantize before ranking — see the matching note in nulltest.py (1-ulp Math.log
          // differences between V8 and CPython's libm were creating/destroying tie groups)
          scores[tf[0]] = Math.round(sc * 1e9) / 1e9;
        });
      });
      return Array.prototype.slice.call(scores);
    };
  }
  function nbScores(texts, y, featfn, k, seed) { return new NB(texts, featfn, k, seed).score(y); }

  /* name -> [kind, fn]: "nb" is a fitted probe over features, "score" an unfitted per-text
     score. Same names, same order as nulltest.py's NULLS. v1.3 also carried a "stratum" probe
     (the per-stratum label rate); it was degenerate in every per-stratum cell by construction and
     never scored, and under the stratified null of v1.4 it is held fixed. It is gone. */
  var NULLS = {
    lexicality: ["nb", ngrams],
    words: ["nb", words],
    length: ["score", function (x) { return cps(x).length + 0.001 * x.split(PY_WS_RE).filter(Boolean).length; }],
    shape: ["nb", shapeSig],
    alpha_first: ["score", alphaFirst],
    alpha_last: ["score", alphaLast]
  };

  /* Everything about a battery that does not depend on the labels, computed once and shared by
     the observation and every permutation — nulltest.py's _Prepared. */
  function Prepared(texts, strata) {
    var self = this;
    this.fixed = {}; this.nb = {};
    Object.keys(NULLS).forEach(function (name) {
      var kind = NULLS[name][0], fn = NULLS[name][1];
      if (kind === "score") self.fixed[name] = texts.map(function (t) { return fn(t); });
      else self.nb[name] = new NB(texts, fn);
    });
    this.scores = function (name, y) {
      if (NULLS[name][0] === "score") return self.fixed[name];
      return self.nb[name].score(y);
    };
  }

  var VERSION = "1.4";
  var KEYSEP = "\u0000";   // NUL: cannot occur in a stratum name, so cell keys never collide
  var SCOPE =
    "SCOPE: this measures how much of the label signal is recoverable from SURFACE FORM alone " +
    "by six model-free probes, two-sided, refit inside every permutation (labels shuffled within stratum) and family-wise " +
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
    var uniq = sortCp(Array.from(new Set(strata))), out = [];
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

  /* Fit every probe on THESE labels and return A* for every (probe, stratum) cell.
     Called once for the observation and once per permutation — the refit IS the fix. */
  function scoreAllCells(prep, y, cells, folds) {
    var out = {};
    if (!folds) folds = foldOf(y.length);
    Object.keys(NULLS).forEach(function (name) {
      var s = prep.scores(name, y);
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

  var r3 = function (x) { return pyRound(x, 3); };   // python round(x, 3): half-to-even
  var r4 = function (x) { return pyRound(x, 4); };

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

    var texts = items.map(function (i) { return itemText(i, tk); });
    var y = items.map(function (i) { return parseInt(i[lk], 10) || 0; });
    var strata = strataOf(items, sk);

    var cells = cellDefs(strata);
    var folds = foldOf(y.length);
    var rng = MT(seed);
    var prep = new Prepared(texts, strata);
    var obs = scoreAllCells(prep, y, cells, folds);
    var ks = sortCp(Object.keys(obs).filter(function (k) { return obs[k] !== null; }));

    // ENOUGH PERMUTATIONS FOR THE FAMILY — mirrors nulltest.py. Under min-p the smallest adjusted p
    // a family of K cells can reach is about (K+1)/(B+1), so B is raised to at least 2(K+1)/alpha,
    // rounded up to a hundred, and the raise is recorded. nPerm is a floor, not a ceiling.
    var nPermRequested = nPerm;
    var need = Math.ceil(2.0 * (ks.length + 1) / alpha / 100.0) * 100;
    if (ks.length && nPerm < need) nPerm = need;

    var nFake = y.reduce(function (a, b) { return a + b; }, 0);
    var rateBy = {};
    cells.forEach(function (c) {
      var sum = 0; c[1].forEach(function (i) { sum += y[i]; });
      rateBy[c[0]] = { n: c[1].length, label1_rate: pyRound(sum / c[1].length, 3) };
    });
    var report = {
      tool: "nulltest", version: VERSION, probes: Object.keys(NULLS),
      n: items.length, n_fake: nFake, n_real: items.length - nFake,
      strata: cells.map(function (c) { return c[0]; }), min_cell: minCell, n_perm: nPerm,
      n_perm_requested: nPermRequested,
      alpha: alpha, family_size: ks.length, correction: "westfall_young_min_p",
      "null": "labels shuffled within stratum (stratified permutation), every probe refit",
      label_rate_by_stratum: rateBy,
      nulls: {}, underpowered_cells: []
    };
    if (nPerm !== nPermRequested) {
      report.n_perm_note = nPermRequested + " permutations requested; " + ks.length + " cells need at least " +
        need + " to resolve alpha=" + pyRound(alpha, 2).toFixed(2) + " under min-p, so " + nPerm + " were run.";
    }

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
    // THE NULL IS STRATIFIED — mirrors nulltest.py's _permutation_draws. Labels are shuffled WITHIN
    // each stratum (cells in cellDefs order, the same random.shuffle calls in the same order), so
    // every permuted battery keeps the observed label rate in every cell. v1.3 shuffled across the
    // whole battery and fired 44% of the time on no-signal text at an 85/15 split.
    // Draws are kept ALIGNED by permutation index, null where a cell could not be scored on that
    // shuffle, so the min-p pass sees the same permutation across all cells.
    var groups = cells.map(function (c) { return c[1]; });
    var draws = {}; ks.forEach(function (k) { draws[k] = []; });
    for (var b = 0; b < nPerm; b++) {
      var ys = y.slice();
      for (var g = 0; g < groups.length; g++) {
        var idxg = groups[g], vals = idxg.map(function (i) { return y[i]; });
        rng.shuffle(vals);
        for (var t = 0; t < idxg.length; t++) ys[idxg[t]] = vals[t];
      }
      var sc = scoreAllCells(prep, ys, cells, folds);
      for (var i = 0; i < ks.length; i++) {
        var v = sc[ks[i]];
        draws[ks[i]].push(v === undefined ? null : v);
      }
      yield { done: b + 1, total: nPerm, label: "permutation " + (b + 1) + " of " + nPerm + " · refitting every scored null" };
    }

    var cols = {};
    ks.forEach(function (k) {
      cols[k] = draws[k].filter(function (v) { return v !== null; }).sort(function (a, c) { return a - c; });
    });

    // ---- Westfall-Young min-p -----------------------------------------------------
    // The observed statistic and the B permuted ones are B+1 exchangeable values under the null,
    // and every one gets its p from the SAME pool: values at or above it, out of B+1. v1.3 counted
    // the observation into its own p (floor 1/(B+1)) but not into the permuted ones (floor
    // 2/(B+1)), so the observed could undercut every permuted min-p by beating all B draws in ANY
    // one cell: family-wise error ~K/(B+1) instead of alpha. Mirrors nulltest.py exactly.
    var raw = {};
    ks.forEach(function (k) { raw[k] = pval(cols[k], obs[k]); });
    var q = [];
    for (var bb = 0; bb < nPerm; bb++) {
      var best = 1.0;
      for (var j = 0; j < ks.length; j++) {
        var tb = draws[ks[j]][bb];
        if (tb === null) continue;
        var colj = cols[ks[j]];
        var p = (colj.length - bisectLeft(colj, tb) + (obs[ks[j]] >= tb ? 1.0 : 0.0)) / (colj.length + 1.0);
        if (p < best) best = p;
      }
      q.push(best);
    }
    q.sort(function (a, c) { return a - c; });
    var adj = {};
    ks.forEach(function (k) { adj[k] = (bisectRight(q, raw[k]) + 1.0) / (nPerm + 1.0); });

    // ---- report -------------------------------------------------------------------
    // python renders a rounded float as "1.0", JS as "1" — match the CLI's text exactly
    var pyf = function (x) { return Number.isInteger(x) ? x.toFixed(1) : String(x); };
    // _adjExact is the UNROUNDED adjusted p, kept only for comparison. Comparing the
    // unrounded adj[k] against the ROUNDED adj_p stored below made every cell tied at the
    // permutation floor overwrite the previous one (0.0016638 < 0.0017), so the reported
    // worst cell was the LAST tied cell in null order, not the largest effect. Same defect
    // as the Python engine; fixed identically so the two agree.
    // Ties on the adjusted p are broken by EFFECT, (A* - 0.5) * sqrt(n), then by A* — as the CLI.
    var worst = { astar: 0, adj_p: 1.0, _adjExact: 2.0, _effect: -1.0, "null": null, stratum: null, n: 0, threshold: null };
    Object.keys(NULLS).forEach(function (name) {
      var entry = { per_stratum: {} };
      cells.forEach(function (c) {
        var st = c[0], idx = c[1], k = name + KEYSEP + st;
        if (!(k in obs) || obs[k] === null) return;
        var col = cols[k] || [];
        // python: int(round(0.95 * (len - 1))) — half-to-even, so a column of 31, 71, 111 ...
        // draws indexes 28, not 29
        var thr = col.length ? col[Math.min(col.length - 1, pyRound(0.95 * (col.length - 1), 0))] : null;
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
        var effect = (obs[k] - 0.5) * Math.sqrt(idx.length);
        if (adj[k] < worst._adjExact || (adj[k] === worst._adjExact &&
            (effect > worst._effect || (effect === worst._effect && obs[k] > worst.astar)))) {
          worst = { astar: r3(obs[k]), adj_p: r4(adj[k]), _adjExact: adj[k], _effect: effect, raw_p: r4(raw[k]), "null": name,
                    stratum: st, n: idx.length, threshold: cell.threshold,
                    underpowered: cell.underpowered };
        }
      });
      if (Object.keys(entry.per_stratum).length) report.nulls[name] = entry;
    });

    report.worst_cell = worst;
    report.n_separating_cells = ks.filter(function (k) { return adj[k] < alpha; }).length;
    delete worst._adjExact;   // comparison scratch, never part of the published report
    delete worst._effect;
    // SATURATION — mirrors nulltest.py. A permutation p cannot go below 1/(B+1); landing exactly
    // there makes the value a BOUND, not a measurement.
    var floorP = 1.0 / (nPerm + 1.0);
    report.p_floor = pyRound(floorP, 6);
    report.saturated = worst.adj_p <= pyRound(floorP, 4) + 1e-12;
    if (report.saturated) {
      report.saturation_note = "adjusted p is AT the permutation floor 1/(" + nPerm + "+1) = " +
        floorP.toFixed(5) + ". This is the smallest value " + nPerm + " permutations can express, so " +
        "the true p is '<= " + floorP.toFixed(5) + "', not '= " + floorP.toFixed(5) + "'. Raise the " +
        "permutation count to resolve further; it cannot change the verdict.";
    }
    report.verdict = worst.adj_p < alpha ? "DISQUALIFIED" : "PASS";
    // BORDERLINE — mirrors nulltest.py. A family-adjusted p within a factor of two of alpha, either
    // side, is a verdict the family size alone could have flipped; say so.
    report.borderline = alpha / 2 <= worst.adj_p && worst.adj_p < 2 * alpha;
    if (report.borderline) {
      report.borderline_note = report.verdict + ", but the worst cell's family-adjusted p (" + pyf(worst.adj_p) +
        ") is within a factor of two of alpha (" + pyRound(alpha, 2).toFixed(2) + "). Treat this as 'close to " +
        "the line at this n and this family size', not as " + (report.verdict === "PASS" ? "clean" : "settled") +
        ". More items, or a different family size, could flip it either way.";
    }
    // MEASURED POWER — mirrors nulltest.py's _power_note exactly. Measured 2026-07-25 by planting
    // a +1-char marker on a fraction of the label-1 half of a clean synthetic base and finding the
    // smallest fraction caught in >=3 of 4 seeds (grid 15/30/60/100%). Low power costs DETECTIONS,
    // not false alarms, so a verdict that fired stands at any n; a PASS at small n does not.
    var MDE = [[1496, 0.15], [702, 0.30], [324, 0.60], [156, 0.60]];
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
    report.power = { n: report.n, measured_mde: mde,
      mde_basis: "one planted spelling/length artifact (a character appended to a fraction of " +
                 "the label-1 items) in a single stratum, 4 seeds; a wider family, a smaller " +
                 "cell or an artifact of another shape lowers power below this",
      comparable_across_batteries: false,
      note_on_comparison: "A* depends on n. Do not rank this battery against one of a different size: cities.csv is DISQUALIFIED at n=1496 and PASSES 5 of 5 subsamples at n=354.",
      reading: rd };
    report.headline = "worst cell A* = " + pyf(worst.astar) + " in " + worst["null"] + "/" +
      worst.stratum + " (n=" + worst.n + "), family-adjusted p = " + pyf(worst.adj_p) +
      " over " + ks.length + " cells";
    report.scope = SCOPE;
    return report;
  }

  /* nulltest.py's item_text and the strata expression, with Python's str() of each value. */
  function itemText(it, tk) {
    if (Array.isArray(tk)) return tk.map(function (k) { return k in it ? pyStr(it[k]) : ""; }).join("\n");
    return pyStr(it[tk]);
  }
  function strataOf(items, sk) {
    return sk ? items.map(function (i) { return i[sk] === undefined ? "_all" : pyStr(i[sk]); })
              : items.map(function () { return "_all"; });
  }

  /* ── input handling — same key sniffing and label coercion as the CLI ────── */
  var TEXT_KEYS = ["entity", "text", "claim", "statement", "question", "answer", "response", "name",
                   "prompt", "title", "sentence"];
  var LABEL_KEYS = ["label", "y", "is_fake", "fabricated", "hallucinated", "hallucination", "type",
                    "kind", "truth", "is_true"];
  var STRATUM_KEYS = ["category", "domain", "stratum", "cell", "topic", "source", "task"];
  var POSITIVE_WORDS = ["fake", "fabrication", "fabricated", "false", "1", "coined", "hallucinated",
                        "hallucination", "unfaithful", "incorrect", "wrong", "no", "yes_hallucinated"];
  var NEGATIVE_WORDS = ["real", "true", "0", "genuine", "faithful", "correct", "right", "yes", "known",
                        "grounded"];

  function parseCSV(raw, sep) {
    // Python's csv "excel" dialect: a quote opens a quoted field ONLY as the field's first
    // character; anywhere else it is a literal (he said "hi" there). v1.3 toggled quoting on any
    // quote, so one mid-field quote swallowed the rest of the file in silence. Doubled quotes
    // inside quotes, CR/LF line ends, and a short row's missing columns are None, as DictReader
    // fills them (restval=None).
    var rows = [], row = [], field = "", i = 0, q = false, atStart = true;
    while (i < raw.length) {
      var ch = raw[i];
      if (q) {
        if (ch === '"') { if (raw[i + 1] === '"') { field += '"'; i++; } else q = false; }
        else field += ch;
      } else if (ch === '"' && atStart) { q = true; atStart = false; }
      else if (ch === sep) { row.push(field); field = ""; atStart = true; }
      else if (ch === "\n" || ch === "\r") {
        if (ch === "\r" && raw[i + 1] === "\n") i++;
        row.push(field); rows.push(row); row = []; field = ""; atStart = true;
      } else { field += ch; atStart = false; }
      i++;
    }
    if (field.length || row.length) { row.push(field); rows.push(row); }
    if (!rows.length) return [];
    var head = rows[0];
    return rows.slice(1).filter(function (r) { return r.length > 1 || (r.length === 1 && r[0] !== ""); })
      .map(function (r) { var o = {}; head.forEach(function (h, j) { o[h] = r[j] === undefined ? null : r[j]; }); return o; });
  }

  /* Map whatever the label column holds onto 0/1, or refuse — nulltest.py's coerce_labels.
     v1.2 mapped any unrecognised string to 0 silently; a yes/no corpus came out backwards and
     a hallucinated/faithful one came out all-zero, and both looked like ordinary runs. */
  function coerceLabels(items, lk, positive) {
    var vals = items.map(function (it) {
      var v = it[lk];
      if (typeof v === "boolean") v = v ? "1" : "0";
      return pyStr(v).trim();
    });
    var distinct = sortCp(Array.from(new Set(vals)));
    if (distinct.length !== 2)
      throw new Error("the label field '" + lk + "' holds " + distinct.length + " distinct values (" +
                      distinct.slice(0, 6).join(", ") + "); this test needs exactly two.");
    var pos;
    if (positive !== undefined && positive !== null) {   // python: `positive is not None` — "" is refused below, not ignored
      pos = String(positive).trim();
      if (distinct.indexOf(pos) < 0) throw new Error("positive label '" + pos + "' is not one of " + distinct.join(" / "));
    } else {
      var low = distinct.map(function (d) { return d.toLowerCase(); });
      if (POSITIVE_WORDS.indexOf(low[0]) >= 0 && NEGATIVE_WORDS.indexOf(low[1]) >= 0) pos = distinct[0];
      else if (POSITIVE_WORDS.indexOf(low[1]) >= 0 && NEGATIVE_WORDS.indexOf(low[0]) >= 0) pos = distinct[1];
      else if (low[0] === "0" && low[1] === "1") pos = distinct[1];
      else if (low[0] === "0.0" && low[1] === "1.0") pos = distinct[1];
      else throw new Error("the label field '" + lk + "' holds '" + distinct[0] + "' and '" + distinct[1] +
                           "' and the tool cannot tell which one is the fabricated/false class. Say which " +
                           "(positive label). It will not guess.");
    }
    return { items: items.map(function (it, i) { var c = {}; for (var k in it) c[k] = it[k]; c[lk] = vals[i] === pos ? 1 : 0; return c; }),
             positive: pos };
  }

  /* opts: { text, label, stratum, positive } — any of them overrides the sniffing. `text` may
     be "a,b": the fields are joined with a newline when scored, as the CLI does. */
  function loadItems(raw, opts) {
    opts = opts || {};
    var items;
    // utf-8-sig and universal newlines, as Python's open() reads the file: the BOM goes, and a
    // \r\n inside a quoted CSV field becomes \n, so the length probe counts the same characters
    raw = String(raw).replace(/^\ufeff/, "").replace(/\r\n?/g, "\n");
    var trimmed = raw.trim();
    if (!trimmed) throw new Error("nothing to read");
    if (trimmed[0] !== "[" && trimmed[0] !== "{") {
      var firstLine = trimmed.split("\n")[0];
      var sep = firstLine.indexOf("\t") >= 0 ? "\t" : ",";
      items = parseCSV(raw, sep);
      if (!items.length) throw new Error("that is not JSON, and did not parse as CSV/TSV either");
    } else {
      try { items = JSON.parse(trimmed); }
      catch (e) { items = trimmed.split("\n").filter(function (l) { return l.trim(); }).map(function (l) { return JSON.parse(l); }); }
    }
    if (!Array.isArray(items)) {
      var found = null;
      ["items", "battery", "data", "rows", "examples", "instances"].forEach(function (k) {
        if (!found && Array.isArray(items[k])) found = items[k];
      });
      if (!found) throw new Error("could not find a list of items (looked for items / battery / data / rows / examples / instances)");
      items = found;
    }
    if (!items.length) throw new Error("the list of items is empty");

    var keys = new Set();
    items.slice(0, 200).forEach(function (it) { if (it && typeof it === "object") Object.keys(it).forEach(function (k) { keys.add(k); }); });
    function sniff(cands) { for (var i = 0; i < cands.length; i++) if (keys.has(cands[i])) return cands[i]; return null; }
    var tk = opts.text || sniff(TEXT_KEYS);
    var lk = opts.label || sniff(LABEL_KEYS);
    var sk = opts.stratum || sniff(STRATUM_KEYS);
    if (!tk) throw new Error("no text field found (looked for " + TEXT_KEYS.join(" / ") + "). The items carry: " + Array.from(keys).slice(0, 20).join(", "));
    if (!lk) throw new Error("no label field found (looked for " + LABEL_KEYS.join(" / ") + "). The items carry: " + Array.from(keys).slice(0, 20).join(", "));
    var tkeys = tk.indexOf(",") >= 0 ? tk.split(",").map(function (x) { return x.trim(); }).filter(Boolean) : [tk];

    var out = items.filter(function (it) {
      return it && it[lk] !== undefined && tkeys.every(function (k) { return it[k] !== undefined; });
    });
    if (!out.length) throw new Error("no item had both a text field and a label field");
    var coerced = coerceLabels(out, lk, opts.positive);
    return { items: coerced.items, keys: { text: tkeys.length > 1 ? tkeys : tk, label: lk, stratum: sk },
             positive: coerced.positive };
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

  /* ── EXPLAIN — mirrors nulltest.py's explain_cell / explain ──────────────
     An in-sample description of the separating cells: the n-grams, words, length gap or
     initials that carry the label. For FINDING the artifact, never for the verdict, which is
     held-out and permutation-calibrated. Same thresholds (min_count 3, top 8) as the CLI. */
  function median(xs) {
    var a = xs.slice().sort(function (p, q) { return p - q; }), n = a.length;
    if (!n) return null;
    return n % 2 ? a[(n - 1) / 2] : 0.5 * (a[n / 2 - 1] + a[n / 2]);
  }
  function showFeature(name, g) { return "'" + (name === "lexicality" ? g.replace(/ /g, "␣") : g) + "'"; }
  function explainCell(name, texts, y, top, minCount) {
    top = top || 8; minCount = minCount || 3;
    var kind = NULLS[name][0], fn = NULLS[name][1];
    var n1 = y.reduce(function (a, b) { return a + b; }, 0), n0 = y.length - n1;
    var out = { probe: name, n: y.length, n_label0: n0, n_label1: n1 };
    if (kind === "nb") {
      var pos = new Map(), neg = new Map();
      var feats = texts.map(function (t) { return fn(t); });
      feats.forEach(function (f, i) {
        var d = y[i] === 1 ? pos : neg;
        f.forEach(function (g) { d.set(g, (d.get(g) || 0) + 1); });
      });
      var rows = [];
      new Set([].concat(Array.from(pos.keys()), Array.from(neg.keys()))).forEach(function (g) {
        var p = pos.get(g) || 0, q = neg.get(g) || 0;
        if (p + q < minCount) return;
        var lo = Math.log((p + 0.5) / (n1 + 1.0)) - Math.log((q + 0.5) / (n0 + 1.0));
        rows.push([lo, g, p, q]);
      });
      rows.sort(function (a, b) { return a[0] - b[0] || cpCmp(a[1], b[1]); });   // python: tuple sort
      var row = function (r) { return { feature: r[1], in_label1: r[2], in_label0: r[3], log_odds: pyRound(r[0], 2) }; };
      var fav1 = rows.slice(-top).reverse().filter(function (r) { return r[0] > 0; }).map(row);
      var fav0 = rows.slice(0, top).filter(function (r) { return r[0] < 0; }).map(row);
      out.favours_label1 = fav1; out.favours_label0 = fav0;
      var score = feats.map(function (f) {
        // python: sum(fav1 terms) + sum(fav0 terms) — two partial sums, then added. One running
        // total associates differently and can break a tie the other way.
        var fs = new Set(f), s1 = 0, s0 = 0;
        fav1.forEach(function (r) { if (fs.has(r.feature)) s1 += r.log_odds; });
        fav0.forEach(function (r) { if (fs.has(r.feature)) s0 += r.log_odds; });
        return s1 + s0;
      });
      var idx = y.map(function (_, i) { return i; });
      var ones = idx.filter(function (i) { return y[i] === 1; }).sort(function (a, b) { return score[b] - score[a] || a - b; }).slice(0, 2);
      var zeros = idx.filter(function (i) { return y[i] === 0; }).sort(function (a, b) { return score[a] - score[b] || a - b; }).slice(0, 2);
      var cut = function (t) { return cps(t).slice(0, 120).join(""); };   // python: t[:120], code points
      out.examples = { label1: ones.map(function (i) { return cut(texts[i]); }),
                       label0: zeros.map(function (i) { return cut(texts[i]); }) };
      var sf = function (r) { return showFeature(name, r.feature); };
      out.reading = "features over-represented in label-1: " + (fav1.slice(0, 5).map(sf).join(", ") || "none") +
                    "; in label-0: " + (fav0.slice(0, 5).map(sf).join(", ") || "none");
    } else if (kind === "score") {
      var s = texts.map(function (t) { return Number(fn(t)); });
      var m0 = median(s.filter(function (_, i) { return y[i] === 0; }));
      var m1 = median(s.filter(function (_, i) { return y[i] === 1; }));
      out.median_label0 = m0; out.median_label1 = m1;
      if (name === "length") {
        out.reading = "label-1 items are " + (m1 > m0 ? "longer" : m1 < m0 ? "shorter" : "the same length") +
                      ": median " + pyRound(m1) + " vs " + pyRound(m0) + " characters";
      } else {
        var letter = function (v) { return (v >= 1 && v <= 26) ? String.fromCharCode(96 + pyRound(v)) : "non-letter"; };
        out.reading = (name === "alpha_first" ? "first" : "last") + "-word initials: label-1 median '" + letter(m1) +
                      "' vs label-0 median '" + letter(m0) + "' (alphabet position " + pyRound(m1, 1).toFixed(1) + " vs " + pyRound(m0, 1).toFixed(1) + ")";
      }
    } else {
      out.reading = "the label-1 rate differs between strata; see the per-stratum counts";
    }
    return out;
  }
  function explain(items, keys, rep, maxCells) {
    maxCells = maxCells || 8;
    var tk = keys.text, lk = keys.label, sk = keys.stratum;
    var texts = items.map(function (i) { return itemText(i, tk); });
    var y = items.map(function (i) { return parseInt(i[lk], 10) || 0; });
    var strata = strataOf(items, sk);
    var cells = [];
    Object.keys(rep.nulls).forEach(function (nm) {
      var e = rep.nulls[nm];
      Object.keys(e.per_stratum).forEach(function (st) {
        var c = e.per_stratum[st];
        if (c.separates) cells.push([nm, st, c]);
      });
    });
    var w = rep.worst_cell || {};
    if (!cells.length && w.null) cells.push([w.null, w.stratum, rep.nulls[w.null].per_stratum[w.stratum]]);
    cells.sort(function (a, b) { return a[2].adj_p - b[2].adj_p || b[2].astar - a[2].astar; });
    // one cell per probe first, so a corpus whose `length` cells all separate still shows what the
    // words/shape/lexicality readings say; then the remaining cells in order — as nulltest.py
    var first = [], rest = [], seen = new Set();
    cells.forEach(function (t) { (seen.has(t[0]) ? rest : first).push(t); seen.add(t[0]); });
    cells = first.concat(rest);
    var out = { note: "In-sample description of the separating cells, for finding the artifact. The " +
                      "verdict above is held-out; these tables are not evidence for it.", cells: [] };
    cells.slice(0, maxCells).forEach(function (t) {
      var idx = []; strata.forEach(function (x, i) { if (x === t[1]) idx.push(i); });
      var d = explainCell(t[0], idx.map(function (i) { return texts[i]; }), idx.map(function (i) { return y[i]; }));
      d.stratum = t[1]; d.astar = t[2].astar; d.adj_p = t[2].adj_p;
      out.cells.push(d);
    });
    return out;
  }

  global.NullTest = { VERSION: VERSION, PROBES: Object.keys(NULLS), _MT: MT, _scoreAllCells: scoreAllCells,
                      _cellDefs: cellDefs, _Prepared: Prepared, evaluate: evaluate, evaluateAsync: evaluateAsync,
                      loadItems: loadItems, coerceLabels: coerceLabels, explain: explain, explainCell: explainCell, parseCSV: parseCSV, astar: astar,
                      pyRound: pyRound, pyStr: pyStr,
                      auroc: auroc, plantedSeparable: plantedSeparable, plantedClean: plantedClean };
})(window);
