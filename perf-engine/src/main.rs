use axum::{
    routing::{get, post},
    Router,
};
use std::sync::Arc;
use tower_http::{
    compression::CompressionLayer,
    cors::CorsLayer,
    timeout::TimeoutLayer,
    trace::TraceLayer,
};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

mod config;
mod crypto;
mod db;
mod error;
mod handler;
mod model;
mod state;

use crate::config::AppConfig;
use crate::crypto::CryptoService;
use crate::db::Database;
use crate::state::AppState;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialize tracing
    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "info".into()),
        ))
        .with(tracing_subscriber::fmt::layer())
        .init();

    let config = AppConfig::load();
    let db = Database::new(&config).await?;
    let crypto = CryptoService::new(&config)?;

    let app_state = Arc::new(AppState { db, crypto, config: config.clone() });

    let app = Router::new()
        .route("/health", get(handler::health::health_check))
        .route("/auth/register", post(handler::auth::register))
        .route("/auth/login", post(handler::auth::login))
        
        // Integrations
        .route("/api/users/:user_id/integrations", post(handler::integrations::create_integration))
        .route("/api/users/:user_id/integrations", get(handler::integrations::list_integrations))
        .route("/api/users/:user_id/integrations/:id", get(handler::integrations::get_integration))
        .route("/api/users/:user_id/integrations/:id", axum::routing::delete(handler::integrations::delete_integration))
        
        // Conversations
        .route("/api/users/:user_id/conversations", post(handler::conversations::create_conversation))
        .route("/api/users/:user_id/conversations", get(handler::conversations::list_conversations))
        .route("/api/users/:user_id/conversations/:id", axum::routing::delete(handler::conversations::delete_conversation))
        .route("/api/users/:user_id/conversations/:id/messages", post(handler::conversations::add_message))
        .route("/api/users/:user_id/conversations/:id/messages", get(handler::conversations::list_conversations))
        
        // Settings
        .route("/api/users/:user_id/settings", get(handler::settings::get_settings))
        .route("/api/users/:user_id/settings/gemini-key", post(handler::settings::update_settings))
        .route("/api/users/:user_id/settings/gemini-key", get(handler::settings::get_gemini_key))

        .layer(TraceLayer::new_for_http())
        .layer(CorsLayer::permissive())
        .layer(CompressionLayer::new())
        .layer(TimeoutLayer::new(std::time::Duration::from_secs(30)))
        .with_state(app_state);

    let addr = format!("0.0.0.0:{}", config.port);
    tracing::info!("Listening on {}", addr);
    
    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
