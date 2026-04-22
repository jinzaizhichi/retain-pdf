use crate::models::{
    redact_json_value, redact_optional_text, redact_text, sensitive_values, JobEventRecord,
    JobSnapshot,
};

pub fn redacted_error(job: &JobSnapshot) -> Option<String> {
    let secrets = sensitive_values(&job.request_payload);
    redact_optional_text(job.error.as_deref(), &secrets)
}

pub fn redacted_log_tail(job: &JobSnapshot) -> Vec<String> {
    let secrets = sensitive_values(&job.request_payload);
    job.log_tail
        .iter()
        .map(|line| redact_text(line, &secrets))
        .collect()
}

pub fn redact_job_events(job: &JobSnapshot, items: Vec<JobEventRecord>) -> Vec<JobEventRecord> {
    let secrets = sensitive_values(&job.request_payload);
    items
        .into_iter()
        .map(|mut item| {
            item.message = redact_text(&item.message, &secrets);
            item.payload = item
                .payload
                .as_ref()
                .map(|payload| redact_json_value(payload, &secrets));
            item
        })
        .collect()
}
