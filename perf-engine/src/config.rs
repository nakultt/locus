use dotenvy::dotenv;
use std::env;

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub mongodb_uri: String,
    pub mongodb_db: String,
    pub encryption_key: String,
    pub jwt_secret: String,
    pub port: u16,
}

impl AppConfig {
    pub fn load() -> Self {
        dotenv().ok(); // Load .env if it exists

        Self {
            mongodb_uri: env::var("MONGODB_URI").expect("MONGODB_URI must be set"),
            mongodb_db: env::var("MONGODB_DB").unwrap_or_else(|_| "locus".to_string()),
            encryption_key: env::var("ENCRYPTION_KEY").expect("ENCRYPTION_KEY must be set"),
            jwt_secret: env::var("JWT_SECRET").expect("JWT_SECRET must be set"),
            port: env::var("PORT")
                .unwrap_or_else(|_| "8081".to_string())
                .parse()
                .expect("PORT must be a number"),
        }
    }
}
