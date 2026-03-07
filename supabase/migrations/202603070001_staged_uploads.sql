create extension if not exists pgcrypto;

-- 1) Storage bucket for staging uploads
insert into storage.buckets (id, name, public)
values ('user-uploads-staging', 'user-uploads-staging', false)
on conflict (id) do nothing;

-- 2) Track upload sessions
create table if not exists public.upload_sessions (
    id uuid primary key,
    filename text not null,
    storage_bucket text not null,
    storage_path text not null,
    content_type text,
    size_bytes bigint not null default 0,
    status text not null check (
        status in (
            'processing',
            'staged',
            'failed',
            'promoted',
            'rejected',
            'rolled_back'
        )
    ),
    error_message text,
    review_notes text,
    promoted_document_id uuid,
    created_at timestamptz not null default now(),
    processed_at timestamptz,
    promoted_at timestamptz,
    rolled_back_at timestamptz
);

-- 3) Add traceability to live documents
alter table public.documents
add column if not exists promoted_from_upload_session_id uuid;

-- 4) Staged document metadata
create table if not exists public.staged_documents (
    id uuid primary key default gen_random_uuid(),
    upload_session_id uuid not null references public.upload_sessions(id) on delete cascade,
    title text not null,
    source text,
    extracted_text text,
    status text not null default 'processing' check (
        status in ('processing', 'staged', 'promoted', 'rejected')
    ),
    created_at timestamptz not null default now()
);

-- 5) Staged chunks
create table if not exists public.staged_chunks (
    id uuid primary key default gen_random_uuid(),
    staged_document_id uuid not null references public.staged_documents(id) on delete cascade,
    section_heading text,
    content text not null,
    summary text,
    chapter_summary text,
    position_in_doc integer not null default 0,
    created_at timestamptz not null default now()
);

-- 6) Helpful indexes
create index if not exists idx_upload_sessions_status
on public.upload_sessions(status);

create index if not exists idx_staged_documents_upload_session_id
on public.staged_documents(upload_session_id);

create index if not exists idx_staged_chunks_staged_document_id
on public.staged_chunks(staged_document_id);

create index if not exists idx_staged_chunks_position
on public.staged_chunks(staged_document_id, position_in_doc);

-- 7) Add FK after documents alteration exists
do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'upload_sessions_promoted_document_id_fkey'
    ) then
        alter table public.upload_sessions
        add constraint upload_sessions_promoted_document_id_fkey
        foreign key (promoted_document_id)
        references public.documents(id)
        on delete set null;
    end if;
end $$;