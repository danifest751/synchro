//! mpv plays the video; Synchro controls it over mpv's JSON IPC named pipe.
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Write};
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

pub struct Mpv {
    child: Child,
    reader: BufReader<std::fs::File>,
    writer: std::fs::File,
    next_id: u64,
}

impl Mpv {
    pub fn open(mpv: &Path, file: &Path, title: &str) -> Result<Mpv, String> {
        let pipe = format!(
            r"\\.\pipe\synchro-mpv-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis()
        );
        let mut child = Command::new(mpv)
            .arg(format!("--input-ipc-server={pipe}"))
            .args([
                "--no-config",
                "--pause",
                "--keep-open=yes",
                "--force-window=immediate",
                "--hr-seek=yes",
                "--idle=no",
                "--osd-duration=1500",
                "--volume=100",
                "--mute=no",
            ])
            .arg(format!("--title={title}"))
            .arg("--")
            .arg(file)
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .creation_flags(0x0800_0000)
            .spawn()
            .map_err(|e| format!("Could not start mpv ({}): {e}", mpv.display()))?;
        // The video window closes with Synchro, even after a crash.
        let _ = crate::engine::adopt(&child);
        for _ in 0..100 {
            if let Ok(pipe) = std::fs::OpenOptions::new()
                .read(true)
                .write(true)
                .open(&pipe)
            {
                let writer = pipe.try_clone().map_err(|e| e.to_string())?;
                return Ok(Mpv {
                    child,
                    reader: BufReader::new(pipe),
                    writer,
                    next_id: 1,
                });
            }
            if let Ok(Some(_)) = child.try_wait() {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        let _ = child.kill();
        Err("mpv did not open its control channel".into())
    }

    pub fn alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }

    /// One request at a time from one thread: blocking reads and writes on one pipe handle would wait for each other.
    pub fn request(&mut self, command: Value) -> Result<Value, String> {
        let id = self.next_id;
        self.next_id += 1;
        let mut line = serde_json::to_vec(&json!({"command": command, "request_id": id})).unwrap();
        line.push(b'\n');
        self.writer.write_all(&line).map_err(|e| e.to_string())?;
        loop {
            let mut text = String::new();
            if self
                .reader
                .read_line(&mut text)
                .map_err(|e| e.to_string())?
                == 0
            {
                return Err("mpv closed".into());
            }
            let Ok(message) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            if message["request_id"] == id {
                return if message["error"] == "success" {
                    Ok(message["data"].clone())
                } else {
                    Err(message["error"].as_str().unwrap_or("mpv error").into())
                };
            }
        }
    }

    pub fn number(&mut self, name: &str) -> Option<f64> {
        self.request(json!(["get_property", name])).ok()?.as_f64()
    }

    pub fn flag(&mut self, name: &str) -> Option<bool> {
        self.request(json!(["get_property", name])).ok()?.as_bool()
    }

    pub fn set(&mut self, name: &str, value: Value) {
        let _ = self.request(json!(["set_property", name, value]));
    }

    pub fn show(&mut self, text: &str, milliseconds: u64) {
        let _ = self.request(json!(["show-text", text, milliseconds]));
    }

    pub fn quit(&mut self) {
        let _ = self.request(json!(["quit"]));
        let _ = self.child.wait();
    }
}

impl Drop for Mpv {
    fn drop(&mut self) {
        if self.alive() {
            let _ = self.child.kill();
        }
    }
}
