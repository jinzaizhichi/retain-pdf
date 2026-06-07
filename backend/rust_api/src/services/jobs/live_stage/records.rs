use std::path::Path;

use crate::models::{JobEventRecord, JobSnapshot};
use crate::storage_paths::resolve_events_jsonl;

use super::canonical_events::canonicalize_job_event;
use super::pipeline_events::load_pipeline_events_jsonl;

pub(crate) fn load_pipeline_event_records(
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
            canonicalize_job_event(&mut item, "pipeline_jsonl");
            item
        })
        .collect()
}
