-- 004_documents_storage.sql
-- Storage for the generated Kakeibo documents: the monthly review and the profile
-- that comes out of the onboarding interview.
--
-- HOW TO RUN: Supabase dashboard -> SQL Editor -> New query, paste this whole
-- file in, hit Run. Safe to re-run.
--
-- The Python side of this lives in Backend/reports.py.
--
-- Why files and not a table: these two documents are read whole and never queried
-- by their contents -- nothing ever asks "which users mentioned rent?". Keeping
-- them as Markdown in a bucket means the thing we store is the thing we show, and
-- "have we already generated this month?" is a file lookup rather than a row.
--
-- Layout inside the bucket, one folder per user:
--     {user_id}/profile.md
--     {user_id}/monthly/2026-08.md
--
-- That leading folder is load-bearing: every policy below matches on it, which is
-- what stops one user reading another's documents.


-- ---------------------------------------------------------------------------
-- The bucket. Private -- these are read through the API with the user's token,
-- never linked to directly.
-- ---------------------------------------------------------------------------
insert into storage.buckets (id, name, public)
values ('kakeibo-docs', 'kakeibo-docs', false)
on conflict (id) do nothing;


-- ---------------------------------------------------------------------------
-- Row Level Security on the objects themselves -- same ownership rule as the
-- tables in 001/002/003, expressed against the first path segment.
--
-- storage.foldername(name) splits 'abc-123/monthly/2026-08.md' into
-- {abc-123, monthly}, so [1] is the owning user's id.
-- ---------------------------------------------------------------------------
drop policy if exists kakeibo_docs_select_own on storage.objects;
create policy kakeibo_docs_select_own on storage.objects
    for select to authenticated
    using (
        bucket_id = 'kakeibo-docs'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

drop policy if exists kakeibo_docs_insert_own on storage.objects;
create policy kakeibo_docs_insert_own on storage.objects
    for insert to authenticated
    with check (
        bucket_id = 'kakeibo-docs'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

-- Update needs both: `using` picks which existing rows may be touched, `with
-- check` validates the row you are replacing it with. Without the second one a
-- user could overwrite their own file with a path belonging to someone else.
drop policy if exists kakeibo_docs_update_own on storage.objects;
create policy kakeibo_docs_update_own on storage.objects
    for update to authenticated
    using (
        bucket_id = 'kakeibo-docs'
        and (storage.foldername(name))[1] = auth.uid()::text
    )
    with check (
        bucket_id = 'kakeibo-docs'
        and (storage.foldername(name))[1] = auth.uid()::text
    );

drop policy if exists kakeibo_docs_delete_own on storage.objects;
create policy kakeibo_docs_delete_own on storage.objects
    for delete to authenticated
    using (
        bucket_id = 'kakeibo-docs'
        and (storage.foldername(name))[1] = auth.uid()::text
    );
