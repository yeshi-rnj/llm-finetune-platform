CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE projects (
  id TEXT PRIMARY KEY,
  owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
CREATE INDEX idx_projects_owner ON projects(owner_id);
CREATE TABLE datasets (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  row_count INTEGER NOT NULL,
  labels_json TEXT NOT NULL,
  file_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_datasets_project ON datasets(project_id);
CREATE TABLE jobs (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  dataset_id TEXT REFERENCES datasets(id) ON DELETE SET NULL,
  method TEXT NOT NULL,
  model_name TEXT NOT NULL,
  params_json TEXT NOT NULL,
  status TEXT NOT NULL,
  error TEXT,
  metrics_json TEXT,
  model_id TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);
CREATE INDEX idx_jobs_project ON jobs(project_id);
CREATE TABLE models (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  job_id TEXT,
  name TEXT NOT NULL,
  method TEXT NOT NULL,
  labels_json TEXT NOT NULL,
  artifact_path TEXT NOT NULL,
  test_path TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_models_project ON models(project_id);
CREATE TABLE evaluations (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL REFERENCES models(id) ON DELETE CASCADE,
  metrics_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX idx_evaluations_model ON evaluations(model_id)
