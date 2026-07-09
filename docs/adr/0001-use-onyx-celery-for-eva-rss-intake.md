# Use Onyx Celery for EVA RSS Intake

EVA's first RSS intake service is local and user-specific, but its scheduled fetching will run through the existing Onyx Celery infrastructure rather than a separate EVA daemon. This keeps task scheduling, expiration, logging, and deployment behavior aligned with the rest of Onyx while the RSS storage and EVA-facing tools remain scoped to the local personal information pool.
