//! Starts the bundled Synchro engine (the server's Python code in host mode) on loopback.
use crate::api::Api;
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use crate::process::Process;
use std::time::{Duration, Instant};


pub struct Layout {
    pub python: PathBuf,
    pub python_path: Vec<PathBuf>,
    pub models: PathBuf,
    pub silero: PathBuf,
    pub tools: PathBuf,
    pub mpv: PathBuf,
}

impl Layout {
    /// Installed: next to Synchro.exe or in the Mac app's Resources. Development: repository files.
    pub fn find() -> Result<Layout, String> {
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        let dir = exe.parent().unwrap().to_path_buf();
        let python = if cfg!(windows) { "runtime/python.exe" } else { "runtime/bin/python3" };
        let resources = dir.parent().map(|p| p.join("Resources"));
        let base = resources.filter(|p| p.join(python).is_file()).unwrap_or_else(|| dir.clone());
        if base.join(python).is_file() {
            return Ok(Layout {
                python: base.join(python), python_path: vec![base.join("engine")],
                models: base.join("models"), silero: base.join("models/silero/v5_cis_base_nostress.pt"),
                tools: base.join("tools"),
                mpv: base.join(if cfg!(windows) { "mpv/mpv.exe" } else { "mpv/mpv.app/Contents/MacOS/mpv" }),
            });
        }
        let root = dir.ancestors().find(|p| p.join("server/synchro/app.py").is_file()).ok_or("Synchro engine files were not found next to the program")?;
        let models = root.join(".local/host-models");
        Ok(Layout {
            python: root.join(if cfg!(windows) { ".local/host-env/Scripts/python.exe" } else { ".local/host-env/bin/python3" }),
            python_path: vec![root.join("server"), root.to_path_buf()],
            silero: models.join("silero-cis.pt"),
            models,
            tools: root.join(".local/host-tools"),
            mpv: std::env::var_os("SYNCHRO_MPV").map(PathBuf::from).unwrap_or_else(|| root.join(if cfg!(windows) { ".local/host-tools/mpv/mpv.exe" } else { ".local/host-tools/mpv/mpv.app/Contents/MacOS/mpv" })),
        })
    }
}

pub struct Engine {
    child: Process,
    pub api: Api,
}

fn random_hex() -> String {
    // RandomState is seeded from the OS random generator; 256 bits are plenty for a loopback key.
    (0..4).map(|i| { let mut h = RandomState::new().build_hasher(); h.write_u32(i); format!("{:016x}", h.finish()) }).collect()
}

pub fn log_path() -> PathBuf {
    dirs::data_local_dir().unwrap_or_else(std::env::temp_dir).join("Synchro").join("engine.log")
}

/// Keep the previous run's log so a crash that triggered a restart is still diagnosable.
pub fn keep_previous_log(path: &Path) {
    if path.is_file() {
        let mut name = path.file_name().unwrap_or_default().to_os_string();
        name.push(".1");
        let _ = std::fs::rename(path, path.with_file_name(name));
    }
}

impl Engine {
    pub fn start(layout: &Layout) -> Result<Engine, String> {
        let mut last = String::new();
        for attempt in 0..3 {
            match Self::start_once(layout) {
                Ok(engine) => return Ok(engine),
                Err((message, retryable)) => {
                    last = message;
                    // An early exit is usually a lost race for the ephemeral port; try a fresh one.
                    if !retryable || attempt == 2 {
                        break;
                    }
                }
            }
        }
        Err(last)
    }

    fn start_once(layout: &Layout) -> Result<Engine, (String, bool)> {
        let port = TcpListener::bind("127.0.0.1:0").and_then(|l| l.local_addr()).map_err(|e| (e.to_string(), false))?.port();
        let token = random_hex();
        let log = log_path();
        std::fs::create_dir_all(log.parent().unwrap()).ok();
        keep_previous_log(&log);
        let output = std::fs::File::create(&log).map_err(|e| (format!("engine log: {e}"), false))?;
        let path = std::env::join_paths(std::iter::once(layout.tools.clone()).chain(std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())))
            .map_err(|e| (e.to_string(), false))?;
        let models = &layout.models;
        let mut command = Command::new(&layout.python);
        command
            .args(["-m", "uvicorn", "synchro.app:app", "--host", "127.0.0.1", "--port", &port.to_string(), "--no-access-log"])
            .env("PYTHONPATH", std::env::join_paths(&layout.python_path).map_err(|e| (e.to_string(), false))?)
            .env("PATH", path)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("HF_HUB_OFFLINE", "1")
            .env("SYNCHRO_DESKTOP", "1")
            .env("SYNCHRO_HOST_MODE", "1")
            .env("SYNCHRO_MAX_SESSIONS", "1")
            .env("SYNCHRO_TOKEN", &token)
            // The engine requires an extension Origin; the desktop client sends none.
            .env("SYNCHRO_ORIGIN", format!("chrome-extension://{}", "a".repeat(32)))
            .env("SYNCHRO_HOST_ASR_MODEL", models.join("gigaam"))
            .env("SYNCHRO_SENSEVOICE_MODEL", models.join("sensevoice"))
            .env("SYNCHRO_SPEAKER_MODEL", models.join("speaker/model.onnx"))
            .env("SYNCHRO_HOST_ACCENT_MODEL", models.join("ruaccent"))
            .env("SYNCHRO_HOST_TTS_MODEL", &layout.silero)
            .env_remove("SYNCHRO_HOST_WHISPER_MODEL")
            .stdin(Stdio::null())
            .stdout(output.try_clone().map_err(|e| (e.to_string(), false))?)
            .stderr(output);
        let child = Process::spawn(&mut command)
            .map_err(|e| (format!("Could not start the engine ({}): {e}", layout.python.display()), false))?;
        let mut engine = Engine { child, api: Api::new(format!("http://127.0.0.1:{port}"), token) };
        let started = Instant::now();
        while started.elapsed() < Duration::from_secs(90) {
            if engine.child.try_wait().map_err(|e| (e.to_string(), false))?.is_some() {
                return Err((format!("The engine exited during startup; see {}", log.display()), true));
            }
            if engine.api.health() {
                return Ok(engine);
            }
            std::thread::sleep(Duration::from_millis(300));
        }
        Err((format!("The engine did not start; see {}", log.display()), false))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn previous_log_is_kept_once_and_replaced_on_the_next_run() {
        let dir = tempfile::tempdir().unwrap();
        let log = dir.path().join("engine.log");
        std::fs::write(&log, b"first run").unwrap();
        keep_previous_log(&log);
        assert!(!log.exists());
        assert_eq!(std::fs::read(dir.path().join("engine.log.1")).unwrap(), b"first run");
        std::fs::write(&log, b"second run").unwrap();
        keep_previous_log(&log);
        assert_eq!(std::fs::read(dir.path().join("engine.log.1")).unwrap(), b"second run");
        // No log yet: nothing to rotate and no panic.
        keep_previous_log(&dir.path().join("absent.log"));
    }
}
