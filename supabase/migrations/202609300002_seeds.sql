create table public.seeds (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  value text not null,
  seed_type text not null check (seed_type in ('keyword','theme','brand','competitor','product','problem')),
  priority integer not null default 50 check (priority between 0 and 100),
  language text not null default 'fr',
  market text not null default 'BE',
  source text not null default 'manual',
  enabled boolean not null default true,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(project_id, value, seed_type, language, market)
);

create index seeds_project_priority_idx on public.seeds(project_id, enabled, priority desc);
alter table public.seeds enable row level security;
