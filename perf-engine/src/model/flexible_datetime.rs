use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serializer};
use bson::Bson;

pub fn serialize<S>(date: &DateTime<Utc>, serializer: S) -> Result<S::Ok, S::Error>
where
    S: Serializer,
{
    // Serialize as RFC3339 string
    serializer.serialize_str(&date.to_rfc3339())
}

pub fn deserialize<'de, D>(deserializer: D) -> Result<DateTime<Utc>, D::Error>
where
    D: Deserializer<'de>,
{
    let bson = Bson::deserialize(deserializer)?;
    match bson {
        Bson::String(s) => {
            DateTime::parse_from_rfc3339(&s)
                .map(|dt| dt.with_timezone(&Utc))
                .map_err(serde::de::Error::custom)
        }
        Bson::DateTime(dt) => Ok(dt.to_chrono()),
        _ => Err(serde::de::Error::custom("expected a string or BSON DateTime")),
    }
}
