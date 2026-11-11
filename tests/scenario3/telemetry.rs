//! Real inbox propagation and JSON logs without an external collector.
use super::*;
use opentelemetry::trace::TracerProvider as _;
use opentelemetry_sdk::{
    export::trace::{SpanData, SpanExporter},
    trace::TracerProvider,
};
use std::sync::{Arc, Mutex};
use tracing_subscriber::layer::SubscriberExt;

#[derive(Debug, Clone)]
struct Exporter(Arc<Mutex<Vec<SpanData>>>);
#[derive(Clone)]
struct LogWriter(Arc<Mutex<Vec<u8>>>);
impl std::io::Write for LogWriter {
    fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
        self.0.lock().unwrap().extend_from_slice(bytes);
        Ok(bytes.len())
    }
    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}
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
    let logs = Arc::new(Mutex::new(Vec::new()));
    let writer = LogWriter(logs.clone());
    let subscriber = tracing_subscriber::registry()
        .with(
            tracing_subscriber::fmt::layer()
                .json()
                .with_writer(move || writer.clone()),
        )
        .with(tracing_opentelemetry::layer().with_tracer(provider.tracer("esc3-test")));
    // One subscriber for this integration binary avoids callsite-interest races
    // between instrumented and uninstrumented test threads. Filter by owned IDs.
    tracing::subscriber::set_global_default(subscriber).unwrap();
    async {
        let device = json!({"id":db.source,"facility_id":"trace-test","limits":{"temperature_min":0,"temperature_max":30,"humidity_min":20,"humidity_max":80}});
        assert_eq!(request(&app,"POST","/v1/devices",Some("test-producer"),Some(device)).await.0,201);
        let mut first = reading(&db.source,0);
        first["temperature"] = json!(40); // Produce an alert if the batch commits.
        let response = app.clone().oneshot(Request::builder().method("POST").uri("/v1/readings")
            .header("x-api-key","test-producer").header("content-type","application/json")
            .header("traceparent","00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
            .body(Body::from(first.to_string())).unwrap()).await.unwrap();
        assert_eq!(response.status(),202);
        let receipt: Value = serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes()).unwrap();
        let id = uuid::Uuid::parse_str(receipt["reading_id"].as_str().unwrap()).unwrap();
        let original: String = sqlx::query_scalar("SELECT traceparent FROM readings WHERE id=$1").bind(id).fetch_one(&db.pool).await.unwrap();
        assert!(original.starts_with("00-4bf92f3577b34da6a3ce929d0e0e4736-"));
        assert_eq!(request(&app,"POST","/v1/readings",Some("test-producer"),Some(reading(&db.source,0))).await.0,200);
        let retained: String = sqlx::query_scalar("SELECT traceparent FROM readings WHERE id=$1").bind(id).fetch_one(&db.pool).await.unwrap();
        assert_eq!(retained,original);
        let mut invalid = reading(&db.source,10);
        invalid["temperature"] = json!(999);
        assert_eq!(request(&app,"POST","/v1/readings",Some("test-producer"),Some(invalid)).await.0,422);
        let mut unknown = reading("unregistered-log-device",11);
        assert_eq!(request(&app,"POST","/v1/readings",Some("test-producer"),Some(unknown.clone())).await.0,422);
        unknown["private_body_marker"] = json!("must-not-appear-in-logs");
        assert_eq!(request(&app,"POST","/v1/readings",Some("test-producer"),Some(unknown)).await.0,422);
        // A separate pool represents a worker started after API reception.
        let worker = Store { pool: db.repository().pool().unwrap().clone() };
        // Fail after alert insertion and prove the whole batch rolls back.
        sqlx::query("ALTER TABLE readings ADD CONSTRAINT trace_test_failure CHECK (processed_at IS NULL)").execute(&db.pool).await.unwrap();
        assert!(worker.process(1000).await.is_err());
        assert_eq!(store.counters(Some(&db.source)).await.unwrap().pending,1);
        let alerts: i64 = sqlx::query_scalar("SELECT count(*) FROM business_alerts").fetch_one(&db.pool).await.unwrap();
        assert_eq!(alerts,0);
        sqlx::query("ALTER TABLE readings DROP CONSTRAINT trace_test_failure").execute(&db.pool).await.unwrap();
        worker.process(1000).await.unwrap();
        for result in provider.force_flush() {
            result.unwrap();
        }
        {
        let exported = spans.lock().unwrap();
        assert!(exported.iter().any(|s| s.name == "process_reading" && matches!(s.status, opentelemetry::trace::Status::Error { .. })));
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
        let failed = Store { pool: db.repository().pool().unwrap().clone() };
        failed.pool.close().await;
        assert!(failed.receive(&serde_json::from_value(reading(&db.source,99)).unwrap()).await.is_err());
        assert!(failed.reject(Some(&db.source),"invalid_format").await.is_err());
    }.await;
    let receipt_ids: Vec<uuid::Uuid> = sqlx::query_scalar("SELECT id FROM reception_receipts")
        .fetch_all(&db.pool)
        .await
        .unwrap();
    let text = String::from_utf8(logs.lock().unwrap().clone()).unwrap();
    assert!(!text.contains("must-not-appear-in-logs"));
    assert!(!text.contains("test-producer"));
    let records: Vec<Value> = text
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    let receptions: Vec<&Value> = records
        .iter()
        .filter(|r| {
            r["fields"]["message"] == "reading reception committed"
                && r["fields"]["receipt_id"]
                    .as_str()
                    .and_then(|id| uuid::Uuid::parse_str(id).ok())
                    .is_some_and(|id| receipt_ids.contains(&id))
        })
        .collect();
    assert_eq!(receptions.len(), 7, "{text}"); // accepted + duplicate + 3 rejections + 2 old-context fixtures
    let accepted = receptions
        .iter()
        .find(|r| r["fields"]["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736")
        .unwrap();
    let id = accepted["fields"]["reading_id"].as_str().unwrap();
    assert!(
        receptions
            .iter()
            .any(|r| r["fields"]["outcome"] == "duplicate" && r["fields"]["reading_id"] == id)
    );
    for reason in ["invalid_fields", "unknown_device", "invalid_format"] {
        let rejection = receptions
            .iter()
            .find(|r| r["fields"]["reason"] == reason)
            .unwrap();
        assert_eq!(rejection["fields"]["outcome"], "rejected");
        assert_eq!(rejection["fields"]["reading_id_present"], false);
        assert!(rejection["fields"].get("reading_id").is_none());
        uuid::Uuid::parse_str(rejection["fields"]["receipt_id"].as_str().unwrap()).unwrap();
    }
    assert!(
        records
            .iter()
            .any(|r| r["fields"]["message"] == "reading processing committed"
                && r["fields"]["reading_id"] == id
                && r["fields"]["trace_id"] == accepted["fields"]["trace_id"])
    );
    db.cleanup().await;
    sqlx::query(&format!("DROP SCHEMA {schema} CASCADE"))
        .execute(&admin)
        .await
        .unwrap();
    admin.close().await;
}
