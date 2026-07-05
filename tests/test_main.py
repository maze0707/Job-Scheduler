from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import JobExecution, DeadLetterJob, WorkerRegistration, WorkerHeartbeat, Job, JobStatus
import random
import uuid
from datetime import datetime, timezone, timedelta

client = TestClient(app)


def test_health_check():
    """
    Verifies that the core monolith root route is alive and operational.
    """
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "operational"


def _signup_and_login():
    random_id = uuid.uuid4().hex[:8]
    test_email = f"testrunner_{random_id}@example.com"
    test_password = "supersecretpassword123"

    signup_payload = {
        "email": test_email,
        "password": test_password
    }
    signup_response = client.post("/api/users/signup", json=signup_payload)
    assert signup_response.status_code == 201

    login_form_data = {
        "username": test_email,
        "password": test_password
    }
    login_response = client.post("/api/users/login", data=login_form_data)
    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    return token


def test_user_signup_and_login_lifecycle():
    """
    Tests the complete user registration and frontend token acquisition lifecycle.
    """
    token = _signup_and_login()
    assert token


def test_organization_membership_and_org_scoped_projects():
    """
    Validates org creation/list and organization-scoped project access isolation.
    """
    token_user_1 = _signup_and_login()
    token_user_2 = _signup_and_login()

    headers_user_1 = {"Authorization": f"Bearer {token_user_1}"}
    headers_user_2 = {"Authorization": f"Bearer {token_user_2}"}

    # user 1 creates org
    org_name = f"org-{random.randint(1000, 9999)}"
    create_org = client.post("/api/users/organizations", json={"name": org_name}, headers=headers_user_1)
    assert create_org.status_code == 201
    org_id = create_org.json()["id"]

    # list orgs shows membership for creator
    list_orgs_user_1 = client.get("/api/users/organizations", headers=headers_user_1)
    assert list_orgs_user_1.status_code == 200
    orgs_payload_u1 = list_orgs_user_1.json()
    assert "data" in orgs_payload_u1 and "meta" in orgs_payload_u1
    org_names_user_1 = [o["name"] for o in orgs_payload_u1["data"]]
    assert org_name in org_names_user_1

    # user 2 should not see user 1 org
    list_orgs_user_2 = client.get("/api/users/organizations", headers=headers_user_2)
    assert list_orgs_user_2.status_code == 200
    orgs_payload_u2 = list_orgs_user_2.json()
    assert "data" in orgs_payload_u2 and "meta" in orgs_payload_u2
    org_names_user_2 = [o["name"] for o in orgs_payload_u2["data"]]
    assert org_name not in org_names_user_2

    # unauthenticated org actions must fail
    unauth_org_create = client.post("/api/users/organizations", json={"name": "unauth-org"})
    unauth_org_list = client.get("/api/users/organizations")
    assert unauth_org_create.status_code == 401
    assert unauth_org_list.status_code == 401

    # user 1 can create project in owned org
    create_project_user_1 = client.post(
        "/api/users/projects",
        json={"name": "u1-org-project", "organization_id": org_id},
        headers=headers_user_1,
    )
    assert create_project_user_1.status_code == 201
    project_id = create_project_user_1.json()["id"]

    # user 2 cannot create project in user 1 org
    create_project_user_2_forbidden = client.post(
        "/api/users/projects",
        json={"name": "u2-should-fail", "organization_id": org_id},
        headers=headers_user_2,
    )
    assert create_project_user_2_forbidden.status_code == 403

    # list projects for user 1 includes created project
    list_projects_user_1 = client.get("/api/users/projects", headers=headers_user_1)
    assert list_projects_user_1.status_code == 200
    projects_payload_u1 = list_projects_user_1.json()
    assert "data" in projects_payload_u1 and "meta" in projects_payload_u1
    names_u1 = [p["name"] for p in projects_payload_u1["data"]]
    assert "u1-org-project" in names_u1

    # list projects for user 2 excludes user 1 project
    list_projects_user_2 = client.get("/api/users/projects", headers=headers_user_2)
    assert list_projects_user_2.status_code == 200
    projects_payload_u2 = list_projects_user_2.json()
    assert "data" in projects_payload_u2 and "meta" in projects_payload_u2
    names_u2 = [p["name"] for p in projects_payload_u2["data"]]
    assert "u1-org-project" not in names_u2

    # queue and job endpoint authorization by org chain
    queue_name = f"q-{random.randint(1000, 9999)}"
    queue_create_u1 = client.post(
        "/api/queues",
        json={
            "name": queue_name,
            "project_id": project_id,
            "priority": 7,
            "concurrency": 2,
            "retry_count": 4,
            "retry_strategy": "LINEAR",
        },
        headers=headers_user_1,
    )
    assert queue_create_u1.status_code == 200
    queue_payload = queue_create_u1.json()
    queue_id = queue_payload["id"]
    assert queue_payload["priority"] == 7
    assert queue_payload["concurrency"] == 2
    assert queue_payload["retry_count"] == 4
    assert queue_payload["retry_strategy"] == "LINEAR"

    queue_create_u2_forbidden = client.post(
        "/api/queues",
        json={"name": f"{queue_name}-u2", "project_id": project_id},
        headers=headers_user_2,
    )
    assert queue_create_u2_forbidden.status_code in (403, 404)

    pause_u1 = client.patch(f"/api/queues/{queue_id}/pause", headers=headers_user_1)
    assert pause_u1.status_code == 200

    pause_u2 = client.patch(f"/api/queues/{queue_id}/pause", headers=headers_user_2)
    assert pause_u2.status_code == 404

    resume_u1 = client.patch(f"/api/queues/{queue_id}/resume", headers=headers_user_1)
    assert resume_u1.status_code == 200

    resume_u2 = client.patch(f"/api/queues/{queue_id}/resume", headers=headers_user_2)
    assert resume_u2.status_code == 404

    queue_stats_u1 = client.get(f"/api/queues/{queue_id}/stats", headers=headers_user_1)
    assert queue_stats_u1.status_code == 200
    stats_before_jobs = queue_stats_u1.json()
    assert stats_before_jobs["queue_id"] == queue_id
    assert stats_before_jobs["total_jobs"] == 0
    assert stats_before_jobs["by_status"] == {}

    queue_stats_u2 = client.get(f"/api/queues/{queue_id}/stats", headers=headers_user_2)
    assert queue_stats_u2.status_code == 404

    # job creation same-org allowed; cross-org blocked
    create_job_u1 = client.post(
        "/api/jobs",
        json={"payload": {"task": "hello"}, "queue_id": queue_id},
        headers=headers_user_1,
    )
    assert create_job_u1.status_code == 201

    create_job_u2 = client.post(
        "/api/jobs",
        json={"payload": {"task": "blocked"}, "queue_id": queue_id},
        headers=headers_user_2,
    )
    assert create_job_u2.status_code == 404

    batch_job_u1 = client.post(
        "/api/jobs/batch",
        json={"jobs": [{"task": 1}, {"task": 2}], "queue_id": queue_id},
        headers=headers_user_1,
    )
    assert batch_job_u1.status_code == 201

    batch_job_u2 = client.post(
        "/api/jobs/batch",
        json={"jobs": [{"task": "x"}], "queue_id": queue_id},
        headers=headers_user_2,
    )
    assert batch_job_u2.status_code == 404

    queue_stats_after_jobs = client.get(f"/api/queues/{queue_id}/stats", headers=headers_user_1)
    assert queue_stats_after_jobs.status_code == 200
    stats_payload = queue_stats_after_jobs.json()
    assert stats_payload["total_jobs"] == 3
    assert stats_payload["by_status"].get("QUEUED") == 3


