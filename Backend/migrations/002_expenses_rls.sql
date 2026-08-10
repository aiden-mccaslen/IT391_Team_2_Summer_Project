-- ---------------------------------------------------------------------------
-- Row Level Security for the money tables: expenses, funds and fee.
--
-- 001 gave the chat tables policies; these three never got them. RLS was left
-- enabled with no policy attached, which denies everything -- so every insert
-- from the expenses page came back as
--     42501: new row violates row-level security policy
-- It only ever appeared to work while the backend held a service/secret key,
-- because that key bypasses RLS entirely (and with it, every ownership check).
--
-- Same shape as 001: the backend talks to Postgres as the logged-in user (see
-- user.caller_client), so auth.uid() is that user and other people's rows are
-- simply invisible.
--
-- Safe to re-run.
-- ---------------------------------------------------------------------------

alter table public.expenses enable row level security;
alter table public.funds    enable row level security;
alter table public.fee      enable row level security;


-- expenses: you own the row if user_id is you.
drop policy if exists expenses_select_own on public.expenses;
create policy expenses_select_own on public.expenses
    for select to authenticated
    using (user_id = auth.uid());

drop policy if exists expenses_insert_own on public.expenses;
create policy expenses_insert_own on public.expenses
    for insert to authenticated
    with check (user_id = auth.uid());

drop policy if exists expenses_update_own on public.expenses;
create policy expenses_update_own on public.expenses
    for update to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists expenses_delete_own on public.expenses;
create policy expenses_delete_own on public.expenses
    for delete to authenticated
    using (user_id = auth.uid());


-- funds: same ownership rule.
drop policy if exists funds_select_own on public.funds;
create policy funds_select_own on public.funds
    for select to authenticated
    using (user_id = auth.uid());

drop policy if exists funds_insert_own on public.funds;
create policy funds_insert_own on public.funds
    for insert to authenticated
    with check (user_id = auth.uid());

drop policy if exists funds_update_own on public.funds;
create policy funds_update_own on public.funds
    for update to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists funds_delete_own on public.funds;
create policy funds_delete_own on public.funds
    for delete to authenticated
    using (user_id = auth.uid());


-- fee: same ownership rule.
drop policy if exists fee_select_own on public.fee;
create policy fee_select_own on public.fee
    for select to authenticated
    using (user_id = auth.uid());

drop policy if exists fee_insert_own on public.fee;
create policy fee_insert_own on public.fee
    for insert to authenticated
    with check (user_id = auth.uid());

drop policy if exists fee_update_own on public.fee;
create policy fee_update_own on public.fee
    for update to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists fee_delete_own on public.fee;
create policy fee_delete_own on public.fee
    for delete to authenticated
    using (user_id = auth.uid());


-- ---------------------------------------------------------------------------
-- The unique constraint report_fund() upserts against.
--
-- expenses.report_fund passes on_conflict="user_id", which Postgres rejects
-- with 42P10 unless a matching unique constraint exists. The comment at the top
-- of expenses.py says user_id was made unique -- that change is not in this
-- database, so this puts it in.
--
-- NOTE: one funds row per user. If you later want separate checking/savings
-- balances, make this unique (user_id, account) instead and change the
-- on_conflict argument to match.
-- ---------------------------------------------------------------------------
create unique index if not exists funds_user_id_key on public.funds (user_id);
