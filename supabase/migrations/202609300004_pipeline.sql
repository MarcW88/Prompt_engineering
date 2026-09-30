alter table public.clusters add column if not exists fingerprint text;
create unique index if not exists clusters_project_fingerprint_idx on public.clusters(project_id, fingerprint);
create unique index if not exists questions_project_signal_text_idx on public.questions(project_id, signal_id, text);
create unique index if not exists prompts_project_text_idx on public.prompts(project_id, text);

alter table public.jobs add column if not exists depends_on uuid references public.jobs(id) on delete set null;
create index if not exists jobs_dependency_idx on public.jobs(depends_on, status);
