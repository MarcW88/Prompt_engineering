alter table public.projects
  add column if not exists budget_total_eur numeric(10,2) not null default 8,
  add column if not exists budget_profile jsonb not null default '{}'::jsonb;

alter table public.jobs
  add column if not exists reserved_cost_eur numeric(10,2) not null default 0;
