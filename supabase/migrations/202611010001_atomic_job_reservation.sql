-- Réservation budgétaire atomique : le job est créé dans la même transaction
-- que la vérification du solde (verrou FOR UPDATE sur la ligne projet), ce qui
-- élimine la course entre deux requêtes simultanées.
--
-- La colonne jobs.reserved_cost_eur est la source de vérité des réservations ;
-- les anciennes conventions input.reserved_cost_eur sont lues en secours.
-- jobs.reservation_open reste vrai tant qu'un engagement non rapproché existe :
-- le worker le maintient après terminaison si des coûts pending_reconciliation
-- subsistent, puis le ferme une fois la dépense réelle confirmée.

alter table public.jobs
  add column if not exists reservation_open boolean not null default false;

create or replace function public.create_reserved_job(
  p_project_id uuid,
  p_kind text,
  p_input jsonb default '{}'::jsonb,
  p_reserved_eur numeric default 0
)
returns public.jobs
language plpgsql
security definer
set search_path = public
as $$
declare
  v_budget numeric;
  v_confirmed numeric;
  v_reserved numeric;
  v_job public.jobs;
begin
  if p_reserved_eur is null or p_reserved_eur < 0 then
    raise exception 'invalid_reservation: %', p_reserved_eur;
  end if;
  if p_kind not in ('build_dataset', 'validate_dataset', 'reverse_engineer') then
    raise exception 'invalid_job_kind: %', p_kind;
  end if;

  select budget_total_eur into v_budget
  from public.projects
  where id = p_project_id
  for update;

  if v_budget is null then
    raise exception 'project_not_found: %', p_project_id;
  end if;

  -- Coûts confirmés, mêmes statuts et conversion USD->EUR que confirmedCostEur.
  select coalesce(sum(case when lower(currency) = 'usd' then amount * 0.92 else amount end), 0)
    into v_confirmed
  from public.analysis_costs
  where project_id = p_project_id
    and cost_status in ('actual', 'account_delta')
    and amount is not null;

  -- Resynchronise les provisions résiduelles des jobs terminés : si des
  -- dépenses réelles ont remplacé les estimations en attente (upsert sur la
  -- référence), le reliquat se libère sans intervention.
  update public.jobs j
  set reserved_cost_eur = coalesce((
        select sum(c.amount) from public.analysis_costs c
        where c.job_id = j.id
          and c.cost_status in ('pending_reconciliation', 'usage_only', 'unavailable')
      ), 0),
      reservation_open = coalesce((
        select sum(c.amount) from public.analysis_costs c
        where c.job_id = j.id
          and c.cost_status in ('pending_reconciliation', 'usage_only', 'unavailable')
      ), 0) > 0
  where j.project_id = p_project_id
    and j.reservation_open
    and j.status in ('completed', 'failed', 'cancelled');

  -- Engagements encore ouverts : réservations de jobs actifs + provisions
  -- résiduelles conservées après terminaison en attente de rapprochement.
  select coalesce(sum(greatest(
      coalesce(j.reserved_cost_eur, 0),
      coalesce(nullif(j.input->>'reserved_cost_eur', '')::numeric, 0)
    )), 0)
    into v_reserved
  from public.jobs j
  where j.project_id = p_project_id
    and j.reservation_open;

  if v_confirmed + v_reserved + p_reserved_eur > v_budget then
    raise exception 'budget_exceeded: confirmed=% reserved=% request=% budget=%',
      round(v_confirmed, 2), round(v_reserved, 2), round(p_reserved_eur, 2), v_budget;
  end if;

  insert into public.jobs (project_id, kind, status, input, reserved_cost_eur, reservation_open)
  values (p_project_id, p_kind, 'pending', coalesce(p_input, '{}'::jsonb), p_reserved_eur, p_reserved_eur > 0)
  returning * into v_job;

  return v_job;
end;
$$;

-- Usage réservé au backend (service_role), sur le modèle des RPC worker.
revoke all on function public.create_reserved_job(uuid, text, jsonb, numeric) from public, anon, authenticated;
grant execute on function public.create_reserved_job(uuid, text, jsonb, numeric) to service_role;
