// A small picture out of TIFF and the camera formats built on it (DNG, CR2, NEF, ARW, ORF, RW2, PEF, ...), in the
// browser, without a library (Janis, 14.11.2026: every file that is a picture gets a preview). Browsers other than
// Safari can not draw these files; most of them carry a finished JPEG preview inside, and a plain TIFF keeps its
// pixels uncompressed, LZW or Deflate. The server never opens these files: all reading happens here, in the page.
//   HubTiff.preview(arrayBuffer, large) -> Promise of { blob: JPEG Blob } or { image: ImageData } or null, plus `turn`
//   (the EXIF orientation: 1 normal, 3 upside down, 6 right, 8 left). `large`: the biggest picture inside (for the
//   viewer), else the smallest that still fills a small preview.
(function () {
  "use strict";
  var SIZE = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4 };
  var MAX_PIXELS = 50e6;      // a plain TIFF is decoded whole: beyond this the page would need too much memory

  function reader(buffer) {
    var view = new DataView(buffer);
    var order = view.getUint16(0);
    var little = order === 0x4949;
    if (!little && order !== 0x4d4d) return null;
    var magic = view.getUint16(2, little);
    if (magic !== 42 && magic !== 0x4f52 && magic !== 0x5352 && magic !== 0x55) return null;   // TIFF, ORF, RW2
    return {
      view: view, little: little, length: buffer.byteLength,
      u16: function (at) { return view.getUint16(at, little); },
      u32: function (at) { return view.getUint32(at, little); },
      first: view.getUint32(4, little)
    };
  }

  // One IFD: its tags as { tag: [values] } (numbers only; offsets and counts are what we need).
  function readIfd(r, at) {
    if (at < 8 || at + 2 > r.length) return null;
    var count = r.u16(at);
    if (count === 0 || count > 1000 || at + 2 + count * 12 + 4 > r.length) return null;
    var tags = {};
    for (var i = 0; i < count; i++) {
      var e = at + 2 + i * 12;
      var tag = r.u16(e), type = r.u16(e + 2), n = r.u32(e + 4), size = SIZE[type] || 1;
      if (n > 1e6) continue;
      var where = n * size <= 4 ? e + 8 : r.u32(e + 8);
      if (where + n * size > r.length) continue;
      var values = [];
      for (var k = 0; k < Math.min(n, 4096); k++) {
        var p = where + k * size;
        values.push(type === 3 || type === 8 ? r.u16(p) : (type === 4 || type === 9 || type === 13) ? r.u32(p)
          : (type === 1 || type === 6 || type === 7) ? r.view.getUint8(p) : (type === 5 ? r.u32(p) / (r.u32(p + 4) || 1) : 0));
      }
      tags[tag] = values;
    }
    return { tags: tags, next: r.u32(at + 2 + count * 12) };
  }

  // Every IFD of the file: the chain, their sub-IFDs (where cameras keep previews) and the EXIF IFD.
  function allIfds(r) {
    var found = [], seen = {}, queue = [r.first];
    while (queue.length && found.length < 64) {
      var at = queue.shift();
      if (!at || seen[at]) continue;
      seen[at] = true;
      var ifd = readIfd(r, at);
      if (!ifd) continue;
      found.push(ifd);
      queue.push(ifd.next);
      (ifd.tags[330] || []).forEach(function (sub) { queue.push(sub); });
      if (ifd.tags[34665]) queue.push(ifd.tags[34665][0]);
    }
    return found;
  }

  // A JPEG the browser can draw: baseline or progressive, not the lossless kind (SOF3) of raw data.
  function drawableJpeg(bytes) {
    if (bytes.length < 4 || bytes[0] !== 0xff || bytes[1] !== 0xd8) return false;
    for (var i = 2; i + 3 < bytes.length && i < 65536;) {
      if (bytes[i] !== 0xff) { i++; continue; }
      var marker = bytes[i + 1];
      if (marker === 0xc0 || marker === 0xc1 || marker === 0xc2) return true;
      if (marker === 0xc3 || (marker >= 0xc5 && marker <= 0xcf && marker !== 0xc8 && marker !== 0xcc)) return false;
      if (marker === 0xd8 || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7)) { i += 2; continue; }
      i += 2 + ((bytes[i + 2] << 8) | bytes[i + 3]);
    }
    return false;
  }

  function jpegCandidates(r, ifds) {
    var out = [];
    ifds.forEach(function (ifd) {
      var t = ifd.tags, spans = [];
      if (t[513] && t[514]) spans.push([t[513][0], t[514][0]]);
      var comp = t[259] ? t[259][0] : 1;
      if ((comp === 6 || comp === 7 || comp === 99) && t[273] && t[279] && t[273].length === 1) spans.push([t[273][0], t[279][0]]);
      spans.forEach(function (s) {
        if (s[0] > 0 && s[1] > 1000 && s[0] + s[1] <= r.length) {
          var bytes = new Uint8Array(r.view.buffer, s[0], s[1]);
          if (drawableJpeg(bytes)) out.push(bytes);
        }
      });
    });
    return out.sort(function (a, b) { return a.length - b.length; });
  }

  function lzw(input, expected) {
    var out = new Uint8Array(expected), pos = 0, table = [], bit = 0, width = 9, prev = null;
    function reset() { table = []; for (var i = 0; i < 256; i++) table.push([i]); table.push(null, null); width = 9; prev = null; }
    reset();
    while (pos < expected) {
      if ((bit >> 3) + 2 >= input.length + 1) break;
      var a = input[bit >> 3] || 0, b = input[(bit >> 3) + 1] || 0, c = input[(bit >> 3) + 2] || 0;
      var code = (((a << 16) | (b << 8) | c) >> (24 - (bit & 7) - width)) & ((1 << width) - 1);
      bit += width;
      if (code === 256) { reset(); continue; }
      if (code === 257) break;
      var entry = code < table.length && table[code] ? table[code] : (prev ? prev.concat(prev[0]) : null);
      if (!entry) break;
      for (var k = 0; k < entry.length && pos < expected; k++) out[pos++] = entry[k];
      if (prev) table.push(prev.concat(entry[0]));
      prev = entry;
      if (table.length + 1 >= (1 << width) && width < 12) width++;
    }
    return out;
  }

  function inflate(bytes) {
    if (typeof DecompressionStream !== "function") return Promise.resolve(null);
    var stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate"));
    return new Response(stream).arrayBuffer().then(function (b) { return new Uint8Array(b); }, function () { return null; });
  }

  // A plain image: 8 bits, grey or RGB(A), in strips, uncompressed, LZW or Deflate (with or without predictor).
  function plainImage(r, ifds, large) {
    var best = null;
    ifds.forEach(function (ifd) {
      var t = ifd.tags, w = t[256] && t[256][0], h = t[257] && t[257][0];
      var comp = t[259] ? t[259][0] : 1, spp = t[277] ? t[277][0] : 1, photo = t[262] ? t[262][0] : 1;
      var bits = t[258] || [1];
      if (!w || !h || w * h > MAX_PIXELS || !t[273] || !t[279] || (t[284] && t[284][0] !== 1)) return;
      if (bits.some(function (b) { return b !== 8; }) || [1, 5, 8, 32946].indexOf(comp) < 0) return;
      if (!((photo === 2 && (spp === 3 || spp === 4)) || ((photo === 0 || photo === 1) && spp <= 2))) return;
      var candidate = { w: w, h: h, comp: comp, spp: spp, photo: photo, offsets: t[273], counts: t[279],
                        rows: t[278] ? t[278][0] : h, predictor: t[317] ? t[317][0] : 1 };
      // the smallest one that still fills a preview, else the biggest (for the viewer: the biggest)
      if (!best || (large ? w * h > best.w * best.h
          : (best.w * best.h < 96 * 96 ? w * h > best.w * best.h : (w * h >= 96 * 96 && w * h < best.w * best.h)))) best = candidate;
    });
    if (!best) return Promise.resolve(null);
    var line = best.w * best.spp;
    var parts = best.offsets.map(function (offset, i) {
      var raw = new Uint8Array(r.view.buffer, offset, Math.min(best.counts[i] || 0, r.length - offset));
      var rows = Math.min(best.rows, best.h - i * best.rows);
      if (best.comp === 1) return Promise.resolve(raw);
      if (best.comp === 5) return Promise.resolve(lzw(raw, rows * line));
      return inflate(raw);
    });
    return Promise.all(parts).then(function (strips) {
      var data = new Uint8ClampedArray(best.w * best.h * 4), row = 0;
      for (var s = 0; s < strips.length && strips[s]; s++) {
        var strip = strips[s];
        for (var y = 0; y < best.rows && row < best.h; y++, row++) {
          var base = y * line;
          if (best.predictor === 2) for (var x = best.spp; x < line; x++) strip[base + x] = (strip[base + x] + strip[base + x - best.spp]) & 255;
          for (var px = 0; px < best.w; px++) {
            var o = (row * best.w + px) * 4, i = base + px * best.spp;
            if (best.spp >= 3) { data[o] = strip[i]; data[o + 1] = strip[i + 1]; data[o + 2] = strip[i + 2]; }
            else { var g = best.photo === 0 ? 255 - strip[i] : strip[i]; data[o] = data[o + 1] = data[o + 2] = g; }
            data[o + 3] = 255;
          }
        }
      }
      return new ImageData(data, best.w, best.h);
    });
  }

  function preview(buffer, large) {
    var r;
    try { r = reader(buffer); } catch (e) { r = null; }
    if (!r) return Promise.resolve(null);
    var ifds = allIfds(r);
    if (!ifds.length) return Promise.resolve(null);
    var turn = ifds[0].tags[274] ? ifds[0].tags[274][0] : 1;
    var jpegs = jpegCandidates(r, ifds);
    if (jpegs.length) {
      var pick = large ? jpegs[jpegs.length - 1] : (jpegs.filter(function (j) { return j.length > 4000; })[0] || jpegs[jpegs.length - 1]);
      return Promise.resolve({ blob: new Blob([pick], { type: "image/jpeg" }), turn: turn });
    }
    return plainImage(r, ifds, large).then(function (image) { return image ? { image: image, turn: turn } : null; },
                                    function () { return null; });
  }

  window.HubTiff = { preview: preview };
})();
