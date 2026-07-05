const state = {
  token: localStorage.getItem("access_token") || "",
  organizations: [],
  projects: [],
  queues: [],
  jobs: [],
  dashboard: {},
  currentView: "overview",
  jobFilters: { status: "", queueId: "", search: "" },
  jobPage: 1,
  jobPageSize: 8,
  selectedJob: null,
  queueModal: null,
};

let refreshTimer = null;
let resizeTimer = null;

function setAuthStatus(message, isError = false) {
  const el = document.getElementById("authStatus");
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? "#fb7185" : "#34d399";
}

function setLastUpdated(text) {
  const el = document.getElementById("lastUpdated");
  if (el) {
    el.textContent = text;
  }
}

function setAuthBanner() {
  const banner = document.getElementById("authBanner");
  const logoutButton = document.getElementById("logoutButton");
  if (banner) {
    banner.textContent = state.token ? "Signed in" : "Not signed in";
  }
  if (logoutButton) {
    logoutButton.hidden = !state.token;
  }
}

function updateAuthVisibility() {
  const authPanel = document.getElementById("authPanel");
  const sections = document.querySelectorAll(".view-section");
  if (authPanel) {
    authPanel.classList.toggle("hidden", Boolean(state.token));
  }
  sections.forEach((section) => {
    section.classList.toggle("hidden", !state.token);
  });
  if (state.token) {
    setView(state.currentView);
  }
}

function setAuthFormMode(mode) {
  const loginForm = document.getElementById("loginForm");
  const signupForm = document.getElementById("signupForm");
  const showLoginButton = document.getElementById("showLoginButton");
  const showSignupButton = document.getElementById("showSignupButton");
  const isLogin = mode === "login";
  if (loginForm) loginForm.classList.toggle("hidden", !isLogin);
  if (signupForm) signupForm.classList.toggle("hidden", isLogin);
  if (showLoginButton) showLoginButton.classList.toggle("active", isLogin);
  if (showSignupButton) showSignupButton.classList.toggle("active", !isLogin);
}

function clearToken() {
  state.token = "";
  localStorage.removeItem("access_token");
  state.selectedJob = null;
  setAuthBanner();
  setAuthFormMode("login");
  updateAuthVisibility();
  setAuthStatus("Use the form above to sign in and load the backend data.");
  renderAll();
}

function parseError(detail) {
  if (!detail) return "Request failed";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.join("; ");
  if (typeof detail === "object") return detail.detail || detail.message || detail.error || JSON.stringify(detail);
  return String(detail);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function statusBadge(status) {
  const normalized = String(status || "UNKNOWN").toUpperCase();
  let tone = "info";
  if (["COMPLETED", "ACTIVE", "RUNNING"].includes(normalized)) tone = "success";
  else if (["FAILED", "DEAD", "PAUSED"].includes(normalized)) tone = "danger";
  else if (["SCHEDULED", "QUEUED", "CLAIMED"].includes(normalized)) tone = "warning";
  return `<span class="status-badge ${tone}">${escapeHtml(normalized)}</span>`;
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.token) {
    headers.Authorization = `Bearer ${state.token}`;
  }

  let body = options.body;
  if (body && typeof body === "object" && !(body instanceof FormData) && !(body instanceof URLSearchParams)) {
    headers["Content-Type"] = headers["Content-Type"] || "application/json";
    body = JSON.stringify(body);
  }

  const response = await fetch(path, {
    method: options.method || "GET",
    headers,
    body,
  });

  const text = await response.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch (_) {
      data = text;
    }
  }

  if (!response.ok) {
    const detail = data?.detail || data?.message || data?.error || data || text || `HTTP ${response.status}`;
    const err = new Error(parseError(detail));
    err.status = response.status;
    throw err;
  }

  return data;
}

