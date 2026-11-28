CREATE TABLE hub_events (
    device_id text NOT NULL,
    boot_id uuid NOT NULL,
    sequence bigint NOT NULL CHECK (sequence >= 0),
    received_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    event jsonb NOT NULL,
    PRIMARY KEY (device_id, boot_id, sequence)
);

CREATE INDEX hub_events_latest
    ON hub_events (device_id, received_at DESC, boot_id DESC, sequence DESC);

\getenv ingest_password HUB_INGEST_PASSWORD
CREATE ROLE hub_ingest LOGIN PASSWORD :'ingest_password';
GRANT SELECT, INSERT ON hub_events TO hub_ingest;
