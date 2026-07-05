# API Curl Coverage Guide (Item 8)

This document provides curl-style coverage for major endpoints including auth, users/orgs/projects, queues, jobs, and dashboard.

## 1) Auth bootstrap

### Signup
```bash
curl -X POST http://localhost:8000/api/users/signup \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"user1@example.com\",\"password\":\"supersecretpassword123\"}"
```

### Login
```bash
curl -X POST http://localhost:8000/api/users/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user1@example.com&password=supersecretpassword123"
```

Set token:
```bash
TOKEN="<paste_access_token>"
AUTH_HEADER="Authorization: Bearer $TOKEN"
```

---

## 2) Organizations and Projects

### Create organization
```bash
curl -X POST http://localhost:8000/api/users/organizations \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"org-alpha\"}"
```

### List organizations (paginated)
```bash
curl -X GET "http://localhost:8000/api/users/organizations?limit=20&offset=0" \
  -H "$AUTH_HEADER"
```

### Create project
```bash
curl -X POST http://localhost:8000/api/users/projects \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"project-alpha\",\"organization_id\":1}"
```

### List projects (paginated)
```bash
curl -X GET "http://localhost:8000/api/users/projects?limit=20&offset=0" \
  -H "$AUTH_HEADER"
```

---

## 3) Queues

### Create queue
```bash
curl -X POST http://localhost:8000/api/queues \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"queue-alpha\",\"project_id\":1,\"priority\":5,\"concurrency\":2,\"retry_count\":3,\"retry_strategy\":\"FIXED\"}"
```

### List queues (paginated/filter)
```bash
curl -X GET "http://localhost:8000/api/queues?limit=20&offset=0&project_id=1" \
  -H "$AUTH_HEADER"
```

### Pause / Resume queue
```bash
curl -X PATCH http://localhost:8000/api/queues/1/pause -H "$AUTH_HEADER"
curl -X PATCH http://localhost:8000/api/queues/1/resume -H "$AUTH_HEADER"
```

### Queue stats
```bash
curl -X GET http://localhost:8000/api/queues/1/stats -H "$AUTH_HEADER"
```

---

## 4) Jobs

### Create job
```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"payload\":{\"task\":\"hello\"},\"queue_id\":1,\"priority\":3,\"max_retries\":2,\"retry_strategy\":\"LINEAR\"}"
```

### Create delayed/scheduled job
```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"payload\":{\"task\":\"future\"},\"queue_id\":1,\"run_at\":\"2030-01-01T00:00:00Z\"}"
```

### Batch jobs
```bash
curl -X POST http://localhost:8000/api/jobs/batch \
  -H "$AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d "{\"jobs\":[{\"task\":1},{\"task\":2}],\"queue_id\":1}"
```

### List jobs (paginated/filter)
```bash
curl -X GET "http://localhost:8000/api/jobs?limit=20&offset=0&status_filter=QUEUED&queue_id=1" \
  -H "$AUTH_HEADER"
```

---

## 5) Dashboard

### Static dashboard UI
```bash
curl -X GET http://localhost:8000/dashboard
curl -X GET http://localhost:8000/dashboard/styles.css
curl -X GET http://localhost:8000/dashboard/app.js
```

### Dashboard APIs
```bash
curl -X GET http://localhost:8000/api/dashboard/health -H "$AUTH_HEADER"
curl -X GET http://localhost:8000/api/dashboard/queues -H "$AUTH_HEADER"
curl -X GET http://localhost:8000/api/dashboard/jobs -H "$AUTH_HEADER"
curl -X GET http://localhost:8000/api/dashboard/workers -H "$AUTH_HEADER"
curl -X GET http://localhost:8000/api/dashboard/executions -H "$AUTH_HEADER"
```

---

## 6) Error envelope sanity checks

### Unauthorized sample
```bash
curl -X GET http://localhost:8000/api/dashboard/health
```
Expected shape:
```json
{
  "error": "HTTP_ERROR",
  "detail": "...",
  "path": "/api/dashboard/health"
}
```

### Unknown route sample
```bash
curl -X GET http://localhost:8000/this-route-does-not-exist
```
Expect HTTP error envelope format as configured by exception handlers.
