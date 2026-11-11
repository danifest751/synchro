use serde::Deserialize;
use serde_json::{json, Value};
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
}

impl Api {
    pub fn new(base: String, token: String) -> Api {
        // Windows can take up to the engine's 105-second deadline.
        let client = reqwest::blocking::Client::builder().timeout(Duration::from_secs(130)).build().expect("HTTP client");
        Api { client, base, token }
    }

    fn call(&self, method: reqwest::Method, path: &str, body: Option<Value>) -> Result<Value, ApiError> {
        let mut request = self.client.request(method, format!("{}{}", self.base, path)).bearer_auth(&self.token);
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request.send().map_err(|error| ApiError { status: None, message: format!("Engine unreachable: {error}") })?;
        let status = response.status().as_u16();
        let value: Value = response.json().unwrap_or(Value::Null);
        if !(200..300).contains(&status) {
            let message = value["detail"].as_str().map(str::to_owned).unwrap_or_else(|| format!("Engine error {status}"));
            return Err(ApiError { status: Some(status), message });
        }
        Ok(value)
    }

    pub fn health(&self) -> bool {
        self.client.get(format!("{}/health", self.base)).timeout(Duration::from_secs(2)).send().map(|r| r.status().is_success()).unwrap_or(false)
    }

    pub fn open_file(&self, path: &str, position: f64, session: Value) -> Result<Opened, ApiError> {
        let mut body = session;
        body["path"] = json!(path);
        body["position"] = json!(position);
        let value = self.call(reqwest::Method::POST, "/api/file", Some(body))?;
        serde_json::from_value(value).map_err(|error| ApiError { status: None, message: error.to_string() })
    }

    pub fn next(&self, session: &str, ready: f64) -> Result<Window, ApiError> {
        let value = self.call(reqwest::Method::POST, &format!("/api/video/{session}/next?ready={ready}"), None)?;
        serde_json::from_value(value).map_err(|error| ApiError { status: None, message: error.to_string() })
    }

    pub fn heartbeat(&self, session: &str) -> Result<(), ApiError> {
        self.call(reqwest::Method::GET, &format!("/api/video/{session}"), None).map(|_| ())
    }

    pub fn close(&self, session: &str) {
        let _ = self.call(reqwest::Method::DELETE, &format!("/api/session/{session}"), None);
    }

    /// Loads recognition, translation and speech once, so the first video starts faster.
    pub fn check(&self, session: Value) -> Result<f64, ApiError> {
        let value = self.call(reqwest::Method::POST, "/api/pipeline/check", Some(session))?;
        Ok(value["seconds"].as_f64().unwrap_or_default())
    }
}
