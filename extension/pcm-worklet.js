// Resampling approach adapted from Avorythm's MIT-licensed pcm-worklet.js.
class Capture extends AudioWorkletProcessor {
  constructor() {
    super(); this.pending = []; this.position = 0; this.chunk = new Int16Array(1600); this.index = 0;
  }
  process(inputs, outputs) {
    const channels = inputs[0];
    if (!channels?.length) return true;
    for (let i = 0; i < channels[0].length; i++) {
      let mono = 0;
      for (const channel of channels) mono += channel[i] || 0;
      this.pending.push(mono / channels.length);
    }
    while (this.position + 1 < this.pending.length) {
      const left = Math.floor(this.position), fraction = this.position - left;
      const value = this.pending[left] * (1 - fraction) + this.pending[left + 1] * fraction;
      this.chunk[this.index++] = Math.max(-32768, Math.min(32767, Math.round(value * 32767)));
      this.position += sampleRate / 16000;
      if (this.index === this.chunk.length) {
        this.port.postMessage(this.chunk.buffer, [this.chunk.buffer]);
        this.chunk = new Int16Array(1600); this.index = 0;
      }
    }
    const consumed = Math.floor(this.position);
    this.pending.splice(0, consumed); this.position -= consumed;
    // The worklet intentionally outputs silence: the user hears only the delayed player.
    for (const channel of outputs[0] || []) channel.fill(0);
    return true;
  }
}
registerProcessor('synchro-capture', Capture);
