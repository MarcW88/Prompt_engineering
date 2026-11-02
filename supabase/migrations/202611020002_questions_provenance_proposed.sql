alter table public.questions drop constraint questions_provenance_check;
alter table public.questions add constraint questions_provenance_check
  check (provenance in ('observed', 'transformed', 'synthetic', 'proposed'));