async function loginWithEmail(email, password) {
  const body = new URLSearchParams({ username: email, password }).toString();
  const response = await fetch("/api/users/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (_) {
    data = text;
  }

  if (!response.ok) {
    const detail = data?.detail || data?.message || data?.error || data || text || `HTTP ${response.status}`;
    throw new Error(parseError(detail));
  }

  const token = data?.access_token;
  if (!token) {
    throw new Error("The server did not return an access token.");
  }

  state.token = token;
  localStorage.setItem("access_token", token);
  setAuthBanner();
  setAuthStatus("Signed in. Loading backend data...");
  await loadAllData();
}

async function signupUser(email, password) {
  await request("/api/users/signup", { method: "POST", body: { email, password } });
  await loginWithEmail(email, password);
}

async function loadAllData() {
  if (!state.token) {
    renderAll();
    return;
  }

  try {
    const [health, queuesSummary, jobsSummary, workersSummary, executionsSummary, organizationsPayload, projectsPayload, queuesPayload, jobsPayload] = await Promise.all([
      request("/api/dashboard/health"),
      request("/api/dashboard/queues"),
      request("/api/dashboard/jobs"),
      request("/api/dashboard/workers"),
      request("/api/dashboard/executions"),
      request("/api/users/organizations?limit=100&offset=0"),
      request("/api/users/projects?limit=100&offset=0"),
      request("/api/queues?limit=100&offset=0"),
      request("/api/jobs?limit=100&offset=0"),
    ]);

    state.dashboard = { health, queuesSummary, jobsSummary, workersSummary, executionsSummary };
    state.organizations = organizationsPayload?.data || [];
    state.projects = projectsPayload?.data || [];
    state.queues = queuesPayload?.data || [];
    state.jobs = jobsPayload?.data || [];
    renderAll();
    setLastUpdated(`Last updated: ${new Date().toLocaleTimeString()}`);
    setAuthStatus("Backend data loaded successfully.");
  } catch (error) {
    if (error?.status === 401) {
      clearToken();
      setAuthStatus("Your session expired. Please sign in again.", true);
      return;
    }
    setAuthStatus(error?.message || "Unable to load backend data.", true);
  }
}

function renderAll() {
  setAuthBanner();
  updateAuthVisibility();
  renderOverview();
  renderOrganizations();
  renderProjects();
  renderQueues();
  renderJobs();
  renderWorkers();
  renderDlq();
  renderAdmin();
}

function renderOverview() {
  const queueSummary = state.dashboard.queuesSummary || {};
  const jobsSummary = state.dashboard.jobsSummary || {};
  const workersSummary = state.dashboard.workersSummary || {};
  const executionsSummary = state.dashboard.executionsSummary || {};
  const jobsByStatus = jobsSummary.by_status || {};
  const recentJobs = jobsSummary.recent_jobs || [];

  document.getElementById("kpiQueues").textContent = queueSummary.total_queues ?? state.queues.length;
  document.getElementById("kpiQueuesMeta").textContent = `${queueSummary.active_queues ?? state.queues.filter((queue) => !queue.paused).length} active / ${queueSummary.paused_queues ?? state.queues.filter((queue) => queue.paused).length} paused`;
  document.getElementById("kpiJobs").textContent = Object.values(jobsByStatus).reduce((sum, value) => sum + Number(value || 0), 0) || state.jobs.length;
  document.getElementById("kpiJobsMeta").textContent = `${recentJobs.length} recent records`;
  document.getElementById("kpiWorkers").textContent = Array.isArray(workersSummary.workers) ? workersSummary.workers.length : 0;
  document.getElementById("kpiWorkersMeta").textContent = (workersSummary.workers || []).some((worker) => String(worker.status).toUpperCase() === "ACTIVE") ? "heartbeat active" : "monitoring";
  document.getElementById("kpiDlq").textContent = executionsSummary.dlq_total ?? 0;
  document.getElementById("kpiDlqMeta").textContent = `${(executionsSummary.recent_dlq || []).length} recent entries`;

  document.getElementById("overviewSummary").textContent = JSON.stringify({
    health: state.dashboard.health || {},
    queues: queueSummary,
    jobs: jobsSummary,
    workers: workersSummary,
    executions: executionsSummary,
  }, null, 2);

  document.getElementById("overviewRecentJobs").innerHTML = recentJobs.length
    ? recentJobs.slice(0, 6).map((job) => `
        <div class="resource-item">
          <div class="card-title-row">
            <h4>Job #${job.id}</h4>
            ${statusBadge(job.status)}
          </div>
          <p>Queue ${job.queue_id} · Priority ${job.priority ?? "—"}</p>
          <p>${escapeHtml(formatDate(job.run_at))}</p>
        </div>`).join("")
    : '<div class="empty-state">No recent jobs available yet.</div>';

  const throughputCanvas = document.getElementById("throughputChart");
  const stateCanvas = document.getElementById("stateChart");
  drawChart(throughputCanvas, ["Scheduled", "Queued", "Completed", "Failed"], [
    Number(jobsByStatus.SCHEDULED || 0),
    Number(jobsByStatus.QUEUED || 0),
    Number(jobsByStatus.COMPLETED || 0),
    Number(jobsByStatus.FAILED || 0),
  ], ["#38bdf8", "#14b8a6", "#34d399", "#fb7185"]);
  drawChart(stateCanvas, Object.keys(jobsByStatus), Object.values(jobsByStatus), ["#38bdf8", "#14b8a6", "#34d399", "#f59e0b", "#fb7185"]);
}

