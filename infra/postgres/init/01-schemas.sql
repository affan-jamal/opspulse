-- Runs once, when the postgres volume is first created.
-- provider: what the simulated third-party API serves (loaded from the ETL core).
-- ops:      what OpsPulse ingests over HTTP and analyses.
CREATE SCHEMA IF NOT EXISTS provider;
CREATE SCHEMA IF NOT EXISTS ops;
