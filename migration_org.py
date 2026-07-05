from app.database import engine


def run():
    statements = [
        "CREATE TABLE IF NOT EXISTS organizations (id SERIAL PRIMARY KEY, name VARCHAR NOT NULL UNIQUE)",
        "CREATE TABLE IF NOT EXISTS organization_memberships (id SERIAL PRIMARY KEY, organization_id INTEGER NOT NULL REFERENCES organizations(id), user_id INTEGER NOT NULL REFERENCES users(id), role VARCHAR NOT NULL DEFAULT 'MEMBER')",
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS organization_id INTEGER",
        "INSERT INTO organizations (name) SELECT DISTINCT ('legacy-org-user-' || owner_id) FROM projects WHERE owner_id IS NOT NULL ON CONFLICT (name) DO NOTHING",
        "UPDATE projects p SET organization_id = o.id FROM organizations o WHERE p.organization_id IS NULL AND p.owner_id IS NOT NULL AND o.name = ('legacy-org-user-' || p.owner_id)",
        "INSERT INTO organizations (name) SELECT 'legacy-unowned-projects-org' WHERE EXISTS (SELECT 1 FROM projects WHERE organization_id IS NULL) ON CONFLICT (name) DO NOTHING",
        "UPDATE projects SET organization_id = (SELECT id FROM organizations WHERE name = 'legacy-unowned-projects-org' LIMIT 1) WHERE organization_id IS NULL",
        "INSERT INTO organization_memberships (organization_id, user_id, role) SELECT DISTINCT o.id, p.owner_id, 'OWNER'::organizationrole FROM projects p JOIN organizations o ON o.name = ('legacy-org-user-' || p.owner_id) WHERE p.owner_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM organization_memberships m WHERE m.organization_id = o.id AND m.user_id = p.owner_id)",
        "ALTER TABLE projects ALTER COLUMN organization_id SET NOT NULL",
        "DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'projects_organization_id_fkey') THEN ALTER TABLE projects ADD CONSTRAINT projects_organization_id_fkey FOREIGN KEY (organization_id) REFERENCES organizations(id); END IF; END $$",
        "CREATE INDEX IF NOT EXISTS ix_projects_organization_id ON projects (organization_id)",
        "CREATE INDEX IF NOT EXISTS ix_organization_memberships_org_user ON organization_memberships (organization_id, user_id)",
    ]

    conn = engine.raw_connection()
    cur = conn.cursor()
    try:
        for stmt in statements:
            cur.execute(stmt)
        conn.commit()
        print("migration applied")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    run()
