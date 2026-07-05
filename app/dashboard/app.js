const state = {
  token: localStorage.getItem("access_token") || "",
  organizations: [],
  projects: [],
  queues: [],
  jobs: [],
  dashboard: {},
};

let refreshTimer = null;

function setAuthStatus(message, isError = false) {
  const el = document.getElementById("authStatus");
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? "#fb7185" : "#2dd4bf";
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

function setAuthFormMode(mode) {
  const loginForm = document.getElementById("loginForm");
  const signupForm = document.getElementById("signupForm");
  const showLoginButton = document.getElementById("showLoginButton");
  const showSignupButton = document.getElementById("showSignupButton");
  const isLogin = mode === "login";
  if (loginForm) loginForm.hidden = !isLogin;
  if (signupForm) signupForm.hidden = isLogin;
  if (showLoginButton) showLoginButton.classList.toggle("active", isLogin);
  if (showSignupButton) showSignupButton.classList.toggle("active", !isLogin);
}

function clearToken() {
  state.token = "";
  localStorage.removeItem("access_token");
  setAuthBanner();
  setAuthFormMode("login");
  setAuthStatus("Use the form above to sign in and load the backend data.");
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
  await request("/api/users/signup", {
    method: "POST",
    body: { email, password },
  });
  await loginWithEmail(email, password);
}

async function loadAllData() {
  if (!state.token) {
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
    renderOverview();
    renderOrganizations();
    renderProjects();
    renderQueues();
    renderJobs();
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

function renderOverview() {
  document.getElementById("healthSummary").textContent = JSON.stringify(state.dashboard.health || {}, null, 2);
  document.getElementById("queuesSummary").textContent = JSON.stringify(state.dashboard.queuesSummary || {}, null, 2);
  document.getElementById("jobsSummary").textContent = JSON.stringify(state.dashboard.jobsSummary || {}, null, 2);
  document.getElementById("workersSummary").textContent = JSON.stringify(state.dashboard.workersSummary || {}, null, 2);
  document.getElementById("executionsSummary").textContent = JSON.stringify(state.dashboard.executionsSummary || {}, null, 2);
}

function renderOrganizations() {
  const container = document.getElementById("orgList");
  if (!container) return;
  if (!state.organizations.length) {
    container.innerHTML = '<div class="empty-state">No organizations yet.</div>';
    return;
  }
  container.innerHTML = state.organizations
    .map((org) => `<div class="resource-item"><h4>${org.name}</h4><p>Role: ${org.role}</p></div>`)
    .join("");
}

function renderProjects() {
  const container = document.getElementById("projectList");
  const select = document.getElementById("projectOrgSelect");
  if (!container) return;
  if (select) {
    select.innerHTML = state.organizations.map((org) => `<option value="${org.id}" ${org.id === Number(select.value) ? "selected" : ""}>${org.name}</option>`).join("");
  }
  if (!state.projects.length) {
    container.innerHTML = '<div class="empty-state">No projects yet.</div>';
    return;
  }
  container.innerHTML = state.projects
    .map((project) => `<div class="resource-item"><h4>${project.name}</h4><p>Organization ID: ${project.organization_id}</p></div>`)
    .join("");
}

function renderQueues() {
  const container = document.getElementById("queueList");
  const select = document.getElementById("queueProjectSelect");
  if (!container) return;
  if (select) {
    select.innerHTML = state.projects.map((project) => `<option value="${project.id}" ${project.id === Number(select.value) ? "selected" : ""}>${project.name}</option>`).join("");
  }
  if (!state.queues.length) {
    container.innerHTML = '<div class="empty-state">No queues yet.</div>';
    return;
  }
  container.innerHTML = state.queues
    .map((queue) => `
      <div class="resource-item">
        <h4>${queue.name}</h4>
        <p>Project ID: ${queue.project_id} · Priority: ${queue.priority} · Concurrency: ${queue.concurrency} · Retry: ${queue.retry_count} · Paused: ${queue.paused ? "yes" : "no"}</p>
        <div class="inline-actions">
          <button type="button" data-action="stats" data-id="${queue.id}">Stats</button>
          ${queue.paused ? `<button type="button" data-action="resume" data-id="${queue.id}">Resume</button>` : `<button type="button" data-action="pause" data-id="${queue.id}">Pause</button>`}
          <button type="button" data-action="delete" data-id="${queue.id}">Delete</button>
        </div>
      </div>`)
    .join("");
}

function renderJobs() {
  const container = document.getElementById("jobList");
  const jobQueueSelect = document.getElementById("jobQueueSelect");
  const batchQueueSelect = document.getElementById("batchQueueSelect");
  if (!container) return;
  if (jobQueueSelect) {
    jobQueueSelect.innerHTML = state.queues.map((queue) => `<option value="${queue.id}" ${queue.id === Number(jobQueueSelect.value) ? "selected" : ""}>${queue.name}</option>`).join("");
  }
  if (batchQueueSelect) {
    batchQueueSelect.innerHTML = state.queues.map((queue) => `<option value="${queue.id}" ${queue.id === Number(batchQueueSelect.value) ? "selected" : ""}>${queue.name}</option>`).join("");
  }
  if (!state.jobs.length) {
    container.innerHTML = '<div class="empty-state">No jobs yet.</div>';
    return;
  }
  container.innerHTML = state.jobs
    .map((job) => `
      <div class="resource-item">
        <h4>Job #${job.id}</h4>
        <p>Status: ${job.status} · Queue: ${job.queue_id} · Priority: ${job.priority} · Run at: ${formatDate(job.run_at)}</p>
        <p>${JSON.stringify(job.created_payload)}</p>
      </div>`)
    .join("");
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
    await request("/api/queues", {
      method: "POST",
      body: { name, project_id, priority, concurrency, retry_count, retry_strategy },
    });
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
    await request("/api/jobs", {
      method: "POST",
      body: { payload, queue_id, run_at, cron_expression, priority },
    });
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

async function toggleQueue(event) {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const queueId = Number(button.dataset.id);
  const action = button.dataset.action;
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
    setAuthStatus(`Queue ${action}d.`);
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

  document.getElementById("orgForm").addEventListener("submit", createOrganization);
  document.getElementById("projectForm").addEventListener("submit", createProject);
  document.getElementById("queueForm").addEventListener("submit", createQueue);
  document.getElementById("jobForm").addEventListener("submit", createJob);
  document.getElementById("batchJobForm").addEventListener("submit", createBatchJobs);
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
  document.querySelector(".layout").addEventListener("click", toggleQueue);
}

function init() {
  setAuthBanner();
  setAuthFormMode("login");
  attachEvents();
  renderOverview();
  renderOrganizations();
  renderProjects();
  renderQueues();
  renderJobs();
  if (state.token) {
    loadAllData();
    startAutoRefresh();
  }
}

init();