function handleViewportResize() {
  if (resizeTimer) {
    window.cancelAnimationFrame(resizeTimer);
  }
  resizeTimer = window.requestAnimationFrame(() => {
    if (state.token) {
      renderOverview();
    }
  });
}

function drawChart(canvas, labels, values, colors) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const width = canvas.width = canvas.clientWidth * (window.devicePixelRatio || 1);
  const height = canvas.height = 200 * (window.devicePixelRatio || 1);
  ctx.setTransform((window.devicePixelRatio || 1), 0, 0, (window.devicePixelRatio || 1), 0, 0);
  ctx.clearRect(0, 0, canvas.clientWidth, height / (window.devicePixelRatio || 1));
  if (!values.some(Boolean)) {
    ctx.fillStyle = "#94a3b8";
    ctx.font = "14px Inter, sans-serif";
    ctx.fillText("No data available", 12, 26);
    return;
  }

  const chartWidth = canvas.clientWidth - 40;
  const chartHeight = 140;
  const maxValue = Math.max(...values, 1);
  const step = chartWidth / Math.max(labels.length, 1);
  ctx.strokeStyle = "rgba(148, 163, 184, 0.22)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i += 1) {
    const y = 20 + (chartHeight / 4) * i;
    ctx.beginPath();
    ctx.moveTo(20, y);
    ctx.lineTo(20 + chartWidth, y);
    ctx.stroke();
  }

  values.forEach((value, index) => {
    const barWidth = Math.max(20, step * 0.6);
    const barHeight = (Number(value) / maxValue) * chartHeight;
    const x = 20 + step * index + (step - barWidth) / 2;
    const y = 160 - barHeight;
    ctx.fillStyle = colors[index % colors.length];
    ctx.fillRect(x, y, barWidth, barHeight);
    ctx.fillStyle = "#e2e8f0";
    ctx.font = "12px Inter, sans-serif";
    ctx.fillText(labels[index], x, 182);
  });
}

function renderOrganizations() {
  const container = document.getElementById("orgList");
  if (!container) return;
  if (!state.organizations.length) {
    container.innerHTML = '<div class="empty-state">No organizations yet.</div>';
    return;
  }
  container.innerHTML = state.organizations.map((org) => `<div class="resource-item"><h4>${escapeHtml(org.name)}</h4><p>Role: ${escapeHtml(org.role)}</p></div>`).join("");
}

function renderProjects() {
  const container = document.getElementById("projectList");
  const select = document.getElementById("projectOrgSelect");
  if (!container) return;
  if (select) {
    select.innerHTML = state.organizations.map((org) => `<option value="${org.id}" ${org.id === Number(select.value) ? "selected" : ""}>${escapeHtml(org.name)}</option>`).join("");
  }
  if (!state.projects.length) {
    container.innerHTML = '<div class="empty-state">No projects yet.</div>';
    return;
  }
  container.innerHTML = state.projects.map((project) => `<div class="resource-item"><h4>${escapeHtml(project.name)}</h4><p>Organization ID: ${project.organization_id}</p></div>`).join("");
}

