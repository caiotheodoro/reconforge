CREATE TABLE IF NOT EXISTS recon_entries (
    id serial PRIMARY KEY,
    task_id text NOT NULL UNIQUE,
    event_id uuid NOT NULL,
    pair jsonb,
    verdict jsonb,
    source text NOT NULL CHECK (source IN ('model', 'human', 'system')),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_recon_entries_task_id ON recon_entries (task_id);
CREATE INDEX IF NOT EXISTS idx_recon_entries_created_at ON recon_entries (created_at);

CREATE TABLE IF NOT EXISTS recon_reviews (
    task_id text PRIMARY KEY,
    pair jsonb,
    provisional jsonb,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'resolved', 'timed-out')),
    decision text,
    note text,
    final_verdict jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_recon_reviews_status ON recon_reviews (status, created_at);

CREATE TABLE IF NOT EXISTS recon_schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
