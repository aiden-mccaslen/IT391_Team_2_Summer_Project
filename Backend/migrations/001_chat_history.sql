-- 001_chat_history.sql
-- Persistent, per-user chat history for the Kakeibo coach.
--
-- HOW TO RUN: open the Supabase dashboard -> SQL Editor -> New query, paste this
-- whole file in, and hit Run. It is written to be safe to run more than once, so
-- re-running it after a tweak will not blow away existing data.
--
-- The Python side of this lives in Backend/chat_history.py.


-- One row per chat thread ("New chat" in the sidebar).
create table if not exists public.conversations (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users (id) on delete cascade,
    title text,                 -- first ~60 chars of the user's opening message
    summary text,               -- rolling summary of the OLD turns (see chat_history.py)
    summarized_through bigint,  -- id of the last message already folded into `summary`
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- For databases that were created before `summarized_through` was added.
alter table public.conversations add column if not exists summarized_through bigint;

-- Every message of every chat. Ordered by created_at within a conversation.
create table if not exists public.messages (
    id bigint generated always as identity primary key,
    conversation_id uuid not null references public.conversations (id) on delete cascade,
    role text not null check (role in ('user', 'assistant')),
    content text not null,
    created_at timestamptz not null default now()
);

-- Basically every read is "give me this conversation's messages, in order", so
-- index exactly that.
create index if not exists messages_conversation_created_idx
    on public.messages (conversation_id, created_at);

-- ...and the sidebar is "my chats, newest first".
create index if not exists conversations_user_updated_idx
    on public.conversations (user_id, updated_at desc);


-- ---------------------------------------------------------------------------
-- Row Level Security.
--
-- This is the real ownership check. The backend talks to Postgres with the
-- logged-in user's access token (see user.client_for_token), so auth.uid() is
-- that user, and these policies make other people's rows simply invisible --
-- a bug in the Flask layer still cannot leak one user's chats to another.
-- ---------------------------------------------------------------------------
alter table public.conversations enable row level security;
alter table public.messages enable row level security;

-- conversations: you own the row if user_id is you.
drop policy if exists conversations_select_own on public.conversations;
create policy conversations_select_own on public.conversations
    for select to authenticated
    using (user_id = auth.uid());

drop policy if exists conversations_insert_own on public.conversations;
create policy conversations_insert_own on public.conversations
    for insert to authenticated
    with check (user_id = auth.uid());

drop policy if exists conversations_update_own on public.conversations;
create policy conversations_update_own on public.conversations
    for update to authenticated
    using (user_id = auth.uid())
    with check (user_id = auth.uid());

drop policy if exists conversations_delete_own on public.conversations;
create policy conversations_delete_own on public.conversations
    for delete to authenticated
    using (user_id = auth.uid());

-- messages: you own the message if you own its parent conversation.
drop policy if exists messages_select_own on public.messages;
create policy messages_select_own on public.messages
    for select to authenticated
    using (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
              and c.user_id = auth.uid()
        )
    );

drop policy if exists messages_insert_own on public.messages;
create policy messages_insert_own on public.messages
    for insert to authenticated
    with check (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
              and c.user_id = auth.uid()
        )
    );

drop policy if exists messages_update_own on public.messages;
create policy messages_update_own on public.messages
    for update to authenticated
    using (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
              and c.user_id = auth.uid()
        )
    )
    with check (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
              and c.user_id = auth.uid()
        )
    );

drop policy if exists messages_delete_own on public.messages;
create policy messages_delete_own on public.messages
    for delete to authenticated
    using (
        exists (
            select 1 from public.conversations c
            where c.id = messages.conversation_id
              and c.user_id = auth.uid()
        )
    );
