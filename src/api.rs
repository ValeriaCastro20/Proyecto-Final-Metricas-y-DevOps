//! Axum HTTP adapter, request correlation and generated OpenAPI documentation.
use crate::{
    auth::{self, Principal},
    config::Settings,
    domain::*,
    error::{Error, ErrorEnvelope},
    service::EventService,
};
use axum::{
    Json, Router,
    extract::{DefaultBodyLimit, FromRequestParts, MatchedPath, Path, Query, Request, State},
    http::{HeaderValue, StatusCode, request::Parts},
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{get, post},
};
use serde::Serialize;
use std::sync::Arc;
use utoipa::{
    Modify, OpenApi, ToSchema,
    openapi::security::{ApiKey, ApiKeyValue, SecurityScheme},
};
use uuid::Uuid;

#[derive(Clone)]
pub struct AppState {
    pub settings: Arc<Settings>,
    pub service: EventService,
    /// ESC3 shares the service's pool, including the connection tested by readiness.
    pub scenario: Option<crate::scenario::store::Store>,
}

impl FromRequestParts<AppState> for Principal {
    type Rejection = Error;
    /// Authenticate exactly one API-key header before body extraction or repository access.
    async fn from_request_parts(parts: &mut Parts, state: &AppState) -> Result<Self, Error> {
        let mut keys = parts.headers.get_all("x-api-key").iter();
        let key = keys.next().and_then(|key| key.to_str().ok());
        if keys.next().is_some() {
            return Err(Error::Unauthenticated);
        }
        auth::authenticate(key, &state.settings)
    }
}

/// The outer correlation layer also normalizes extraction, routing and panic errors.
pub fn router(state: AppState) -> Router {
    let scenario = crate::scenario::http::router(state.settings.clone(), state.scenario.clone());

    // MET-03: Expose Prometheus metrics endpoint
    use metrics_exporter_prometheus::PrometheusHandle;
    let recorder_handle = metrics_exporter_prometheus::PrometheusBuilder::new()
        .build_recorder()
        .handle();

    Router::new()
        .route("/health/live", get(live))
        .route("/health/ready", get(ready))
        .route("/metrics", get(move || std::future::ready(recorder_handle.render())))
        .route("/v1/events", post(create_event).get(list_events))
        .route("/v1/events/batch", post(create_batch))
        .route("/v1/events/{id}", get(get_event))
        .route("/v1/analysis/counts", get(counts))
        .route("/v1/analysis/timeseries", get(timeseries))
        .route("/v1/analysis/summary", get(summary))
        .route("/openapi.json", get(|| async { Json(ApiDoc::openapi()) }))
        .route(
            "/docs",
            get(|| async { Html(include_str!("../docs/api.html")) }),
        )
        .fallback(|| async { Error::NotFound })
        .with_state(state)
        .merge(scenario)
        .layer(DefaultBodyLimit::max(4 * 1024 * 1024))
        .layer(tower_http::catch_panic::CatchPanicLayer::custom(|_| {
            Error::Internal.into_response()
        }))
        .layer(middleware::from_fn(correlate))
}

/// Accept only bounded printable identifier characters safe for headers and structured logs.
fn valid_request_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value.as_bytes()[0].is_ascii_alphanumeric()
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'.' | b'_' | b'-'))
}

