#[tokio::main]
/// Initialize safe diagnostics and translate command failures to a nonzero process exit status.
async fn main() -> ExitCode {
    // The default hook prints panic payloads even when catch_unwind handles them.
    // Never send potentially sensitive panic messages to application logs.
    std::panic::set_hook(Box::new(|_| tracing::error!("unexpected panic")));

    // MET-03: Initialize Prometheus Exporter
    if metrics_exporter_prometheus::PrometheusBuilder::new()
        .install()
        .is_err()
    {
        tracing::error!("failed to install Prometheus exporter");
    }

    // MET-04: Initialize OpenTelemetry for Tracing (export to Jaeger)
    let tracer = opentelemetry_otlp::new_pipeline()
        .tracing()
        .with_exporter(
            opentelemetry_otlp::new_exporter()
                .http()
                .with_endpoint("http://jaeger-collector.eventos-development.svc.cluster.local:4318/v1/traces"),
        )
        .with_trace_config(
            opentelemetry_sdk::trace::config().with_resource(
                opentelemetry_sdk::Resource::new(vec![opentelemetry::KeyValue::new(
                    "service.name",
                    "event-service",
                )]),
            ),
        )
        .install_batch(opentelemetry_sdk::runtime::Tokio)
        .unwrap_or_else(|_| opentelemetry_sdk::trace::TracerProvider::builder().build().tracer("fallback"));

    let telemetry = tracing_opentelemetry::layer().with_tracer(tracer);
    use tracing_subscriber::layer::SubscriberExt;
    use tracing_subscriber::util::SubscriberInitExt;

    // MET-02: Structured JSON Logs
    tracing_subscriber::registry()
        .with(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "event_service=info,sqlx=off".into()),
        )
        .with(tracing_subscriber::fmt::layer().json().with_writer(std::io::stderr))
        .with(telemetry)
        .init();

    match run().await {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            tracing::error!(message, "operation failed");
            ExitCode::FAILURE
        }
    }
}