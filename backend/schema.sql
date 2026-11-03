DROP TABLE IF EXISTS events;

CREATE TABLE IF NOT EXISTS appliances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    wattage INTEGER NOT NULL CHECK (wattage > 0),
    priority INTEGER NOT NULL CHECK (priority >= 1),
    state TEXT NOT NULL DEFAULT 'off' CHECK (state IN ('running', 'off', 'shed')),
    shed_at TEXT
);
