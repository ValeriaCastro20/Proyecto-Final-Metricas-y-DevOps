//! Real inbox propagation without a global subscriber or an external collector.
use super::*;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::{
    export::trace::{SpanData, SpanExporter},
    trace::TracerProvider,
};
use std::sync::{Arc, Mutex};
use tracing::instrument::WithSubscriber;
use tracing_subscriber::layer::SubscriberExt;

#[derive(Debug, Clone)]
struct Exporter(Arc<Mutex<Vec<SpanData>>>);
impl SpanExporter for Exporter {
    fn export(
        &mut self,
        batch: Vec<SpanData>,
    ) -> std::pin::Pin<
        Box<
            dyn std::future::Future<Output = opentelemetry::trace::TraceResult<()>>
                + Send
                + 'static,
        >,
    > {
        self.0.lock().unwrap().extend(batch);
        Box::pin(async { Ok(()) })
    }
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL pointing to dedicated PostgreSQL"]
/// API parent survives durable storage; retries preserve it and old rows still drain.
async fn api_context_survives_inbox_and_parents_worker_span() {
    let mut db = Database::new().await;
    // Other tests start workers which drain every public-schema reading. Give this
    // test its own search_path so parallel workers cannot consume its trace fixture.
    let admin = db.pool.clone();
    let schema = format!("trace_{}", uuid::Uuid::new_v4().simple());
    sqlx::query(&format!("CREATE SCHEMA {schema}"))
        .execute(&admin)
        .await
        .unwrap();
    let url = db.settings.database_url.as_mut().unwrap();
    let separator = if url.contains('?') { '&' } else { '?' };
    url.push_str(&format!("{separator}options=-csearch_path%3D{schema}"));
    db.pool = db.repository().pool().unwrap().clone();
    MIGRATOR.run(&db.pool).await.unwrap();
    let app = db.app();
    let store = Store {
        pool: db.pool.clone(),
    };
    let spans = Arc::new(Mutex::new(Vec::new()));
    let provider = TracerProvider::builder()
        .with_simple_exporter(Exporter(spans.clone()))
        .build();
    let subscriber = tracing_subscriber::registry()
        .with(tracing_opentelemetry::layer().with_tracer(provider.tracer("esc3-test")));
    async {
        let device = json!({"id":db.source,"facility_id":"trace-test","limits":{"temperature_min":0,"temperature_max":30,"humidity_min":20,"humidity_max":80}});
        assert_eq!(request(&app,"POST","/v1/devices",Some("test-producer"),Some(device)).await.0,201);
        let response = app.clone().oneshot(Request::builder().method("POST").uri("/v1/readings")
            .header("x-api-key","test-producer").header("content-type","application/json")
            .header("traceparent","00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
            .body(Body::from(reading(&db.source,0).to_string())).unwrap()).await.unwrap();
        assert_eq!(response.status(),202);
        let receipt: Value = serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes()).unwrap();
        let id = uuid::Uuid::parse_str(receipt["reading_id"].as_str().unwrap()).unwrap();
        let original: String = sqlx::query_scalar("SELECT traceparent FROM readings WHERE id=$1").bind(id).fetch_one(&db.pool).await.unwrap();
        assert!(original.starts_with("00-4bf92f3577b34da6a3ce929d0e0e4736-"));
        assert_eq!(request(&app,"POST","/v1/readings",Some("test-producer"),Some(reading(&db.source,0))).await.0,200);
        let retained: String = sqlx::query_scalar("SELECT traceparent FROM readings WHERE id=$1").bind(id).fetch_one(&db.pool).await.unwrap();
        assert_eq!(retained,original);
        // A separate pool represents a worker started after API reception.
        let worker = Store { pool: db.repository().pool().unwrap().clone() };
        worker.process(1000).await.unwrap();
        for result in provider.force_flush() {
            result.unwrap();
        }
        {
        let exported = spans.lock().unwrap();
        let consumer = exported.iter().find(|s| s.name == "process_reading" && s.span_context.trace_id().to_string() == "4bf92f3577b34da6a3ce929d0e0e4736").unwrap();
        let api = exported.iter().find(|s| s.span_context.span_id() == consumer.parent_span_id).unwrap();
        assert_eq!(api.name,"http_request");
        assert_eq!(api.parent_span_id.to_string(),"00f067aa0ba902b7");
        }
        // Historical readings, and invalid stored context, must not prevent processing.
        for (n, context) in [(1,None),(2,Some("invalid"))] {
            let input = serde_json::from_value(reading(&db.source,n)).unwrap();
            let receipt = store.receive(&input).await.unwrap();
            sqlx::query("UPDATE readings SET traceparent=$2 WHERE id=$1").bind(receipt.reading_id).bind(context).execute(&db.pool).await.unwrap();
        }
        worker.process(1000).await.unwrap();
        assert_eq!(store.counters(Some(&db.source)).await.unwrap().pending,0);
        worker.pool.close().await;
    }.with_subscriber(subscriber).await;
    db.cleanup().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&admin)
        .await
        .unwrap();
    admin.close().await;
}
