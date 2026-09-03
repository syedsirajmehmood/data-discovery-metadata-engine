-- Seed data for local dev / integration tests: a small "analytics" schema
-- with a couple of tables, a view, comments, and a foreign key, so the
-- Postgres connector has something realistic to discover.

CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE analytics.users (
    id BIGSERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
COMMENT ON TABLE analytics.users IS 'Registered users';
COMMENT ON COLUMN analytics.users.email IS 'Unique login email';

CREATE TABLE analytics.orders (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES analytics.users(id),
    amount NUMERIC(10, 2) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT now()
);
COMMENT ON TABLE analytics.orders IS 'Customer orders';

CREATE VIEW analytics.recent_orders AS
    SELECT * FROM analytics.orders WHERE created_at > now() - interval '30 days';

INSERT INTO analytics.users (email) VALUES ('a@example.com'), ('b@example.com');
INSERT INTO analytics.orders (user_id, amount, status) VALUES (1, 19.99, 'paid'), (2, 5.00, 'pending');

ANALYZE analytics.users;
ANALYZE analytics.orders;
