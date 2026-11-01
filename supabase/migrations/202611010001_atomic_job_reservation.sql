-- Réservation budgétaire atomique : le job est créé dans la même transaction
-- que la vérification du solde (verrou FOR UPDATE sur la ligne projet), ce qui
-- élimine la course entre deux requêtes simultanées.
--
-- La colonne jobs.reserved_cost_eur est la source de vérité des réservations ;
-- les anciennes conventions input.reserved_cost_eur sont lues en secours.

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

  -- Réservations encore actives (colonne = source de vérité, input en secours).
  select coalesce(sum(greatest(
      coalesce(j.reserved_cost_eur, 0),
      coalesce(nullif(j.input->>'reserved_cost_eur', '')::numeric, 0)
    )), 0)
    into v_reserved
  from public.jobs j
  where j.project_id = p_project_id
    and j.status in ('pending', 'running');

  if v_confirmed + v_reserved + coalesce(p_reserved_eur, 0) > v_budget then
    raise exception 'budget_exceeded: confirmed=% reserved=% request=% budget=%',
      round(v_confirmed, 2), round(v_reserved, 2), round(coalesce(p_reserved_eur, 0), 2), v_budget;
  end if;

  insert into public.jobs (project_id, kind, status, input, reserved_cost_eur)
  values (p_project_id, p_kind, 'pending', coalesce(p_input, '{}'::jsonb), coalesce(p_reserved_eur, 0))
  returning * into v_job;

  return v_job;
end;
$$;
