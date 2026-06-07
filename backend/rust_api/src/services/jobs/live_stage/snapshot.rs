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
            let stage = item
                .stage
                .as_deref()
                .map(str::trim)
                .unwrap_or("")
                .to_string();
            raw_event_type != "artifact_published" && !stage.is_empty()
        })
        .max_by(|left, right| {
            job_stage_rank(left.stage.as_deref())
                .cmp(&job_stage_rank(right.stage.as_deref()))
                .then_with(|| left.ts.cmp(&right.ts))
                .then_with(|| left.seq.cmp(&right.seq))
        })?;
    let page_progress = latest_render_page_progress(items);
    let fallback_progress = latest_progress(items);
    let selected_stage = selected
        .stage
        .as_deref()
        .map(str::to_string)
        .unwrap_or_default();
    let progress_stage = fallback_progress
        .and_then(|item| item.stage.as_deref().map(str::to_string))
        .unwrap_or_default();
    let should_keep_progress_stage = progress_current(selected).is_none()
        && selected_stage.trim() == "failed"
        && !progress_stage.trim().is_empty();
    let progress_event = display_progress_event(selected, page_progress);
    Some(LiveStageSnapshot {
        stage: if should_keep_progress_stage {
            fallback_progress.and_then(|item| item.stage.clone())
        } else {
            selected.stage.clone()
        },
        stage_detail: if should_keep_progress_stage {
            fallback_progress.and_then(|item| item.stage_detail.clone())
        } else {
            selected.stage_detail.clone()
        },
        progress_current: progress_event
            .and_then(progress_current)
            .or_else(|| fallback_progress.and_then(progress_current)),
        progress_total: progress_event
            .and_then(progress_total)
            .or_else(|| fallback_progress.and_then(progress_total)),
        progress_unit: progress_event
            .and_then(progress_unit)
            .or_else(|| fallback_progress.and_then(progress_unit)),
    })
}

fn latest_render_page_progress(items: &[JobEventRecord]) -> Option<&JobEventRecord> {
    latest_by_time(items.iter().filter(|item| {
        item.lane.as_deref().map(str::trim).unwrap_or("") == "main"
            && progress_unit(item).as_deref().map(str::trim) == Some("page")
            && (item.display_stage.as_deref().map(str::trim) == Some("render")
                || item.stage.as_deref().map(str::trim) == Some("rendering"))
            && (progress_current(item).is_some() || progress_total(item).is_some())
    }))
}

fn latest_progress(items: &[JobEventRecord]) -> Option<&JobEventRecord> {
    latest_by_time(items.iter().filter(|item| {
        item.lane.as_deref().map(str::trim).unwrap_or("") == "main"
            && (progress_current(item).is_some() || progress_total(item).is_some())
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

fn display_progress_event<'a>(
    selected: &'a JobEventRecord,
    page_progress: Option<&'a JobEventRecord>,
) -> Option<&'a JobEventRecord> {
    if progress_unit(selected).as_deref().map(str::trim) == Some("page") {
        return Some(selected);
    }
    let selected_stage = selected.stage.as_deref().map(str::trim).unwrap_or("");
    let selected_display_stage = selected
        .display_stage
        .as_deref()
        .map(str::trim)
        .unwrap_or("");
    if selected_display_stage == "render" || selected_stage == "rendering" {
        return page_progress.or(Some(selected));
    }
    Some(selected)
}

fn progress_current(item: &JobEventRecord) -> Option<i64> {
    item.progress
        .as_ref()
        .and_then(|progress| progress.current)
        .or(item.progress_current)
}

fn progress_total(item: &JobEventRecord) -> Option<i64> {
    item.progress
        .as_ref()
        .and_then(|progress| progress.total)
        .or(item.progress_total)
}

fn progress_unit(item: &JobEventRecord) -> Option<String> {
    item.progress
        .as_ref()
        .and_then(|progress| progress.unit.clone())
        .or_else(|| item.progress_unit.clone())
}
