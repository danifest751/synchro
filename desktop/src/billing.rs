use crate::config::Settings;
use serde::Deserialize;
use serde_json::Value;
use std::collections::HashMap;

#[derive(Clone, Copy, Default, Deserialize)]
#[serde(default)]
pub struct Usage {
    pub reported_cost_usd: f64,
    pub unpriced_requests: u64,
}

impl Usage {
    fn read(value: &Value) -> Option<Self> {
        if !value.get("reported_cost_usd")?.is_number() || !value.get("unpriced_requests")?.is_u64()
        {
            return None;
        }
        let usage: Self = serde_json::from_value(value.clone()).ok()?;
        (usage.reported_cost_usd.is_finite() && usage.reported_cost_usd >= 0.0).then_some(usage)
    }
}

#[derive(Clone, PartialEq, Eq, Hash)]
struct Account {
    provider: String,
    key: String,
    endpoint: String,
}

impl Account {
    fn from_translation(value: &Value) -> Self {
        Self {
            provider: value["provider"].as_str().unwrap_or_default().into(),
            key: value["api_key"].as_str().unwrap_or_default().trim().into(),
            endpoint: value["base_url"].as_str().unwrap_or_default().trim().into(),
        }
    }
}

struct Record {
    account: Account,
    video: Option<u64>,
    usage: Usage,
    incomplete: bool,
}

#[derive(Default)]
pub struct Ledger {
    records: HashMap<String, Record>,
    sequence: u64,
}

impl Ledger {
    pub fn new_video(&mut self) -> u64 {
        self.sequence += 1;
        self.sequence
    }

    pub fn observe(
        &mut self,
        path: &str,
        body: Option<&Value>,
        response: &Value,
        video: Option<u64>,
    ) {
        if path == "/api/file" {
            if let (Some(id), Some(body)) = (response["session_id"].as_str(), body) {
                self.records.insert(
                    id.into(),
                    Record {
                        account: Account::from_translation(&body["translation"]),
                        video,
                        usage: Usage::default(),
                        incomplete: false,
                    },
                );
                if let Some(usage) = response.get("cloud_usage") {
                    self.session(id, usage);
                }
            } else if let Some(body) = body {
                self.sequence += 1;
                let usage = response.get("cloud_usage").and_then(Usage::read);
                self.records.insert(
                    format!("file-error-{}", self.sequence),
                    Record {
                        account: Account::from_translation(&body["translation"]),
                        video,
                        usage: usage.unwrap_or_default(),
                        incomplete: usage.is_none(),
                    },
                );
            }
        } else if path == "/api/pipeline/check" {
            if let Some(body) = body {
                self.sequence += 1;
                let usage = response.get("cloud_usage").and_then(Usage::read);
                self.records.insert(
                    format!("check-{}", self.sequence),
                    Record {
                        account: Account::from_translation(&body["translation"]),
                        video: None,
                        usage: usage.unwrap_or_default(),
                        incomplete: usage.is_none(),
                    },
                );
            }
        } else if let Some(id) = path
            .strip_prefix("/api/video/")
            .and_then(|s| s.split('/').next())
        {
            if let Some(usage) = response.get("cloud_usage") {
                self.session(id, usage);
            } else if path.contains("/next")
                && let Some(record) = self.records.get_mut(id)
            {
                record.incomplete = true;
            }
        }
    }

    fn session(&mut self, id: &str, value: &Value) {
        if let Some(record) = self.records.get_mut(id) {
            if let Some(usage) = Usage::read(value) {
                // Summaries are cumulative. Retries and out-of-order heartbeats cannot count twice.
                record.usage.reported_cost_usd =
                    record.usage.reported_cost_usd.max(usage.reported_cost_usd);
                record.usage.unpriced_requests =
                    record.usage.unpriced_requests.max(usage.unpriced_requests);
                record.incomplete = false;
            } else {
                record.incomplete = true;
            }
        }
    }

    pub fn totals(&self, settings: &Settings, video: Option<u64>) -> Usage {
        let account = Account::from_translation(&settings.translation());
        self.records
            .values()
            .filter(|record| {
                if let Some(video) = video {
                    record.video == Some(video)
                } else {
                    record.account == account
                }
            })
            .fold(Usage::default(), |mut total, record| {
                total.reported_cost_usd += record.usage.reported_cost_usd;
                total.unpriced_requests +=
                    record.usage.unpriced_requests + u64::from(record.incomplete);
                total
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn cumulative_cost_is_not_counted_twice_and_accounts_are_isolated() {
        let mut ledger = Ledger::default();
        let first = Settings {
            api_key: "first-key".into(),
            ..Default::default()
        };
        let second = Settings {
            api_key: "second-key".into(),
            ..first.clone()
        };
        let group = ledger.new_video();
        ledger.observe(
            "/api/file",
            Some(&first.session()),
            &json!({"session_id":"one"}),
            Some(group),
        );
        let response = json!({"cloud_usage":{"reported_cost_usd":0.12,"unpriced_requests":1}});
        for _ in 0..3 {
            ledger.observe("/api/video/one/next?ready=0", None, &response, Some(group));
        }
        assert_eq!(ledger.totals(&first, None).reported_cost_usd, 0.12);
        assert_eq!(ledger.totals(&first, Some(group)).unpriced_requests, 1);
        assert_eq!(ledger.totals(&second, None).reported_cost_usd, 0.0);
        ledger.observe(
            "/api/file",
            Some(&first.session()),
            &json!({"session_id":"two"}),
            Some(group),
        );
        ledger.observe("/api/video/two/next", None, &response, Some(group));
        assert_eq!(ledger.totals(&first, Some(group)).reported_cost_usd, 0.24);
        ledger.observe(
            "/api/pipeline/check",
            Some(&first.session()),
            &response,
            None,
        );
        assert_eq!(ledger.totals(&first, None).reported_cost_usd, 0.36);
        assert_eq!(ledger.totals(&first, Some(group)).reported_cost_usd, 0.24);
    }

    #[test]
    fn missing_cost_is_unknown_and_later_summary_resolves_it() {
        let mut ledger = Ledger::default();
        let settings = Settings::default();
        ledger.observe(
            "/api/file",
            Some(&settings.session()),
            &json!({"session_id":"one"}),
            None,
        );
        ledger.observe("/api/video/one/next", None, &json!({}), None);
        assert_eq!(ledger.totals(&settings, None).unpriced_requests, 1);
        ledger.observe(
            "/api/video/one",
            None,
            &json!({"cloud_usage":{"reported_cost_usd":0,"unpriced_requests":0}}),
            None,
        );
        assert_eq!(ledger.totals(&settings, None).unpriced_requests, 0);
        assert!(Usage::read(&json!({"reported_cost_usd":-1,"unpriced_requests":0})).is_none());
    }
}
