alter table public.fan_outs add column if not exists source text not null default 'provider';
alter table public.fan_outs add column if not exists metadata jsonb not null default '{}'::jsonb;
create index if not exists fan_outs_source_idx on public.fan_outs(source);
