-- §5 Provenance: a fallback extraction is an independent re-execution, kept as
-- its own observation linked to the run it complements. The worker also writes
-- the same link inside raw_response/fan_outs.metadata so the relation is
-- preserved even before this migration is applied.
alter table public.observations
    add column if not exists parent_observation_id uuid references public.observations(id),
    add column if not exists relation text not null default 'same_run';

alter table public.observations
    drop constraint if exists observations_relation_check;

alter table public.observations
    add constraint observations_relation_check
    check (relation in ('same_run', 'independent_reexecution'));

create index if not exists observations_parent_idx
    on public.observations (parent_observation_id);

-- Trace status on scored examples: a run that exposes no searches is
-- "not_exposed" / "none_reported", never a silent zero reproduction.
alter table public.dataset_examples
    add column if not exists trace_status text;

alter table public.dataset_examples
    drop constraint if exists dataset_examples_trace_status_check;

alter table public.dataset_examples
    add constraint dataset_examples_trace_status_check
    check (trace_status is null or trace_status in ('provider_reported', 'independent_reexecution', 'none_reported', 'not_exposed'));
