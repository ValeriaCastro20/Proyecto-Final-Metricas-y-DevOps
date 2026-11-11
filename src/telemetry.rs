//! Bounded W3C trace context only: never persist baggage or arbitrary request headers.
use opentelemetry::{Context, propagation::TextMapPropagator, trace::TraceContextExt};
use opentelemetry_sdk::propagation::TraceContextPropagator;
use std::collections::HashMap;
use tracing_opentelemetry::OpenTelemetrySpanExt;

/// Extract a valid remote parent; invalid/missing context starts an independent trace.
pub fn parent(traceparent: Option<&str>) -> Context {
    let mut carrier = HashMap::new();
    if let Some(value) = traceparent.filter(|v| v.len() <= 512) {
        carrier.insert("traceparent".to_owned(), value.to_owned());
    }
    TraceContextPropagator::new().extract(&carrier)
}

/// Serialize the current span for the durable inbox, omitting invalid/no-op contexts.
pub fn current_traceparent() -> Option<String> {
    let context = tracing::Span::current().context();
    if !context.span().span_context().is_valid() {
        return None;
    }
    let mut carrier = HashMap::new();
    TraceContextPropagator::new().inject_context(&context, &mut carrier);
    carrier.remove("traceparent")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_context_is_not_a_remote_parent() {
        for input in [
            None,
            Some("invalid"),
            Some("00-00000000000000000000000000000000-00f067aa0ba902b7-01"),
            Some("00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01"),
        ] {
            assert!(!parent(input).span().span_context().is_valid());
        }
        let context = parent(Some(
            "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01",
        ));
        assert!(context.span().span_context().is_remote());
        assert!(context.span().span_context().is_sampled());
    }
}