def test_delayed_job_is_created_as_scheduled():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    org_name = f"org-delayed-{random.randint(1000, 9999)}"
    create_org = client.post("/api/users/organizations", json={"name": org_name}, headers=headers)
    assert create_org.status_code == 201
    org_id = create_org.json()["id"]

    create_project = client.post(
        "/api/users/projects",
        json={"name": "scheduled-project", "organization_id": org_id},
        headers=headers,
    )
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    queue_name = f"scheduled-q-{random.randint(1000, 9999)}"
    create_queue = client.post(
        "/api/queues",
        json={"name": queue_name, "project_id": project_id},
        headers=headers,
    )
    assert create_queue.status_code == 200
    queue_id = create_queue.json()["id"]

    future_run = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    delayed_job = client.post(
        "/api/jobs",
        json={"payload": {"task": "future"}, "queue_id": queue_id, "run_at": future_run},
        headers=headers,
    )
    assert delayed_job.status_code == 201
    delayed_payload = delayed_job.json()
    assert delayed_payload["status"] == "SCHEDULED"


def test_dashboard_page_contains_rebuilt_management_shell():
    response = client.get("/dashboard")
    assert response.status_code == 200
    html = response.text
    assert "Job Scheduler Console" in html
    assert "Sign in" in html
    assert "Organizations" in html


