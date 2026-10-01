alter table public.jobs add column if not exists worker_id text;
alter table public.jobs add column if not exists cloud_execution_id text;
alter table public.jobs add column if not exists heartbeat_at timestamptz;
alter table public.jobs add column if not exists attempt_count integer not null default 0;
alter table public.jobs add column if not exists max_attempts integer not null default 3;

create or replace function public.claim_job(p_job_id uuid, p_worker_id text, p_cloud_execution_id text default null)
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  update public.jobs
  set status = 'running',
      worker_id = p_worker_id,
      cloud_execution_id = p_cloud_execution_id,
      heartbeat_at = now(),
      started_at = coalesce(started_at, now()),
      attempt_count = attempt_count + 1,
      error = null
  where id = p_job_id
    and status = 'pending'
    and attempt_count < max_attempts
  returning *;
end;
$$;

create or replace function public.claim_next_job(p_worker_id text, p_cloud_execution_id text default null)
returns setof public.jobs
language plpgsql
security definer
set search_path = public
as $$
begin
  return query
  with candidate as (
    select id
    from public.jobs
    where status = 'pending'
      and attempt_count < max_attempts
      and kind in ('collect_sources','transform_signals','cluster_questions','build_dataset','validate_dataset','reverse_engineer')
    order by created_at asc
    for update skip locked
    limit 1
  )
  update public.jobs
  set status = 'running',
      worker_id = p_worker_id,
      cloud_execution_id = p_cloud_execution_id,
      heartbeat_at = now(),
      started_at = coalesce(started_at, now()),
      attempt_count = attempt_count + 1,
      error = null
  where id in (select id from candidate)
  returning *;
end;
$$;

revoke all on function public.claim_job(uuid, text, text) from public, anon, authenticated;
revoke all on function public.claim_next_job(text, text) from public, anon, authenticated;
grant execute on function public.claim_job(uuid, text, text) to service_role;
grant execute on function public.claim_next_job(text, text) to service_role;

create index if not exists jobs_worker_idx on public.jobs(worker_id, status);
create index if not exists jobs_heartbeat_idx on public.jobs(status, heartbeat_at);
