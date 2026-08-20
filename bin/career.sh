#!/bin/bash
# career.sh - deterministic CLI for the career data hub (SQLite + FTS5).
# The hub indexes every fact about the owner's career; raw files in
# career-corpus/ stay the untouched source archive. PRIVATE: the db lives in
# career-corpus/, which is never committed anywhere.
# Usage:
#   scripts/career.sh init                 # create tables (idempotent)
#   scripts/career.sh export               # ALL facts as JSON (agent context)
#   scripts/career.sh search "query"       # FTS5 full-text search
#   scripts/career.sh sql "statement"      # raw SQL (pipeline workers only)
#   scripts/career.sh questions            # open metric questions, one per line
#   scripts/career.sh ask <fact_id> "q"    # queue a follow-up question
#   scripts/career.sh answer <id> "text"   # record an answer, close question
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# data lives OUTSIDE this repo (privacy + clean history for open-sourcing):
# CAREER_DATA_DIR overrides; default = ../career-corpus next to this repo
DATA_DIR="${CAREER_DATA_DIR:-$ROOT/../career-corpus}"
DB="$DATA_DIR/career.db"

init() {
  sqlite3 "$DB" << 'SQL'
CREATE TABLE IF NOT EXISTS facts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT DEFAULT (datetime('now','localtime')),
  updated TEXT DEFAULT (datetime('now','localtime')),
  type TEXT NOT NULL,                -- job | project | achievement | skill | metric | education | cert
  title TEXT NOT NULL,
  detail TEXT,                       -- full context, owner's wording preserved
  action TEXT,                       -- what the owner did
  impact TEXT,                       -- what changed because of it
  metrics TEXT,                      -- JSON [{value, unit, basis: direct|estimated, how_estimated}]
  tags TEXT,                         -- JSON array of strings
  priority TEXT DEFAULT 'backlog',   -- resume | updates | backlog
  resume_section TEXT,               -- summary | experience | projects | skills | education
  in_resume INTEGER DEFAULT 0,       -- 1 once the live resume reflects this fact
  status TEXT DEFAULT 'past',        -- current | past
  source TEXT,                       -- provenance: source file or checkin date
  weight INTEGER DEFAULT 0           -- 0-100 resume-relevance score (set by archivist; drives 1-page selection)
);
CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts USING fts5(
  title, detail, action, impact, tags, content=facts, content_rowid=id);
CREATE TRIGGER IF NOT EXISTS facts_ai AFTER INSERT ON facts BEGIN
  INSERT INTO facts_fts(rowid, title, detail, action, impact, tags)
  VALUES (new.id, new.title, new.detail, new.action, new.impact, new.tags);
END;
CREATE TRIGGER IF NOT EXISTS facts_ad AFTER DELETE ON facts BEGIN
  INSERT INTO facts_fts(facts_fts, rowid, title, detail, action, impact, tags)
  VALUES ('delete', old.id, old.title, old.detail, old.action, old.impact, old.tags);
END;
CREATE TRIGGER IF NOT EXISTS facts_au AFTER UPDATE ON facts BEGIN
  INSERT INTO facts_fts(facts_fts, rowid, title, detail, action, impact, tags)
  VALUES ('delete', old.id, old.title, old.detail, old.action, old.impact, old.tags);
  INSERT INTO facts_fts(rowid, title, detail, action, impact, tags)
  VALUES (new.id, new.title, new.detail, new.action, new.impact, new.tags);
END;
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created TEXT DEFAULT (datetime('now','localtime')),
  fact_id INTEGER,
  question TEXT NOT NULL,
  status TEXT DEFAULT 'open',        -- open | answered | dropped
  answer TEXT
);
SQL
  # migrate existing hubs that predate the weight column (errors if present -> ignore)
  sqlite3 "$DB" "ALTER TABLE facts ADD COLUMN weight INTEGER DEFAULT 0;" 2>/dev/null || true
  chmod 600 "$DB"
  echo "career hub ready: $DB"
}

export_facts() { sqlite3 -json "$DB" "SELECT * FROM facts ORDER BY type, resume_section, updated DESC;"; }
search() { sqlite3 -json "$DB" "SELECT f.* FROM facts f JOIN facts_fts s ON f.id = s.rowid WHERE facts_fts MATCH '$(printf '%s' "$1" | sed "s/'/''/g")' ORDER BY rank LIMIT 25;"; }
run_sql() { sqlite3 -json "$DB" "$1"; }
questions() { sqlite3 -separator '|' "$DB" "SELECT id, question FROM questions WHERE status='open' ORDER BY id;"; }
ask() { sqlite3 "$DB" "INSERT INTO questions (fact_id, question) VALUES (${1:-NULL}, '$(printf '%s' "$2" | sed "s/'/''/g")');"; }
answer() { sqlite3 "$DB" "UPDATE questions SET status='answered', answer='$(printf '%s' "$2" | sed "s/'/''/g")' WHERE id=$1;"; }
weigh() { sqlite3 "$DB" "UPDATE facts SET weight=$2, updated=datetime('now','localtime') WHERE id=$1;"; }

case "${1:-}" in
  init) init ;;
  export) export_facts ;;
  search) search "$2" ;;
  sql) run_sql "$2" ;;
  questions) questions ;;
  ask) ask "$2" "$3" ;;
  answer) answer "$2" "$3" ;;
  weigh) weigh "$2" "$3" ;;
  *) echo "usage: career.sh init|export|search|sql|questions|ask|answer|weigh"; exit 1 ;;
esac