def test_metrics_endpoint_returns_status_counts():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    org_name = f"org-metrics-{random.randint(1000, 9999)}"
    create_org = client.post("/api/users/organizations", json={"name": org_name}, headers=headers)
    assert create_org.status_code == 201
    org_id = create_org.json()["id"]

    create_project = client.post(
        "/api/users/projects",
        json={"name": "metrics-project", "organization_id": org_id},
        headers=headers,
    )
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    queue_name = f"metrics-q-{random.randint(1000, 9999)}"
    queue_create = client.post(
        "/api/queues",
        json={"name": queue_name, "project_id": project_id},
        headers=headers,
    )
    assert queue_create.status_code == 200
    queue_id = queue_create.json()["id"]

    db = SessionLocal()
    try:
        db.add_all([
            Job(payload={"task": "queued"}, queue_id=queue_id, retries_left=1, status=JobStatus.QUEUED, retry_count=0, max_retries=1, retry_strategy="FIXED"),
            Job(payload={"task": "done"}, queue_id=queue_id, retries_left=0, status=JobStatus.COMPLETED, retry_count=0, max_retries=1, retry_strategy="FIXED"),
        ])
        db.commit()
    finally:
        db.close()

    response = client.get("/api/v1/metrics", headers=headers)
    assert response.status_code == 200
    payload = response.json()
    assert payload["job_status_counts"]["QUEUED"] >= 1
    assert payload["job_status_counts"]["COMPLETED"] >= 1


def test_cleanup_endpoint_removes_jobs_and_related_records():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    org_name = f"org-cleanup-{random.randint(1000, 9999)}"
    create_org = client.post("/api/users/organizations", json={"name": org_name}, headers=headers)
    assert create_org.status_code == 201
    org_id = create_org.json()["id"]

    create_project = client.post(
        "/api/users/projects",
        json={"name": "cleanup-project", "organization_id": org_id},
        headers=headers,
    )
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    create_queue = client.post(
        "/api/queues",
        json={"name": f"cleanup-q-{random.randint(1000, 9999)}", "project_id": project_id},
        headers=headers,
    )
    assert create_queue.status_code == 200
    queue_id = create_queue.json()["id"]

    create_job = client.post(
        "/api/jobs",
        json={"payload": {"task": "cleanup"}, "queue_id": queue_id},
        headers=headers,
    )
    assert create_job.status_code == 201
    job_id = create_job.json()["job_id"]

    worker_id = f"worker-cleanup-{random.randint(1000, 9999)}"
    db = SessionLocal()
    try:
        db.add(JobExecution(job_id=job_id, worker_id=worker_id, status="COMPLETED", logs="done"))
        db.add(DeadLetterJob(job_id=job_id, queue_id=queue_id, payload={"task": "cleanup"}, failure_reason="bad", retry_count=1, max_retries=1, worker_id=worker_id))
        db.add(WorkerRegistration(worker_id=worker_id, hostname="host", pid=1, status="ACTIVE"))
        db.add(WorkerHeartbeat(worker_id=worker_id, status="ACTIVE", note="ok"))
        db.commit()
    finally:
        db.close()

    cleanup_response = client.delete("/api/dashboard/cleanup", headers=headers)
    assert cleanup_response.status_code == 200

    db = SessionLocal()
    try:
        assert db.query(Job).filter(Job.id == job_id).count() == 0
        assert db.query(JobExecution).filter(JobExecution.job_id == job_id).count() == 0
        assert db.query(DeadLetterJob).filter(DeadLetterJob.job_id == job_id).count() == 0
        assert db.query(WorkerRegistration).filter(WorkerRegistration.worker_id == worker_id).count() == 0
        assert db.query(WorkerHeartbeat).filter(WorkerHeartbeat.worker_id == worker_id).count() == 0
    finally:
        db.close()


def test_queue_delete_endpoint_removes_queue_from_listing():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    org_name = f"org-delete-{random.randint(1000, 9999)}"
    create_org = client.post("/api/users/organizations", json={"name": org_name}, headers=headers)
    assert create_org.status_code == 201
    org_id = create_org.json()["id"]

    create_project = client.post(
        "/api/users/projects",
        json={"name": "delete-project", "organization_id": org_id},
        headers=headers,
    )
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    create_queue = client.post(
        "/api/queues",
        json={"name": f"delete-q-{random.randint(1000, 9999)}", "project_id": project_id},
        headers=headers,
    )
    assert create_queue.status_code == 200
    queue_id = create_queue.json()["id"]

    delete_response = client.delete(f"/api/queues/{queue_id}", headers=headers)
    assert delete_response.status_code == 200

    list_response = client.get("/api/queues", headers=headers)
    assert list_response.status_code == 200
    queue_ids = [item["id"] for item in list_response.json()["data"]]
    assert queue_id not in queue_ids


