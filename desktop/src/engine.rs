//! Starts the bundled Synchro engine (the server's Python code in host mode) on loopback.
use crate::api::Api;
use std::collections::hash_map::RandomState;
use std::hash::{BuildHasher, Hasher};
use std::net::TcpListener;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub struct Layout {
    pub python: PathBuf,
    pub python_path: Vec<PathBuf>,
    pub models: PathBuf,
    pub silero: PathBuf,
    pub tools: PathBuf,
    pub mpv: PathBuf,
}

impl Layout {
    /// Installed: everything next to Synchro.exe. Development: the repository's server code and .local models.
    pub fn find() -> Result<Layout, String> {
        let exe = std::env::current_exe().map_err(|e| e.to_string())?;
        let dir = exe.parent().unwrap().to_path_buf();
        if dir.join("runtime/python.exe").is_file() {
            return Ok(Layout {
                python: dir.join("runtime/python.exe"),
                python_path: vec![dir.join("engine")],
                models: dir.join("models"),
                silero: dir.join("models/silero/v5_cis_base_nostress.pt"),
                tools: dir.join("tools"),
                mpv: dir.join("mpv/mpv.exe"),
            });
        }
        let root = dir.ancestors().find(|p| p.join("server/synchro/app.py").is_file()).ok_or("Synchro engine files were not found next to the program")?;
        let models = root.join(".local/host-models");
        Ok(Layout {
            python: root.join(".local/host-env/Scripts/python.exe"),
            python_path: vec![root.join("server"), root.to_path_buf()],
            silero: models.join("silero-cis.pt"),
            models,
            tools: root.join(".local/host-tools"),
            mpv: std::env::var_os("SYNCHRO_MPV").map(PathBuf::from).unwrap_or_else(|| root.join(".local/host-tools/mpv/mpv.exe")),
        })
    }
}

pub struct Engine {
    child: Child,
    pub api: Api,
}

fn random_hex() -> String {
    // RandomState is seeded from the OS random generator; 256 bits are plenty for a loopback key.
    (0..4).map(|i| { let mut h = RandomState::new().build_hasher(); h.write_u32(i); format!("{:016x}", h.finish()) }).collect()
}

pub fn log_path() -> PathBuf {
    dirs::data_local_dir().unwrap_or_else(std::env::temp_dir).join("Synchro").join("engine.log")
}

impl Engine {
    pub fn start(layout: &Layout) -> Result<Engine, String> {
        let port = TcpListener::bind("127.0.0.1:0").and_then(|l| l.local_addr()).map_err(|e| e.to_string())?.port();
        let token = random_hex();
        let log = log_path();
        std::fs::create_dir_all(log.parent().unwrap()).ok();
        let output = std::fs::File::create(&log).map_err(|e| format!("engine log: {e}"))?;
        let path = std::env::join_paths(std::iter::once(layout.tools.clone()).chain(std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())))
            .map_err(|e| e.to_string())?;
        let models = &layout.models;
        let child = Command::new(&layout.python)
            .args(["-m", "uvicorn", "synchro.app:app", "--host", "127.0.0.1", "--port", &port.to_string(), "--no-access-log"])
            .env("PYTHONPATH", std::env::join_paths(&layout.python_path).map_err(|e| e.to_string())?)
            .env("PATH", path)
            .env("PYTHONUNBUFFERED", "1")
            .env("HF_HUB_OFFLINE", "1")
            .env("SYNCHRO_DESKTOP", "1")
            .env("SYNCHRO_HOST_MODE", "1")
            .env("SYNCHRO_MAX_SESSIONS", "1")
            .env("SYNCHRO_TOKEN", &token)
            // The engine requires an extension Origin; the desktop client sends none.
            .env("SYNCHRO_ORIGIN", format!("chrome-extension://{}", "a".repeat(32)))
            .env("SYNCHRO_HOST_ASR_MODEL", models.join("gigaam"))
            .env("SYNCHRO_SENSEVOICE_MODEL", models.join("sensevoice"))
            .env("SYNCHRO_HOST_ACCENT_MODEL", models.join("ruaccent"))
            .env("SYNCHRO_HOST_TTS_MODEL", &layout.silero)
            .env_remove("SYNCHRO_HOST_WHISPER_MODEL")
            .stdin(Stdio::null())
            .stdout(output.try_clone().map_err(|e| e.to_string())?)
            .stderr(output)
            .creation_flags(CREATE_NO_WINDOW)
            .spawn()
            .map_err(|e| format!("Could not start the engine ({}): {e}", layout.python.display()))?;
        adopt(&child)?;
        let engine = Engine { child, api: Api::new(format!("http://127.0.0.1:{port}"), token) };
        let started = Instant::now();
        while started.elapsed() < Duration::from_secs(90) {
            if engine.api.health() {
                return Ok(engine);
            }
            std::thread::sleep(Duration::from_millis(300));
        }
        Err(format!("The engine did not start; see {}", log.display()))
    }
}

impl Drop for Engine {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}

/// One kill-on-close job for the whole program: the engine and mpv die with Synchro even if it crashes.
/// The handle is never closed explicitly; Windows closes it when this process ends.
struct Job(windows_sys::Win32::Foundation::HANDLE);

unsafe impl Send for Job {}
unsafe impl Sync for Job {}

static JOB: std::sync::OnceLock<Option<Job>> = std::sync::OnceLock::new();

fn create_job() -> Option<Job> {
    use windows_sys::Win32::System::JobObjects::*;
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return None;
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let size = std::mem::size_of_val(&info) as u32;
        if SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info as *const _ as *const _, size) == 0 {
            windows_sys::Win32::Foundation::CloseHandle(job);
            return None;
        }
        Some(Job(job))
    }
}

pub fn adopt(child: &Child) -> Result<(), String> {
    let job = JOB.get_or_init(create_job).as_ref().ok_or("Could not create a job object")?;
    if unsafe { windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(job.0, child.as_raw_handle() as _) } == 0 {
        return Err("Could not attach a helper process to Synchro".into());
    }
    Ok(())
}
