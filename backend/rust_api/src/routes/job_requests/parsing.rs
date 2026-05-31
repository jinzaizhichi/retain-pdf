use crate::error::AppError;
use crate::models::GlossaryEntryInput;

pub(super) fn parse_glossary_entries_field(
    value: &str,
) -> Result<Vec<GlossaryEntryInput>, AppError> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Ok(Vec::new());
    }
    serde_json::from_str::<Vec<GlossaryEntryInput>>(trimmed)
        .map_err(|err| AppError::bad_request(format!("glossary_json must be a JSON array: {err}")))
}

pub(super) fn parse_bool_like(value: &str) -> bool {
    matches!(
        value.trim(),
        "1" | "true" | "True" | "TRUE" | "yes" | "Yes" | "YES" | "on" | "ON"
    )
}

pub(super) fn parse_i64_like(name: &str, value: &str) -> Result<i64, AppError> {
    value
        .parse::<i64>()
        .map_err(|_| AppError::bad_request(format!("{name} must be an integer")))
}

pub(super) fn parse_f64_like(name: &str, value: &str) -> Result<f64, AppError> {
    value
        .parse::<f64>()
        .map_err(|_| AppError::bad_request(format!("{name} must be a number")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_glossary_entries_field_rejects_non_array_payload() {
        let err = parse_glossary_entries_field(r#"{"source":"band gap"}"#)
            .expect_err("should reject non-array glossary payload");
        assert!(err
            .to_string()
            .contains("glossary_json must be a JSON array"));
    }
}