/// Assign a validated request ID, sanitize failures and log only the matched route template.
/// Preserve method-routing Allow metadata while preventing raw extractor or panic responses.
async fn correlate(request: Request, next: Next) -> Response {
    let mut values = request.headers().get_all("x-request-id").iter();
    let supplied = values
        .next()
        .and_then(|v| v.to_str().ok())
        .filter(|v| valid_request_id(v));
    let request_id = if values.next().is_none() {
        supplied.map(str::to_owned)
    } else {
        None
    }
    .unwrap_or_else(|| Uuid::new_v4().to_string());
    let route = request
        .extensions()
        .get::<MatchedPath>()
        .map(|p| p.as_str().to_owned())
        .unwrap_or_else(|| "<unmatched>".to_owned());

    // MET-04: Start a trace span for the HTTP request
    let span = tracing::info_span!("http_request", %request_id, %route, status = tracing::field::Empty);
    let _enter = span.enter();

    let start = std::time::Instant::now();
    let mut response = next.run(request).await;
    let latency = start.elapsed().as_secs_f64();

    // MET-03: Record HTTP latency and count
    metrics::histogram!("http_request_duration_seconds", latency, "route" => route.clone(), "status" => response.status().as_u16().to_string());
    metrics::counter!("http_requests_total", 1, "route" => route.clone(), "status" => response.status().as_u16().to_string());

    span.record("status", &response.status().as_u16());

    if (response.status().is_client_error() || response.status().is_server_error())
        && response
            .extensions()
            .get::<crate::scenario::http::RecordedRejection>()
            .is_none()
    {
        let error = response
            .extensions()
            .get::<Error>()
            .copied()
            .unwrap_or_else(|| {
                if response.status() == StatusCode::METHOD_NOT_ALLOWED {
                    Error::MethodNotAllowed
                } else if response.status().is_client_error() {
                    Error::InvalidInput
                } else {
                    Error::Internal
                }
            });
        let (status, code, _) = error.details();
        // No user-controlled URL, headers, payload or underlying error is logged.
        if status.is_server_error() {
            tracing::error!(%request_id, %route, %status, code, "request failed");
        } else {
            tracing::warn!(%request_id, %route, %status, code, "request failed");
        }
        let allow = response.headers().get(axum::http::header::ALLOW).cloned();
        response = error.response(request_id.clone());
        if let Some(allow) = allow {
            response
                .headers_mut()
                .insert(axum::http::header::ALLOW, allow);
        }
    }
    if let Ok(value) = HeaderValue::from_str(&request_id) {
        response.headers_mut().insert("x-request-id", value);
    }
    response
}

#[derive(Serialize, ToSchema)]
struct Health {
    status: &'static str,
}

#[utoipa::path(get, path = "/health/live", responses((status = 200, body = Health)))]
/// Report process liveness without requiring storage or valid protected-route credentials.
async fn live() -> Json<Health> {
    Json(Health { status: "alive" })
}
#[utoipa::path(get, path = "/health/ready", responses((status = 200, body = Health), (status = 503, body = ErrorEnvelope)))]
/// Report basic database connectivity; traffic removal requires an external readiness integration.
async fn ready(State(state): State<AppState>) -> Result<Json<Health>, Error> {
    state.service.ready().await?;
    Ok(Json(Health { status: "ready" }))
}

