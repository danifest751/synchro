use crate::billing::{Ledger, Usage};
use crate::config::Settings;
use serde::Deserialize;
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};
use std::time::Duration;

#[derive(Debug)]
pub struct ApiError {
    pub status: Option<u16>,
    pub message: String,
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl ApiError {
    /// Network trouble and busy or failed windows are retried; the engine keeps a failed window pending.
    pub fn transient(&self) -> bool {
        matches!(self.status, None | Some(409 | 502 | 503 | 504))
    }
}

#[derive(Deserialize)]
pub struct Opened {
    pub session_id: String,
    pub base: f64,
    pub duration: f64,
}

#[derive(Deserialize)]
pub struct Segment {
    pub id: u64,
    pub start: f64,
    pub duration: f64,
    pub source_duration: f64,
    pub text: String,
    pub wav: String,
}

#[derive(Deserialize)]
pub struct Window {
    pub segments: Vec<Segment>,
    pub ready_until: f64,
    pub finished: bool,
}

#[derive(Clone)]
pub struct Api {
    client: reqwest::blocking::Client,
    base: String,
    token: String,
    pub ledger: Arc<Mutex<Ledger>>,
    video_id: Option<u64>,
}

impl Api {
    pub fn new(base: String, token: String) -> Api {
        // Windows can take up to the engine's 105-second deadline.
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(130))
            .build()
            .expect("HTTP client");
        Api {
            client,
            base,
            token,
            ledger: Default::default(),
            video_id: None,
        }
    }

    fn call(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<Value, ApiError> {
        let mut request = self
            .client
            .request(method, format!("{}{}", self.base, path))
            .bearer_auth(&self.token);
        if let Some(body) = &body {
            request = request.json(&body);
        }
        let response = request.send().map_err(|error| {
            self.ledger
                .lock()
                .unwrap()
                .observe(path, body.as_ref(), &Value::Null, self.video_id);
            ApiError {
                status: None,
                message: format!("Engine unreachable: {error}"),
            }
        })?;
        let status = response.status().as_u16();
        let value: Value = response.json().unwrap_or(Value::Null);
        self.ledger
            .lock()
            .unwrap()
            .observe(path, body.as_ref(), &value, self.video_id);
        if !(200..300).contains(&status) {
            let message = value["detail"]
                .as_str()
                .map(str::to_owned)
                .unwrap_or_else(|| format!("Engine error {status}"));
            return Err(ApiError {
                status: Some(status),
                message,
            });
        }
        Ok(value)
    }

    pub fn health(&self) -> bool {
        self.client
            .get(format!("{}/health", self.base))
            .timeout(Duration::from_secs(2))
            .send()
            .map(|r| r.status().is_success())
            .unwrap_or(false)
    }

    pub fn open_file(&self, path: &str, position: f64, session: Value) -> Result<Opened, ApiError> {
        let mut body = session;
        body["path"] = json!(path);
        body["position"] = json!(position);
        let value = self.call(reqwest::Method::POST, "/api/file", Some(body))?;
        serde_json::from_value(value).map_err(|error| ApiError {
            status: None,
            message: error.to_string(),
        })
    }

    pub fn next(&self, session: &str, ready: f64) -> Result<Window, ApiError> {
        let value = self.call(
            reqwest::Method::POST,
            &format!("/api/video/{session}/next?ready={ready}"),
            None,
        )?;
        serde_json::from_value(value).map_err(|error| ApiError {
            status: None,
            message: error.to_string(),
        })
    }

    pub fn heartbeat(&self, session: &str) -> Result<(), ApiError> {
        self.call(reqwest::Method::GET, &format!("/api/video/{session}"), None)
            .map(|_| ())
    }

    pub fn close(&self, session: &str) {
        let _ = self.heartbeat(session);
        let _ = self.call(
            reqwest::Method::DELETE,
            &format!("/api/session/{session}"),
            None,
        );
    }

    /// Loads recognition, translation and speech once, so the first video starts faster.
    pub fn check(&self, session: Value) -> Result<f64, ApiError> {
        let value = self.call(reqwest::Method::POST, "/api/pipeline/check", Some(session))?;
        Ok(value["seconds"].as_f64().unwrap_or_default())
    }

    pub fn for_video(&self) -> Self {
        let mut api = self.clone();
        api.video_id = Some(self.ledger.lock().unwrap().new_video());
        api
    }

    pub fn video_id(&self) -> u64 {
        self.video_id.unwrap_or_default()
    }

    pub fn usage(&self, settings: &Settings, video: Option<u64>) -> Usage {
        self.ledger.lock().unwrap().totals(settings, video)
    }

    pub fn models(&self, provider: &str) -> Result<Vec<Model>, ApiError> {
        let result = self.call(
            reqwest::Method::POST,
            "/api/translation/models",
            Some(json!({"provider":provider})),
        )?;
        serde_json::from_value(result["models"].clone()).map_err(|e| ApiError {
            status: None,
            message: e.to_string(),
        })
    }

    pub fn balance(&self, settings: &Settings) -> Result<Balance, ApiError> {
        let mut body = settings.translation();
        if settings.provider == "openrouter" && !settings.balance_key.trim().is_empty() {
            body["management_key"] = json!(settings.balance_key.trim());
        }
        let result = self.call(
            reqwest::Method::POST,
            "/api/translation/balance",
            Some(body),
        )?;
        serde_json::from_value(result).map_err(|e| ApiError {
            status: None,
            message: e.to_string(),
        })
    }
}

#[derive(Clone, Deserialize)]
pub struct Model {
    pub id: String,
    pub name: String,
    pub input_price: Option<f64>,
    pub output_price: Option<f64>,
}

#[derive(Clone, Default, Deserialize)]
pub struct Balance {
    pub balance_usd: Option<f64>,
    pub total_spent_usd: Option<f64>,
    pub key_spent_usd: Option<f64>,
    pub key_limit_remaining_usd: Option<f64>,
    pub balance_note: Option<String>,
}
