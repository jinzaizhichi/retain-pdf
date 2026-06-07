use crate::models::{job_stage_rank, JobEventRecord};

use super::LiveStageSnapshot;

pub(super) fn select_live_stage_snapshot(items: &[JobEventRecord]) -> Option<LiveStageSnapshot> {
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
    let page_progress = latest_render_page_progress(items);
    let fallback_progress = latest_progress(items);
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
    let progress_event = display_progress_event(selected, page_progress);
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
        progress_current: progress_event
            .and_then(|item| item.progress_current)
            .or_else(|| fallback_progress.and_then(|item| item.progress_current)),
        progress_total: progress_event
            .and_then(|item| item.progress_total)
            .or_else(|| fallback_progress.and_then(|item| item.progress_total)),
        progress_unit: progress_event
            .and_then(|item| item.progress_unit.clone())
            .or_else(|| fallback_progress.and_then(|item| item.progress_unit.clone())),
    })
}

fn latest_render_page_progress(items: &[JobEventRecord]) -> Option<&JobEventRecord> {
    latest_by_time(items.iter().filter(|item| {
        item.lane.as_deref().map(str::trim).unwrap_or("") == "main"
            && item.progress_unit.as_deref().map(str::trim) == Some("page")
            && (item.user_stage.as_deref().map(str::trim) == Some("render")
                || item.stage.as_deref().map(str::trim) == Some("rendering"))
            && (item.progress_current.is_some() || item.progress_total.is_some())
    }))
}

fn latest_progress(items: &[JobEventRecord]) -> Option<&JobEventRecord> {
    latest_by_time(items.iter().filter(|item| {
        item.lane.as_deref().map(str::trim).unwrap_or("") == "main"
            && (item.progress_current.is_some() || item.progress_total.is_some())
    }))
}

fn latest_by_time<'a>(
    items: impl Iterator<Item = &'a JobEventRecord>,
) -> Option<&'a JobEventRecord> {
    items.max_by(|left, right| {
        left.ts
            .cmp(&right.ts)
            .then_with(|| left.seq.cmp(&right.seq))
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
