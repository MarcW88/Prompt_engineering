create table public.analysis_costs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  job_id uuid references public.jobs(id) on delete set null,
  dataset_id uuid references public.datasets(id) on delete set null,
  provider text not null,
  category text not null,
  amount numeric(12,6),
  currency text not null default 'usd',
  quantity numeric(14,4),
  unit text,
  cost_status text not null check (cost_status in ('actual','account_delta','usage_only','pending_reconciliation','unavailable')),
  external_reference text,
  metadata jsonb not null default '{}'::jsonb,
  occurred_at timestamptz not null default now(),
  unique(provider, category, external_reference)
);

alter table public.jobs add column if not exists actual_cost_usd numeric(12,6) not null default 0;
alter table public.jobs add column if not exists cost_status text not null default 'pending_reconciliation';
alter table public.datasets add column if not exists actual_cost_usd numeric(12,6) not null default 0;
alter table public.datasets add column if not exists cost_status text not null default 'pending_reconciliation';

create index if not exists analysis_costs_project_idx on public.analysis_costs(project_id, occurred_at desc);
create index if not exists analysis_costs_job_idx on public.analysis_costs(job_id);
alter table public.analysis_costs enable row level security;
