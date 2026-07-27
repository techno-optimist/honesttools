// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Kevin Russell (Aperture / Project Forty Two)
/* verify_widget.js — interactive receipt verification that runs in the READER'S browser.
 *
 * No terminal, no download, no account. The signature check happens on their machine against a
 * key written into the page source; we never tell the page whether the receipt is good.
 *
 * Byte-for-byte identical to aperture_verify.py:
 *   1. strip the unsigned fields (signature, id)
 *   2. canonicalise: keys sorted recursively, separators ",", ":", unicode raw
 *   3. ed25519-verify base64(signature.sig) over those bytes with base64(signature.pub)
 *   4. signature.pub MUST be pinned — a valid signature by an unknown key is a forgery
 *
 * TWO TRAPS, both caught by comparing against Python in a browser BEFORE this shipped:
 *   - Python writes the float 1.0 as "1.0"; JSON.parse collapses it to 1 and JSON.stringify
 *     writes "1", losing two bytes and breaking the signature. So we parse with a tokenizer
 *     that preserves every number's original literal text. (JS 2601 vs PY 2603 bytes.)
 *   - The transparency-log leaf is DOMAIN-SEPARATED: sha256("aperture.receipt.leaf/v1\0" + body).
 *     Omitting the prefix yields a plausible-looking wrong hash.
 */
(function () {
  "use strict";

  var PINS = {
    "U9pHq3UwrFT5oyLwOnSgt+J6YpCkG1zUEcOO4Sxm7hA=":
      "registry (2f48ea75c592) — /api/read receipts + verify/photon primary certs"
  };
  var LEAF_DOMAIN = "aperture.receipt.leaf/v1\u0000";   // NUL byte, not a space — see aperture_verify.py leaf_hash

  var go, tam, out, RAW = null, ID = "f0c39b1d0a5b";

  /* ---- JSON parse that keeps number literals verbatim ---- */
  function parseKeepNums(text) {
    var i = 0;
    function ws() { while (i < text.length && " \t\n\r".indexOf(text[i]) >= 0) i++; }
    function str() {
      var st = i; i++;
      while (i < text.length) {
        if (text[i] === "\\") { i += 2; continue; }
        if (text[i] === '"') { i++; break; }
        i++;
      }
      return JSON.parse(text.slice(st, i));
    }
    function val() {
      ws();
      var c = text[i];
      if (c === "{") {
        i++; var o = {}; ws();
        if (text[i] === "}") { i++; return o; }
        for (;;) {
          ws(); var k = str(); ws(); i++;
          o[k] = val(); ws();
          if (text[i] === ",") { i++; continue; }
          i++; return o;
        }
      }
      if (c === "[") {
        i++; var a = []; ws();
        if (text[i] === "]") { i++; return a; }
        for (;;) {
          a.push(val()); ws();
          if (text[i] === ",") { i++; continue; }
          i++; return a;
        }
      }
      if (c === '"') return str();
      if (text.substr(i, 4) === "true") { i += 4; return true; }
      if (text.substr(i, 5) === "false") { i += 5; return false; }
      if (text.substr(i, 4) === "null") { i += 4; return null; }
      var st = i;
      while (i < text.length && "-+.eE0123456789".indexOf(text[i]) >= 0) i++;
      return { __num: text.slice(st, i) };
    }
    return val();
  }

  function canon(o) {
    if (o !== null && typeof o === "object" && "__num" in o && Object.keys(o).length === 1) return o.__num;
    if (o === null || typeof o !== "object") return JSON.stringify(o);
    if (Array.isArray(o)) return "[" + o.map(canon).join(",") + "]";
    return "{" + Object.keys(o).sort().map(function (k) {
      return JSON.stringify(k) + ":" + canon(o[k]);
    }).join(",") + "}";
  }

  function b64(s) {
    var b = atob(s), a = new Uint8Array(b.length);
    for (var j = 0; j < b.length; j++) a[j] = b.charCodeAt(j);
    return a;
  }
  function hex(buf) {
    return Array.prototype.map.call(new Uint8Array(buf), function (x) {
      return ("0" + x.toString(16)).slice(-2);
    }).join("");
  }
  function concat(a, b) {
    var r = new Uint8Array(a.length + b.length);
    r.set(a, 0); r.set(b, a.length);
    return r;
  }

  async function check(rec) {
    var sig = rec.signature, k;
    if (!sig || !sig.sig || !sig.pub) {
      return { ok: false, reason: "no ed25519 signature block — an unsigned receipt is theater" };
    }
    var role = PINS[sig.pub];
    if (!role) {
      return { ok: false, reason: "signature key is not pinned — a correct signature by an unknown key is a forgery" };
    }
    var body = {};
    for (k in rec) if (k !== "signature" && k !== "id") body[k] = rec[k];
    var enc = new TextEncoder(), cb = enc.encode(canon(body));
    var key = await crypto.subtle.importKey("raw", b64(sig.pub), { name: "Ed25519" }, false, ["verify"]);
    var ok = await crypto.subtle.verify({ name: "Ed25519" }, key, b64(sig.sig), cb);

    var signed = {};
    for (k in rec) if (k !== "id") signed[k] = rec[k];
    var leaf = hex(await crypto.subtle.digest("SHA-256",
      concat(enc.encode(LEAF_DOMAIN), enc.encode(canon(signed)))));

    return {
      ok: ok, key: sig.pub, role: role, bytes: cb.length, leaf: leaf,
      reason: ok ? null : "SIGNATURE INVALID — the receipt was altered, or the signature does not match"
    };
  }

  function paint(r, tampered) {
    if (r.ok) {
      out.innerHTML =
        '<span style="color:#57d6a0">&#10003; VERIFIED</span> — signed by the Aperture registry, unaltered.\n' +
        "  key   " + r.key + "\n        " + r.role + "\n" +
        "  id    " + ID + "\n" +
        "  kind  read · " + r.bytes + " bytes signed\n" +
        "  leaf  " + r.leaf.slice(0, 48) + "\n" +
        "  note  provenance, not truth — this proves what was signed, not that the answer is correct.";
    } else {
      out.innerHTML =
        '<span style="color:#e0566b">&#10007; NOT VERIFIED</span> — ' + r.reason +
        (tampered ? "\n\n  one character changed — and the signature no longer matches the bytes." : "");
    }
  }

  async function run(tamper) {
    out.textContent = "working, in your browser…";
    try {
      if (!RAW) {
        var res = await fetch("/api/read/" + ID, { cache: "no-store" });
        RAW = await res.text();
      }
      var whole = parseKeepNums(RAW);
      var rec = (whole && whole.receipt !== undefined) ? whole.receipt : whole;
      if (tamper) rec.answer = (rec.answer || "") + " ";
      paint(await check(rec), tamper);
      tam.disabled = false;
      if (tamper) tam.textContent = "signature broken";
    } catch (e) {
      out.innerHTML =
        '<span style="color:#e0566b">could not run here</span> — ' + ((e && e.message) ? e.message : e) +
        "\n\n  this needs WebCrypto Ed25519 (Chrome 137+, Safari 17+, Firefox 129+).\n" +
        "  the offline command below performs the identical check with no browser at all.";
    }
  }

  function init() {
    go = document.getElementById("vbGo");
    tam = document.getElementById("vbTamper");
    out = document.getElementById("vbOut");
    if (!go) return;
    go.addEventListener("click", function () { run(false); });
    tam.addEventListener("click", function () { run(true); });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
