-- Durable per-site daily facts used to build comparable monthly/yearly graphs.
-- Unlike raw monitoring snapshots, these rows are intentionally retained.

create table if not exists public.monitoring_site_daily (
  platform text not null,
  station_id text not null,
  station_name text not null,
  bucket_date date not null,
  energy_kwh double precision,
  revenue_amount double precision,
  currency text,
  source_scraped_at timestamptz not null,
  updated_at timestamptz not null default now(),
  primary key (platform, station_id, bucket_date)
);

create index if not exists monitoring_site_daily_station_date_idx
  on public.monitoring_site_daily (platform, station_id, bucket_date desc);

alter table public.monitoring_site_daily enable row level security;
revoke all on table public.monitoring_site_daily from anon, authenticated;
grant all on table public.monitoring_site_daily to service_role;
