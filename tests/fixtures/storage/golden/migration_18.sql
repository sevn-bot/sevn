PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
INSERT INTO schema_migrations VALUES(1,'<applied_at>');
INSERT INTO schema_migrations VALUES(2,'<applied_at>');
INSERT INTO schema_migrations VALUES(3,'<applied_at>');
INSERT INTO schema_migrations VALUES(4,'<applied_at>');
INSERT INTO schema_migrations VALUES(5,'<applied_at>');
INSERT INTO schema_migrations VALUES(6,'<applied_at>');
INSERT INTO schema_migrations VALUES(7,'<applied_at>');
INSERT INTO schema_migrations VALUES(8,'<applied_at>');
INSERT INTO schema_migrations VALUES(9,'<applied_at>');
INSERT INTO schema_migrations VALUES(10,'<applied_at>');
INSERT INTO schema_migrations VALUES(11,'<applied_at>');
INSERT INTO schema_migrations VALUES(12,'<applied_at>');
INSERT INTO schema_migrations VALUES(13,'<applied_at>');
INSERT INTO schema_migrations VALUES(14,'<applied_at>');
INSERT INTO schema_migrations VALUES(15,'<applied_at>');
INSERT INTO schema_migrations VALUES(16,'<applied_at>');
INSERT INTO schema_migrations VALUES(17,'<applied_at>');
INSERT INTO schema_migrations VALUES(18,'<applied_at>');
CREATE TABLE lcm_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_key TEXT UNIQUE NOT NULL,
    channel TEXT NOT NULL,
    group_name TEXT,
    topic TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE lcm_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES lcm_conversations(id),
    seq INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER DEFAULT 0,
    message_parts TEXT,
    kind TEXT NOT NULL DEFAULT 'message'
        CHECK (kind IN ('message', 'command', 'blocked')),
    visible_to_llm INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'sent'
        CHECK (status IN ('pending', 'sent', 'failed')),
    created_at TEXT NOT NULL,
    CHECK (kind NOT IN ('command', 'blocked') OR visible_to_llm = 0)
);
CREATE TABLE lcm_summaries (
    summary_id TEXT PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES lcm_conversations(id),
    content TEXT NOT NULL,
    depth INTEGER NOT NULL DEFAULT 0,
    token_count INTEGER DEFAULT 0,
    summary_kind TEXT NOT NULL DEFAULT 'compaction'
        CHECK (summary_kind IN ('compaction', 'session_end')),
    subsumed_by TEXT REFERENCES lcm_summaries(summary_id),
    merged_from TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE lcm_summary_messages (
    summary_id TEXT NOT NULL REFERENCES lcm_summaries(summary_id),
    message_id INTEGER NOT NULL REFERENCES lcm_messages(id),
    PRIMARY KEY (summary_id, message_id)
);
CREATE TABLE lcm_summary_parents (
    child_id TEXT NOT NULL REFERENCES lcm_summaries(summary_id),
    parent_id TEXT NOT NULL REFERENCES lcm_summaries(summary_id),
    PRIMARY KEY (child_id, parent_id)
);
CREATE TABLE lcm_context_items (
    conversation_id INTEGER NOT NULL REFERENCES lcm_conversations(id),
    ordinal INTEGER NOT NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('message', 'summary')),
    message_id INTEGER REFERENCES lcm_messages(id),
    summary_id TEXT REFERENCES lcm_summaries(summary_id),
    PRIMARY KEY (conversation_id, ordinal)
);
CREATE TABLE lcm_large_files (
    file_id TEXT PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES lcm_conversations(id),
    file_name TEXT,
    mime_type TEXT,
    content TEXT,
    exploration_summary TEXT,
    byte_size INTEGER,
    storage_path TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE gateway_sessions (
    session_id TEXT PRIMARY KEY NOT NULL,
    scope_key TEXT NOT NULL UNIQUE,
    channel TEXT NOT NULL,
    user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    unanswered_tail_message_id INTEGER,
    last_final_assistant_message_id INTEGER,
    metadata_json TEXT
);
CREATE TABLE gateway_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES gateway_sessions(session_id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    kind TEXT NOT NULL CHECK (kind IN ('message', 'command', 'blocked', 'steer')),
    content TEXT NOT NULL,
    visible_to_llm INTEGER NOT NULL DEFAULT 1 CHECK (visible_to_llm IN (0, 1)),
    platform_message_id TEXT,
    platform_chat_id TEXT,
    extras_json TEXT,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('pending', 'sent', 'failed')),
    created_at TEXT NOT NULL
);
CREATE TABLE dispatcher_callbacks (
    callback_query_id TEXT PRIMARY KEY NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE gateway_media_tokens (
    token TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL,
    rel_path TEXT NOT NULL,
    expires_at_ns INTEGER NOT NULL
);
CREATE TABLE telegram_topic_names (
    chat_id INTEGER NOT NULL,
    topic_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (chat_id, topic_id)
);
CREATE TABLE dispatcher_state (
    token TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL DEFAULT 'callback_overflow',
    user_id INTEGER NOT NULL,
    chat_id INTEGER NOT NULL,
    topic_id INTEGER,
    payload_json TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE openui_tokens (
    record_id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    message_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'webchat',
    sanitised_html TEXT NOT NULL,
    expires_at_ns INTEGER NOT NULL,
    submit_consumed INTEGER NOT NULL DEFAULT 0,
    fallback_text TEXT NOT NULL DEFAULT '',
    extra_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS "active_run_snapshots" (
    run_id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('triager','A','B','C','D')),
    plan_state TEXT,
    in_flight_tools TEXT,
    excerpt TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL,
    awaiting_callback_token TEXT
);
CREATE TABLE triage_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    triager_span_id TEXT NOT NULL,
    triage_result_json TEXT NOT NULL,
    registry_version INTEGER NOT NULL,
    personality_version INTEGER NOT NULL,
    triager_model_id TEXT NOT NULL,
    c_d_backend TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (workspace_id, turn_id)
);
CREATE TABLE turn_replay_dedupe (
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    replay_job_id TEXT NOT NULL,
    created_at_ns INTEGER NOT NULL,
    PRIMARY KEY (session_id, turn_id)
);
CREATE TABLE pending_plans (
    plan_id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL,
    turn_id TEXT NOT NULL,
    c_d_backend TEXT NOT NULL CHECK (c_d_backend IN ('dspy', 'lambda_rlm')),
    plan_json TEXT NOT NULL CHECK (json_valid(plan_json)),
    status TEXT NOT NULL DEFAULT 'awaiting'
        CHECK (status IN ('awaiting', 'approved', 'rejected', 'superseded', 'expired')),
    created_at_ns INTEGER NOT NULL,
    expires_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL
);
CREATE TABLE trigger_webhook_dedupe (
    source TEXT NOT NULL,
    delivery_id TEXT NOT NULL,
    first_seen_ns INTEGER NOT NULL,
    expire_at_ns INTEGER NOT NULL,
    correlation_id TEXT NOT NULL,
    PRIMARY KEY (source, delivery_id)
);
CREATE TABLE trigger_cron_jobs (
    job_id TEXT PRIMARY KEY NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    cron_expr TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'UTC',
    next_fire_at_ns INTEGER NOT NULL,
    jitter_s INTEGER NOT NULL DEFAULT 0,
    routing_mode TEXT NOT NULL DEFAULT 'fixed'
        CHECK (routing_mode IN ('fixed', 'auto_route')),
    delivery_mode TEXT NOT NULL DEFAULT 'agent_pass'
        CHECK (delivery_mode IN ('agent_pass', 'notify_only')),
    permission_template_ref TEXT NOT NULL DEFAULT 'default',
    allow_tier_cd INTEGER NOT NULL DEFAULT 0,
    overlap_policy TEXT NOT NULL DEFAULT 'skip'
        CHECK (overlap_policy IN ('skip', 'queue', 'allow')),
    result_channel_json TEXT NOT NULL DEFAULT '{}',
    payload_template TEXT,
    last_correlation_id TEXT,
    last_status TEXT
);
CREATE TABLE memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT,
    created_at TEXT NOT NULL,
    metadata TEXT
);
CREATE TABLE self_improve_jobs (
    job_id TEXT PRIMARY KEY NOT NULL,
    workspace_id TEXT NOT NULL,
    state TEXT NOT NULL,
    preset TEXT NOT NULL,
    experiment_snapshot_json TEXT NOT NULL DEFAULT '{}',
    sampler_seed INTEGER NOT NULL,
    shortlist_path TEXT,
    patch_artifact_path TEXT,
    eval_report_path TEXT,
    pr_url TEXT,
    correlation_id TEXT,
    client_token TEXT,
    blocked_reason TEXT,
    started_at TEXT,
    finished_at TEXT,
    UNIQUE(workspace_id, client_token)
);
CREATE TABLE feedback_events (
    feedback_id TEXT PRIMARY KEY NOT NULL,
    kind TEXT NOT NULL,
    target_turn_id TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE skills (
    workspace_id TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    failure_count INTEGER NOT NULL DEFAULT 0,
    chronic_skill_failure INTEGER NOT NULL DEFAULT 0
        CHECK (chronic_skill_failure IN (0, 1)),
    failure_timestamps_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(failure_timestamps_json)),
    updated_at_ns INTEGER NOT NULL,
    PRIMARY KEY (workspace_id, skill_name)
);
CREATE TABLE memory_search_events (
    event_id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    source TEXT NOT NULL,
    result_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE memory_recall_signals (
    signal_id TEXT PRIMARY KEY NOT NULL,
    memory_key TEXT NOT NULL,
    session_id TEXT NOT NULL,
    recall_weight REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL
);
CREATE TABLE structured_feedback (
    feedback_id TEXT PRIMARY KEY NOT NULL,
    target_turn_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    platform_message_id TEXT,
    body_text TEXT NOT NULL DEFAULT '',
    dropdowns_json TEXT NOT NULL DEFAULT '{}',
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    submission_key TEXT
);
CREATE TABLE trajectory_fact (
    turn_id TEXT PRIMARY KEY NOT NULL,
    session_id TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'unknown',
    intent TEXT,
    tier TEXT,
    budget_regime TEXT,
    model_id TEXT,
    signals_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(signals_json)),
    trace_span_id TEXT,
    created_at TEXT NOT NULL
);
DELETE FROM sqlite_sequence;
CREATE INDEX idx_lcm_messages_conv_seq ON lcm_messages (conversation_id, seq);
CREATE INDEX idx_lcm_messages_kind ON lcm_messages (conversation_id, kind, seq);
CREATE INDEX idx_lcm_messages_pending ON lcm_messages (status) WHERE status = 'pending';
CREATE INDEX idx_lcm_summaries_conv ON lcm_summaries (conversation_id, created_at);
CREATE INDEX ix_gateway_messages_session_id ON gateway_messages(session_id, id);
CREATE INDEX ix_gateway_messages_session_kind ON gateway_messages(session_id, kind);
CREATE INDEX ix_gateway_media_tokens_expiry ON gateway_media_tokens(expires_at_ns);
CREATE INDEX ix_dispatcher_callbacks_created_at ON dispatcher_callbacks(created_at);
CREATE INDEX ix_telegram_topic_names_chat ON telegram_topic_names(chat_id);
CREATE INDEX ix_dispatcher_state_expires_at ON dispatcher_state(expires_at);
CREATE INDEX ix_dispatcher_state_chat_kind ON dispatcher_state(chat_id, kind);
CREATE INDEX ix_openui_tokens_expiry ON openui_tokens(expires_at_ns);
CREATE INDEX ix_openui_tokens_session ON openui_tokens(session_id);
CREATE INDEX ix_active_run_snapshots_session ON active_run_snapshots(session_id);
CREATE INDEX ix_active_run_snapshots_status ON active_run_snapshots(status);
CREATE INDEX ix_triage_decisions_workspace_session ON triage_decisions (workspace_id, session_id);
CREATE INDEX ix_turn_replay_dedupe_created ON turn_replay_dedupe(created_at_ns);
CREATE INDEX ix_pending_plans_expiry ON pending_plans(status, expires_at_ns);
CREATE UNIQUE INDEX ux_pending_plans_active_turn
    ON pending_plans(session_id, turn_id)
    WHERE status = 'awaiting';
