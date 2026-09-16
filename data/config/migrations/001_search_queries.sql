-- Search templates only. Execution history belongs to company/query runs.
BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS catalog_migrations (
    migration_key TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE TABLE IF NOT EXISTS search_queries (
    query_key TEXT PRIMARY KEY CHECK(length(trim(query_key)) > 0),
    keyword TEXT NOT NULL CHECK(length(trim(keyword)) > 0),
    location TEXT NOT NULL DEFAULT 'United States' CHECK(length(trim(location)) > 0),
    country TEXT NOT NULL DEFAULT 'us' CHECK(length(country)=2 AND country=lower(country)),
    tier INTEGER NOT NULL DEFAULT 1 CHECK(tier IN (1, 2)),
    sort_order INTEGER NOT NULL DEFAULT 0 CHECK(sort_order >= 0),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(keyword COLLATE NOCASE, location COLLATE NOCASE, country)
);
CREATE TRIGGER IF NOT EXISTS search_queries_updated
AFTER UPDATE OF keyword, location, country, tier, sort_order, enabled, notes ON search_queries
BEGIN
    UPDATE search_queries SET updated_at=strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE query_key=NEW.query_key;
END;
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'electrical_engineer', 'electrical engineer', 1, 0 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'hardware_engineer', 'hardware engineer', 1, 1 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'asic_design_engineer', 'ASIC design engineer', 1, 2 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'rtl_design_engineer', 'RTL design engineer', 1, 3 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'design_verification_engineer', 'design verification engineer', 1, 4 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'physical_design_engineer', 'physical design engineer', 1, 5 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'analog_design_engineer', 'analog design engineer', 1, 6 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'mixed_signal_design_engineer', 'mixed-signal design engineer', 1, 7 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'fpga_engineer', 'FPGA engineer', 1, 8 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'soc_design_engineer', 'SoC design engineer', 1, 9 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'silicon_validation_engineer', 'silicon validation engineer', 2, 10 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'signal_integrity_engineer', 'signal integrity engineer', 2, 11 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'power_electronics_engineer', 'power electronics engineer', 2, 12 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'rf_engineer', 'RF engineer', 2, 13 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'pcb_design_engineer', 'PCB design engineer', 2, 14 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'embedded_hardware_engineer', 'embedded hardware engineer', 2, 15 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'cpu_design_engineer', 'CPU design engineer', 2, 16 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT INTO search_queries (query_key, keyword, tier, sort_order) SELECT 'memory_design_engineer', 'memory design engineer', 2, 17 WHERE NOT EXISTS (SELECT 1 FROM catalog_migrations WHERE migration_key='001_search_queries');
INSERT OR IGNORE INTO catalog_migrations (migration_key) VALUES ('001_search_queries');
COMMIT;
