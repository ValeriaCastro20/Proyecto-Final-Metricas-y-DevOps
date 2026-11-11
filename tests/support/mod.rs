#![allow(dead_code)]
use axum::{
    Router,
    body::Body,
    http::{Request, StatusCode},
};
use event_service::{
    MIGRATOR,
    api::{self, AppState},
    config::Settings,
    postgres::PostgresRepository,
    service::EventService,
};
use http_body_util::BodyExt;
use serde_json::{Value, json};
use std::{collections::BTreeMap, sync::Arc};
use tower::ServiceExt;

/// Return isolated deterministic credentials without reading or mutating the process environment.
pub fn settings() -> Settings {
    Settings::from_map(&BTreeMap::from([
        ("EVENT_PRODUCER_KEY".into(), "test-producer".into()),
        ("EVENT_ANALYST_KEY".into(), "test-analyst".into()),
        (
            "EVENT_PRODUCER_SOURCE_KEYS".into(),
            "sensor-a:scoped-a,sensor-b:scoped-b".into(),
        ),
    ]))
}
/// Compose the real HTTP stack with a lazy PostgreSQL adapter for boundary tests.
pub fn app(settings: Settings) -> Router {
    let repository = PostgresRepository::new(&settings);
    let scenario = repository
        .pool()
        .ok()
        .cloned()
        .map(|pool| event_service::scenario::store::Store { pool });
    api::router(AppState {
        settings: Arc::new(settings),
        service: EventService::new(Arc::new(repository)),
        scenario,
        metrics: metrics_exporter_prometheus::PrometheusBuilder::new()
            .build_recorder()
            .handle(),
    })
}
/// Build a valid event whose natural key is owned by the calling test.
pub fn event(source: &str, id: &str) -> Value {
    json!({"source": source, "external_id": id, "type": "temperature", "occurred_at": "2040-01-01T12:00:00Z", "payload": {"value": 23.5}})
}
/// Send an in-process HTTP request and collect status, parsed JSON and correlation header.
pub async fn request(
    app: &Router,
    method: &str,
    path: &str,
    key: Option<&str>,
    body: Option<Value>,
) -> (StatusCode, Value, String) {
    let mut request = Request::builder()
        .method(method)
        .uri(path)
        .header("x-request-id", "test-request");
    if let Some(key) = key {
        request = request.header("x-api-key", key);
    }
    if body.is_some() {
        request = request.header("content-type", "application/json");
    }
    let request = request
        .body(
            body.map(|b| Body::from(b.to_string()))
                .unwrap_or_else(Body::empty),
        )
        .unwrap();
    let response = app.clone().oneshot(request).await.unwrap();
    let status = response.status();
    let id = response.headers()["x-request-id"]
        .to_str()
        .unwrap()
        .to_owned();
    let bytes = response.into_body().collect().await.unwrap().to_bytes();
    (status, serde_json::from_slice(&bytes).unwrap(), id)
}
/// Assert the exact public error envelope, fixed message and matching request/body identifiers.
pub fn assert_error(response: &(StatusCode, Value, String), status: u16, code: &str) {
    assert_eq!(response.0.as_u16(), status);
    assert_eq!(response.1["error"]["code"], code);
    let message = match code {
        "INVALID_INPUT" => "Invalid request input.",
        "UNAUTHENTICATED" => "Authentication required.",
        "FORBIDDEN" => "Access denied.",
        "NOT_FOUND" => "Resource not found.",
        "DUPLICATE" => "Event already exists.",
        "DEPENDENCY_UNAVAILABLE" => "Dependency unavailable.",
        "INTERNAL_ERROR" => "Internal server error.",
        _ => panic!("unknown public error code"),
    };
    assert_eq!(
        response.1["error"]["message"],
        if status == 405 {
            "Invalid request."
        } else {
            message
        }
    );
    assert_eq!(response.1["error"]["request_id"], response.2);
    assert_eq!(response.1["error"].as_object().unwrap().len(), 3);
}

/// Integration tests are explicitly ignored unless requested; missing DB then fails.
/// Test data is scoped by a UUID source and cleanup never truncates shared tables.
pub struct Database {
    pub settings: Settings,
    pub pool: sqlx::PgPool,
    pub source: String,
}
impl Database {
    /// Require a dedicated test DB, validate URL consistency, migrate and allocate an owned UUID source.
    pub async fn new() -> Self {
        let url = std::env::var("TEST_DATABASE_URL")
            .expect("set TEST_DATABASE_URL to a dedicated *_test database");
        let options: sqlx::postgres::PgConnectOptions =
            url.parse().expect("invalid TEST_DATABASE_URL");
        let name = options.get_database().unwrap_or("");
        assert!(
            name.starts_with("test_") || name.ends_with("_test"),
            "integration tests require test_* or *_test database"
        );
        if let Ok(configured) = std::env::var("DATABASE_URL") {
            assert_eq!(configured, url, "DATABASE_URL must equal TEST_DATABASE_URL");
        }
        let mut settings = settings();
        settings.database_url = Some(url);
        let repo = PostgresRepository::new(&settings);
        let pool = repo.pool().unwrap().clone();
        MIGRATOR.run(&pool).await.unwrap();
        Self {
            settings,
            pool,
            source: format!("test-{}", uuid::Uuid::new_v4().simple()),
        }
    }
    /// Build a separate lazy pool using the same isolated test configuration.
    pub fn repository(&self) -> PostgresRepository {
        PostgresRepository::new(&self.settings)
    }
    /// Compose an HTTP application connected only to the validated integration-test database.
    pub fn app(&self) -> Router {
        app(self.settings.clone())
    }
    /// Delete only this test's source rows and close its pool, without truncating shared tables.
    pub async fn cleanup(self) {
        sqlx::query("DELETE FROM events WHERE source = $1")
            .bind(&self.source)
            .execute(&self.pool)
            .await
            .unwrap();
        self.pool.close().await;
    }
}
