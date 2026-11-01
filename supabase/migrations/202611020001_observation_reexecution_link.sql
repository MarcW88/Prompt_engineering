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
