-- Hermes Digest Dashboard — Supabase schema
-- Run this once in your Supabase project's SQL editor.

create table if not exists digest_items (
  id text primary key,              -- stable idempotency key: hash of source link/job id, NOT a random uuid
  digest_date date not null,
  category text not null check (category in ('deadline','internship','scholarship','course','other')),
  title text not null,
  summary text,
  sender text,
  link text,
  deadline_date date,
  status text not null default 'new' check (status in ('new','interested','done','not_interested')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_digest_items_status on digest_items(status);
create index if not exists idx_digest_items_sender on digest_items(sender);
create index if not exists idx_digest_items_category on digest_items(category);

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_digest_items_updated_at on digest_items;
create trigger trg_digest_items_updated_at
before update on digest_items
for each row execute function set_updated_at();

alter table digest_items enable row level security;

-- Anyone can read the board (you said public content is fine).
drop policy if exists "public read" on digest_items;
create policy "public read" on digest_items
  for select using (true);

-- Only a signed-in user (you, via magic link) can change a card's status.
drop policy if exists "authenticated update status" on digest_items;
create policy "authenticated update status" on digest_items
  for update
  using (auth.role() = 'authenticated')
  with check (auth.role() = 'authenticated');

-- Inserts/deletes only happen from Hermes using the service_role key (bypasses RLS),
-- never from the browser. Explicitly lock the browser roles out.
revoke insert, delete on digest_items from anon, authenticated;

-- Even signed-in browser sessions may only ever touch status/updated_at —
-- title/link/summary/etc. stay tamper-proof from the client.
revoke update on digest_items from authenticated;
grant update (status, updated_at) on digest_items to authenticated;
grant select on digest_items to anon, authenticated;

-- Aggregated feedback Hermes reads before generating the next digest, to
-- learn which senders/categories you actually care about.
create or replace view sender_feedback as
select sender,
       count(*) filter (where status = 'interested') as interested_count,
       count(*) filter (where status = 'done') as done_count,
       count(*) filter (where status = 'not_interested') as not_interested_count,
       count(*) as total
from digest_items
where sender is not null
group by sender;

create or replace view category_feedback as
select category,
       count(*) filter (where status = 'interested') as interested_count,
       count(*) filter (where status = 'done') as done_count,
       count(*) filter (where status = 'not_interested') as not_interested_count,
       count(*) as total
from digest_items
group by category;
