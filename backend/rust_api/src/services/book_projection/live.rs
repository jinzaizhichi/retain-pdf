use std::path::Path;

use crate::db::Db;
use crate::models::{JobProgressView, JobSnapshot};
use crate::services::jobs::live_stage::{build_progress_view, load_live_stage_snapshot};

pub(super) struct BookLiveProjection {
    pub stage: Option<String>,
    pub stage_detail: Option<String>,
    pub progress: JobProgressView,
}

pub(super) fn build_live_projection(
    db: &Db,
    job: &JobSnapshot,
    data_root: &Path,
) -> BookLiveProjection {
    let live_stage = load_live_stage_snapshot(db, job, data_root);
    BookLiveProjection {
        stage: live_stage
            .as_ref()
            .and_then(|snapshot| snapshot.stage.clone())
            .or_else(|| job.stage.clone()),
        stage_detail: live_stage
            .as_ref()
            .and_then(|snapshot| snapshot.stage_detail.clone())
            .or_else(|| job.stage_detail.clone()),
        progress: build_progress_view(job, live_stage.as_ref()),
    }
}
