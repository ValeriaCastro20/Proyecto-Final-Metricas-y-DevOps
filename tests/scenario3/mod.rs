//! Real PostgreSQL + HTTP + separate OS processor, run by the existing postgres CI job.
mod telemetry;
use super::support::*;
use axum::{body::Body, http::Request};
use chrono::{TimeZone, Utc};
use event_service::{
    MIGRATOR,
    scenario::{Period, store::Store},
};
use http_body_util::BodyExt;
use serde_json::{Value, json};
use std::{
    process::{Command, Stdio},
    time::{Duration, Instant},
};
use tower::ServiceExt;

/// Create a fictitious reading with deterministic measurements and generation time.
fn reading(device: &str, n: usize) -> Value {
    json!({"device_id":device,"event_id":format!("event-{n}"),
        "occurred_at":(Utc.with_ymd_and_hms(2040,1,1,12,0,0).unwrap()+chrono::Duration::seconds(n as i64)).to_rfc3339(),
        "temperature":20.0+(n%30) as f64,"humidity":40.0,"state":"running"})
}
/// Select the half-open interval containing only this test's generated fixture timestamps.
fn period() -> Period {
    serde_json::from_value(
        json!({"from":"2040-01-01T12:00:00Z","to":"2040-01-01T13:00:00Z","limit":1000}),
    )
    .unwrap()
}
/// Start a real, separately stoppable processor against the dedicated integration database.
fn worker(db: &Database, mode: &str) -> std::process::Child {
    Command::new(env!("CARGO_BIN_EXE_event-service"))
        .arg(mode)
        .env("DATABASE_URL", db.settings.database_url.as_ref().unwrap())
        .env("PROCESSOR_BATCH_SIZE", "1")
        .env("PROCESSOR_POLL_MS", "20")
        .env("WORKER_METRICS_ADDR", "127.0.0.1:0")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap()
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL pointing to dedicated PostgreSQL"]
/// Closing the shared pool makes readiness and ESC3 fail together, while liveness remains up.
async fn shared_pool_aligns_readiness_with_scenario_routes() {
    let db = Database::new().await;
    let repository = db.repository();
    let pool = repository.pool().unwrap().clone();
    let app = event_service::api::router(event_service::api::AppState {
        settings: std::sync::Arc::new(db.settings.clone()),
        service: event_service::service::EventService::new(std::sync::Arc::new(repository)),
        scenario: Some(Store { pool: pool.clone() }),
        metrics: metrics_exporter_prometheus::PrometheusBuilder::new()
            .build_recorder()
            .handle(),
    });
    assert_eq!(
        request(&app, "GET", "/health/ready", None, None).await.0,
        200
    );
    assert_eq!(
        request(&app, "GET", "/v1/devices", Some("test-analyst"), None)
            .await
            .0,
        200
    );
    pool.close().await;
    assert_eq!(
        request(&app, "GET", "/health/ready", None, None).await.0,
        503
    );
    assert_eq!(
        request(&app, "GET", "/v1/devices", Some("test-analyst"), None)
            .await
            .0,
        503
    );
    assert_eq!(
        request(&app, "GET", "/health/live", None, None).await.0,
        200
    );
    db.cleanup().await;
}

#[tokio::test]
#[ignore = "requires TEST_DATABASE_URL pointing to dedicated PostgreSQL"]
/// Verify official ESC3 acceptance, recovery, alerts and conservation with HTTP and real workers.
async fn esc3_acceptance_1000_duplicates_late_rejections_and_worker_recovery() {
    let db = Database::new().await;
    let app = db.app();
    let store = Store {
        pool: db.pool.clone(),
    };
    let id = &db.source;
    let device = json!({"id":id,"facility_id":"maintenance-test","limits":{"temperature_min":0,"temperature_max":30,"humidity_min":20,"humidity_max":80}});
    assert_eq!(
        request(
            &app,
            "POST",
            "/v1/devices",
            Some("test-analyst"),
            Some(device.clone())
        )
        .await
        .0,
        403
    );
    assert_eq!(
        request(
            &app,
            "POST",
            "/v1/devices",
            Some("scoped-a"),
            Some(device.clone())
        )
        .await
        .0,
        403
    );
    assert_eq!(
        request(
            &app,
            "POST",
            "/v1/devices",
            Some("test-producer"),
            Some(device.clone())
        )
        .await
        .0,
        201
    );
    assert_eq!(
        request(
            &app,
            "POST",
            "/v1/devices",
            Some("test-producer"),
            Some(device)
        )
        .await
        .0,
        409
    );
    assert_eq!(
        store.device(id).await.unwrap().facility_id,
        "maintenance-test"
    );
    assert_eq!(
        request(&app, "POST", "/v1/readings", None, Some(reading(id, 0)))
            .await
            .0,
        401
    );
    assert_eq!(
        request(
            &app,
            "POST",
            "/v1/readings",
            Some("scoped-a"),
            Some(reading(id, 0))
        )
        .await
        .0,
        403
    );
    // P3 functional: 1,000 unique valid readings with no worker running.
    let mut receipt_ids = Vec::new();
    for n in 0..1000 {
        let response = request(
            &app,
            "POST",
            "/v1/readings",
            Some("test-producer"),
            Some(reading(id, n)),
        )
        .await;
        assert_eq!(response.0, 202, "{n}: {}", response.1);
        receipt_ids.push(response.1["id"].as_str().unwrap().to_owned());
    }
    let before = store.counters(Some(id)).await.unwrap();
    assert_eq!(
        (
            before.received,
            before.accepted,
            before.pending,
            before.processed
        ),
        (1000, 1000, 1000, 0)
    );
    assert_eq!(store.aggregate(id, &period()).await.unwrap().count, 0);
    // Identified additional test: 50 duplicates (different content cannot overwrite), 50 late readings.
    for n in 0..50 {
        let mut duplicate = reading(id, n);
        duplicate["temperature"] = json!(149);
        assert_eq!(
            request(
                &app,
                "POST",
                "/v1/readings",
                Some("test-producer"),
                Some(duplicate)
            )
            .await
            .0,
            200
        );
        let mut late = reading(id, 49 - n);
        late["event_id"] = json!(format!("late-{n}"));
        assert_eq!(
            request(
                &app,
                "POST",
                "/v1/readings",
                Some("test-producer"),
                Some(late)
            )
            .await
            .0,
            202
        );
    }
    // Concurrent same natural key: one acceptance, all retransmissions refer to the same row.
    let mut tasks = Vec::new();
    for _ in 0..8 {
        let app = app.clone();
        let input = reading(id, 1100);
        tasks.push(tokio::spawn(async move {
            request(
                &app,
                "POST",
                "/v1/readings",
                Some("test-producer"),
                Some(input),
            )
            .await
        }));
    }
    let mut winners = 0;
    for task in tasks {
        let response = task.await.unwrap();
        assert!(response.0 == 200 || response.0 == 202);
        winners += i32::from(response.0 == 202);
    }
    assert_eq!(winners, 1);
    // Missing, range, unknown device, wrong state, absent timezone, unknown field, wrong type.
    let mut invalid = reading(id, 2000);
    invalid.as_object_mut().unwrap().remove("humidity");
    let mut range = reading(id, 2001);
    range["humidity"] = json!(101);
    let mut state = reading(id, 2002);
    state["state"] = json!("invalid");
    let mut timezone = reading(id, 2003);
    timezone["occurred_at"] = json!("2040-01-01T12:00:00");
    let mut extra = reading(id, 2004);
    extra["secret"] = json!("do-not-store-me");
    let mut wrong = reading(id, 2005);
    wrong["temperature"] = json!("hot");
    for bad in [invalid, range, state, timezone, extra, wrong] {
        let response = request(
            &app,
            "POST",
            "/v1/readings",
            Some("test-producer"),
            Some(bad),
        )
        .await;
        assert_eq!(response.0, 422);
        assert_eq!(response.1["outcome"], "rejected");
        assert!(!response.1.to_string().contains("do-not-store-me"));
        assert_eq!(
            request(
                &app,
                "GET",
                &format!("/v1/receipts/{}", response.1["id"].as_str().unwrap()),
                Some("test-analyst"),
                None
            )
            .await
            .0,
            200
        );
    }
    let unknown = request(
        &app,
        "POST",
        "/v1/readings",
        Some("test-producer"),
        Some(reading(&format!("missing-{id}"), 0)),
    )
    .await;
    assert_eq!(unknown.0, 422);
    assert_eq!(unknown.1["reason"], "unknown_device");
    let malformed = Request::builder()
        .method("POST")
        .uri("/v1/readings")
        .header("x-api-key", "test-producer")
        .header("content-type", "application/json")
        .body(Body::from("{bad-json"))
        .unwrap();
    let malformed = app.clone().oneshot(malformed).await.unwrap();
    assert_eq!(malformed.status(), 422);
    let malformed: Value =
        serde_json::from_slice(&malformed.into_body().collect().await.unwrap().to_bytes()).unwrap();
    assert_eq!(malformed["reason"], "invalid_format");
    let counts = store.counters(Some(id)).await.unwrap();
    assert_eq!(
        (
            counts.received,
            counts.validated,
            counts.accepted,
            counts.duplicates,
            counts.rejected
        ),
        (1114, 1108, 1051, 57, 6)
    );
    assert_eq!(counts.received, counts.validated + counts.rejected);
    assert_eq!(counts.validated, counts.accepted + counts.duplicates);
    // New pool and repeated migration preserve every acceptance before any processing.
    let fresh = db.repository();
    let restarted = Store {
        pool: fresh.pool().unwrap().clone(),
    };
    MIGRATOR.run(&restarted.pool).await.unwrap();
    assert_eq!(restarted.counters(Some(id)).await.unwrap().pending, 1051);
    for receipt in receipt_ids {
        assert!(restarted.receipt(receipt.parse().unwrap()).await.is_ok());
    }
    // Kill a real worker with pending work, continue intake, then restart with no new input.
    let mut process = worker(&db, "process");
    let deadline = Instant::now() + Duration::from_secs(15);
    while store.counters(Some(id)).await.unwrap().processed == 0 {
        assert!(Instant::now() < deadline, "worker did not start");
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    process.kill().unwrap();
    process.wait().unwrap();
    assert!(store.counters(Some(id)).await.unwrap().pending > 0);
    // Config change affects only future receptions, not already accepted work.
    let limits =
        json!({"temperature_min":-10,"temperature_max":100,"humidity_min":0,"humidity_max":100});
    assert_eq!(
        request(
            &app,
            "PUT",
            &format!("/v1/devices/{id}/limits"),
            Some("test-producer"),
            Some(limits)
        )
        .await
        .0,
        200
    );
    assert_eq!(
        request(
            &app,
            "POST",
            "/v1/readings",
            Some("test-producer"),
            Some(reading(id, 1200))
        )
        .await
        .0,
        202
    );
    let mut drain = Command::new(env!("CARGO_BIN_EXE_event-service"))
        .arg("drain")
        .env("DATABASE_URL", db.settings.database_url.as_ref().unwrap())
        .env("PROCESSOR_BATCH_SIZE", "1000")
        .env("PROCESSOR_POLL_MS", "1")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(15);
    loop {
        if let Some(status) = drain.try_wait().unwrap() {
            assert!(status.success());
            break;
        }
        if Instant::now() >= deadline {
            drain.kill().unwrap();
            drain.wait().unwrap();
            panic!("drain timed out");
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    let final_counts = store.counters(Some(id)).await.unwrap();
    assert_eq!(
        (
            final_counts.accepted,
            final_counts.processed,
            final_counts.pending
        ),
        (1052, 1052, 0)
    );
    assert_eq!(store.process(100).await.unwrap(), 0);
    let rows = store.readings(id, &period()).await.unwrap();
    assert_eq!(rows.len(), 1000);
    assert!(
        rows.windows(2)
            .all(|w| (w[0].occurred_at, w[0].id) <= (w[1].occurred_at, w[1].id))
    );
    let mut tail_period = period();
    tail_period.offset = 1000;
    let tail = store.readings(id, &tail_period).await.unwrap();
    assert_eq!(tail.len(), 52);
    let all_ids: std::collections::HashSet<_> = rows.iter().chain(&tail).map(|r| r.id).collect();
    assert_eq!(all_ids.len(), 1052);
    let stats = store.aggregate(id, &period()).await.unwrap();
    assert_eq!(stats.count, 1052);
    assert_eq!(
        (stats.temperature_min, stats.temperature_max),
        (Some(20.0), Some(49.0))
    );
    let sum: f64 = (0..1000)
        .chain((0..50).rev())
        .chain([1100, 1200])
        .map(|n| 20.0 + (n % 30) as f64)
        .sum();
    assert!((stats.temperature_avg.unwrap() - sum / 1052.0).abs() < 1e-10);
    let alerts = store.alerts(id, &period()).await.unwrap();
    assert!(!alerts.is_empty());
    assert!(
        alerts
            .iter()
            .all(|a| a.kind == "temperature_high" && a.threshold == 30.0)
    );
    assert!(!alerts.iter().any(|a| a.event_id == "event-1200"));
    let end: Period =
        serde_json::from_value(json!({"from":"2040-01-01T12:00:00Z","to":"2040-01-01T12:00:01Z"}))
            .unwrap();
    assert_eq!(store.aggregate(id, &end).await.unwrap().count, 2); // first + late, end exclusive
    // Same event_id on a second device is a different event.
    let second = format!("other-{id}");
    store.register(&serde_json::from_value(json!({"id":second,"facility_id":"other-site","limits":{"temperature_min":0,"temperature_max":30,"humidity_min":0,"humidity_max":100}})).unwrap()).await.unwrap();
    assert_eq!(
        store
            .receive(&serde_json::from_value(reading(&second, 0)).unwrap())
            .await
            .unwrap()
            .outcome,
        "accepted"
    );
    let second_limits = serde_json::from_value(
        json!({"temperature_min":0,"temperature_max":30,"humidity_min":20,"humidity_max":80}),
    )
    .unwrap();
    store.limits(&second, &second_limits).await.unwrap();
    for (n, temperature, humidity) in [(1, -10, 10), (2, 40, 90), (3, 30, 80)] {
        let mut input = reading(&second, n);
        input["temperature"] = json!(temperature);
        input["humidity"] = json!(humidity);
        assert_eq!(
            store
                .receive(&serde_json::from_value(input).unwrap())
                .await
                .unwrap()
                .outcome,
            "accepted"
        );
    }
    // Independent workers divide locked rows; retries after completion produce no effects.
    let (first, second_worker) = tokio::join!(store.process(2), store.process(2));
    assert_eq!(first.unwrap() + second_worker.unwrap(), 4);
    assert_eq!(store.process(100).await.unwrap(), 0);
    let alerts = store.alerts(&second, &period()).await.unwrap();
    assert_eq!(alerts.len(), 4);
    let kinds: std::collections::HashSet<_> = alerts.iter().map(|a| a.kind.as_str()).collect();
    assert_eq!(
        kinds,
        std::collections::HashSet::from([
            "temperature_low",
            "temperature_high",
            "humidity_low",
            "humidity_high"
        ])
    );
    assert!(alerts.iter().all(|a| a.event_id != "event-3"));
    // Scoped cleanup, never truncate or delete other tests' records.
    for device in [id.as_str(), second.as_str()] {
        sqlx::query("DELETE FROM business_alerts WHERE reading_id IN (SELECT id FROM readings WHERE device_id=$1)").bind(device).execute(&db.pool).await.unwrap();
        sqlx::query("DELETE FROM reception_receipts WHERE device_id=$1")
            .bind(device)
            .execute(&db.pool)
            .await
            .unwrap();
        sqlx::query("DELETE FROM readings WHERE device_id=$1")
            .bind(device)
            .execute(&db.pool)
            .await
            .unwrap();
        sqlx::query("DELETE FROM devices WHERE id=$1")
            .bind(device)
            .execute(&db.pool)
            .await
            .unwrap();
    }
    sqlx::query("DELETE FROM reception_receipts WHERE id=$1 OR id=$2")
        .bind(
            unknown.1["id"]
                .as_str()
                .unwrap()
                .parse::<uuid::Uuid>()
                .unwrap(),
        )
        .bind(
            malformed["id"]
                .as_str()
                .unwrap()
                .parse::<uuid::Uuid>()
                .unwrap(),
        )
        .execute(&db.pool)
        .await
        .unwrap();
    db.cleanup().await;
}
