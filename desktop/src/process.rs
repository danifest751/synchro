//! Own helper processes and their descendants, including after an application crash.
use std::io;
use std::process::{Child, Command, ExitStatus};
#[cfg(unix)]
use std::process::Stdio;

pub struct Process {
    child: Child,
    closed: bool,
    #[cfg(unix)]
    watcher: Child,
}

impl Process {
    pub fn spawn(command: &mut Command) -> Result<Self, String> {
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x0800_0000);
        }
        #[cfg(unix)]
        {
            use std::os::unix::process::CommandExt;
            command.process_group(0);
        }
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        #[cfg(windows)]
        if let Err(error) = adopt(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        #[cfg(unix)]
        let watcher = {
            use std::os::unix::process::CommandExt;
            // Only numeric PIDs are arguments; no file names or user content enter the shell script.
            let result = Command::new("/bin/sh")
                .args(["-c", "while kill -0 \"$1\" 2>/dev/null && kill -0 \"$2\" 2>/dev/null; do sleep 0.5; done; kill -TERM -\"$2\" 2>/dev/null; sleep 1; kill -KILL -\"$2\" 2>/dev/null", "synchro-watchdog"])
                .arg(std::process::id().to_string()).arg(child.id().to_string())
                .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null())
                .process_group(0).spawn();
            match result {
                Ok(watcher) => watcher,
                Err(error) => {
                    unsafe { libc::kill(-(child.id() as i32), libc::SIGKILL); }
                    let _ = child.wait();
                    return Err(format!("Could not supervise helper process: {error}"));
                }
            }
        };
        Ok(Self { child, closed: false, #[cfg(unix)] watcher })
    }

    fn finish(&mut self) {
        if self.closed { return; }
        #[cfg(unix)]
        {
            unsafe { libc::kill(-(self.child.id() as i32), libc::SIGKILL); }
            unsafe { libc::kill(-(self.watcher.id() as i32), libc::SIGKILL); }
            let _ = self.watcher.kill();
            let _ = self.watcher.wait();
        }
        self.closed = true;
    }

    pub fn try_wait(&mut self) -> io::Result<Option<ExitStatus>> {
        let result = self.child.try_wait()?;
        if result.is_some() { self.finish(); }
        Ok(result)
    }

    pub fn wait(&mut self) -> io::Result<ExitStatus> {
        let result = self.child.wait();
        self.finish();
        result
    }

    pub fn kill(&mut self) {
        if self.closed { return; }
        #[cfg(unix)]
        unsafe { libc::kill(-(self.child.id() as i32), libc::SIGKILL); }
        let _ = self.child.kill();
        let _ = self.child.wait();
        self.finish();
    }
}

impl Drop for Process {
    fn drop(&mut self) { self.kill(); }
}

#[cfg(windows)]
struct Job(windows_sys::Win32::Foundation::HANDLE);
#[cfg(windows)]
unsafe impl Send for Job {}
#[cfg(windows)]
unsafe impl Sync for Job {}
#[cfg(windows)]
static JOB: std::sync::OnceLock<Option<Job>> = std::sync::OnceLock::new();

#[cfg(windows)]
fn create_job() -> Option<Job> {
    use windows_sys::Win32::System::JobObjects::*;
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() { return None; }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info as *const _ as *const _, std::mem::size_of_val(&info) as u32) == 0 {
            windows_sys::Win32::Foundation::CloseHandle(job);
            return None;
        }
        Some(Job(job))
    }
}

#[cfg(windows)]
fn adopt(child: &Child) -> Result<(), String> {
    use std::os::windows::io::AsRawHandle;
    let job = JOB.get_or_init(create_job).as_ref().ok_or("Could not create a job object")?;
    if unsafe { windows_sys::Win32::System::JobObjects::AssignProcessToJobObject(job.0, child.as_raw_handle() as _) } == 0 {
        return Err("Could not attach a helper process to Synchro".into());
    }
    Ok(())
}

#[cfg(all(test, unix))]
mod tests {
    use super::*;

    #[test]
    fn dropping_a_helper_terminates_and_reaps_it() {
        let mut command = Command::new("/bin/sleep");
        command.arg("60");
        let process = Process::spawn(&mut command).unwrap();
        let pid = process.child.id() as i32;
        drop(process);
        assert_eq!(unsafe { libc::kill(pid, 0) }, -1);
        assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::ESRCH));
    }
}