CREATE INDEX ix_trigger_webhook_dedupe_expiry ON trigger_webhook_dedupe(expire_at_ns);
CREATE INDEX ix_trigger_cron_jobs_due ON trigger_cron_jobs(enabled, next_fire_at_ns);
CREATE INDEX ix_memory_session_created ON memory(session_id, created_at);
CREATE INDEX ix_self_improve_jobs_workspace ON self_improve_jobs(workspace_id);
CREATE INDEX ix_self_improve_jobs_state ON self_improve_jobs(state);
CREATE INDEX ix_feedback_events_turn ON feedback_events(target_turn_id);
CREATE INDEX ix_feedback_events_kind ON feedback_events(kind);
CREATE INDEX ix_skills_chronic_failure
    ON skills(workspace_id, skill_name)
    WHERE chronic_skill_failure = 1;
CREATE INDEX ix_memory_search_events_session ON memory_search_events(session_id, created_at);
CREATE INDEX ix_memory_recall_signals_key ON memory_recall_signals(memory_key, created_at);
CREATE INDEX ix_structured_feedback_turn ON structured_feedback(target_turn_id);
CREATE INDEX ix_structured_feedback_user_created
    ON structured_feedback(user_id, created_at DESC);
CREATE UNIQUE INDEX ix_structured_feedback_submission_key
    ON structured_feedback(submission_key) WHERE submission_key IS NOT NULL;
CREATE INDEX ix_trajectory_fact_session ON trajectory_fact(session_id);
CREATE INDEX ix_trajectory_fact_created ON trajectory_fact(created_at DESC);
COMMIT;
