//! mpv plays the video; Synchro controls it over a named pipe or private Unix socket.
use serde_json::{Value, json};
use std::io::{BufRead, BufReader, Write};
use crate::process::Process;
#[cfg(windows)]
type Pipe = std::fs::File;
#[cfg(unix)]
type Pipe = std::os::unix::net::UnixStream;
use std::path::Path;
use std::process::{Command, Stdio};
use std::time::Duration;

pub struct Mpv {
    child: Process,
    reader: BufReader<Pipe>,
    writer: Pipe,
    #[cfg(unix)]
    _socket_dir: tempfile::TempDir,
    next_id: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    #[ignore = "requires SYNCHRO_TEST_MPV and SYNCHRO_TEST_VIDEO; opens the real player"]
    fn native_player_controls_and_cleanup() {
        let binary = std::env::var_os("SYNCHRO_TEST_MPV").expect("Set SYNCHRO_TEST_MPV");
        let video = std::env::var_os("SYNCHRO_TEST_VIDEO").expect("Set SYNCHRO_TEST_VIDEO");
        let mut player = Mpv::open(Path::new(&binary), Path::new(&video), "Synchro IPC test").unwrap();
        for _ in 0..100 {
            if player.number("duration").is_some() { break; }
            std::thread::sleep(Duration::from_millis(50));
        }
        assert!(player.number("duration").unwrap() > 5.0);
        for volume in [0.0, 25.0, 100.0] {
            player.set("volume", json!(volume));
            assert!((player.number("volume").unwrap() - volume).abs() < 0.01);
        }
        player.set("speed", json!(0.75));
        assert_eq!(player.number("speed"), Some(0.75));
        player.set("pause", json!(true));
        assert_eq!(player.flag("pause"), Some(true));
        player.request(json!(["seek", 3.0, "absolute+exact"])).unwrap();
        for _ in 0..100 {
            if player.number("time-pos").is_some_and(|time| (time - 3.0).abs() < 0.2) { break; }
            std::thread::sleep(Duration::from_millis(50));
        }
        assert!((player.number("time-pos").unwrap() - 3.0).abs() < 0.2);
        player.set("pause", json!(false));
        assert_eq!(player.flag("pause"), Some(false));
        player.quit();
        assert!(!player.alive());
    }
}

impl Mpv {
    pub fn open(mpv: &Path, file: &Path, title: &str) -> Result<Mpv, String> {
        #[cfg(windows)]
        let pipe = format!(
            r"\\.\pipe\synchro-mpv-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_millis()
        );
        #[cfg(unix)]
        let socket_dir = tempfile::Builder::new().prefix("synchro-mpv-").tempdir_in("/tmp").map_err(|e| e.to_string())?;
        #[cfg(unix)]
        let pipe = socket_dir.path().join("ipc").to_string_lossy().into_owned();
        let mut command = Command::new(mpv);
        command.arg(format!("--input-ipc-server={pipe}"))
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
            .stderr(Stdio::null());
        let mut child = Process::spawn(&mut command).map_err(|e| format!("Could not start mpv ({}): {e}", mpv.display()))?;
        for _ in 0..100 {
            #[cfg(windows)]
            let connected = std::fs::OpenOptions::new().read(true).write(true).open(&pipe);
            #[cfg(unix)]
            let connected = Pipe::connect(&pipe);
            if let Ok(pipe) = connected {
                let writer = pipe.try_clone().map_err(|e| e.to_string())?;
                return Ok(Mpv {
                    child,
                    reader: BufReader::new(pipe),
                    writer,
                    next_id: 1,
                    #[cfg(unix)]
                    _socket_dir: socket_dir,
                });
            }
            if let Ok(Some(_)) = child.try_wait() {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
        child.kill();
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
