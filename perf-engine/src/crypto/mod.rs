use argon2::{
    password_hash::{rand_core::OsRng, PasswordHash, PasswordHasher, PasswordVerifier, SaltString},
    Argon2,
};
use fernet::Fernet;
use jsonwebtoken::{encode, EncodingKey, Header};
use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::config::AppConfig;
use crate::error::AppError;

#[derive(Clone)]
pub struct CryptoService {
    fernet: Fernet,
    jwt_secret: String,
}

#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub email: String,
    pub exp: usize,
}

impl CryptoService {
    pub fn new(config: &AppConfig) -> Result<Self, AppError> {
        let fernet = Fernet::new(&config.encryption_key).ok_or_else(|| {
            AppError::CryptoError
        })?;
        Ok(Self {
            fernet,
            jwt_secret: config.jwt_secret.clone(),
        })
    }

    pub fn hash_password(&self, password: &str) -> Result<String, AppError> {
        let salt = SaltString::generate(&mut OsRng);
        let argon2 = Argon2::default();
        let password_hash = argon2
            .hash_password(password.as_bytes(), &salt)
            .map_err(|_| AppError::CryptoError)?
            .to_string();
        Ok(password_hash)
    }

    pub fn verify_password(&self, password: &str, password_hash: &str) -> Result<bool, AppError> {
        let parsed_hash = PasswordHash::new(password_hash).map_err(|_| AppError::CryptoError)?;
        let argon2 = Argon2::default();
        Ok(argon2
            .verify_password(password.as_bytes(), &parsed_hash)
            .is_ok())
    }

    pub fn encrypt(&self, data: &str) -> Result<String, AppError> {
        Ok(self.fernet.encrypt(data.as_bytes()))
    }

    pub fn decrypt(&self, encrypted_data: &str) -> Result<String, AppError> {
        let decrypted_bytes = self.fernet.decrypt(encrypted_data).map_err(|_| AppError::CryptoError)?;
        String::from_utf8(decrypted_bytes).map_err(|_| AppError::CryptoError)
    }

    pub fn create_jwt(&self, user_id: &str, email: &str) -> Result<String, AppError> {
        let expiration = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs() as usize
            + 24 * 3600; // 24 hours

        let claims = Claims {
            sub: user_id.to_string(),
            email: email.to_string(),
            exp: expiration,
        };

        encode(
            &Header::default(),
            &claims,
            &EncodingKey::from_secret(self.jwt_secret.as_bytes()),
        )
        .map_err(|_| AppError::CryptoError)
    }
}