function renderQueues() {
  const container = document.getElementById("queueList");
  const select = document.getElementById("queueProjectSelect");
  if (!container) return;
  if (select) {
    select.innerHTML = state.projects.map((project) => `<option value="${project.id}" ${project.id === Number(select.value) ? "selected" : ""}>${escapeHtml(project.name)}</option>`).join("");
  }
  if (!state.queues.length) {
    container.innerHTML = '<div class="empty-state">No queues yet.</div>';
    return;
  }
  container.innerHTML = state.queues.map((queue) => `
    <div class="resource-item">
      <div class="card-title-row">
        <h4>${escapeHtml(queue.name)}</h4>
        ${statusBadge(queue.paused ? "PAUSED" : "ACTIVE")}
      </div>
      <p>Project ID: ${queue.project_id} · Priority: ${queue.priority} · Concurrency: ${queue.concurrency} · Retry: ${queue.retry_count}</p>
      <div class="button-row">
        <button type="button" data-action="manage-queue" data-id="${queue.id}">Manage</button>
        ${queue.paused ? `<button type="button" data-action="resume" data-id="${queue.id}">Resume</button>` : `<button type="button" data-action="pause" data-id="${queue.id}">Pause</button>`}
        <button type="button" data-action="delete" data-id="${queue.id}">Delete</button>
      </div>
    </div>`).join("");
}

function renderJobs() {
  const container = document.getElementById("jobList");
  const jobQueueSelect = document.getElementById("jobQueueSelect");
  const batchQueueSelect = document.getElementById("batchQueueSelect");
  const queueFilter = document.getElementById("jobQueueFilter");
  if (!container) return;
  if (jobQueueSelect) {
    jobQueueSelect.innerHTML = state.queues.map((queue) => `<option value="${queue.id}" ${queue.id === Number(jobQueueSelect.value) ? "selected" : ""}>${escapeHtml(queue.name)}</option>`).join("");
  }
  if (batchQueueSelect) {
    batchQueueSelect.innerHTML = state.queues.map((queue) => `<option value="${queue.id}" ${queue.id === Number(batchQueueSelect.value) ? "selected" : ""}>${escapeHtml(queue.name)}</option>`).join("");
  }
  if (queueFilter) {
    queueFilter.innerHTML = `<option value="">All queues</option>${state.queues.map((queue) => `<option value="${queue.id}" ${queue.id === Number(queueFilter.value) ? "selected" : ""}>${escapeHtml(queue.name)}</option>`).join("")}`;
  }
  const filteredJobs = getFilteredJobs();
  const totalPages = Math.max(1, Math.ceil(filteredJobs.length / state.jobPageSize));
  if (state.jobPage > totalPages) {
    state.jobPage = totalPages;
  }
  const visibleJobs = filteredJobs.slice((state.jobPage - 1) * state.jobPageSize, state.jobPage * state.jobPageSize);
  const resultsSummary = document.getElementById("jobResultsSummary");
  if (resultsSummary) {
    resultsSummary.textContent = `${filteredJobs.length} matching jobs · page ${state.jobPage} of ${totalPages}`;
  }
  const pageLabel = document.getElementById("jobPageLabel");
  if (pageLabel) {
    pageLabel.textContent = `Page ${state.jobPage} of ${totalPages}`;
  }
  if (!filteredJobs.length) {
    container.innerHTML = '<div class="empty-state">No jobs match the current filters.</div>';
    return;
  }
  container.innerHTML = visibleJobs.map((job) => `
    <button class="resource-item" type="button" data-action="job-select" data-id="${job.id}">
      <div class="card-title-row">
        <h4>Job #${job.id}</h4>
        ${statusBadge(job.status)}
      </div>
      <p>Queue ${job.queue_id} · Priority ${job.priority ?? "—"} · Retry ${job.retry_count ?? 0}/${job.max_retries ?? 0}</p>
      <p>${escapeHtml(formatDate(job.run_at))}</p>
      <p>${escapeHtml(JSON.stringify(job.created_payload || {}))}</p>
    </button>`).join("");
}

