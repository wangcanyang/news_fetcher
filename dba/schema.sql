-- News table for Global Finance Terminal
-- Stores up to 7 days of news articles

CREATE TABLE IF NOT EXISTS news (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  sourceName TEXT NOT NULL,
  title_en TEXT NOT NULL,
  title_zh TEXT NOT NULL,
  link TEXT NOT NULL,
  timestamp INTEGER NOT NULL,
  category TEXT NOT NULL,
  description TEXT DEFAULT '',
  tags TEXT DEFAULT '[]',
  created_at INTEGER DEFAULT (unixepoch())
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_timestamp ON news(timestamp);
CREATE INDEX IF NOT EXISTS idx_source ON news(source);
CREATE INDEX IF NOT EXISTS idx_category ON news(category);
