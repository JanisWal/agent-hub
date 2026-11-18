// The upload engine of the file storage (web/app/files.py). The pattern of tus and of S3 multipart uploads:
//  - The SERVER is the truth. A file is made first, then its blocks are sent as runs (one request each) in any order.
//    What the server holds can be asked for (`progress`), so a break (lost line, closed tab, reload) goes on from
//    there and sends only what is missing. The server keeps the part of a broken request that arrived.
//  - Several requests are on their way at the same time (`parallel`): one alone does not fill the line, many together
//    do (the same reason S3, Nextcloud and rclone upload parts in parallel).
//  - The size of a request follows the speed the server CONFIRMED for the last requests, so that one takes about
//    `targetSeconds`: big on a fast line, small on a slow one, and always far below Cloudflare's 100 MB.
//  - A request that failed (network, no progress for `stall`, longer than `timeout`, a hiccup of the tunnel) is not
//    sent again blindly: after a growing pause the engine asks the server what arrived and sends the rest. While the
//    browser is offline it waits instead of using up its tries.
// This file knows nothing about the page: files.js gives it the addresses and listens to its events.
(function () {
  "use strict";

  var DEFAULTS = {
    parallel: 6,                         // requests on their way at the same time, over all files (measured 13.11.2026:
                                         // 12 brought no more than 6 and twice the load on the server)
    startRequest: 8388608,               // size of a request before the speed is known
    minRequest: 524288,
    maxRequest: 33554432,                // far below Cloudflare's 100 MB per request
                                         // (files.js passes the owner's choice for parallel and maxRequest)
    targetSeconds: 20,                   // what one request should take (Cloudflare waits about 100 s for an answer)
    delays: [0, 1000, 3000, 5000, 10000, 20000, 30000],   // pauses before each new try of a request (about a minute in all)
    stall: 30000,                        // no progress for this long: give up on the request
    timeout: 90000,                      // longest a request may take
    window: 10000,                       // the speed shown is measured over this long
    minSpan: 3000                        // and shown after this long
  };
  var FREE = 0, DONE = 1, SENDING = 2;                      // the state of a block in the browser

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
    var speed = 0;                               // shown: what the browser sent over the last seconds, all requests
    var rate = 0;                                // for sizing: bytes per second of ONE request, as the server confirmed
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
    function store(change) {
      try {
        var all = JSON.parse(localStorage.getItem("hub-uploads") || "{}");
        change(all);
        Object.keys(all).forEach(function (key) { if (Date.now() - all[key].at > 86400000) delete all[key]; });   // the server drops them after a day
        localStorage.setItem("hub-uploads", JSON.stringify(all));
      } catch (e) {}
    }
    function remember(job) { store(function (all) { all[job.key] = { id: job.id, at: Date.now() }; }); }
    function forget(job) { store(function (all) { delete all[job.key]; }); }
    function recall(job) {
      try { var found = JSON.parse(localStorage.getItem("hub-uploads") || "{}")[job.key]; return found ? found.id : null; } catch (e) { return null; }
    }
    function waitOnline() {
      if (typeof navigator === "undefined" || navigator.onLine !== false) return Promise.resolve();
      return new Promise(function (resolve) { window.addEventListener("online", function once() { window.removeEventListener("online", once); resolve(); }); });
    }
    function sleep(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }

    // --- sizes
    function requestBytes() {
      var bytes = rate > 0 ? rate * cfg.targetSeconds : Math.min(cfg.startRequest, cfg.maxRequest);
      bytes = Math.max(cfg.minRequest, Math.min(cfg.maxRequest, bytes));
      return Math.max(block, Math.floor(bytes / block) * block);
    }
    function sizeOf(job, i) { return Math.min(block, job.file.size - i * block); }
    function sentOf(job) {
      var sum = job.confirmed;
      Object.keys(job.loaded).forEach(function (key) { sum += job.loaded[key]; });
      return sum;
    }
    function markDone(job, i) {                  // counts a block once, however often it is confirmed
      if (job.blocks[i] === DONE) return;
      job.blocks[i] = DONE;
      job.confirmedBlocks++;
      job.confirmed += sizeOf(job, i);
    }

    // --- one request: resolves when the server confirmed the run; rejects with .retry for anything worth another try
    function sendRun(job, run) {
      return new Promise(function (resolve, reject) {
        var xhr = new XMLHttpRequest();
        var t0 = Date.now();
        var last = t0;
        var settled = false;
        var dog = setInterval(function () { if (Date.now() - last > cfg.stall) { xhr.__why = "stall"; xhr.abort(); } }, Math.max(50, Math.min(5000, cfg.stall / 4)));
        function end(problem) {
          if (settled) return;
          settled = true;
          clearInterval(dog);
          delete job.loaded[run.offset];
          var at = job.xhrs.indexOf(xhr);
          if (at >= 0) job.xhrs.splice(at, 1);
          if (!problem) return resolve(Date.now() - t0);
          reject(problem);
        }
        function retry(why) { var problem = new Error(text.net); problem.retry = why; end(problem); }
        job.xhrs.push(xhr);
        xhr.open("POST", urls.chunk(job.id) + "?offset=" + run.offset);
        xhr.timeout = cfg.timeout;
        xhr.upload.onprogress = function (event) { last = Date.now(); if (event.lengthComputable) job.loaded[run.offset] = event.loaded; };
        xhr.onerror = function () { retry("network"); };
        xhr.ontimeout = function () { retry("timeout"); };
        xhr.onabort = function () { if (job.cancelled || job.state === "failed") end(CANCELLED); else retry(xhr.__why || "abort"); };
        xhr.onload = function () {
          var data = {};
          try { data = JSON.parse(xhr.responseText); } catch (e) {}
          if (xhr.status === 200 && data.ok) end(null);
          else if ([0, 408, 429, 500, 502, 503, 504, 520, 522, 524].indexOf(xhr.status) >= 0) retry("status");   // the tunnel hiccuped
          else { var fail = new Error(data.message || text.net); fail.permanent = true; end(fail); }
        };
        xhr.send(job.file.slice(run.offset, run.offset + run.length));
      });
    }

    // --- the work of a job
    function nextRun(job) {
      var i = job.scan;
      while (i < job.count && job.blocks[i] !== FREE) i++;
      job.scan = i;
      if (i >= job.count) return null;
      var most = Math.max(1, Math.floor(requestBytes() / block));
      var n = 0;
      while (i + n < job.count && job.blocks[i + n] === FREE && n < most) n++;
      for (var k = 0; k < n; k++) job.blocks[i + k] = SENDING;
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

    function adopt(job, parts) {                 // at a resume: what the server already has is done
      for (var i = 0; i < job.count; i++) if (parts.charAt(i) === "1") markDone(job, i);
    }

    function startJob(job) {
      var known = activeKeys[job.key] ? null : recall(job);   // a second copy of the same file starts afresh
      activeKeys[job.key] = true;
      function fresh() {
        var name = (job.meta && job.meta.name) || job.file.name;   // files.js may give another name ("keep both")
        var values = { name: name, size: job.file.size };
        if (job.meta && job.meta.folder) values.folder = job.meta.folder;   // into a folder (18.11.2026)
        if (job.meta && job.meta.label) values.label = job.meta.label;     // dropped on a tab: its label (file-tags)
        return call(urls.start, form(values)).then(function (info) { job.id = info.id; remember(job); });
      }
      var begin = known ? call(urls.progress(known), null, "GET").then(function (data) {
        if (data.size !== job.file.size) throw new Error("other file");
        job.id = known;
        adopt(job, data.parts);
        job.base = job.confirmed;
        remember(job);
      }).catch(function () { return fresh(); }) : fresh();
      return begin.then(function () {
        if (job.cancelled) return call(urls.remove(job.id)).catch(function () {});
        job.state = "sending";
        emit("onStart", job);
      }, function (problem) { failJob(job, problem); });
    }

    function runJob(job, run, attempt) {
      attempt = attempt || 0;
      return sendRun(job, run).then(function (ms) {
        for (var k = 0; k < run.count; k++) markDone(job, run.first + k);
        job.inflight--;
        var sample = run.length / Math.max(ms / 1000, 0.05);
        rate = rate > 0 ? rate * 0.7 + sample * 0.3 : sample;
        emit("onRequest", job, { offset: run.offset, length: run.length, ms: ms, attempt: attempt + 1 });   // for measuring
      }, function (problem) {
        if (problem === CANCELLED || !problem.retry) { job.inflight--; return failJob(job, problem); }
        rate = (rate > 0 ? rate : cfg.startRequest / cfg.targetSeconds) * 0.5;        // smaller requests for a while
        if (attempt >= cfg.delays.length) { job.inflight--; var fail = new Error(text.net); fail.network = true; return failJob(job, fail); }
        emit("onRetry", job, { why: problem.retry, attempt: attempt + 1 });
        // Wait, ask what of this run arrived (the server keeps the front part of a broken request), send only the rest.
        return sleep(cfg.delays[attempt]).then(waitOnline).then(function () {
          return call(urls.progress(job.id), null, "GET").then(function (data) { return data.parts; }, function () { return ""; });
        }).then(function (parts) {
          if (job.state !== "sending") { job.inflight--; return; }
          var k = 0;
          for (var i = 0; i < run.count; i++) if (parts.charAt(run.first + i) === "1") markDone(job, run.first + i);
          while (k < run.count && job.blocks[run.first + k] === DONE) k++;
          if (k === run.count) { job.inflight--; return; }
          var offset = (run.first + k) * block;
          return runJob(job, { first: run.first + k, count: run.count - k, offset: offset,
                               length: Math.min((run.count - k) * block, job.file.size - offset) }, attempt + 1);
        });
      });
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
      // Every file has its own speed and time left (Janis, 14.11.2026: one number for all said nothing). A file the
      // engine has not reached yet (the requests serve the files in order) is `waiting`.
      jobs.forEach(function (job) {
        if (job.state === "failed" || job.state === "cancelled" || job.state === "done") return;
        var done = sentOf(job);
        var own = job.samples;
        if (own.length && done < own[own.length - 1][1]) own.length = 0;
        own.push([now, done]);
        while (own.length > 2 && now - own[0][0] > cfg.window) own.shift();
        var ownSpan = now - own[0][0];
        if (ownSpan >= cfg.minSpan) job.speed = Math.max(0, (done - own[0][1]) / (ownSpan / 1000));
        emit("onProgress", job, {
          sent: done, size: job.file.size, speed: job.speed, waiting: job.inflight === 0 && done - job.base === 0,
          left: job.speed > 0 ? Math.round((job.file.size - done) / job.speed) : null
        });
      });
    }

    function add(file, meta) {
      var count = Math.ceil(file.size / block);
      var job = {
        file: file, meta: meta, key: keyOf(file), id: null, state: "new", count: count, blocks: new Uint8Array(count),
        scan: 0, confirmedBlocks: 0, confirmed: 0, base: 0, inflight: 0, loaded: {}, xhrs: [], cancelled: false,
        samples: [], speed: 0
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
