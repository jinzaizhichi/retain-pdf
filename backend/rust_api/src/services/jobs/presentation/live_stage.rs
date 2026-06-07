use std::path::Path;

use crate::models::{JobProgressView, JobSnapshot};

// Public live-stage projection stays here; event loading, child-event merging,
// and snapshot selection are split out to keep the progress contract auditable.
mod canonical_events;
mod combined_events;
mod pipeline_events;
mod records;
mod snapshot;

pub(crate) use combined_events::list_combined_job_events;
pub(crate) use records::load_pipeline_event_records;

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
    snapshot::select_live_stage_snapshot(&items)
}
