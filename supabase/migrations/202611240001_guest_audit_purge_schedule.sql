-- Security V2: schedule the hourly purge of expired Guest audit events.
-- Applied to JARVIS-AI-PRO on 2026-11-24 (pg_cron was not enabled when 202611050001 ran).
create extension if not exists pg_cron;
select cron.schedule('jarvis-purge-guest-audit', '17 * * * *', 'select public.jarvis_purge_expired_guest_audit()');
