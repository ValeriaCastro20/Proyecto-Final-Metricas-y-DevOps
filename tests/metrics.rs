#![allow(clippy::unwrap_used, clippy::expect_used)]
mod support;

use axum::{body::Body, http::Request};
use event_service::{
    api::{self, AppState},
    service::EventService,
};
use http_body_util::BodyExt;
use std::sync::{Arc, OnceLock};
use tower::ServiceExt;

/// Install one recorder per test process and share its handle with the HTTP adapter.
fn handle() -> metrics_exporter_prometheus::PrometheusHandle {
    static HANDLE: OnceLock<metrics_exporter_prometheus::PrometheusHandle> = OnceLock::new();
    HANDLE
        .get_or_init(|| {
            metrics_exporter_prometheus::PrometheusBuilder::new()
                .install_recorder()
                .unwrap()
        })
        .clone()
}

/// Request the real metrics endpoint and collect its successful text exposition.
async fn scrape(app: &axum::Router) -> String {
    let response = app
        .clone()
        .oneshot(
            Request::builder()
                .uri("/metrics")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 200);
    String::from_utf8(
        response
            .into_body()
            .collect()
            .await
            .unwrap()
            .to_bytes()
            .to_vec(),
    )
    .unwrap()
}

#[tokio::test]
/// Expose global instruments while excluding user-controlled URLs from metric labels.
async fn endpoint_renders_global_recorder_and_bounded_http_labels() {
    let metrics = handle();
    let repository = event_service::postgres::PostgresRepository::new(&support::settings());
    let app = api::router(AppState {
        settings: Arc::new(support::settings()),
        service: EventService::new(Arc::new(repository)),
        scenario: None,
        metrics,
    });
    metrics::counter!("global_recorder_probe_total").increment(3);
    support::request(&app, "GET", "/health/live", None, None).await;
    support::request(&app, "GET", "/untrusted-unique-path", None, None).await;
    let text = scrape(&app).await;
    assert!(text.contains("global_recorder_probe_total 3"));
    assert!(text.contains("http_requests_total{route=\"/health/live\",status=\"200\"} 1"));
    assert!(text.contains("http_request_duration_seconds"));
    assert!(!text.contains("untrusted-unique-path"));
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL pointing to dedicated PostgreSQL"]
/// Verify durable outcomes, live backlog and nonempty batch latency against PostgreSQL.
async fn backlog_scrape_tracks_database_without_worker_and_fails_closed() {
    let db = support::Database::new().await;
    let repository = db.repository();
    let pool = repository.pool().unwrap().clone();
    let store = event_service::scenario::store::Store { pool: pool.clone() };
    let app = api::router(AppState {
        settings: Arc::new(db.settings.clone()),
        service: EventService::new(Arc::new(repository)),
        scenario: Some(store.clone()),
        metrics: handle(),
    });
    assert_eq!(store.process(1000).await.unwrap(), 0);
    assert!(
        !scrape(&app)
            .await
            .contains("esc3_processor_duration_seconds")
    );
    let device: event_service::scenario::DeviceCreate = serde_json::from_value(serde_json::json!({
        "id": db.source, "facility_id": "metrics-test",
        "limits": {"temperature_min": 0, "temperature_max": 40, "humidity_min": 0, "humidity_max": 100}
    })).unwrap();
    store.register(&device).await.unwrap();
    let event = serde_json::from_value(serde_json::json!({"device_id": db.source, "event_id": "one", "occurred_at": "2040-01-01T12:00:00Z", "temperature":20,"humidity":40,"state":"running"})).unwrap();
    let before = store.pending().await.unwrap();
    assert_eq!(store.receive(&event).await.unwrap().outcome, "accepted");
    assert_eq!(store.receive(&event).await.unwrap().outcome, "duplicate");
    let receipt = store
        .reject(Some(&db.source), "invalid_fields")
        .await
        .unwrap();
    assert_eq!(receipt.outcome, "rejected");
    assert_eq!(receipt.reason.as_deref(), Some("invalid_fields"));
    let persisted = store.receipt(receipt.id).await.unwrap();
    assert_eq!(persisted["reason"], "invalid_fields");
    let text = scrape(&app).await;
    assert!(text.contains(&format!("esc3_events_backlog_total {}", before + 1)));
    for outcome in ["accepted", "duplicate", "rejected"] {
        assert!(text.contains(&format!(
            "esc3_events_received_total{{outcome=\"{outcome}\"}} 1"
        )));
    }
    store.process(1000).await.unwrap();
    let text = scrape(&app).await;
    assert!(text.contains("esc3_events_backlog_total 0"));
    assert!(text.contains("esc3_processor_duration_seconds_count 1"));
    assert!(text.contains("esc3_events_processed_total 1"));
    assert_eq!(store.process(1000).await.unwrap(), 0);
    let text = scrape(&app).await;
    assert!(text.contains("esc3_processor_duration_seconds_count 1"));
    assert!(text.contains("esc3_events_processed_total 1"));
    sqlx::query("DELETE FROM reception_receipts WHERE device_id=$1")
        .bind(&db.source)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM readings WHERE device_id=$1")
        .bind(&db.source)
        .execute(&pool)
        .await
        .unwrap();
    sqlx::query("DELETE FROM devices WHERE id=$1")
        .bind(&db.source)
        .execute(&pool)
        .await
        .unwrap();
    pool.close().await;
    let response = app
        .oneshot(
            Request::builder()
                .uri("/metrics")
                .body(Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), 503);
    db.cleanup().await;
}
