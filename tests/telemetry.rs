#![allow(clippy::unwrap_used, clippy::expect_used)]
//! Exercise optional trace export in real child processes without changing the test environment.
use std::process::{Child, Command, Stdio};
use std::time::Duration;

/// Kill and reap only the API process owned by this test, including on assertion failure.
struct ApiProcess(Child);
impl Drop for ApiProcess {
    /// Prevent a failed telemetry assertion from leaving an HTTP server running.
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// Send a real request and observe export to a local collector with or without explicit opt-in.
async fn check_export(configured: bool) {
    let collector = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let collector_url = format!("http://{}", collector.local_addr().unwrap());
    let (send, mut receive) = tokio::sync::mpsc::channel(8);
    let app = axum::Router::new().fallback(move |request: axum::extract::Request| {
        let send = send.clone();
        async move {
            let _ = send.send(request.uri().path().to_owned()).await;
            axum::http::StatusCode::OK
        }
    });
    let server = tokio::spawn(async move { axum::serve(collector, app).await.unwrap() });
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let address = listener.local_addr().unwrap();
    drop(listener);
    let mut command = Command::new(env!("CARGO_BIN_EXE_event-service"));
    command
        .arg("serve")
        .env("BIND_ADDR", address.to_string())
        .env("RUST_LOG", "event_service=info")
        .env("OTEL_BSP_SCHEDULE_DELAY", "100")
        .env("OTEL_EXPORTER_OTLP_ENDPOINT", &collector_url)
        .env_remove("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
        .env_remove("DATABASE_URL")
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    if configured {
        command.env(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            format!("{collector_url}/custom-traces"),
        );
    }
    let mut process = ApiProcess(command.spawn().unwrap());
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
        .unwrap();
    let url = format!("http://{address}/health/live");
    let mut ready = false;
    for _ in 0..100 {
        assert!(
            process.0.try_wait().unwrap().is_none(),
            "API exited before readiness"
        );
        if client
            .get(&url)
            .send()
            .await
            .is_ok_and(|response| response.status().is_success())
        {
            ready = true;
            break;
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    assert!(ready, "API listener did not become ready");
    if configured {
        let path = tokio::time::timeout(Duration::from_secs(10), receive.recv())
            .await
            .unwrap()
            .unwrap();
        assert_eq!(path, "/custom-traces");
    } else {
        assert!(
            tokio::time::timeout(Duration::from_millis(750), receive.recv())
                .await
                .is_err()
        );
    }
    server.abort();
}

#[tokio::test]
/// A generic OTLP endpoint alone must not enable trace export or affect liveness.
async fn traces_are_disabled_without_explicit_signal_endpoint() {
    check_export(false).await;
}

#[tokio::test]
/// Preserve the explicitly configured full signal path without appending another suffix.
async fn traces_use_the_explicit_signal_endpoint() {
    check_export(true).await;
}