function getFilteredJobs() {
  const search = state.jobFilters.search.trim().toLowerCase();
  return state.jobs.filter((job) => {
    const statusMatches = !state.jobFilters.status || String(job.status).toUpperCase() === state.jobFilters.status.toUpperCase();
    const queueMatches = !state.jobFilters.queueId || String(job.queue_id) === String(state.jobFilters.queueId);
    const searchMatches = !search || [job.id, job.queue_id, job.status, JSON.stringify(job.created_payload || {})].some((value) => String(value).toLowerCase().includes(search));
    return statusMatches && queueMatches && searchMatches;
  });
}

function renderWorkers() {
  const container = document.getElementById("workerList");
  if (!container) return;
  const workers = state.dashboard.workersSummary?.workers || [];
  if (!workers.length) {
    container.innerHTML = '<div class="empty-state">No worker registrations available.</div>';
    return;
  }
  container.innerHTML = workers.map((worker) => `
    <article class="worker-card">
      <div class="worker-card-header">
        ${statusBadge(worker.status)}
        <h4>${escapeHtml(worker.hostname || worker.worker_id)}</h4>
      </div>
      <p>${escapeHtml(worker.worker_id)} · PID ${worker.pid}</p>
      <p>Heartbeat: ${escapeHtml(formatDate(worker.last_heartbeat_at))}</p>
      <p>Shutdown: ${escapeHtml(worker.shutdown_at ? formatDate(worker.shutdown_at) : "—")}</p>
    </article>`).join("");
}

function renderDlq() {
  const container = document.getElementById("dlqList");
  if (!container) return;
  const dlqItems = state.dashboard.executionsSummary?.recent_dlq || [];
  if (!dlqItems.length) {
    container.innerHTML = '<div class="empty-state">No dead-letter jobs recorded yet.</div>';
    return;
  }
  container.innerHTML = dlqItems.map((item) => `
    <div class="resource-item">
      <div class="card-title-row">
        <h4>DLQ #${item.id}</h4>
        ${statusBadge("DEAD")}
      </div>
      <p>Job ${item.job_id} · Queue ${item.queue_id} · Worker ${escapeHtml(item.worker_id || "—")}</p>
      <p>${escapeHtml(item.failure_reason || "No failure reason recorded")}</p>
      <p>${escapeHtml(formatDate(item.failed_at))}</p>
    </div>`).join("");
}

function renderAdmin() {
  const projectSelect = document.getElementById("projectOrgSelect");
  if (projectSelect) {
    projectSelect.innerHTML = state.organizations.map((org) => `<option value="${org.id}" ${org.id === Number(projectSelect.value) ? "selected" : ""}>${escapeHtml(org.name)}</option>`).join("");
  }
  const queueSelect = document.getElementById("queueProjectSelect");
  if (queueSelect) {
    queueSelect.innerHTML = state.projects.map((project) => `<option value="${project.id}" ${project.id === Number(queueSelect.value) ? "selected" : ""}>${escapeHtml(project.name)}</option>`).join("");
  }
  const jobQueueSelect = document.getElementById("jobQueueSelect");
  if (jobQueueSelect) {
    jobQueueSelect.innerHTML = state.queues.map((queue) => `<option value="${queue.id}" ${queue.id === Number(jobQueueSelect.value) ? "selected" : ""}>${escapeHtml(queue.name)}</option>`).join("");
  }
  const batchQueueSelect = document.getElementById("batchQueueSelect");
  if (batchQueueSelect) {
    batchQueueSelect.innerHTML = state.queues.map((queue) => `<option value="${queue.id}" ${queue.id === Number(batchQueueSelect.value) ? "selected" : ""}>${escapeHtml(queue.name)}</option>`).join("");
  }
  renderOrganizations();
  renderProjects();
  renderQueues();
  renderJobs();
}

