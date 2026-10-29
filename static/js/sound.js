// Sons da entrada no tema retrô: o bipe da BIOS, o HD lendo a cada linha e um acorde de abertura. Tudo sintetizado
// aqui (nada de arquivo de áudio; o acorde é nosso, não o de nenhum sistema). O navegador pode não deixar tocar antes
// de alguém apertar um botão: aí a entrada fica muda, e "Reiniciar o Sofá" (um clique) toca normalmente.
const KEY = "iptv.sound";
const VOLUME = 0.22;
let ctx = null;

export const soundOn = () => { try { return localStorage.getItem(KEY) !== "off"; } catch { return true; } };
export const soundLabel = () => (soundOn() ? "Desligar o som da entrada" : "Ligar o som da entrada");

export function toggleSound() {
  try { localStorage.setItem(KEY, soundOn() ? "off" : "on"); } catch { /* sem armazenamento: fica como está */ }
}

function audio() {
  if (!soundOn()) return null;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) return null;
  if (!ctx) ctx = new Ctx();
  if (ctx.state === "suspended") ctx.resume().catch(() => {});
  return ctx.state === "closed" ? null : ctx;
}

/** Uma nota com ataque e queda (o "envelope"), para não estalar. */
function tone(a, { freq, type = "triangle", at = 0, len = 0.3, gain = VOLUME, detune = 0 }) {
  const t = a.currentTime + at;
  const osc = a.createOscillator(), env = a.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  osc.detune.value = detune;
  env.gain.setValueAtTime(0.0001, t);
  env.gain.exponentialRampToValueAtTime(gain, t + Math.min(0.04, len / 4));
  env.gain.exponentialRampToValueAtTime(0.0001, t + len);
  osc.connect(env).connect(a.destination);
  osc.start(t);
  osc.stop(t + len + 0.05);
}

/** O bipe curto do alto-falante do gabinete: "passou no teste". */
export function postBeep() {
  const a = audio();
  if (a) tone(a, { freq: 988, type: "square", len: 0.16, gain: VOLUME * 0.35 });
}

/** O HD procurando: um chiado curtinho e abafado. */
export function diskSeek() {
  const a = audio();
  if (!a) return;
  const len = 0.05 + Math.random() * 0.05;
  const buffer = a.createBuffer(1, Math.floor(a.sampleRate * len), a.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < data.length; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / data.length);
  const noise = a.createBufferSource(), band = a.createBiquadFilter(), env = a.createGain();
  noise.buffer = buffer;
  band.type = "bandpass";
  band.frequency.value = 1800 + Math.random() * 1400;
  band.Q.value = 3;
  env.gain.value = VOLUME * 0.5;
  noise.connect(band).connect(env).connect(a.destination);
  noise.start();
}

/** O acorde de abertura: notas que entram uma depois da outra e somem devagar, como as aberturas dos anos 90. */
export function startupChime() {
  const a = audio();
  if (!a) return;
  // Lá bemol maior com nona (Ab, Eb, C, Bb) e um brilho agudo no fim; cada nota em dupla, levemente desafinada
  [[207.65, 0], [311.13, 0.14], [523.25, 0.28], [932.33, 0.42], [1567.98, 0.9]].forEach(([freq, at], i) => {
    const len = i === 4 ? 1.6 : 3.2 - at;
    tone(a, { freq, at, len, gain: VOLUME * (i === 4 ? 0.35 : 0.55) });
    tone(a, { freq, at, len, gain: VOLUME * 0.3, type: "sine", detune: 7 });
  });
}
