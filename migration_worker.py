from app.database import engine


def run():
    statements = [
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_by VARCHAR",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS finished_at TIMESTAMP",
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS last_error TEXT",
        "CREATE INDEX IF NOT EXISTS ix_jobs_claimed_by ON jobs (claimed_by)",
        "CREATE INDEX IF NOT EXISTS ix_jobs_claimed_at ON jobs (claimed_at)",
        "CREATE INDEX IF NOT EXISTS ix_jobs_heartbeat_at ON jobs (heartbeat_at)",
        """
        CREATE TABLE IF NOT EXISTS worker_registrations (
            id SERIAL PRIMARY KEY,
            worker_id VARCHAR NOT NULL UNIQUE,
            hostname VARCHAR NOT NULL,
            pid INTEGER NOT NULL,
            status VARCHAR NOT NULL DEFAULT 'ACTIVE',
            started_at TIMESTAMP NOT NULL DEFAULT NOW(),
            last_heartbeat_at TIMESTAMP NOT NULL DEFAULT NOW(),
            shutdown_at TIMESTAMP NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_worker_registrations_worker_id ON worker_registrations (worker_id)",
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            id SERIAL PRIMARY KEY,
            worker_id VARCHAR NOT NULL REFERENCES worker_registrations(worker_id) ON DELETE CASCADE,
            heartbeat_at TIMESTAMP NOT NULL DEFAULT NOW(),
            status VARCHAR NOT NULL DEFAULT 'ACTIVE',
            note VARCHAR NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_worker_heartbeats_worker_id ON worker_heartbeats (worker_id)",
        "CREATE INDEX IF NOT EXISTS ix_worker_heartbeats_heartbeat_at ON worker_heartbeats (heartbeat_at)",
        """
        CREATE TABLE IF NOT EXISTS dead_letter_jobs (
            id SERIAL PRIMARY KEY,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            queue_id INTEGER NOT NULL REFERENCES queues(id) ON DELETE CASCADE,
            payload JSON NOT NULL,
            failure_reason TEXT NULL,
            failed_at TIMESTAMP NOT NULL DEFAULT NOW(),
            retry_count INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL DEFAULT 0,
            worker_id VARCHAR NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_dead_letter_jobs_job_id ON dead_letter_jobs (job_id)",
        "CREATE INDEX IF NOT EXISTS ix_dead_letter_jobs_queue_id ON dead_letter_jobs (queue_id)",
        "CREATE INDEX IF NOT EXISTS ix_dead_letter_jobs_failed_at ON dead_letter_jobs (failed_at)",
    ]

    conn = engine.raw_connection()
    cur = conn.cursor()
    try:
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
        print("worker migration applied")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
