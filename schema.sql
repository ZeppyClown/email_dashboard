-- Hermes Digest Dashboard — Supabase schema
-- Run this once in your Supabase project's SQL editor.

create table if not exists digest_items (
  id text primary key,              -- stable idempotency key: hash of source link/job id, NOT a random uuid
  digest_date date not null,
  category text not null check (category in ('deadline','internship','hackathon','scholarship','course','other')),
  title text not null,
  summary text,          -- short blurb shown on the card face
  details text,          -- fuller write-up shown in the detail panel (why it matters, context, etc.)
  meta jsonb,            -- ordered key/value facts rendered as a table above `details`.
                         -- Internships carry the full CareerAxis row: Position, Employer,
                         -- Industry, Country, Commences, Remuneration, Vacancies, Published,
                         -- Closes, Added, Occupation, Contract type, CareerAxis ID.
                         -- Free-form on purpose: a course item wants different keys than
                         -- an internship, and a jsonb blob beats a migration per category.
                         -- Adding keys needs no migration — jsonb, and the drawer renders
                         -- whatever keys it finds, in insertion order.
  sender text,
  source text,           -- where the facts were collected: 'careeraxis' for the
                         -- NTU portal, 'ntu-email' for roles that only ever
                         -- appeared in a careers email, and one slug per site
                         -- added later (e.g. 'justpostedjob'). Kept separate
                         -- from `sender` on purpose: sender is who mailed you,
                         -- source is which system the details were scraped from,
                         -- and one JOB-BLAST email yields cards of both kinds.
  link text,
  deadline_date date,
  status text not null default 'new' check (status in ('new','interested','done','not_interested')),
  note text,             -- why you moved it where you did, in your own words.
                         -- `status` alone says a card was rejected; it cannot
                         -- say whether that was "Y3+ only" or "not interested
                         -- in finance", which are opposite lessons for the next
                         -- digest. The only client-writable free-text column,
                         -- so the grant below has to name it explicitly.
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- `create table if not exists` above is a no-op on an existing board, so new
-- columns need their own idempotent ALTER to reach a database created earlier.
alter table digest_items add column if not exists meta jsonb;
alter table digest_items add column if not exists source text;
alter table digest_items add column if not exists note text;

-- The category list is a CHECK, so widening it means replacing the constraint —
-- `create table if not exists` will not do it on a board that already exists.
alter table digest_items drop constraint if exists digest_items_category_check;
alter table digest_items add constraint digest_items_category_check
  check (category in ('deadline','internship','hackathon','scholarship','course','other'));

create index if not exists idx_digest_items_status on digest_items(status);
create index if not exists idx_digest_items_source on digest_items(source);
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

-- Only YOU (matched by email, not just "any signed-in user") can change a
-- card's status. Anyone can request a magic link for their own email and
-- become "authenticated" — checking auth.role() alone would let a stranger
-- who finds the sign-in box edit the board. Checking the email closes that.
drop policy if exists "authenticated update status" on digest_items;
create policy "owner update status" on digest_items
  for update
  using ((auth.jwt() ->> 'email') = 'victorchua865@gmail.com')
  with check ((auth.jwt() ->> 'email') = 'victorchua865@gmail.com');

-- Inserts/deletes only happen from Hermes using the service_role key (bypasses RLS),
-- never from the browser. Explicitly lock the browser roles out.
revoke insert, delete on digest_items from anon, authenticated;

-- Even signed-in browser sessions may only ever touch status/note/updated_at —
-- title/link/summary/etc. stay tamper-proof from the client.
revoke update on digest_items from authenticated;
grant update (status, note, updated_at) on digest_items to authenticated;
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

-- The counts above say a card was rejected; this says why, in Victor's own
-- words. Hermes reads it before writing the next digest — "Y3+ only" and "not
-- interested in finance" are opposite lessons that the counts cannot tell
-- apart. Ordered newest first so a prompt can take the most recent N.
create or replace view feedback_notes as
select id, title, category, source, sender, status, note, updated_at
from digest_items
where note is not null and note <> ''
order by updated_at desc;

create or replace view category_feedback as
select category,
       count(*) filter (where status = 'interested') as interested_count,
       count(*) filter (where status = 'done') as done_count,
       count(*) filter (where status = 'not_interested') as not_interested_count,
       count(*) as total
from digest_items
group by category;
