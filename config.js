// Copy this file to config.js and fill in your project's values.
// SUPABASE_ANON_KEY is the *public* anon key — it is meant to be shipped in
// client-side code. Row Level Security (see schema.sql) is what actually
// protects the data, not secrecy of this key.
//
// NEVER put your service_role key here or anywhere in this folder — that
// key stays local, used only by Hermes to write new digest items.

export const SUPABASE_URL = "https://YOUR-PROJECT-REF.supabase.co";
export const SUPABASE_ANON_KEY = "YOUR-ANON-PUBLIC-KEY";
