use crate::models::JobArtifacts;

use super::{mineru, paddle, OcrProviderCapabilities, OcrProviderDiagnostics, OcrProviderKind};

#[derive(Debug, Clone)]
pub struct OcrProviderDefinition {
    pub kind: OcrProviderKind,
    pub key: &'static str,
    pub capabilities: OcrProviderCapabilities,
}

pub fn provider_definition(kind: &OcrProviderKind) -> Option<OcrProviderDefinition> {
    match kind {
        OcrProviderKind::Mineru => Some(OcrProviderDefinition {
            kind: OcrProviderKind::Mineru,
            key: "mineru",
            capabilities: mineru::capabilities(),
        }),
        OcrProviderKind::Paddle => Some(OcrProviderDefinition {
            kind: OcrProviderKind::Paddle,
            key: "paddle",
            capabilities: paddle::capabilities(),
        }),
        OcrProviderKind::Unknown => None,
    }
}

pub fn provider_capabilities(kind: &OcrProviderKind) -> Option<OcrProviderCapabilities> {
    provider_definition(kind).map(|definition| definition.capabilities)
}

pub fn supported_provider_keys() -> Vec<&'static str> {
    [
        OcrProviderKind::Mineru,
        OcrProviderKind::Paddle,
        OcrProviderKind::Unknown,
    ]
    .iter()
    .filter_map(|kind| provider_definition(kind).map(|definition| definition.key))
    .collect()
}

pub fn is_supported_provider(kind: &OcrProviderKind) -> bool {
    provider_definition(kind).is_some()
}

pub fn ensure_provider_diagnostics(
    artifacts: &mut JobArtifacts,
    provider_kind: OcrProviderKind,
) -> &mut OcrProviderDiagnostics {
    let Some(definition) = provider_definition(&provider_kind) else {
        return artifacts
            .ocr_provider_diagnostics
            .get_or_insert_with(|| OcrProviderDiagnostics::new(provider_kind));
    };

    if artifacts.ocr_provider_diagnostics.is_none() {
        let mut diagnostics = OcrProviderDiagnostics::new(definition.kind.clone());
        diagnostics.capabilities = Some(definition.capabilities);
        artifacts.ocr_provider_diagnostics = Some(diagnostics);
    } else if artifacts
        .ocr_provider_diagnostics
        .as_ref()
        .map(|diag| diag.capabilities.is_none() || diag.provider != definition.kind)
        .unwrap_or(true)
    {
        let diagnostics = artifacts.ocr_provider_diagnostics.as_mut().unwrap();
        diagnostics.provider = definition.kind;
        diagnostics.capabilities = Some(definition.capabilities);
    }
    artifacts.ocr_provider_diagnostics.as_mut().unwrap()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn provider_definition_exposes_supported_provider_keys() {
        assert_eq!(
            provider_definition(&OcrProviderKind::Mineru)
                .as_ref()
                .map(|item| item.key),
            Some("mineru")
        );
        assert_eq!(
            provider_definition(&OcrProviderKind::Paddle)
                .as_ref()
                .map(|item| item.key),
            Some("paddle")
        );
        assert!(provider_definition(&OcrProviderKind::Unknown).is_none());
    }

    #[test]
    fn supported_provider_keys_lists_all_supported_backends() {
        assert_eq!(supported_provider_keys(), vec!["mineru", "paddle"]);
    }

    #[test]
    fn ensure_provider_diagnostics_initializes_capabilities() {
        let mut artifacts = JobArtifacts::default();
        let diagnostics = ensure_provider_diagnostics(&mut artifacts, OcrProviderKind::Paddle);
        assert_eq!(diagnostics.provider, OcrProviderKind::Paddle);
        assert!(diagnostics.capabilities.is_some());
    }
}
