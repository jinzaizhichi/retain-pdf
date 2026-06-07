use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::Path;

use serde::Deserialize;
use serde_json::Value;

use crate::models::{
    event_progress_unit, job_user_stage, normalize_event_user_stage, JobEventRecord,
};

#[derive(Debug, Deserialize)]
struct PipelineEventJsonlRecord {
    #[serde(default)]
    job_id: Option<String>,
    #[serde(default)]
    ts: Option<String>,
    #[serde(default)]
    level: Option<String>,
    #[serde(default)]
    user_stage: Option<String>,
    #[serde(default)]
    stage: Option<String>,
    #[serde(default)]
    substage: Option<String>,
    #[serde(default)]
    stage_detail: Option<String>,
    #[serde(default)]
    provider: Option<String>,
    #[serde(default)]
    provider_stage: Option<String>,
    #[serde(default)]
    event: Option<String>,
    #[serde(default)]
    event_type: Option<String>,
    #[serde(default)]
    raw_event_type: Option<String>,
    #[serde(default)]
    semantic_event_type: Option<String>,
    #[serde(default)]
    message: Option<String>,
    #[serde(default)]
    progress_current: Option<i64>,
    #[serde(default)]
    progress_total: Option<i64>,
    #[serde(default)]
    progress_unit: Option<String>,
    #[serde(default)]
    retry_count: Option<u32>,
    #[serde(default)]
    elapsed_ms: Option<i64>,
    #[serde(default)]
    payload: Option<Value>,
}

pub(super) fn load_pipeline_events_jsonl(
    job_id: &str,
    path: &Path,
    base_seq: i64,
) -> Vec<JobEventRecord> {
    let Ok(file) = File::open(path) else {
        return Vec::new();
    };
    let reader = BufReader::new(file);
    reader
        .lines()
        .enumerate()
        .filter_map(|(index, line)| {
            let line = line.ok()?;
            let trimmed = line.trim();
            if trimmed.is_empty() {
                return None;
            }
            let parsed = serde_json::from_str::<PipelineEventJsonlRecord>(trimmed).ok()?;
            if parsed
                .job_id
                .as_deref()
                .map(str::trim)
                .filter(|value| !value.is_empty() && *value != job_id)
                .is_some()
            {
                return None;
            }
            let event = normalized_event_name(&parsed);
            let raw_event_type = parsed
                .raw_event_type
                .clone()
                .or_else(|| parsed.event_type.clone())
                .or_else(|| Some(event.clone()));
            let mut payload = parsed.payload.unwrap_or(Value::Object(Default::default()));
            if let Value::Object(map) = &mut payload {
                map.entry("raw_source_kind".to_string())
                    .or_insert_with(|| Value::String("pipeline_jsonl".to_string()));
            }
            Some(JobEventRecord {
                job_id: job_id.to_string(),
                seq: base_seq + index as i64 + 1,
                ts: parsed.ts.clone().unwrap_or_default(),
                created_at: parsed.ts.unwrap_or_default(),
                level: parsed.level.unwrap_or_else(|| "info".to_string()),
                lane: None,
                display_stage: None,
                user_stage: parsed
                    .user_stage
                    .map(normalize_user_stage)
                    .or_else(|| user_stage_for_event(parsed.stage.as_deref())),
                substage: parsed
                    .substage
                    .clone()
                    .or_else(|| parsed.provider_stage.clone()),
                progress_unit: parsed
                    .progress_unit
                    .or_else(|| progress_unit_for_event(parsed.stage.as_deref(), &event)),
                stage: parsed.stage,
                stage_detail: parsed.stage_detail,
                provider: parsed.provider,
                provider_stage: parsed.provider_stage,
                event_type: Some(
                    parsed
                        .semantic_event_type
                        .clone()
                        .or_else(|| parsed.event_type.clone())
                        .unwrap_or_else(|| event.clone()),
                ),
                raw_event_type,
                raw: None,
                progress: None,
                event,
                message: parsed.message.unwrap_or_default(),
                progress_current: parsed.progress_current,
                progress_total: parsed.progress_total,
                retry_count: parsed.retry_count,
                elapsed_ms: parsed.elapsed_ms,
                payload: Some(payload),
            })
        })
        .collect()
}

fn user_stage_for_event(stage: Option<&str>) -> Option<String> {
    job_user_stage(stage).map(str::to_string)
}

fn normalize_user_stage(value: String) -> String {
    normalize_event_user_stage(&value)
        .unwrap_or_else(|| value.trim())
        .to_string()
}

fn progress_unit_for_event(stage: Option<&str>, event: &str) -> Option<String> {
    Some(event_progress_unit(stage, event).to_string())
}

fn normalized_event_name(parsed: &PipelineEventJsonlRecord) -> String {
    parsed
        .event
        .clone()
        .or_else(|| parsed.event_type.clone())
        .unwrap_or_else(|| "diagnostic".to_string())
}
