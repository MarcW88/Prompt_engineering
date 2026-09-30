alter table public.datasets add column if not exists candidate_pool_size integer not null default 500;
alter table public.datasets add column if not exists execution_sample_size integer not null default 100;
alter table public.datasets add column if not exists cost_per_execution_eur numeric(10,4) not null default 0;
alter table public.datasets add column if not exists max_budget_eur numeric(10,2) not null default 20;
alter table public.datasets add column if not exists estimated_cost_eur numeric(10,2) not null default 0;

alter table public.dataset_examples add column if not exists pre_execution_score numeric(5,4);
alter table public.dataset_examples add column if not exists selected_for_execution boolean not null default false;
alter table public.dataset_examples add column if not exists selection_reason text;
alter table public.dataset_examples add column if not exists validation_tier integer not null default 3 check (validation_tier between 1 and 3);
alter table public.dataset_examples add column if not exists target_runs integer not null default 1 check (target_runs in (1, 3, 5));
alter table public.dataset_examples add column if not exists completed_runs integer not null default 0;

create index if not exists dataset_examples_selection_idx on public.dataset_examples(dataset_id, selected_for_execution, pre_execution_score desc);
