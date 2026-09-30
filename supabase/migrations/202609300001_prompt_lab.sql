create extension if not exists pgcrypto;

create table public.projects (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text not null unique,
  website text,
  country text not null default 'BE',
  language text not null default 'fr',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table public.sources (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  kind text not null check (kind in ('gsc','reddit','forum','review','serp','manual')),
  name text not null,
  config jsonb not null default '{}'::jsonb,
  enabled boolean not null default true,
  last_synced_at timestamptz,
  created_at timestamptz not null default now()
);

create table public.signals (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  source_id uuid references public.sources(id) on delete set null,
  source_type text not null,
  platform text not null,
  raw_text text not null,
  title text,
  url text,
  language text,
  theme text,
  brand text,
  metadata jsonb not null default '{}'::jsonb,
  content_hash text not null,
  collected_at timestamptz not null default now(),
  unique(project_id, content_hash)
);

create table public.questions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  signal_id uuid references public.signals(id) on delete set null,
  text text not null,
  provenance text not null check (provenance in ('observed','transformed','synthetic')),
  language text not null default 'fr',
  confidence numeric(5,4) not null default 1,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.clusters (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  label text not null,
  representative_question text not null,
  question_count integer not null default 0,
  source_count integer not null default 0,
  is_geo_relevant boolean not null default false,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.cluster_questions (
  cluster_id uuid not null references public.clusters(id) on delete cascade,
  question_id uuid not null references public.questions(id) on delete cascade,
  similarity numeric(5,4),
  primary key(cluster_id, question_id)
);

create table public.prompts (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  cluster_id uuid references public.clusters(id) on delete set null,
  text text not null,
  provenance text not null check (provenance in ('observed','reverse_engineered','synthetic')),
  confidence numeric(5,4) not null default 0,
  status text not null default 'draft' check (status in ('draft','testing','validated','archived')),
  expected_fan_outs jsonb not null default '[]'::jsonb,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table public.observations (
  id uuid primary key default gen_random_uuid(),
  prompt_id uuid not null references public.prompts(id) on delete cascade,
  provider text not null,
  engine text not null,
  model text,
  country text not null,
  language text not null,
  answer text,
  web_search_triggered boolean,
  raw_response jsonb not null default '{}'::jsonb,
  observed_at timestamptz not null default now()
);

create table public.fan_outs (
  id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references public.observations(id) on delete cascade,
  position integer not null,
  query text not null,
  normalized_query text not null,
  unique(observation_id, position)
);

create table public.citations (
  id uuid primary key default gen_random_uuid(),
  observation_id uuid not null references public.observations(id) on delete cascade,
  position integer,
  url text not null,
  title text,
  excerpt text
);

create table public.validations (
  id uuid primary key default gen_random_uuid(),
  prompt_id uuid not null references public.prompts(id) on delete cascade,
  observation_id uuid not null references public.observations(id) on delete cascade,
  fan_out_reproduction_score numeric(5,4) not null default 0,
  citation_overlap_score numeric(5,4) not null default 0,
  stability_score numeric(5,4) not null default 0,
  overall_score numeric(5,4) not null default 0,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(prompt_id, observation_id)
);

create table public.jobs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  kind text not null,
  status text not null default 'pending' check (status in ('pending','running','completed','failed')),
  progress integer not null default 0 check (progress between 0 and 100),
  input jsonb not null default '{}'::jsonb,
  output jsonb not null default '{}'::jsonb,
  error text,
  created_at timestamptz not null default now(),
  started_at timestamptz,
  completed_at timestamptz
);

create index sources_project_idx on public.sources(project_id);
create index signals_project_idx on public.signals(project_id);
create index questions_project_idx on public.questions(project_id);
create index clusters_project_idx on public.clusters(project_id);
create index prompts_project_idx on public.prompts(project_id);
create index observations_prompt_idx on public.observations(prompt_id);
create index jobs_project_status_idx on public.jobs(project_id, status);

alter table public.projects enable row level security;
alter table public.sources enable row level security;
alter table public.signals enable row level security;
alter table public.questions enable row level security;
alter table public.clusters enable row level security;
alter table public.cluster_questions enable row level security;
alter table public.prompts enable row level security;
alter table public.observations enable row level security;
alter table public.fan_outs enable row level security;
alter table public.citations enable row level security;
alter table public.validations enable row level security;
alter table public.jobs enable row level security;