function setView(view) {
  state.currentView = view;
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  document.querySelectorAll(".view-section").forEach((section) => section.classList.toggle("active", section.id === `${view}View`));
}

function openJobDrawer(job) {
  state.selectedJob = job;
  const drawer = document.getElementById("jobDrawer");
  const overlay = document.getElementById("drawerOverlay");
  const title = document.getElementById("drawerTitle");
  const body = document.getElementById("drawerBody");
  if (!drawer || !overlay || !title || !body || !job) return;
  title.textContent = `Job #${job.id}`;
  const execution = (state.dashboard.executionsSummary?.recent_executions || []).find((entry) => entry.job_id === job.id);
  body.innerHTML = `
    <div class="resource-item">
      <div class="card-title-row">
        <h4>Overview</h4>
        ${statusBadge(job.status)}
      </div>
      <p>Queue: ${job.queue_id}</p>
      <p>Priority: ${job.priority ?? "—"}</p>
      <p>Retry: ${job.retry_count ?? 0}/${job.max_retries ?? 0}</p>
      <p>Run at: ${formatDate(job.run_at)}</p>
    </div>
    <div class="resource-item">
      <h4>Payload</h4>
      <pre class="mono-block">${escapeHtml(JSON.stringify(job.created_payload || {}, null, 2))}</pre>
    </div>
    <div class="resource-item">
      <h4>Execution log</h4>
      <pre class="mono-block">${escapeHtml(execution?.logs || "No execution log available for this job yet.")}</pre>
    </div>`;
  drawer.classList.remove("hidden");
  overlay.classList.remove("hidden");
}

function closeJobDrawer() {
  document.getElementById("jobDrawer").classList.add("hidden");
  document.getElementById("drawerOverlay").classList.add("hidden");
}

function openQueueModal(queue) {
  const modal = document.getElementById("queueModal");
  const overlay = document.getElementById("queueModalOverlay");
  const title = document.getElementById("queueModalTitle");
  const body = document.getElementById("queueModalBody");
  if (!modal || !overlay || !body || !queue) return;
  state.queueModal = queue;
  title.textContent = `${queue.name} · Queue ${queue.id}`;
  body.innerHTML = `
    <div class="resource-item">
      <h4>Configuration</h4>
      <p>Project ID: ${queue.project_id}</p>
      <p>Priority: ${queue.priority}</p>
      <p>Concurrency: ${queue.concurrency}</p>
      <p>Retry strategy: ${queue.retry_strategy || "—"}</p>
      <p>Paused: ${queue.paused ? "Yes" : "No"}</p>
    </div>
    <div class="button-row">
      <button type="button" data-modal-action="pause" data-id="${queue.id}">${queue.paused ? "Pause" : "Pause"}</button>
      <button type="button" data-modal-action="resume" data-id="${queue.id}">Resume</button>
      <button type="button" data-modal-action="delete" data-id="${queue.id}" class="ghost-button">Delete</button>
    </div>`;
  modal.classList.remove("hidden");
  overlay.classList.remove("hidden");
}

function closeQueueModal() {
  document.getElementById("queueModal").classList.add("hidden");
  document.getElementById("queueModalOverlay").classList.add("hidden");
  state.queueModal = null;
}

async function createOrganization(event) {
  event.preventDefault();
  const name = document.getElementById("orgNameInput").value.trim();
  if (!name) return;
  try {
    await request("/api/users/organizations", { method: "POST", body: { name } });
    document.getElementById("orgForm").reset();
    await loadAllData();
    setAuthStatus("Organization created.");
  } catch (error) {
    setAuthStatus(error.message, true);
  }
}

async function createProject(event) {
  event.preventDefault();
  const name = document.getElementById("projectNameInput").value.trim();
  const organization_id = Number(document.getElementById("projectOrgSelect").value);
  if (!name || !organization_id) return;
  try {
    await request("/api/users/projects", { method: "POST", body: { name, organization_id } });
    document.getElementById("projectForm").reset();
    await loadAllData();
    setAuthStatus("Project created.");
  } catch (error) {
    setAuthStatus(error.message, true);
  }
}

