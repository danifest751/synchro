//! Decode into a bounded, latest-frame mailbox. The audio player's media clock is the only clock:
//! buffering, pause and variable-speed voiceover all hold or advance the picture at that position.
use crate::{player::Shared, process::Process};
use eframe::egui::ColorImage;
use std::io::{self, BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{ChildStdout, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::Duration;

const FPS: f64 = 30.0;
type FrameSlot = Arc<Mutex<Option<(u64, ColorImage)>>>;

#[derive(Default)]
pub struct Picture {
    latest: FrameSlot,
    process: Arc<Mutex<Option<Process>>>,
}

impl Picture {
    pub fn start(
        binary: PathBuf,
        file: PathBuf,
        clock: Arc<Mutex<Shared>>,
    ) -> (Self, JoinHandle<()>) {
        let latest: FrameSlot = Default::default();
        let process = Arc::new(Mutex::new(None));
        let picture = Self {
            latest: latest.clone(),
            process: process.clone(),
        };
        let worker = thread::spawn(move || {
            let mut epoch = u64::MAX;
            let mut next = 0.0;
            let mut stream = None;
            let mut played = false;
            let mut published = std::time::Instant::now();
            loop {
                let (stop, time, seek) = {
                    let s = clock.lock().unwrap();
                    let elapsed = s
                        .moving_since
                        .map_or(0.0, |(at, rate)| at.elapsed().as_secs_f64().min(0.2) * rate);
                    (s.stop, s.position + elapsed, s.seek_epoch)
                };
                if stop {
                    break;
                }
                if seek != epoch || (stream.is_some() && time - next > 1.0) {
                    epoch = seek;
                    // Decode a short lead-in so a seek between source frames also has a picture.
                    next = (time - 0.25).max(0.0);
                    let mut owner = process.lock().unwrap();
                    owner.take();
                    if clock.lock().unwrap().stop {
                        break;
                    }
                    match decoder(&binary, &file, next) {
                        Ok((child, pipe)) => {
                            *owner = Some(child);
                            stream = Some(pipe);
                            played = false;
                        }
                        Err(_) => {
                            fail(&clock);
                            break;
                        }
                    }
                }
                if time + 0.002 < next || stream.is_none() {
                    thread::sleep(Duration::from_millis(8));
                    continue;
                }
                match read_frame(stream.as_mut().unwrap()) {
                    Ok(Some((size, rgb))) => {
                        // Drop frames overtaken by a long phrase's speed adjustment before uploading.
                        if !played
                            || next + 1.0 / FPS >= time
                            || published.elapsed() >= Duration::from_millis(80)
                        {
                            published = std::time::Instant::now();
                            *latest.lock().unwrap() =
                                Some((epoch, ColorImage::from_rgb(size, &rgb)));
                        }
                        next += 1.0 / FPS;
                        played = true;
                    }
                    Ok(None) if played => {
                        stream = None; // Keep the last image until replay or a seek.
                        process.lock().unwrap().take();
                    }
                    _ => {
                        fail(&clock);
                        break;
                    }
                }
            }
            process.lock().unwrap().take();
        });
        (picture, worker)
    }

    pub fn take(&self, epoch: u64) -> Option<ColorImage> {
        self.latest
            .lock()
            .unwrap()
            .take()
            .filter(|(id, _)| *id == epoch)
            .map(|(_, image)| image)
    }

    pub fn cancel(&self) {
        self.process.lock().unwrap().take();
    }
}

fn fail(clock: &Mutex<Shared>) {
    let mut s = clock.lock().unwrap();
    if !s.stop {
        s.error = Some("Could not decode the video picture".into());
        s.stop = true;
    }
}

fn decoder(
    binary: &Path,
    file: &Path,
    at: f64,
) -> Result<(Process, BufReader<ChildStdout>), String> {
    let mut cmd = Command::new(binary);
    cmd.args(["-nostdin", "-hide_banner", "-loglevel", "error", "-ss"]).arg(format!("{at:.6}"))
        .arg("-i").arg(file)
        .args(["-map", "0:V:0", "-an", "-sn", "-dn", "-vf",
            "fps=30,scale=w='max(1,round(min(1920,min(ih,1080)*dar)))':h='max(1,round(min(min(ih,1080),1920/dar)))',setsar=1",
            "-c:v", "ppm", "-pix_fmt", "rgb24", "-f", "image2pipe", "pipe:1"])
        .stdin(Stdio::null()).stderr(Stdio::null()).stdout(Stdio::piped());
    let mut child = Process::spawn(&mut cmd)?;
    let pipe = child
        .take_stdout()
        .ok_or("Video decoder pipe is unavailable")?;
    Ok((child, BufReader::new(pipe)))
}

fn read_frame(reader: &mut impl BufRead) -> io::Result<Option<([usize; 2], Vec<u8>)>> {
    let mut line = String::new();
    if reader.read_line(&mut line)? == 0 {
        return Ok(None);
    }
    let invalid = || io::Error::new(io::ErrorKind::InvalidData, "Invalid decoder frame");
    if line.trim_end() != "P6" {
        return Err(invalid());
    }
    line.clear();
    reader.read_line(&mut line)?;
    let (w, h) = line.trim().split_once(' ').ok_or_else(invalid)?;
    let width = w.parse::<usize>().map_err(|_| invalid())?;
    let height = h.parse::<usize>().map_err(|_| invalid())?;
    if !(1..=1920).contains(&width) || !(1..=1080).contains(&height) {
        return Err(invalid());
    }
    line.clear();
    reader.read_line(&mut line)?;
    if line.trim_end() != "255" {
        return Err(invalid());
    }
    let mut rgb = vec![0; width * height * 3];
    reader.read_exact(&mut rgb)?;
    Ok(Some(([width, height], rgb)))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn truncated_and_oversized_frames_are_rejected() {
        for bytes in [b"P6\n1921 1080\n255\n".as_slice(), b"P6\n1 1\n255\n\x10"] {
            assert!(read_frame(&mut &bytes[..]).is_err());
        }
        let (_, rgb) = read_frame(&mut b"P6\n1 1\n255\n\x00\x80\xff".as_slice())
            .unwrap()
            .unwrap();
        assert_eq!(rgb, [0, 128, 255]);
    }

    #[test]
    #[ignore = "requires SYNCHRO_TEST_FFMPEG and SYNCHRO_TEST_VIDEO"]
    fn native_picture_follows_pause_and_seek() {
        let clock: Arc<Mutex<Shared>> = Default::default();
        let (picture, worker) = Picture::start(
            std::env::var_os("SYNCHRO_TEST_FFMPEG").unwrap().into(),
            std::env::var_os("SYNCHRO_TEST_VIDEO").unwrap().into(),
            clock.clone(),
        );
        let wait = |epoch| {
            for _ in 0..500 {
                if let Some(frame) = picture.take(epoch) {
                    return frame;
                }
                thread::sleep(Duration::from_millis(10));
            }
            panic!("No image for epoch {epoch}");
        };
        let first = wait(0);
        thread::sleep(Duration::from_millis(80));
        assert!(picture.take(0).is_none());
        {
            let mut s = clock.lock().unwrap();
            s.position = 3.0;
            s.seek_epoch += 1;
        }
        assert_eq!(wait(1).size, first.size);
        clock.lock().unwrap().position += 1.0 / FPS;
        assert_eq!(wait(1).size, first.size);
        clock.lock().unwrap().stop = true;
        picture.cancel();
        worker.join().unwrap();
    }
}
