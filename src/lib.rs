//! Modular event service: HTTP adapters → application service → repository port.
//! PostgreSQL is the consistency authority; no successful write precedes COMMIT.
pub mod api;
pub mod auth;
pub mod config;
pub mod domain;
pub mod error;
pub mod postgres;
pub mod repository;
pub mod scenario;
pub mod service;
pub mod telemetry;

/// Versioned, embedded migrations shared by the CLI and integration tests.
pub static MIGRATOR: sqlx::migrate::Migrator = sqlx::migrate!("./migrations");