async function createQueue(event) {
  event.preventDefault();
  const name = document.getElementById("queueNameInput").value.trim();
  const project_id = Number(document.getElementById("queueProjectSelect").value);
  const priority = Number(document.getElementById("queuePriorityInput").value || 1);
  const concurrency = Number(document.getElementById("queueConcurrencyInput").value || 5);
  const retry_count = Number(document.getElementById("queueRetryInput").value || 3);
  const retry_strategy = document.getElementById("queueRetryStrategyInput").value;
  if (!name || !project_id) return;
  try {
    await request("/api/queues", { method: "POST", body: { name, project_id, priority, concurrency, retry_count, retry_strategy } });
    document.getElementById("queueForm").reset();
    await loadAllData();
    setAuthStatus("Queue created.");
  } catch (error) {
    setAuthStatus(error.message, true);
  }
}

async function createJob(event) {
  event.preventDefault();
  const queue_id = Number(document.getElementById("jobQueueSelect").value);
  const payloadText = document.getElementById("jobPayloadInput").value;
  let payload;
  try {
    payload = JSON.parse(payloadText);
  } catch (_) {
    setAuthStatus("Payload must be valid JSON.", true);
    return;
  }
  const run_at = document.getElementById("jobRunAtInput").value || null;
  const cron_expression = document.getElementById("jobCronInput").value || null;
  const priority = document.getElementById("jobPriorityInput").value ? Number(document.getElementById("jobPriorityInput").value) : null;
  try {
    await request("/api/jobs", { method: "POST", body: { payload, queue_id, run_at, cron_expression, priority } });
    document.getElementById("jobForm").reset();
    await loadAllData();
    setAuthStatus("Job created.");
  } catch (error) {
    setAuthStatus(error.message, true);
  }
}

async function createBatchJobs(event) {
  event.preventDefault();
  const queue_id = Number(document.getElementById("batchQueueSelect").value);
  const payloadText = document.getElementById("batchPayloadInput").value;
  let jobs;
  try {
    jobs = JSON.parse(payloadText);
  } catch (_) {
    setAuthStatus("Batch payload must be valid JSON array.", true);
    return;
  }
  if (!Array.isArray(jobs)) {
    setAuthStatus("Batch payload must be a JSON array.", true);
    return;
  }
  try {
    await request("/api/jobs/batch", { method: "POST", body: { jobs, queue_id } });
    document.getElementById("batchJobForm").reset();
    await loadAllData();
    setAuthStatus("Batch jobs created.");
  } catch (error) {
    setAuthStatus(error.message, true);
  }
}

async function handleQueueAction(queueId, action) {
  try {
    if (action === "pause") {
      await request(`/api/queues/${queueId}/pause`, { method: "PATCH" });
    } else if (action === "resume") {
      await request(`/api/queues/${queueId}/resume`, { method: "PATCH" });
    } else if (action === "delete") {
      const confirmed = window.confirm(`Delete queue ${queueId}?`);
      if (!confirmed) return;
      await request(`/api/queues/${queueId}`, { method: "DELETE" });
    } else if (action === "stats") {
      const stats = await request(`/api/queues/${queueId}/stats`);
      setAuthStatus(`Queue ${queueId} stats: ${JSON.stringify(stats)}`);
      return;
    }
    await loadAllData();
    setAuthStatus(`Queue ${action === "delete" ? "deleted" : action === "pause" ? "paused" : action === "resume" ? "resumed" : "updated"}.`);
  } catch (error) {
    setAuthStatus(error.message, true);
  }
}

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  if (!state.token) return;
  refreshTimer = setInterval(() => {
    if (!state.token) {
      clearInterval(refreshTimer);
      refreshTimer = null;
      return;
    }
    loadAllData();
  }, 10000);
}

