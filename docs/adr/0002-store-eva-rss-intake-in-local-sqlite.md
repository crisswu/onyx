# Store EVA RSS Intake in Local SQLite

The first RSS intake implementation will store feed subscriptions and collected articles in EVA's local SQLite-backed store under the configured Onyx data directory, accessed through database interfaces in `backend/onyx/db`. Although scheduled fetching runs through Onyx Celery, the data remains outside the main Onyx Postgres schema because this version is a local EVA personal information pool rather than a product-wide multi-user news index.
