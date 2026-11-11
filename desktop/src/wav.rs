/// Decode the engine's PCM16 RIFF WAV into float samples.
pub struct Pcm {
    pub samples: Vec<f32>,
    pub rate: u32,
    pub channels: u16,
}

pub fn decode(data: &[u8]) -> Result<Pcm, String> {
    if data.len() < 12 || &data[0..4] != b"RIFF" || &data[8..12] != b"WAVE" {
        return Err("not a WAV file".into());
    }
    let (mut offset, mut format) = (12, None);
    while offset + 8 <= data.len() {
        let id = &data[offset..offset + 4];
        let size = u32::from_le_bytes(data[offset + 4..offset + 8].try_into().unwrap()) as usize;
        let body = &data[offset + 8..(offset + 8 + size).min(data.len())];
        if id == b"fmt " && body.len() >= 16 {
            let kind = u16::from_le_bytes([body[0], body[1]]);
            let channels = u16::from_le_bytes([body[2], body[3]]);
            let rate = u32::from_le_bytes(body[4..8].try_into().unwrap());
            let bits = u16::from_le_bytes([body[14], body[15]]);
            if kind != 1 || bits != 16 || channels == 0 || rate == 0 {
                return Err("unsupported WAV format".into());
            }
            format = Some((channels, rate));
        } else if id == b"data" {
            let (channels, rate) = format.ok_or("WAV data before format")?;
            let samples = body.chunks_exact(2).map(|pair| i16::from_le_bytes([pair[0], pair[1]]) as f32 / 32768.0).collect();
            return Ok(Pcm { samples, rate, channels });
        }
        offset += 8 + size + (size & 1);
    }
    Err("WAV without data".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wav(rate: u32, samples: &[i16]) -> Vec<u8> {
        let mut out = b"RIFF".to_vec();
        out.extend(((36 + samples.len() * 2) as u32).to_le_bytes());
        out.extend(b"WAVEfmt ");
        out.extend(16u32.to_le_bytes());
        out.extend(1u16.to_le_bytes());
        out.extend(1u16.to_le_bytes());
        out.extend(rate.to_le_bytes());
        out.extend((rate * 2).to_le_bytes());
        out.extend(2u16.to_le_bytes());
        out.extend(16u16.to_le_bytes());
        out.extend(b"data");
        out.extend(((samples.len() * 2) as u32).to_le_bytes());
        for sample in samples {
            out.extend(sample.to_le_bytes());
        }
        out
    }

    #[test]
    fn pcm16_mono_round_trip() {
        let pcm = decode(&wav(48000, &[0, 16384, -32768])).unwrap();
        assert_eq!((pcm.rate, pcm.channels), (48000, 1));
        assert_eq!(pcm.samples, vec![0.0, 0.5, -1.0]);
        assert!(decode(b"RIFF....WAVE").is_err());
        assert!(decode(b"not audio").is_err());
    }
}
