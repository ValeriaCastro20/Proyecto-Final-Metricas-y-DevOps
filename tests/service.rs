#![allow(clippy::unwrap_used, clippy::expect_used)]
mod support;
use async_trait::async_trait;
use event_service::{
    api::{self, AppState},
    auth::authenticate,
    domain::*,
    error::Error,
    repository::EventRepository,
    service::EventService,
};
use std::sync::{
    Arc,
    atomic::{AtomicBool, AtomicUsize, Ordering},
};
use uuid::Uuid;

#[derive(Default)]
struct ProbeRepository {
    calls: AtomicUsize,
    available: AtomicBool,
}
impl ProbeRepository {
    /// Count unexpected storage access so denied use cases cannot silently touch persistence.
    fn accessed<T>(&self) -> Result<T, Error> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Err(Error::Unavailable)
    }
}
#[async_trait]
impl EventRepository for ProbeRepository {
    /// Model a recoverable dependency without rebuilding the HTTP application.
    async fn ready(&self) -> Result<(), Error> {
        if self.available.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(Error::Unavailable)
        }
    }
    async fn create(&self, _: &[EventCreate]) -> Result<Vec<Event>, Error> {
        self.accessed()
    }
    async fn get(&self, _: Uuid) -> Result<Option<Event>, Error> {
        self.accessed()
    }
    async fn list(&self, _: &ListQuery) -> Result<(i64, Vec<Event>), Error> {
        self.accessed()
    }
    /// Return deliberately unsorted dimensions to verify locale-independent application ordering.
    async fn counts(&self, _: &CountsQuery) -> Result<Vec<Count>, Error> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        Ok(vec![
            Count {
                key: "a".into(),
                count: 1,
            },
            Count {
                key: "B".into(),
                count: 2,
            },
        ])
    }
    async fn timeseries(&self, _: &TimeseriesQuery) -> Result<Vec<Point>, Error> {
        self.accessed()
    }
    async fn summary(&self, _: &SummaryQuery) -> Result<SummaryResponse, Error> {
        self.accessed()
    }
}

#[tokio::test]
/// Call use cases directly to prove HTTP adapters are not the sole authorization boundary.
async fn service_rechecks_permissions_before_repository_access() {
    let repository = Arc::new(ProbeRepository::default());
    let service = EventService::new(repository.clone());
    let settings = support::settings();
    let producer = authenticate(Some("test-producer"), &settings).unwrap();
    let analyst = authenticate(Some("test-analyst"), &settings).unwrap();
    let batch = EventBatchCreate {
        events: vec![serde_json::from_value(support::event("sensor-a", "id")).unwrap()],
    };
    assert!(matches!(
        service.create(&analyst, batch).await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        service.get(&producer, Uuid::new_v4()).await,
        Err(Error::Forbidden)
    ));
    let query = serde_json::json!({"from":"2026-01-01T00:00:00Z", "to":"2026-01-02T00:00:00Z"});
    assert!(matches!(
        service
            .list(&producer, serde_json::from_value(query.clone()).unwrap())
            .await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        service
            .summary(&producer, serde_json::from_value(query.clone()).unwrap())
            .await,
        Err(Error::Forbidden)
    ));
    assert!(matches!(
        service
            .timeseries(&producer, serde_json::from_value(query.clone()).unwrap())
            .await,
        Err(Error::Forbidden)
    ));
    let mut query = query;
    query["group_by"] = serde_json::json!("type");
    assert!(matches!(
        service
            .counts(&producer, serde_json::from_value(query).unwrap())
            .await,
        Err(Error::Forbidden)
    ));
    assert_eq!(repository.calls.load(Ordering::SeqCst), 0);
    let query: CountsQuery = serde_json::from_value(serde_json::json!({
        "from":"2026-01-01T00:00:00Z", "to":"2026-01-02T00:00:00Z", "group_by":"type"
    }))
    .unwrap();
    let counted = service.counts(&analyst, query).await.unwrap();
    assert_eq!(counted.total, 3);
    assert_eq!(
        counted
            .buckets
            .iter()
            .map(|bucket| bucket.key.as_str())
            .collect::<Vec<_>>(),
        ["B", "a"]
    );
}

#[tokio::test]
/// Preserve liveness during dependency failure and recover readiness on the same router instance.
async fn dependency_recovers_without_rebuilding_app() {
    let repository = Arc::new(ProbeRepository::default());
    let app = api::router(AppState {
        settings: Arc::new(support::settings()),
        service: EventService::new(repository.clone()),
        scenario: None,
        metrics: metrics_exporter_prometheus::PrometheusBuilder::new()
            .build_recorder()
            .handle(),
    });
    support::assert_error(
        &support::request(&app, "GET", "/health/ready", None, None).await,
        503,
        "DEPENDENCY_UNAVAILABLE",
    );
    assert_eq!(
        support::request(&app, "GET", "/health/live", None, None)
            .await
            .0,
        200
    );
    repository.available.store(true, Ordering::SeqCst);
    assert_eq!(
        support::request(&app, "GET", "/health/ready", None, None)
            .await
            .0,
        200
    );
}
