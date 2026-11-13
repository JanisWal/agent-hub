// The upload engine of the file storage (web/app/files.py), rebuilt from what proven systems do (Janis, 13.11.2026):
//  - tus: the SERVER is the truth. A file is made first, and what it already holds is asked for (`progress`), so an
//    upload that broke off (closed tab, lost line, reload) goes on from there and sends only what is missing.
//  - Nextcloud's desktop client: the size of a request follows the measured speed so that one takes about a fixed
//    time (min and max bounds); a slow line gets small requests, a fast line big ones. After a request that timed out,
//    the next ones are smaller for a while.
//  - Uppy and tus-js-client: a failed request is sent again after growing pauses; while the browser is offline it waits
//    instead of using up its tries. Timeouts are layered: a request with no progress for a while, or one that takes
//    too long, is given up on here, before the tunnel's own limit (about 100 s) cuts it.
//  - The speed shown is what the browser has sent over the last seconds (not only what was confirmed, which on a slow
//    line comes late), without the part that was already on the server at a resume.
// The server counts in blocks (files.BLOCK_SIZE); a request is any run of missing blocks, in any order.
// This file knows nothing about the page: files.js gives it the addresses and listens to its events.
(function () {
  "use strict";

  var DEFAULTS = {
    parallel: 2,                         // requests on their way at the same time, over all files
    startRequest: 1048576,               // size of a request before the speed is known
    minRequest: 524288,
    maxRequest: 33554432,
    targetSeconds: 15,                   // what one request should take
    delays: [0, 1000, 3000, 5000, 10000],// pauses before each new try of a request
    stall: 45000,                        // no progress for this long: give up on the request
    timeout: 90000,                      // longest a request may take
    window: 10000,                       // the speed is measured over this long
    minSpan: 3000                        // and shown after this long
  };

  function create(options) {
    var cfg = {};
    Object.keys(DEFAULTS).forEach(function (key) { cfg[key] = DEFAULTS[key]; });
    Object.keys(options.config || {}).forEach(function (key) { cfg[key] = options.config[key]; });
    var block = options.block;
    var urls = options.urls;                     // start, progress(id), chunk(id), finish(id), remove(id)
    var text = options.text || {};               // net: the message for a line that broke
    var jobs = [];
    var running = 0;
    var samples = [];
    var speed = 0;
    var penalty = 1;                             // 1 = normal; smaller after a request timed out
    var ticker = null;
    var activeKeys = {};
    var CANCELLED = { cancelled: true };

    function emit(name, a, b) { if (options[name]) options[name](a, b); }

    // --- small helpers
    function call(url, body, method) {
      return fetch(url, { method: method || "POST", body: body, credentials: "same-origin" }).then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (data) {
          if (!response.ok || !data.ok) { var problem = new Error(data.message || text.net); problem.status = response.status; throw problem; }
          return data;
        });
      }, function () { var problem = new Error(text.net); problem.network = true; throw problem; });
    }
    function form(values) {
      var body = new FormData();
      Object.keys(values).forEach(function (key) { body.append(key, values[key]); });
      return body;
    }
    function keyOf(file) {
      return [options.scope || "", file.name, file.size, file.lastModified || 0].join("|");
    }
    function remember(job) {
      try {
        var all = JSON.parse(localStorage.getItem("hub-uploads") || "{}");
        all[job.key] = { id: job.id, at: Date.now() };
        Object.keys(all).forEach(function (key) { if (Date.now() - all[key].at > 86400000) delete all[key]; });   // the server drops them after a day
        localStorage.setItem("hub-uploads", JSON.stringify(all));
      } catch (e) {}
    }
    function recall(job) {
      try { var found = JSON.parse(localStorage.getItem("hub-uploads") || "{}")[job.key]; return found ? found.id : null; } catch (e) { return null; }
    }
    function forget(job) {
      try {
        var all = JSON.parse(localStorage.getItem("hub-uploads") || "{}");
        delete all[job.key];
        localStorage.setItem("hub-uploads", JSON.stringify(all));
      } catch (e) {}
    }

    // --- sizes
    function requestBytes() {
      var bytes = speed > 0 ? speed * cfg.targetSeconds / cfg.parallel : cfg.startRequest;
      bytes = Math.max(cfg.minRequest, Math.min(cfg.maxRequest, bytes * penalty));
      return Math.max(block, Math.floor(bytes / block) * block);
    }
    function sentOf(job) {
      var sum = job.confirmed;
      Object.keys(job.loaded).forEach(function (key) { sum += job.loaded[key]; });
      return sum;
    }

    // --- one request of a run of blocks, with its tries
    function waitOnline() {
      if (typeof navigator === "undefined" || navigator.onLine !== false) return Promise.resolve();
      return new Promise(function (resolve) { window.addEventListener("online", function once() { window.removeEventListener("online", once); resolve(); }); });
    }

    function sendRun(job, run) {
      var blob = job.file.slice(run.offset, run.offset + run.length);
      return new Promise(function (resolve, reject) {
        var attempt = 0;
        function over() { return job.cancelled || job.state === "failed" || job.state === "cancelled"; }   // no ghosts after a failure
        function go() {
          if (over()) return reject(CANCELLED);
          var xhr = new XMLHttpRequest();
          var t0 = Date.now();
          var last = t0;
          var finished = false;
          var dog = setInterval(function () { if (Date.now() - last > cfg.stall) { xhr.__why = "stall"; xhr.abort(); } }, Math.max(50, Math.min(5000, cfg.stall / 4)));
          function done() { finished = true; clearInterval(dog); var at = job.xhrs.indexOf(xhr); if (at >= 0) job.xhrs.splice(at, 1); }
          function again(why) {
            if (finished) return;
            done();
            if (over()) return reject(CANCELLED);
            job.loaded[run.offset] = 0;
            if (why === "stall" || why === "timeout") penalty = Math.max(0.1, penalty * 0.5);   // smaller requests for a while
            if (attempt >= cfg.delays.length) { var fail = new Error(text.net); fail.network = true; return reject(fail); }
            var pause = cfg.delays[attempt++];
            emit("onRetry", job, { why: why, attempt: attempt });
            waitOnline().then(function () { setTimeout(go, pause); });
          }
          job.xhrs.push(xhr);
          xhr.open("POST", urls.chunk(job.id) + "?offset=" + run.offset);
          xhr.timeout = cfg.timeout;
          xhr.upload.onprogress = function (event) { last = Date.now(); if (event.lengthComputable) job.loaded[run.offset] = event.loaded; };
          xhr.onerror = function () { again("network"); };
          xhr.ontimeout = function () { again("timeout"); };
          xhr.onabort = function () { again(xhr.__why || "abort"); };
          xhr.onload = function () {
            if (finished) return;
            var data = {};
            try { data = JSON.parse(xhr.responseText); } catch (e) {}
            if (xhr.status === 200 && data.ok) {
              done();
              emit("onRequest", job, { offset: run.offset, length: run.length, ms: Date.now() - t0, attempt: attempt + 1 });   // for measuring
              resolve();
            }
            else if ([408, 429, 502, 503, 504, 524].indexOf(xhr.status) >= 0) again("status");   // the tunnel hiccuped
            else { done(); var fail = new Error(data.message || text.net); fail.permanent = true; reject(fail); }
          };
          xhr.send(blob);
        }
        go();
      });
    }

    // --- the work of a job
    function nextRun(job) {
      var i = job.scan;
      while (i < job.count && job.blocks[i] !== 0) i++;
      job.scan = i;
      if (i >= job.count) return null;
      var most = Math.max(1, Math.floor(requestBytes() / block));
      var n = 0;
      while (i + n < job.count && job.blocks[i + n] === 0 && n < most) n++;
      for (var k = 0; k < n; k++) job.blocks[i + k] = 2;                       // on its way
      var offset = i * block;
      job.inflight++;
      return { first: i, count: n, offset: offset, length: Math.min(n * block, job.file.size - offset) };
    }

    function nextWork() {
      for (var n = 0; n < jobs.length; n++) {
        var job = jobs[n];
        if (job.state === "new") { job.state = "starting"; return function () { return startJob(job); }; }
        if (job.state !== "sending") continue;
        var run = nextRun(job);
        if (run) return function () { return runJob(job, run); };
        if (job.inflight === 0 && job.confirmedBlocks === job.count) { job.state = "finishing"; return function () { return finishJob(job); }; }
      }
      return null;
    }

    function pump() {
      var work;
      while (running < cfg.parallel && (work = nextWork())) {
        running++;
        work().then(null, function () {}).then(function () { running--; pump(); });
      }
      if (!running && jobs.length && !jobs.some(function (job) { return ["new", "starting", "sending", "finishing"].indexOf(job.state) >= 0; })) idle();
    }

    function adopt(job, parts) {                 // what the server already has: those blocks are done
      for (var i = 0; i < job.count; i++) {
        if (parts.charAt(i) === "1" && job.blocks[i] === 0) {
          job.blocks[i] = 1;
          job.confirmedBlocks++;
          job.confirmed += Math.min(block, job.file.size - i * block);
        }
      }
      job.base = job.confirmed;
    }

    function startJob(job) {
      var known = activeKeys[job.key] ? null : recall(job);   // a second copy of the same file starts afresh
      activeKeys[job.key] = true;
      function fresh() {
        return call(urls.start, form({ name: job.file.name, size: job.file.size })).then(function (info) { job.id = info.id; job.info = info; remember(job); });
      }
      var begin = known ? call(urls.progress(known), null, "GET").then(function (data) {
        if (data.size !== job.file.size) throw new Error("other file");
        job.id = known;
        adopt(job, data.parts);
        remember(job);
      }).catch(function () { return fresh(); }) : fresh();
      return begin.then(function () {
        if (job.cancelled) return call(urls.remove(job.id)).catch(function () {});
        job.state = "sending";
        emit("onStart", job);
      }, function (problem) { failJob(job, problem); });
    }

    function runJob(job, run) {
      return sendRun(job, run).then(function () {
        delete job.loaded[run.offset];
        for (var k = 0; k < run.count; k++) job.blocks[run.first + k] = 1;
        job.confirmedBlocks += run.count;
        job.confirmed += run.length;
        job.inflight--;
        penalty = Math.min(1, penalty * 1.25);                   // requests may grow again
      }, function (problem) { job.inflight--; failJob(job, problem); });
    }

    function finishJob(job) {
      return call(urls.finish(job.id)).then(function (info) {
        return Promise.resolve(options.onDone ? options.onDone(job, info) : null);
      }).then(function () {
        job.state = "done";
        forget(job);
        delete activeKeys[job.key];
        emit("onFinished", job);
      }, function (problem) { failJob(job, problem); });
    }

    function drop(job, state, keepOnServer) {
      job.state = state;
      job.xhrs.slice().forEach(function (xhr) { xhr.abort(); });
      job.loaded = {};
      job.confirmed = 0;
      delete activeKeys[job.key];
      if (job.id && !keepOnServer) { forget(job); call(urls.remove(job.id)).catch(function () {}); }   // an upload that cannot go on is removed
    }
    function failJob(job, problem) {
      if (job.cancelled || problem === CANCELLED || job.state === "failed") return;
      // A line that broke keeps the file on the server and the memory of it: adding the same file again goes on from there.
      drop(job, "failed", !!problem.network);
      emit("onFail", job, problem.message);
    }
    function cancel(job) {
      if (job.cancelled || job.state === "done") return;
      job.cancelled = true;
      drop(job, "cancelled", false);
      emit("onCancel", job);
      pump();
    }

    function idle() {
      jobs = [];
      samples = [];
      speed = 0;
      clearInterval(ticker);
      ticker = null;
      emit("onIdle");
    }

    // --- speed and time left, twice a second
    function tick() {
      var now = Date.now();
      var sent = 0;
      jobs.forEach(function (job) { if (job.state !== "failed" && job.state !== "cancelled") sent += sentOf(job) - job.base; });
      if (samples.length && sent < samples[samples.length - 1][1]) samples = [];       // a request started again: the count fell
      samples.push([now, sent]);
      while (samples.length > 2 && now - samples[0][0] > cfg.window) samples.shift();
      var span = now - samples[0][0];
      if (span >= cfg.minSpan) speed = Math.max(0, (sent - samples[0][1]) / (span / 1000));
      var ahead = 0;
      jobs.forEach(function (job) {
        if (job.state === "failed" || job.state === "cancelled" || job.state === "done") return;
        var done = sentOf(job);
        ahead += job.file.size - done;
        emit("onProgress", job, { sent: done, size: job.file.size, speed: speed, left: speed > 0 ? Math.round(ahead / speed) : null });
      });
    }

    function add(file, meta) {
      var count = Math.ceil(file.size / block);
      var job = {
        file: file, meta: meta, key: keyOf(file), id: null, state: "new", count: count, blocks: new Uint8Array(count),
        scan: 0, confirmedBlocks: 0, confirmed: 0, base: 0, inflight: 0, loaded: {}, xhrs: [], cancelled: false
      };
      jobs.push(job);
      emit("onAdd", job);
      if (!ticker) ticker = setInterval(tick, 500);
      pump();
      return job;
    }

    return { add: add, cancel: cancel, speed: function () { return speed; }, requestBytes: requestBytes, tick: tick,
             jobs: function () { return jobs; } };
  }

  window.HubUpload = { create: create, DEFAULTS: DEFAULTS };
})();
