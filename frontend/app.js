(function () {
  "use strict";
  var CFG = /** @type {any} */ (window).APP_CONFIG || {};
  var API = CFG.apiBase || "";
  var root = /** @type {HTMLElement} */ (document.getElementById("app"));
  if (!root) { return; }
  var renderSeq = 0;
  /** @type {ReturnType<typeof setTimeout> | null} */
  var pollTimer = null;

  // ---------------------------------------------------------------- helpers
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function getToken() { try { return localStorage.getItem("token"); } catch (e) { return null; } }
  function setSession(token, user) {
    try { localStorage.setItem("token", token); localStorage.setItem("email", user.email); } catch (e) { /* storage unavailable */ }
  }
  function clearSession() {
    try { localStorage.removeItem("token"); localStorage.removeItem("email"); } catch (e) { /* ignore */ }
  }
  function val(id) { var el = /** @type {HTMLInputElement | null} */ (document.getElementById(id)); return el ? el.value : ""; }
  function setHtml(id, html) { var el = document.getElementById(id); if (el) el.innerHTML = html; }
  function flash(msg, kind) {
    var el = document.getElementById("flash");
    if (el) el.innerHTML = msg ? '<div class="flash ' + (kind || "ok") + '">' + esc(msg) + "</div>" : "";
  }
  function fmtPct(x) { return (x * 100).toFixed(1) + "%"; }

  function api(method, path, body, contentType) {
    /** @type {Record<string, string>} */
    var headers = {};
    var t = getToken();
    if (t) headers["Authorization"] = "Bearer " + t;
    var payload;
    if (body !== undefined) {
      if (contentType) { headers["Content-Type"] = contentType; payload = body; }
      else { headers["Content-Type"] = "application/json"; payload = JSON.stringify(body); }
    }
    return fetch(API + path, { method: method, headers: headers, body: payload }).then(function (res) {
      return res.json().catch(function () { return null; }).then(function (data) {
        if (res.status === 401 && t) { clearSession(); location.hash = "#/login"; }
        if (!res.ok) throw new Error((data && data.error) || "Request failed (" + res.status + ")");
        return data;
      });
    });
  }

  // ---------------------------------------------------------------- routing
  function parseRoute() {
    var p = (location.hash || "#/projects").slice(1).split("/").filter(Boolean);
    if (p[0] === "login" && p.length === 1) return { name: "login" };
    if (p[0] === "projects" && p.length === 1) return { name: "projects" };
    if (p[0] === "projects" && p.length === 2) return { name: "project", id: p[1] };
    if (p[0] === "models" && p.length === 2) return { name: "model", id: p[1] };
    return { name: "notfound" };
  }

  function shell(inner) {
    var email = "";
    try { email = localStorage.getItem("email") || ""; } catch (e) { /* ignore */ }
    return '<header class="top"><a class="brand" href="#/projects">LLM Fine-Tuning Platform</a>' +
      '<a href="#/projects">Projects</a><span class="spacer"></span><span class="who">' + esc(email) + "</span>" +
      '<button class="secondary" id="btn-logout" data-action="logout">Log out</button></header>' +
      '<main><div id="flash"></div>' + inner + "</main>";
  }

  function render() {
    var seq = ++renderSeq;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
    var route = parseRoute();
    if (!getToken() && route.name !== "login") { location.hash = "#/login"; return Promise.resolve(); }
    var p;
    if (route.name === "login") p = Promise.resolve(viewLogin());
    else if (route.name === "projects") p = viewProjects();
    else if (route.name === "project") p = viewProject(route.id, seq);
    else if (route.name === "model") p = viewModel(route.id);
    else p = Promise.resolve(shell('<div class="card"><h1>Page not found</h1><a href="#/projects">Back to projects</a></div>'));
    return p.then(function (html) { if (seq === renderSeq) root.innerHTML = html; })
      .catch(function (e) {
        if (seq === renderSeq) root.innerHTML = shell('<div class="card"><h1>Something went wrong</h1><p class="err" id="page-error">' + esc(e.message) + '</p><a href="#/projects">Back to projects</a></div>');
      });
  }

  // ---------------------------------------------------------------- views
  function viewLogin() {
    return '<div class="card auth"><div id="flash"></div><h1>Sign in</h1>' +
      '<form data-action="login"><label for="auth-email">Email</label><input id="auth-email" type="email" autocomplete="username">' +
      '<label for="auth-password">Password (min 8 characters)</label><input id="auth-password" type="password" autocomplete="current-password">' +
      '<button type="submit" id="btn-login">Sign in</button> ' +
      '<button type="button" class="secondary" id="btn-register" data-action="register">Create account</button></form></div>';
  }

  function viewProjects() {
    return api("GET", "/api/projects").then(function (d) {
      var rows = d.projects.map(function (p) {
        return '<tr><td><a href="#/projects/' + esc(p.id) + '">' + esc(p.name) + "</a></td><td class=\"muted\">" + esc(p.description) +
          '</td><td class="muted small">' + esc(p.created_at) + '</td><td><button class="danger" data-action="delete-project" data-id="' + esc(p.id) + '">Delete</button></td></tr>';
      }).join("");
      return shell('<div class="card"><h1>Projects</h1>' +
        (rows ? '<table id="projects-table"><tr><th>Name</th><th>Description</th><th>Created</th><th></th></tr>' + rows + "</table>" : '<p class="muted" id="no-projects">No projects yet.</p>') +
        '</div><div class="card"><h2>New project</h2><form data-action="create-project"><div class="row"><div><label for="proj-name">Name</label><input id="proj-name" maxlength="100"></div>' +
        '<div><label for="proj-desc">Description</label><input id="proj-desc" maxlength="1000"></div></div><button type="submit" id="btn-create-project">Create project</button></form></div>');
    });
  }

  function viewProject(id, seq) {
    return Promise.all([
      api("GET", "/api/projects/" + id), api("GET", "/api/projects/" + id + "/datasets"),
      api("GET", "/api/projects/" + id + "/jobs"), api("GET", "/api/projects/" + id + "/models")
    ]).then(function (r) {
      var project = r[0], datasets = r[1].datasets, jobs = r[2].jobs, models = r[3].models;
      var active = jobs.some(function (j) { return j.status === "queued" || j.status === "running"; });
      if (active) {
        pollTimer = setTimeout(function () { if (seq === renderSeq) render(); }, 1500);
      }
      var dsRows = datasets.map(function (d) {
        var labels = Object.keys(d.labels).map(function (k) { return esc(k) + " (" + d.labels[k] + ")"; }).join(", ");
        return "<tr><td>" + esc(d.name) + "</td><td>" + d.row_count + '</td><td class="small muted">' + labels +
          '</td><td><button class="danger" data-action="delete-dataset" data-id="' + esc(d.id) + '">Delete</button></td></tr>';
      }).join("");
      var dsOptions = datasets.map(function (d) { return '<option value="' + esc(d.id) + '">' + esc(d.name) + " (" + d.row_count + " rows)</option>"; }).join("");
      var jobRows = jobs.map(function (j) {
        var detail = j.status === "succeeded" ? "accuracy " + fmtPct(j.metrics.accuracy) + " · macro-F1 " + j.metrics.macro_f1 :
          (j.error ? '<span class="err">' + esc(j.error) + "</span>" : "");
        var link = j.model_id ? '<a href="#/models/' + esc(j.model_id) + '">open model</a>' : "";
        return "<tr><td>" + esc(j.model_name) + '</td><td class="small">' + esc(j.method) + '</td><td><span class="badge ' + esc(j.status) + '">' + esc(j.status) +
          '</span></td><td class="small">' + detail + "</td><td>" + link + "</td></tr>";
      }).join("");
      var modelRows = models.map(function (m) {
        return '<tr><td><a href="#/models/' + esc(m.id) + '">' + esc(m.name) + '</a></td><td class="small">' + esc(m.method) + '</td><td class="small muted">' + esc(m.labels.join(", ")) + "</td></tr>";
      }).join("");
      return shell(
        '<div class="card"><a href="#/projects">← Projects</a><h1 id="project-title">' + esc(project.name) + '</h1><p class="muted">' + esc(project.description) + "</p></div>" +
        '<div class="card"><h2>Datasets</h2>' + (dsRows ? '<table id="datasets-table"><tr><th>Name</th><th>Rows</th><th>Labels</th><th></th></tr>' + dsRows + "</table>" : '<p class="muted">No datasets yet.</p>') +
        '<label for="ds-file">Upload CSV (columns: <code>text</code>, <code>label</code>)</label><input id="ds-file" type="file" accept=".csv,text/csv">' +
        '<button id="btn-upload" data-action="upload-dataset" data-id="' + esc(id) + '">Upload dataset</button></div>' +
        '<div class="card"><h2>Train a model</h2>' + (datasets.length ?
          '<form data-action="submit-job" data-id="' + esc(id) + '"><div class="row"><div><label for="job-dataset">Dataset</label><select id="job-dataset">' + dsOptions + "</select></div>" +
          '<div><label for="job-method">Method</label><select id="job-method"><option value="tfidf-logreg">tfidf-logreg (CPU)</option><option value="lora-causal-lm">lora (needs torch/peft)</option></select></div>' +
          '<div><label for="job-name">Model name (optional)</label><input id="job-name" maxlength="100"></div></div>' +
          '<div class="row"><div><label for="job-c">C (tfidf)</label><input id="job-c" value="1.0"></div><div><label for="job-ngram">Max n-gram (tfidf)</label><input id="job-ngram" value="2"></div>' +
          '<div><label for="job-test">Test split</label><input id="job-test" value="0.2"></div><div><label for="job-base">Base model (lora)</label><input id="job-base" value="distilbert-base-uncased"></div>' +
          '<div><label for="job-epochs">Epochs (lora)</label><input id="job-epochs" value="3"></div></div>' +
          '<button type="submit" id="btn-train">Start training</button></form>' : '<p class="muted">Upload a dataset first.</p>') + "</div>" +
        '<div class="card"><h2>Training jobs</h2>' + (jobRows ? '<table id="jobs-table"><tr><th>Name</th><th>Method</th><th>Status</th><th>Result</th><th></th></tr>' + jobRows + "</table>" : '<p class="muted">No jobs yet.</p>') + "</div>" +
        '<div class="card"><h2>Model registry</h2>' + (modelRows ? '<table id="models-table"><tr><th>Name</th><th>Method</th><th>Labels</th></tr>' + modelRows + "</table>" : '<p class="muted">No models yet.</p>') + "</div>"
      );
    });
  }

  function metricsHtml(m) {
    var per = m.per_class.map(function (c) {
      return "<tr><td>" + esc(c.label) + "</td><td>" + c.precision + "</td><td>" + c.recall + "</td><td>" + c.f1 + "</td><td>" + c.support + "</td></tr>";
    }).join("");
    var cm = m.confusion_matrix;
    var head = "<tr><th>true \\ pred</th>" + cm.labels.map(function (l) { return "<th>" + esc(l) + "</th>"; }).join("") + "</tr>";
    var body = cm.matrix.map(function (row, i) { return "<tr><th>" + esc(cm.labels[i]) + "</th>" + row.map(function (n) { return "<td>" + n + "</td>"; }).join("") + "</tr>"; }).join("");
    return '<p><strong id="eval-accuracy">Accuracy ' + fmtPct(m.accuracy) + "</strong> · macro-F1 " + m.macro_f1 + " · n=" + m.n + "</p>" +
      "<table><tr><th>Label</th><th>Precision</th><th>Recall</th><th>F1</th><th>Support</th></tr>" + per + '</table><h2 class="small">Confusion matrix</h2><table class="cm">' + head + body + "</table>";
  }

  function viewModel(id) {
    return Promise.all([api("GET", "/api/models/" + id), api("GET", "/api/models/" + id + "/evaluations")]).then(function (r) {
      var m = r[0], evs = r[1].evaluations;
      return shell(
        '<div class="card"><a href="#/projects/' + esc(m.project_id) + '">← Project</a><h1 id="model-title">' + esc(m.name) + '</h1><p class="muted small">' + esc(m.method) + " · labels: " + esc(m.labels.join(", ")) + "</p>" +
        '<button class="danger" data-action="delete-model" data-id="' + esc(m.id) + '" data-project="' + esc(m.project_id) + '">Delete model</button></div>' +
        '<div class="card"><h2>Evaluation (held-out test split)</h2><button id="btn-evaluate" data-action="evaluate" data-id="' + esc(m.id) + '">Run evaluation</button>' +
        '<div id="eval-result">' + (evs.length ? metricsHtml(evs[0].metrics) + '<p class="muted small">Latest of ' + evs.length + " run(s)</p>" : '<p class="muted">Not evaluated yet.</p>') + "</div></div>" +
        '<div class="card"><h2>Inference</h2><form data-action="predict" data-id="' + esc(m.id) + '"><label for="predict-input">Texts (one per line)</label><textarea id="predict-input"></textarea>' +
        '<button type="submit" id="btn-predict">Predict</button></form><div id="predict-result"></div></div>'
      );
    });
  }

  // ---------------------------------------------------------------- actions
  function busy(id, on) { var b = /** @type {HTMLButtonElement | null} */ (document.getElementById(id)); if (b) b.disabled = on; }

  var actions = {
    login: function () {
      return api("POST", "/api/auth/login", { email: val("auth-email"), password: val("auth-password") }).then(function (d) {
        setSession(d.token, d.user); location.hash = "#/projects"; return render();
      });
    },
    register: function () {
      return api("POST", "/api/auth/register", { email: val("auth-email"), password: val("auth-password") }).then(function (d) {
        setSession(d.token, d.user); location.hash = "#/projects"; return render();
      });
    },
    logout: function () { clearSession(); location.hash = "#/login"; return render(); },
    "create-project": function () {
      return api("POST", "/api/projects", { name: val("proj-name"), description: val("proj-desc") }).then(function (p) { location.hash = "#/projects/" + p.id; });
    },
    "delete-project": function (el) {
      if (!window.confirm("Delete this project and all of its data?")) return Promise.resolve();
      return api("DELETE", "/api/projects/" + el.dataset.id).then(render);
    },
    "upload-dataset": function (el) {
      var input = /** @type {HTMLInputElement | null} */ (document.getElementById("ds-file"));
      var f = input && input.files && input.files[0];
      if (!f) { flash("Choose a CSV file first", "error"); return Promise.resolve(); }
      const file = f;  // const keeps the non-null narrowing inside the callback
      return file.text().then(function (text) {
        return api("POST", "/api/projects/" + el.dataset.id + "/datasets?name=" + encodeURIComponent(file.name), text, "text/csv");
      }).then(function () { return render().then(function () { flash("Dataset uploaded", "ok"); }); });
    },
    "delete-dataset": function (el) {
      return api("DELETE", "/api/datasets/" + el.dataset.id).then(render);
    },
    "submit-job": function (el) {
      var method = val("job-method");
      var params = { test_size: parseFloat(val("job-test")) };
      if (method === "tfidf-logreg") { params.C = parseFloat(val("job-c")); params.ngram_max = parseInt(val("job-ngram"), 10); }
      else { params.base_model = val("job-base"); params.epochs = parseInt(val("job-epochs"), 10); }
      var body = { dataset_id: val("job-dataset"), method: method, params: params };
      if (val("job-name").trim()) body.model_name = val("job-name").trim();
      return api("POST", "/api/projects/" + el.dataset.id + "/jobs", body).then(function () {
        return render().then(function () { flash("Training job queued", "ok"); });
      });
    },
    evaluate: function (el) {
      busy("btn-evaluate", true);
      return api("POST", "/api/models/" + el.dataset.id + "/evaluate").then(function (ev) {
        setHtml("eval-result", metricsHtml(ev.metrics));   // element may be gone if the user navigated away
      }).then(function () { busy("btn-evaluate", false); }, function (e) { busy("btn-evaluate", false); throw e; });
    },
    predict: function (el) {
      var texts = val("predict-input").split("\n").map(function (s) { return s.trim(); }).filter(Boolean);
      return api("POST", "/api/models/" + el.dataset.id + "/predict", { texts: texts }).then(function (d) {
        var rows = d.predictions.map(function (p, i) {
          return "<tr><td>" + esc(texts[i]) + "</td><td><strong>" + esc(p.label) + "</strong></td><td>" + fmtPct(p.confidence) + "</td></tr>";
        }).join("");
        setHtml("predict-result", '<table id="predict-table"><tr><th>Text</th><th>Label</th><th>Confidence</th></tr>' + rows + "</table>");
      });
    },
    "delete-model": function (el) {
      if (!window.confirm("Delete this model?")) return Promise.resolve();
      return api("DELETE", "/api/models/" + el.dataset.id).then(function () { location.hash = "#/projects/" + el.dataset.project; });
    }
  };

  function dispatch(el) {
    var fn = actions[el.dataset.action];
    if (!fn) return;
    flash("");
    var result;
    try { result = fn(el); } catch (e) { flash(/** @type {Error} */ (e).message, "error"); return; }
    return Promise.resolve(result).catch(function (e) { flash(e.message, "error"); });
  }

  document.addEventListener("click", function (e) {
    var t = /** @type {Element | null} */ (e.target);
    var el = t && t.closest ? /** @type {HTMLElement | null} */ (t.closest("button[data-action]")) : null;
    if (el) { e.preventDefault(); dispatch(el); }
  });
  document.addEventListener("submit", function (e) {
    var t = /** @type {Element | null} */ (e.target);
    var el = t && t.closest ? /** @type {HTMLElement | null} */ (t.closest("form[data-action]")) : null;
    if (el) { e.preventDefault(); dispatch(el); }
  });
  window.addEventListener("hashchange", render);
  render();
})();
