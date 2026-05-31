use std::path::Path;

use crate::error::AppError;
use crate::models::{job_stage_rank, JobEventRecord, JobProgressView, JobSnapshot};
use crate::storage_paths::resolve_events_jsonl;
use serde_json::{json, Value};

mod canonical_events;
mod pipeline_events;

use canonical_events::canonicalize_job_event;
use pipeline_events::load_pipeline_events_jsonl;

#[derive(Debug, Clone)]
pub struct LiveStageSnapshot {
    pub stage: Option<String>,
    pub stage_detail: Option<String>,
    pub progress_current: Option<i64>,
    pub progress_total: Option<i64>,
    pub progress_unit: Option<String>,
}

pub fn build_progress_view(
    job: &JobSnapshot,
    live_stage: Option<&LiveStageSnapshot>,
) -> JobProgressView {
    let current = live_stage
        .and_then(|snapshot| snapshot.progress_current)
        .or(job.progress_current);
    let total = live_stage
        .and_then(|snapshot| snapshot.progress_total)
        .or(job.progress_total);
    JobProgressView {
        current,
        total,
        percent: match (current, total) {
            (Some(current), Some(total)) if total > 0 => {
                Some((current as f64 / total as f64) * 100.0)
            }
            _ => None,
        },
        unit: live_stage.and_then(|snapshot| snapshot.progress_unit.clone()),
    }
}

pub fn load_live_stage_snapshot(job: &JobSnapshot, data_root: &Path) -> Option<LiveStageSnapshot> {
    let items = load_pipeline_event_records(job, data_root, 0);
    select_live_stage_snapshot(&items)
}

pub fn load_pipeline_event_records(
    job: &JobSnapshot,
    data_root: &Path,
    base_seq: i64,
) -> Vec<JobEventRecord> {
    let Some(path) = resolve_events_jsonl(job, data_root) else {
        return Vec::new();
    };
    load_pipeline_events_jsonl(&job.job_id, &path, base_seq)
        .into_iter()
        .map(|mut item| {
            canonicalize_job_event(&mut item);
            item
        })
        .collect()
}

pub fn list_combined_job_events(
    db: &crate::db::Db,
    data_root: &Path,
    job: &JobSnapshot,
) -> Result<Vec<JobEventRecord>, AppError> {
    let mut items = db.list_job_events(&job.job_id, 10_000, 0)?;
    let base_seq = items.iter().map(|item| item.seq).max().unwrap_or(0);
    let mut file_items = load_pipeline_event_records(job, data_root, base_seq);
    items.append(&mut file_items);
    append_ocr_child_events(db, data_root, job, &mut items)?;
    items.sort_by(|left, right| {
        left.ts
            .cmp(&right.ts)
            .then_with(|| left.seq.cmp(&right.seq))
            .then_with(|| left.event.cmp(&right.event))
    });
    for (index, item) in items.iter_mut().enumerate() {
        item.seq = (index + 1) as i64;
        canonicalize_job_event(item);
    }
    Ok(items)
}

fn append_ocr_child_events(
    db: &crate::db::Db,
    data_root: &Path,
    parent_job: &JobSnapshot,
    items: &mut Vec<JobEventRecord>,
) -> Result<(), AppError> {
    let Some(ocr_job_id) = parent_job
        .artifacts
        .as_ref()
        .and_then(|artifacts| artifacts.ocr_job_id.as_ref())
        .map(String::as_str)
        .filter(|value| !value.trim().is_empty() && *value != parent_job.job_id)
    else {
        return Ok(());
    };
    let Ok(ocr_job) = db.get_job(ocr_job_id) else {
        return Ok(());
    };
    let base_seq = items.iter().map(|item| item.seq).max().unwrap_or(0);
    let mut child_items = db.list_job_events(ocr_job_id, 10_000, 0)?;
    let mut child_file_items =
        load_pipeline_event_records(&ocr_job, data_root, base_seq + child_items.len() as i64);
    child_items.append(&mut child_file_items);
    items.extend(
        child_items
            .into_iter()
            .map(|item| mirror_child_event(parent_job, ocr_job_id, item)),
    );
    Ok(())
}

fn mirror_child_event(
    parent_job: &JobSnapshot,
    source_job_id: &str,
    mut item: JobEventRecord,
) -> JobEventRecord {
    let original_payload = item
        .payload
        .take()
        .unwrap_or(Value::Object(Default::default()));
    item.job_id = parent_job.job_id.clone();
    item.user_stage = item.user_stage.or_else(|| Some("ocr".to_string()));
    item.payload = Some(json!({
        "source_job_id": source_job_id,
        "source_event": original_payload,
    }));
    item
}