#[utoipa::path(post, path = "/v1/events", request_body = EventCreate, security(("api_key" = [])), responses((status = 201, body = Event), (status = 409, body = ErrorEnvelope), (status = 422, body = ErrorEnvelope)))]
/// Validate and persist one producer event; return its confirmed representation after COMMIT.
async fn create_event(
    State(state): State<AppState>,
    principal: Principal,
    body: Result<Json<EventCreate>, axum::extract::rejection::JsonRejection>,
) -> Result<(StatusCode, Json<Event>), Error> {
    let Json(event) = body.map_err(|_| Error::InvalidInput)?;
    let result = state
        .service
        .create(
            &principal,
            EventBatchCreate {
                events: vec![event],
            },
        )
        .await?;
    let event = result.events.into_iter().next().ok_or(Error::Internal)?;
    Ok((StatusCode::CREATED, Json(event)))
}
#[utoipa::path(post, path = "/v1/events/batch", request_body = EventBatchCreate, security(("api_key" = [])), responses((status = 201, body = BatchResponse), (status = 409, body = ErrorEnvelope), (status = 422, body = ErrorEnvelope)))]
/// Persist a producer batch atomically, rejecting any duplicate or unauthorized source.
async fn create_batch(
    State(state): State<AppState>,
    principal: Principal,
    body: Result<Json<EventBatchCreate>, axum::extract::rejection::JsonRejection>,
) -> Result<(StatusCode, Json<BatchResponse>), Error> {
    let Json(batch) = body.map_err(|_| Error::InvalidInput)?;
    Ok((
        StatusCode::CREATED,
        Json(state.service.create(&principal, batch).await?),
    ))
}
#[utoipa::path(get, path = "/v1/events/{id}", params(("id" = Uuid, Path)), security(("api_key" = [])), responses((status = 200, body = Event), (status = 404, body = ErrorEnvelope)))]
/// Return one event to an analyst; malformed UUIDs and missing resources remain distinct failures.
async fn get_event(
    State(state): State<AppState>,
    principal: Principal,
    id: Result<Path<Uuid>, axum::extract::rejection::PathRejection>,
) -> Result<Json<Event>, Error> {
    let Path(id) = id.map_err(|_| Error::InvalidInput)?;
    Ok(Json(state.service.get(&principal, id).await?))
}
#[utoipa::path(get, path = "/v1/events", params(ListQuery), security(("api_key" = [])), responses((status = 200, body = ListResponse), (status = 422, body = ErrorEnvelope)))]
/// Return an analyst page including total, effective interval and applied source/type filters.
async fn list_events(
    State(state): State<AppState>,
    principal: Principal,
    query: Result<Query<ListQuery>, axum::extract::rejection::QueryRejection>,
) -> Result<Json<ListResponse>, Error> {
    let Query(query) = query.map_err(|_| Error::InvalidInput)?;
    Ok(Json(state.service.list(&principal, query).await?))
}
#[utoipa::path(get, path = "/v1/analysis/counts", params(CountsQuery), security(("api_key" = [])), responses((status = 200, body = CountsResponse), (status = 422, body = ErrorEnvelope)))]
/// Return analyst counts grouped by an allow-listed dimension over a half-open UTC interval.
async fn counts(
    State(state): State<AppState>,
    principal: Principal,
    query: Result<Query<CountsQuery>, axum::extract::rejection::QueryRejection>,
) -> Result<Json<CountsResponse>, Error> {
    let Query(query) = query.map_err(|_| Error::InvalidInput)?;
    Ok(Json(state.service.counts(&principal, query).await?))
}
#[utoipa::path(get, path = "/v1/analysis/timeseries", params(TimeseriesQuery), security(("api_key" = [])), responses((status = 200, body = TimeseriesResponse), (status = 422, body = ErrorEnvelope)))]
/// Return nonempty analyst time buckets at the validated minute, hour or day resolution.
async fn timeseries(
    State(state): State<AppState>,
    principal: Principal,
    query: Result<Query<TimeseriesQuery>, axum::extract::rejection::QueryRejection>,
) -> Result<Json<TimeseriesResponse>, Error> {
    let Query(query) = query.map_err(|_| Error::InvalidInput)?;
    Ok(Json(state.service.timeseries(&principal, query).await?))
}
#[utoipa::path(get, path = "/v1/analysis/summary", params(SummaryQuery), security(("api_key" = [])), responses((status = 200, body = SummaryResponse), (status = 422, body = ErrorEnvelope)))]
/// Return coherent analyst totals and numeric statistics without exposing underlying SQL errors.
async fn summary(
    State(state): State<AppState>,
    principal: Principal,
    query: Result<Query<SummaryQuery>, axum::extract::rejection::QueryRejection>,
) -> Result<Json<SummaryResponse>, Error> {
    let Query(query) = query.map_err(|_| Error::InvalidInput)?;
    Ok(Json(state.service.summary(&principal, query).await?))
}

struct Security;
impl Modify for Security {
    /// Declare API-key authentication and the shared public failure contract for protected paths.
    fn modify(&self, api: &mut utoipa::openapi::OpenApi) {
        api.merge(crate::scenario::http::ScenarioDoc::openapi());
        if let Some(components) = api.components.as_mut() {
            components.add_security_scheme(
                "api_key",
                SecurityScheme::ApiKey(ApiKey::Header(ApiKeyValue::new("X-API-Key"))),
            );
        }
        // Every protected endpoint shares these safe error contracts.
        for (path, item) in &mut api.paths.paths {
            if path.starts_with("/v1/") {
                for operation in [&mut item.get, &mut item.post, &mut item.put]
                    .into_iter()
                    .flatten()
                {
                    for status in ["401", "403", "422", "503", "500"] {
                        // ESC3 intake has its own durable rejection receipt for 422.
                        if operation.responses.responses.contains_key(status) {
                            continue;
                        }
                        operation.responses.responses.insert(
                            status.to_owned(),
                            utoipa::openapi::RefOr::T(
                                utoipa::openapi::ResponseBuilder::new()
                                    .description("See ErrorEnvelope and docs/api.md")
                                    .content(
                                        "application/json",
                                        utoipa::openapi::Content::new(Some(
                                            utoipa::openapi::Ref::from_schema_name("ErrorEnvelope"),
                                        )),
                                    )
                                    .build(),
                            ),
                        );
                    }
                }
            }
        }
    }
}
#[derive(OpenApi)]
#[openapi(paths(live, ready, create_event, create_batch, get_event, list_events, counts, timeseries, summary), modifiers(&Security), info(title = "Event Service", description = "Ingesta y análisis transaccional de eventos. Ventanas UTC [from, to)."))]
pub struct ApiDoc;
