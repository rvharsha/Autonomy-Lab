-- Versioned, synthetic application inputs. These are not evaluation outcomes.
CREATE TABLE products (
    sku TEXT PRIMARY KEY,
    unit_price_minor INTEGER NOT NULL CHECK (unit_price_minor >= 0),
    stock INTEGER NOT NULL CHECK (stock >= 0),
    currency TEXT NOT NULL CHECK (currency = 'USD')
);

INSERT INTO products (sku, unit_price_minor, stock, currency) VALUES
    ('bolt', 125, 100, 'USD'),
    ('motor', 2499, 3, 'USD'),
    ('washer', 25, 0, 'USD');

-- Declared disposable-lab credentials; neither service requires write access.
CREATE ROLE inventory_reader LOGIN PASSWORD 'inventory-test-only';
CREATE ROLE verifier_reader LOGIN PASSWORD 'verifier-test-only';
GRANT CONNECT ON DATABASE lab TO inventory_reader, verifier_reader;
GRANT USAGE ON SCHEMA public TO inventory_reader, verifier_reader;
GRANT SELECT ON TABLE products TO inventory_reader, verifier_reader;