function attachEvents() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => setView(item.dataset.view));
  });

  document.getElementById("loginForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("loginEmail").value.trim();
    const password = document.getElementById("loginPassword").value;
    try {
      await loginWithEmail(email, password);
    } catch (error) {
      setAuthStatus(error.message, true);
    }
  });

  document.getElementById("signupForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const email = document.getElementById("signupEmail").value.trim();
    const password = document.getElementById("signupPassword").value;
    try {
      await signupUser(email, password);
    } catch (error) {
      setAuthStatus(error.message, true);
    }
  });

  document.getElementById("showLoginButton").addEventListener("click", () => setAuthFormMode("login"));
  document.getElementById("showSignupButton").addEventListener("click", () => setAuthFormMode("signup"));
  document.getElementById("logoutButton").addEventListener("click", () => {
    clearToken();
    setLastUpdated("Waiting for data");
  });

  document.getElementById("cleanupButton").addEventListener("click", async () => {
    const confirmed = window.confirm("This will delete existing jobs, executions, DLQ entries, workers, and heartbeats. Continue?");
    if (!confirmed) return;
    try {
      const result = await request("/api/dashboard/cleanup", { method: "DELETE" });
      await loadAllData();
      setAuthStatus(`Cleanup complete: ${JSON.stringify(result)}`);
    } catch (error) {
      setAuthStatus(error.message, true);
    }
  });

  document.getElementById("orgForm").addEventListener("submit", createOrganization);
  document.getElementById("projectForm").addEventListener("submit", createProject);
  document.getElementById("queueForm").addEventListener("submit", createQueue);
  document.getElementById("jobForm").addEventListener("submit", createJob);
  document.getElementById("batchJobForm").addEventListener("submit", createBatchJobs);

  document.querySelector(".content").addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-action], button[data-modal-action]");
    if (!button) return;
    const action = button.dataset.action || button.dataset.modalAction;
    const queueId = Number(button.dataset.id);
    if (action === "manage-queue") {
      const queue = state.queues.find((item) => item.id === queueId);
      if (queue) {
        openQueueModal(queue);
      }
      return;
    }
    if (action === "pause" || action === "resume" || action === "delete") {
      await handleQueueAction(queueId, action);
      closeQueueModal();
      return;
    }
    if (action === "job-select") {
      const job = state.jobs.find((item) => item.id === Number(button.dataset.id));
      if (job) {
        openJobDrawer(job);
      }
    }
  });

  document.getElementById("jobSearchInput").addEventListener("input", (event) => {
    state.jobFilters.search = event.target.value;
    state.jobPage = 1;
    renderJobs();
  });

  document.getElementById("jobStatusFilter").addEventListener("change", (event) => {
    state.jobFilters.status = event.target.value;
    state.jobPage = 1;
    renderJobs();
  });

  document.getElementById("jobQueueFilter").addEventListener("change", (event) => {
    state.jobFilters.queueId = event.target.value;
    state.jobPage = 1;
    renderJobs();
  });

  document.getElementById("clearFiltersButton").addEventListener("click", () => {
    state.jobFilters = { status: "", queueId: "", search: "" };
    document.getElementById("jobSearchInput").value = "";
    document.getElementById("jobStatusFilter").value = "";
    document.getElementById("jobQueueFilter").value = "";
    state.jobPage = 1;
    renderJobs();
  });

  document.getElementById("jobPrevButton").addEventListener("click", () => {
    if (state.jobPage > 1) {
      state.jobPage -= 1;
      renderJobs();
    }
  });

  document.getElementById("jobNextButton").addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(getFilteredJobs().length / state.jobPageSize));
    if (state.jobPage < totalPages) {
      state.jobPage += 1;
      renderJobs();
    }
  });

  document.getElementById("drawerCloseButton").addEventListener("click", closeJobDrawer);
  document.getElementById("drawerOverlay").addEventListener("click", closeJobDrawer);
  document.getElementById("queueModalCloseButton").addEventListener("click", closeQueueModal);
  document.getElementById("queueModalOverlay").addEventListener("click", closeQueueModal);
}

function init() {
  setAuthBanner();
  setAuthFormMode("login");
  attachEvents();
  window.addEventListener("resize", handleViewportResize);
  window.addEventListener("orientationchange", handleViewportResize);
  renderAll();
  if (state.token) {
    loadAllData();
    startAutoRefresh();
  }
}

init();
