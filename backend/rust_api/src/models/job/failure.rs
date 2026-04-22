use serde::{Deserialize, Serialize};

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobFailureInfo {
    pub stage: String,
    pub category: String,
    pub code: Option<String>,
    pub summary: String,
    pub root_cause: Option<String>,
    pub retryable: bool,
    pub upstream_host: Option<String>,
    pub provider: Option<String>,
    pub suggestion: Option<String>,
    pub last_log_line: Option<String>,
    pub raw_error_excerpt: Option<String>,
    pub raw_diagnostic: Option<JobRawDiagnostic>,
    pub ai_diagnostic: Option<JobAiDiagnostic>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobRawDiagnostic {
    pub structured_error_type: Option<String>,
    pub raw_exception_type: Option<String>,
    pub raw_exception_message: Option<String>,
    pub traceback: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone, Default, PartialEq, Eq)]
pub struct JobAiDiagnostic {
    pub summary: String,
    pub root_cause: Option<String>,
    pub suggestion: Option<String>,
    pub confidence: Option<String>,
    pub observed_signals: Vec<String>,
}
