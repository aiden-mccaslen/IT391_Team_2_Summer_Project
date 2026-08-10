-- 005_companion.sql
-- Storage for the dashboard's companion widget: a small mascot whose mood/level
-- is a cosmetic readout of the user's real budgeting activity.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query, paste this whole
-- file in, hit Run. Safe to re-run.
--
-- The Python side of this lives in Backend/companion.py. That module is the
-- ONLY thing that reads or writes this table -- no other backend file imports
-- companion.py, so dropping this migration and companion.py together removes
-- the feature cleanly, with nothing left dangling elsewhere.
--
-- Deliberately thin: mood, level and stage are recomputed from expenses,
-- funds and weekly_reflections on every read (see companion.get_state). The
-- columns below just persist the most recent computed value plus the one
-- thing that is not derived from anything else -- the name the user picked.


-- One row per user. There is nothing to key by week or by day -- unlike
-- weekly_reflections, the companion is a single ongoing character, not a
-- series of entries -- so user_id is the primary key rather than a uuid with
-- a separate unique constraint.
create table if not exists public.companion_state (
    user_id uuid primary key references auth.users (id) on delete cascade,
    name text,                                  -- user-chosen; null until set
    level integer not null default 0,
    stage integer not null default 0,           -- coarse growth tier derived from level
    streak integer not null default 0,           -- consecutive days with a logged expense
    created_at timestamptz not null default now(),
    last_interacted_at timestamptz
);

-- No extra index: user_id is already the primary key, and every query here
-- is "my own row" -- a single-row lookup the primary key already serves.


-- ---------------------------------------------------------------------------
-- Row Level Security -- same shape as 003. The backend talks to Postgres as
-- the logged-in user (see user.caller_client), so auth.uid() is that user and
-- other people's companions do not exist as far as this client is concerned.
-- ---------------------------------------------------------------------------
alter table public.companion_state enable row level security;

drop policy if exists companion_state_select_own on public.companion_state;
create policy companion_state_select_own on public.companion_state
    for select to authenticated
    using (user_id = auth.uid());

drop policy if exists companion_state_insert_own on public.companion_state;
create policy companion_state_insert_own on public.companion_state
    for insert to authenticated
    with check (user_id = auth.uid());

drop policy if exists companion_state_update_own on public.companion_state;
create policy companion_state_update_own on public.companion_state
    for update to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists companion_state_delete_own on public.companion_state;
create policy companion_state_delete_own on public.companion_state
    for delete to authenticated
    using (user_id = auth.uid());