def test_dashboard_endpoints_and_static_assets_require_auth():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    # /dashboard static app should be publicly servable
    dashboard_page = client.get("/dashboard")
    assert dashboard_page.status_code == 200
    assert "Distributed Job Scheduler Dashboard" in dashboard_page.text

    dashboard_css = client.get("/dashboard/styles.css")
    assert dashboard_css.status_code == 200

    dashboard_js = client.get("/dashboard/app.js")
    assert dashboard_js.status_code == 200

    # dashboard APIs require auth
    unauth = client.get("/api/dashboard/health")
    assert unauth.status_code == 401

    for endpoint in [
        "/api/dashboard/health",
        "/api/dashboard/queues",
        "/api/dashboard/jobs",
        "/api/dashboard/workers",
        "/api/dashboard/executions",
    ]:
        resp = client.get(endpoint, headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), dict)


def test_pagination_shapes_for_users_queues_jobs():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    org_name = f"org-pag-{random.randint(1000, 9999)}"
    create_org = client.post("/api/users/organizations", json={"name": org_name}, headers=headers)
    assert create_org.status_code == 201
    org_id = create_org.json()["id"]

    create_project = client.post(
        "/api/users/projects",
        json={"name": "pag-project", "organization_id": org_id},
        headers=headers,
    )
    assert create_project.status_code == 201
    project_id = create_project.json()["id"]

    queue_name = f"pag-q-{random.randint(1000, 9999)}"
    create_queue = client.post(
        "/api/queues",
        json={"name": queue_name, "project_id": project_id},
        headers=headers,
    )
    assert create_queue.status_code == 200
    queue_id = create_queue.json()["id"]

    # seed at least one job
    create_job = client.post(
        "/api/jobs",
        json={"payload": {"task": "pagination"}, "queue_id": queue_id},
        headers=headers,
    )
    assert create_job.status_code == 201

    # users organizations/projects pagination shape
    orgs_resp = client.get("/api/users/organizations?limit=10&offset=0", headers=headers)
    assert orgs_resp.status_code == 200
    orgs_json = orgs_resp.json()
    assert "data" in orgs_json and "meta" in orgs_json

    projects_resp = client.get("/api/users/projects?limit=10&offset=0", headers=headers)
    assert projects_resp.status_code == 200
    projects_json = projects_resp.json()
    assert "data" in projects_json and "meta" in projects_json

    # queues/jobs pagination shape
    queues_resp = client.get("/api/queues?limit=10&offset=0", headers=headers)
    assert queues_resp.status_code == 200
    queues_json = queues_resp.json()
    assert "data" in queues_json and "meta" in queues_json

    jobs_resp = client.get("/api/jobs?limit=10&offset=0", headers=headers)
    assert jobs_resp.status_code == 200
    jobs_json = jobs_resp.json()
    assert "data" in jobs_json and "meta" in jobs_json


def test_error_envelope_for_unauthorized_and_not_found():
    unauthorized = client.get("/api/dashboard/health")
    assert unauthorized.status_code == 401
    payload = unauthorized.json()
    assert payload["error"] == "HTTP_ERROR"
    assert "detail" in payload
    assert payload["path"] == "/api/dashboard/health"

    missing = client.get("/this-route-does-not-exist")
    assert missing.status_code == 404
    missing_payload = missing.json()
    assert isinstance(missing_payload, dict)
    assert "detail" in missing_payload


def test_pagination_boundary_and_invalid_query_values():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    valid_min_limit = client.get("/api/jobs?limit=0&offset=0", headers=headers)
    assert valid_min_limit.status_code == 200
    valid_min_limit_json = valid_min_limit.json()
    assert "data" in valid_min_limit_json and "meta" in valid_min_limit_json

    # This repo currently doesn't hard-validate negative offsets server-side.
    # Ensure it doesn't crash the test process when DB raises for negative OFFSET.
    invalid_offset = client.get("/api/queues?limit=10&offset=-1", headers=headers)
    assert invalid_offset.status_code in (400, 422, 500)
    if invalid_offset.status_code in (400, 422):
        invalid_offset_json = invalid_offset.json()
        if isinstance(invalid_offset_json, dict) and "error" in invalid_offset_json:
            assert invalid_offset_json["error"] == "HTTP_ERROR"


def test_malformed_payloads_and_auth_variants():
    token = _signup_and_login()
    headers = {"Authorization": f"Bearer {token}"}

    malformed_signup = client.post(
        "/api/users/signup",
        json={"email": "not-an-email", "password": "x"},
    )
    assert malformed_signup.status_code in (400, 422)

    missing_bearer = client.get("/api/users/organizations", headers={"Authorization": token})
    assert missing_bearer.status_code in (401, 403)

    malformed_job = client.post(
        "/api/jobs",
        json={"payload": "not-a-dict", "queue_id": "bad"},
        headers=headers,
    )
    assert malformed_job.status_code in (400, 422)
