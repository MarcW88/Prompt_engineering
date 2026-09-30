create table public.datasets (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references public.projects(id) on delete cascade,
  name text not null,
  status text not null default 'building' check (status in ('building','executing','ready','archived')),
  target_size integer not null default 500,
  repetitions integer not null default 3,
  engines jsonb not null default '["chatgpt"]'::jsonb,
  build_config jsonb not null default '{}'::jsonb,
  statistics jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  completed_at timestamptz
);

create table public.dataset_examples (
  id uuid primary key default gen_random_uuid(),
  dataset_id uuid not null references public.datasets(id) on delete cascade,
  prompt_id uuid not null references public.prompts(id) on delete cascade,
  cluster_id uuid references public.clusters(id) on delete set null,
  status text not null default 'candidate' check (status in ('candidate','executing','accepted','rejected')),
  persona text,
  journey_stage text,
  specificity_level integer,
  expected_sub_intents jsonb not null default '[]'::jsonb,
  coverage_score numeric(5,4),
  stability_score numeric(5,4),
  reproduction_score numeric(5,4),
  redundancy_score numeric(5,4),
  quality_score numeric(5,4),
  rejection_reason text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique(dataset_id, prompt_id)
);

create index datasets_project_idx on public.datasets(project_id, created_at desc);
create index dataset_examples_dataset_status_idx on public.dataset_examples(dataset_id, status);
alter table public.datasets enable row level security;
alter table public.dataset_examples enable row level security;