fn select_live_stage_snapshot(items: &[JobEventRecord]) -> Option<LiveStageSnapshot> {
    let selected = items
        .iter()
        .filter(|item| {
            if item.lane.as_deref().map(str::trim).unwrap_or("") != "main" {
                return false;
            }
            let raw_event_type = item
                .raw_event_type
                .as_deref()
                .or(item.event_type.as_deref())
                .map(str::trim)
                .unwrap_or("");
            let stage = raw_stage_for_snapshot(item).unwrap_or_else(|| {
                item.stage
                    .as_deref()
                    .map(str::trim)
                    .unwrap_or("")
                    .to_string()
            });
            raw_event_type != "artifact_published" && !stage.is_empty()
        })
        .max_by(|left, right| {
            job_stage_rank(
                raw_stage_for_snapshot(left)
                    .as_deref()
                    .or(left.stage.as_deref()),
            )
            .cmp(&job_stage_rank(
                raw_stage_for_snapshot(right)
                    .as_deref()
                    .or(right.stage.as_deref()),
            ))
            .then_with(|| left.ts.cmp(&right.ts))
            .then_with(|| left.seq.cmp(&right.seq))
        })?;
    let page_progress = items
        .iter()
        .filter(|item| {
            item.lane.as_deref().map(str::trim).unwrap_or("") == "main"
                && item.progress_unit.as_deref().map(str::trim) == Some("page")
                && (item.user_stage.as_deref().map(str::trim) == Some("render")
                    || item.stage.as_deref().map(str::trim) == Some("rendering"))
                && (item.progress_current.is_some() || item.progress_total.is_some())
        })
        .max_by(|left, right| {
            left.ts
                .cmp(&right.ts)
                .then_with(|| left.seq.cmp(&right.seq))
        });
    let fallback_progress = items
        .iter()
        .filter(|item| {
            item.lane.as_deref().map(str::trim).unwrap_or("") == "main"
                && (item.progress_current.is_some() || item.progress_total.is_some())
        })
        .max_by(|left, right| {
            left.ts
                .cmp(&right.ts)
                .then_with(|| left.seq.cmp(&right.seq))
        });
    let selected_stage = raw_stage_for_snapshot(selected)
        .or_else(|| selected.stage.as_deref().map(str::to_string))
        .unwrap_or_default();
    let progress_stage = fallback_progress
        .and_then(raw_stage_for_snapshot)
        .or_else(|| fallback_progress.and_then(|item| item.stage.as_deref().map(str::to_string)))
        .unwrap_or_default();
    let should_keep_progress_stage = selected.progress_current.is_none()
        && selected_stage.trim() == "failed"
        && !progress_stage.trim().is_empty();
    Some(LiveStageSnapshot {
        stage: if should_keep_progress_stage {
            fallback_progress
                .and_then(raw_stage_for_snapshot)
                .or_else(|| fallback_progress.and_then(|item| item.stage.clone()))
        } else {
            raw_stage_for_snapshot(selected).or_else(|| selected.stage.clone())
        },
        stage_detail: if should_keep_progress_stage {
            fallback_progress.and_then(|item| item.stage_detail.clone())
        } else {
            selected.stage_detail.clone()
        },
        progress_current: display_progress_event(selected, page_progress)
            .and_then(|item| item.progress_current)
            .or_else(|| fallback_progress.and_then(|item| item.progress_current)),
        progress_total: display_progress_event(selected, page_progress)
            .and_then(|item| item.progress_total)
            .or_else(|| fallback_progress.and_then(|item| item.progress_total)),
        progress_unit: display_progress_event(selected, page_progress)
            .and_then(|item| item.progress_unit.clone())
            .or_else(|| fallback_progress.and_then(|item| item.progress_unit.clone())),
    })
}

fn raw_stage_for_snapshot(item: &JobEventRecord) -> Option<String> {
    item.payload
        .as_ref()
        .and_then(|payload| payload.get("raw_stage"))
        .and_then(|value| value.as_str())
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn display_progress_event<'a>(
    selected: &'a JobEventRecord,
    page_progress: Option<&'a JobEventRecord>,
) -> Option<&'a JobEventRecord> {
    if selected.progress_unit.as_deref().map(str::trim) == Some("page") {
        return Some(selected);
    }
    let selected_stage = selected.stage.as_deref().map(str::trim).unwrap_or("");
    let selected_user_stage = selected.user_stage.as_deref().map(str::trim).unwrap_or("");
    if selected_user_stage == "render" || selected_stage == "rendering" {
        return page_progress.or(Some(selected));
    }
    Some(selected)
}
