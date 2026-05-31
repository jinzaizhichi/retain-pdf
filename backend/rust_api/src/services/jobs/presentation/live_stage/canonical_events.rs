use serde_json::{Map, Value};

use crate::models::{
    event_progress_unit, normalize_event_substage, normalize_event_user_stage,
    public_stage_for_raw_stage, public_stage_for_substage, JobEventProgressView, JobEventRecord,
};

pub(super) fn canonicalize_job_event(item: &mut JobEventRecord) {
    let raw_stage = clean(item.stage.as_deref());
    let raw_user_stage = clean(item.user_stage.as_deref());
    let raw_event_type = clean(item.raw_event_type.as_deref())
        .or_else(|| clean(item.event_type.as_deref()))
        .or_else(|| clean(Some(item.event.as_str())))
        .unwrap_or_else(|| "diagnostic".to_string());
    let substage = canonical_substage(item, raw_stage.as_deref());
    let public_stage = canonical_stage(
        substage.as_deref(),
        raw_stage.as_deref(),
        raw_user_stage.as_deref(),
    );
    let public_event_type = canonical_event_type(&raw_event_type, item.level.as_str());
    let lane = canonical_lane(substage.as_deref(), &public_event_type, &raw_event_type);
    let progress = canonical_progress(item, substage.as_deref());

    preserve_raw_stage(
        item,
        raw_stage.as_deref(),
        raw_user_stage.as_deref(),
        &raw_event_type,
    );

    item.stage = public_stage.clone();
    item.user_stage = public_stage;
    item.lane = Some(lane);
    item.substage = substage;
    item.raw_event_type = Some(raw_event_type);
    item.event_type = Some(public_event_type);
    item.progress_current = progress.current;
    item.progress_total = progress.total;
    item.progress_unit = progress.unit.clone();
    item.progress = Some(progress);
}

fn canonical_substage(item: &JobEventRecord, raw_stage: Option<&str>) -> Option<String> {
    if let Some(substage) = clean(item.substage.as_deref()) {
        return Some(normalize_substage(&substage));
    }
    if let Some(provider_stage) = clean(item.provider_stage.as_deref()) {
        return Some(normalize_substage(&provider_stage));
    }
    raw_stage.map(normalize_substage)
}

fn normalize_substage(value: &str) -> String {
    normalize_event_substage(value)
}

fn canonical_stage(
    substage: Option<&str>,
    raw_stage: Option<&str>,
    raw_user_stage: Option<&str>,
) -> Option<String> {
    if let Some(stage) = stage_for_substage(substage) {
        return Some(stage.to_string());
    }
    if let Some(stage) = raw_user_stage.and_then(normalize_user_stage) {
        return Some(stage.to_string());
    }
    raw_stage.and_then(stage_for_raw_stage).map(str::to_string)
}

fn stage_for_substage(substage: Option<&str>) -> Option<&'static str> {
    public_stage_for_substage(substage)
}

fn stage_for_raw_stage(raw_stage: &str) -> Option<&'static str> {
    public_stage_for_raw_stage(Some(raw_stage))
}

fn normalize_user_stage(value: &str) -> Option<&'static str> {
    normalize_event_user_stage(value)
}

fn canonical_event_type(raw_event_type: &str, level: &str) -> String {
    match raw_event_type.trim() {
        "stage_progress" | "stage_transition" => "progress".to_string(),
        "artifact_published" => "artifact".to_string(),
        "job_terminal" => "terminal".to_string(),
        "failure_classified" => "error".to_string(),
        _ if level.trim() == "error" => "error".to_string(),
        _ => "diagnostic".to_string(),
    }
}

fn canonical_lane(substage: Option<&str>, event_type: &str, raw_event_type: &str) -> String {
    match (
        substage.map(str::trim).unwrap_or_default(),
        event_type,
        raw_event_type.trim(),
    ) {
        ("render_prewarm", _, _) => "background".to_string(),
        (_, "artifact", _) | (_, _, "artifact_published") => "artifact".to_string(),
        (_, "diagnostic", _) | (_, "error", "failure_classified") => "diagnostic".to_string(),
        _ => "main".to_string(),
    }
}

fn canonical_progress(item: &JobEventRecord, substage: Option<&str>) -> JobEventProgressView {
    let unit = clean(item.progress_unit.as_deref()).or_else(|| default_progress_unit(substage));
    let current = item.progress_current;
    let total = item.progress_total;
    let percent = match (current, total) {
        (Some(current), Some(total)) if total > 0 => Some((current as f64 / total as f64) * 100.0),
        _ => None,
    };
    JobEventProgressView {
        unit,
        current,
        total,
        percent,
    }
}

fn default_progress_unit(substage: Option<&str>) -> Option<String> {
    match event_progress_unit(substage, "stage_progress") {
        "none" => None,
        unit => Some(unit.to_string()),
    }
}

fn preserve_raw_stage(
    item: &mut JobEventRecord,
    raw_stage: Option<&str>,
    raw_user_stage: Option<&str>,
    raw_event_type: &str,
) {
    let mut payload = item
        .payload
        .take()
        .unwrap_or_else(|| Value::Object(Map::new()));
    if let Value::Object(map) = &mut payload {
        if let Some(raw_stage) = raw_stage {
            map.entry("raw_stage".to_string())
                .or_insert_with(|| Value::String(raw_stage.to_string()));
        }
        if let Some(raw_user_stage) = raw_user_stage {
            map.entry("raw_user_stage".to_string())
                .or_insert_with(|| Value::String(raw_user_stage.to_string()));
        }
        map.entry("raw_event_type".to_string())
            .or_insert_with(|| Value::String(raw_event_type.to_string()));
    }
    item.payload = Some(payload);
}

fn clean(value: Option<&str>) -> Option<String> {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}
