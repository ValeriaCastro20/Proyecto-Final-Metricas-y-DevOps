//! PostgreSQL inbox: a reception commits before 202; processing and alerts commit together.
use super::*;
use sqlx::PgPool;
use tracing_opentelemetry::OpenTelemetrySpanExt;

#[derive(Clone)]
pub struct Store {
    pub pool: PgPool,
}
/// Hide SQL, connection strings and submitted values behind a safe dependency category.
fn db(_: sqlx::Error) -> Error {
    Error::Unavailable
}
impl Store {
    /// Insert one validated stable device, mapping uniqueness conflicts without overwriting it.
    pub async fn register(&self, device: &DeviceCreate) -> Result<Device, Error> {
        device.validate()?;
        let limits = &device.limits;
        sqlx::query_as("INSERT INTO devices(id, facility_id, temperature_min, temperature_max, humidity_min, humidity_max) VALUES ($1,$2,$3,$4,$5,$6) RETURNING *")
            .bind(&device.id).bind(&device.facility_id).bind(limits.temperature_min).bind(limits.temperature_max)
            .bind(limits.humidity_min).bind(limits.humidity_max).fetch_one(&self.pool).await.map_err(|error| {
                if error.as_database_error().is_some_and(|e| e.code().as_deref() == Some("23505")) { Error::Duplicate } else { db(error) }
            })
    }
    /// Read a device's installation and current limits, distinguishing absence from DB failure.
    pub async fn device(&self, id: &str) -> Result<Device, Error> {
        sqlx::query_as("SELECT * FROM devices WHERE id=$1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(db)?
            .ok_or(Error::NotFound)
    }
    /// Return a validated bounded device page in stable identifier order.
    pub async fn devices(&self, page: &Page) -> Result<Vec<Device>, Error> {
        page.validate()?;
        sqlx::query_as("SELECT * FROM devices WHERE ($1::text IS NULL OR id=$1) ORDER BY id LIMIT $2 OFFSET $3")
            .bind(&page.device_id).bind(page.limit).bind(page.offset).fetch_all(&self.pool).await.map_err(db)
    }
    /// Validate and replace current limits; accepted readings keep their own snapshots.
    pub async fn limits(&self, id: &str, limits: &Limits) -> Result<Device, Error> {
        limits.validate()?;
        sqlx::query_as("UPDATE devices SET temperature_min=$2, temperature_max=$3, humidity_min=$4, humidity_max=$5 WHERE id=$1 RETURNING *")
            .bind(id).bind(limits.temperature_min).bind(limits.temperature_max).bind(limits.humidity_min).bind(limits.humidity_max)
            .fetch_optional(&self.pool).await.map_err(db)?.ok_or(Error::NotFound)
    }
    /// Persist only a safe reason, never the malformed body or supplied credentials.
    pub async fn reject(&self, device_id: Option<&str>, reason: &str) -> Result<Receipt, Error> {
        let receipt = Receipt {
            id: Uuid::new_v4(),
            reading_id: None,
            outcome: "rejected".into(),
            reason: Some(reason.into()),
        };
        sqlx::query(
            "INSERT INTO reception_receipts(id,device_id,outcome,reason) VALUES ($1,$2,$3,$4)",
        )
        .bind(receipt.id)
        .bind(device_id)
        .bind(&receipt.outcome)
        .bind(reason)
        .execute(&self.pool)
        .await
        .map_err(db)?;
        metrics::counter!("esc3_events_received_total", "outcome" => receipt.outcome.clone())
            .increment(1);
        Ok(receipt)
    }
    /// Uniqueness arbitrates concurrent retries. Limits are snapshotted at reception.
    pub async fn receive(&self, event: &ReadingCreate) -> Result<Receipt, Error> {
        if event.validate().is_err() {
            return self
                .reject(
                    identifier(&event.device_id).then_some(event.device_id.as_str()),
                    "invalid_fields",
                )
                .await;
        }
        let mut tx = self.pool.begin().await.map_err(db)?;
        // Lock the device row so a concurrent limit change has a defined before/after order.
        let device: Option<Device> = sqlx::query_as("SELECT * FROM devices WHERE id=$1 FOR SHARE")
            .bind(&event.device_id)
            .fetch_optional(&mut *tx)
            .await
            .map_err(db)?;
        let Some(device) = device else {
            tx.rollback().await.map_err(db)?;
            return self.reject(Some(&event.device_id), "unknown_device").await;
        };
        let id = Uuid::new_v4();
        let inserted: Option<Uuid> = sqlx::query_scalar("INSERT INTO readings(id,device_id,event_id,occurred_at,temperature,humidity,state,temperature_min,temperature_max,humidity_min,humidity_max,traceparent) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) ON CONFLICT(device_id,event_id) DO NOTHING RETURNING id")
            .bind(id).bind(&event.device_id).bind(&event.event_id).bind(event.occurred_at)
            .bind(event.temperature).bind(event.humidity).bind(&event.state)
            .bind(device.temperature_min).bind(device.temperature_max).bind(device.humidity_min).bind(device.humidity_max)
            .bind(crate::telemetry::current_traceparent())
            .fetch_optional(&mut *tx).await.map_err(db)?;
        let (reading_id, outcome) = match inserted {
            Some(id) => (id, "accepted"),
            None => (
                sqlx::query_scalar("SELECT id FROM readings WHERE device_id=$1 AND event_id=$2")
                    .bind(&event.device_id)
                    .bind(&event.event_id)
                    .fetch_one(&mut *tx)
                    .await
                    .map_err(db)?,
                "duplicate",
            ),
        };
        let receipt = Receipt {
            id: Uuid::new_v4(),
            reading_id: Some(reading_id),
            outcome: outcome.into(),
            reason: None,
        };
        sqlx::query(
            "INSERT INTO reception_receipts(id,device_id,reading_id,outcome) VALUES($1,$2,$3,$4)",
        )
        .bind(receipt.id)
        .bind(&event.device_id)
        .bind(reading_id)
        .bind(outcome)
        .execute(&mut *tx)
        .await
        .map_err(db)?;
        tx.commit().await.map_err(db)?;
        metrics::counter!("esc3_events_received_total", "outcome" => receipt.outcome.clone())
            .increment(1);
        Ok(receipt)
    }
    /// Retrieve safe durable reception metadata by its verifiable UUID.
    pub async fn receipt(&self, id: Uuid) -> Result<serde_json::Value, Error> {
        sqlx::query_scalar("SELECT to_jsonb(r) FROM reception_receipts r WHERE id=$1")
            .bind(id)
            .fetch_optional(&self.pool)
            .await
            .map_err(db)?
            .ok_or(Error::NotFound)
    }
    /// One SQL statement = one MVCC snapshot, even with concurrent intake and processing.
    pub async fn counters(&self, device: Option<&str>) -> Result<Counters, Error> {
        sqlx::query_as("WITH r AS (SELECT count(*) AS received, count(*) FILTER (WHERE outcome != 'rejected') AS validated, count(*) FILTER (WHERE outcome='accepted') AS accepted, count(*) FILTER (WHERE outcome='duplicate') AS duplicates, count(*) FILTER (WHERE outcome='rejected') AS rejected FROM reception_receipts WHERE ($1::text IS NULL OR device_id=$1)), p AS (SELECT count(*) FILTER (WHERE processed_at IS NOT NULL) AS processed, count(*) FILTER (WHERE processed_at IS NULL) AS pending FROM readings WHERE ($1::text IS NULL OR device_id=$1)) SELECT * FROM r CROSS JOIN p")
            .bind(device).fetch_one(&self.pool).await.map_err(db)
    }
    /// Count only pending readings, without scanning the reception ledger.
    pub async fn pending(&self) -> Result<i64, Error> {
        sqlx::query_scalar("SELECT count(*) FROM readings WHERE processed_at IS NULL")
            .fetch_one(&self.pool)
            .await
            .map_err(db)
    }
    /// List accepted work by generation in [from,to), including unprocessed readings.
    pub async fn readings(&self, device: &str, period: &Period) -> Result<Vec<Reading>, Error> {
        period.validate()?;
        sqlx::query_as("SELECT * FROM readings WHERE device_id=$1 AND occurred_at >= $2 AND occurred_at < $3 ORDER BY occurred_at,id LIMIT $4 OFFSET $5")
            .bind(device).bind(period.from).bind(period.to).bind(period.limit).bind(period.offset).fetch_all(&self.pool).await.map_err(db)
    }
    /// Compute both numeric summaries over processed unique readings, not arrival order.
    pub async fn aggregate(&self, device: &str, period: &Period) -> Result<Aggregate, Error> {
        period.validate()?;
        sqlx::query_as("SELECT count(*) AS count, min(temperature) AS temperature_min, max(temperature) AS temperature_max, avg(temperature) AS temperature_avg, min(humidity) AS humidity_min, max(humidity) AS humidity_max, avg(humidity) AS humidity_avg FROM readings WHERE device_id=$1 AND occurred_at >= $2 AND occurred_at < $3 AND processed_at IS NOT NULL")
            .bind(device).bind(period.from).bind(period.to).fetch_one(&self.pool).await.map_err(db)
    }
    /// Read business alerts in deterministic order using their reading's generation interval.
    pub async fn alerts(&self, device: &str, period: &Period) -> Result<Vec<Alert>, Error> {
        period.validate()?;
        sqlx::query_as("SELECT a.*, r.device_id, r.event_id, r.occurred_at FROM business_alerts a JOIN readings r ON r.id=a.reading_id WHERE r.device_id=$1 AND r.occurred_at >= $2 AND r.occurred_at < $3 ORDER BY r.occurred_at,r.id,a.kind LIMIT $4 OFFSET $5")
            .bind(device).bind(period.from).bind(period.to).bind(period.limit).bind(period.offset).fetch_all(&self.pool).await.map_err(db)
    }
    /// Page the rejection ledger without exposing raw inputs or internal failures.
    pub async fn rejections(&self, page: &Page) -> Result<Vec<serde_json::Value>, Error> {
        page.validate()?;
        sqlx::query_scalar("SELECT to_jsonb(r) FROM reception_receipts r WHERE outcome='rejected' AND ($1::text IS NULL OR device_id=$1) ORDER BY received_at,id LIMIT $2 OFFSET $3")
            .bind(&page.device_id).bind(page.limit).bind(page.offset).fetch_all(&self.pool).await.map_err(db)
    }
    /// Crash-safe batch: locks, alerts and processed marker share one transaction.
    /// A killed worker rolls back; SKIP LOCKED permits independent worker processes.
    pub async fn process(&self, batch_size: i64) -> Result<u64, Error> {
        if !(1..=1000).contains(&batch_size) {
            return Err(Error::InvalidInput);
        }
        let start = std::time::Instant::now();
        let mut tx = self.pool.begin().await.map_err(db)?;

        let rows: Vec<(Uuid, Option<String>)> = sqlx::query_as("SELECT id,traceparent FROM readings WHERE processed_at IS NULL ORDER BY received_at,id LIMIT $1 FOR UPDATE SKIP LOCKED")
            .bind(batch_size).fetch_all(&mut *tx).await.map_err(db)?;
        let ids: Vec<Uuid> = rows.iter().map(|(id, _)| *id).collect();
        let mut processing_spans = Vec::with_capacity(rows.len());
        for (id, traceparent) in rows {
            let span = tracing::info_span!("process_reading", component = "worker", reading_id = %id, batch_size = ids.len(), otel.kind = "consumer", otel.status_code = tracing::field::Empty);
            span.set_parent(crate::telemetry::parent(traceparent.as_deref()));
            processing_spans.push(span);
        }
        // All reading spans cover the same atomic batch. Keep SQL round trips
        // constant instead of adding two sequential statements per reading.
        let committed: Result<u64, Error> = async {
            sqlx::query("INSERT INTO business_alerts(id,reading_id,kind,value,threshold) SELECT gen_random_uuid(),r.id,v.kind,v.value,v.threshold FROM readings r CROSS JOIN LATERAL (VALUES ('temperature_low',temperature,temperature_min,temperature < temperature_min), ('temperature_high',temperature,temperature_max,temperature > temperature_max), ('humidity_low',humidity,humidity_min,humidity < humidity_min), ('humidity_high',humidity,humidity_max,humidity > humidity_max)) AS v(kind,value,threshold,exceeded) WHERE r.id=ANY($1) AND v.exceeded ON CONFLICT(reading_id,kind) DO NOTHING")
                .bind(&ids).execute(&mut *tx).await.map_err(db)?;
            let changed = sqlx::query("UPDATE readings SET processed_at=clock_timestamp() WHERE id=ANY($1)")
                .bind(&ids).execute(&mut *tx).await.map_err(db)?.rows_affected();
            tx.commit().await.map_err(db)?;
            Ok(changed)
        }.await;
        for span in &processing_spans {
            span.record(
                "otel.status_code",
                if committed.is_ok() { "OK" } else { "ERROR" },
            );
        }
        drop(processing_spans);
        let changed = committed?;

        let duration = start.elapsed().as_secs_f64();

        // Empty polls do not represent processed batches or latency observations.
        if changed > 0 {
            tracing::info!(
                batch_size,
                processed = changed,
                duration_s = duration,
                "batch processed"
            );
            metrics::histogram!("esc3_processor_duration_seconds").record(duration);
        }
        metrics::counter!("esc3_events_processed_total").increment(changed);

        Ok(changed)
    }
}
