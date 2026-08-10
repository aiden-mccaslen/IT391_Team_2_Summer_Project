-- 003_weekly_reflections.sql
-- The dashboard's "Weekly reflection" card: one coach question per user per week,
-- plus whatever the user wrote back.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query, paste this whole
-- file in, hit Run. Safe to re-run.
--
-- The Python side of this lives in Backend/reflections.py.


-- One row per user per week. `week_start` is the Monday of that week (UTC), which
-- is what makes "have we already asked this user something this week?" a primary
-- key lookup rather than a date-range scan -- and stops two tabs open at once
-- from generating (and paying for) two different questions.
create table if not exists public.weekly_reflections (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    week_start date not null,       -- Monday of the week this question belongs to
    question text not null,         -- what the coach asked
    answer text,                    -- null until the user writes something back
    created_at timestamptz not null default now(),
    answered_at timestamptz,        -- null until the first answer is saved
    unique (user_id, week_start)
);

-- The history list is "my reflections, newest week first".
create index if not exists weekly_reflections_user_week_idx
    on public.weekly_reflections (user_id, week_start desc);


-- ---------------------------------------------------------------------------
-- Row Level Security -- same shape as 001/002. The backend talks to Postgres as
-- the logged-in user (see user.caller_client), so auth.uid() is that user and
-- other people's reflections do not exist as far as this client is concerned.
-- ---------------------------------------------------------------------------
alter table public.weekly_reflections enable row level security;

drop policy if exists weekly_reflections_select_own on public.weekly_reflections;
create policy weekly_reflections_select_own on public.weekly_reflections
    for select to authenticated
    using (user_id = auth.uid());

drop policy if exists weekly_reflections_insert_own on public.weekly_reflections;
create policy weekly_reflections_insert_own on public.weekly_reflections
    for insert to authenticated
    with check (user_id = auth.uid());

drop policy if exists weekly_reflections_update_own on public.weekly_reflections;
create policy weekly_reflections_update_own on public.weekly_reflections
    for update to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists weekly_reflections_delete_own on public.weekly_reflections;
create policy weekly_reflections_delete_own on public.weekly_reflections
    for delete to authenticated
    using (user_id = auth.uid());
