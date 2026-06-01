use std::sync::Arc;
use crate::crypto::CryptoService;
use crate::db::Database;
use crate::config::AppConfig;

pub struct AppState {
    pub db: Database,
    pub crypto: CryptoService,
    pub config: AppConfig,
}

pub type SharedState = Arc<AppState>;
