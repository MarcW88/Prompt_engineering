alter table public.dataset_examples add column if not exists manual_review_status text not null default 'pending' check (manual_review_status in ('pending','approved','rejected'));
alter table public.dataset_examples add column if not exists reviewed_by uuid references auth.users(id) on delete set null;
alter table public.dataset_examples add column if not exists reviewed_at timestamptz;
alter table public.dataset_examples add column if not exists review_note text;
alter table public.dataset_examples add column if not exists edited_prompt_text text;
alter table public.dataset_examples add column if not exists merged_into_prompt_id uuid references public.prompts(id) on delete set null;
create index if not exists dataset_examples_manual_review_idx on public.dataset_examples(dataset_id, manual_review_status, quality_score desc);
