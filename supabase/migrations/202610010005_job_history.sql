alter table public.jobs add column if not exists hidden_at timestamptz;
create index if not exists jobs_project_hidden_idx on public.jobs(project_id, hidden_at, created_at desc);
