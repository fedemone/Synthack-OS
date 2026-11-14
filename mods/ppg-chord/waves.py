"""Forme d'onda "stile PPG" per SY CHORD: progettate qui, nel FORMATO delle onde PPG Wave 2.x.

Formato PPG (come lo documenta wave-stuff di J. Wieczorek): un'onda e' fatta di 64 campioni a
8 bit senza segno (centro 128) per MEZZO ciclo; la seconda meta' e' la prima letta al contrario e
invertita (`~w[127 - p]`). Quindi 128 campioni per ciclo, simmetria dispari attorno al centro del
ciclo, e la grana dei campioni a 8 bit. Il sapore "PPG" viene molto da qui.

Le onde in WAVES sono nostre (spettri scritti a mano). In alternativa from_ppg_rom() legge una
copia LOCALE dei dati di wave-stuff (data/ppg_data.c) che l'utente mette in local/ (git-ignored):
quei byte non stanno nel repo.

Uscita: un banco di 31 frame (256 campioni + guardia, int32) per i valori WAVE 4, 8 ... 124 di
SY CHORD; SY CHORD interpola fra frame vicini, quindi girare WAVE scorre la wavetable come sul PPG.
Formato del banco: docs/audio-path.md (da syntakt-firmware-workbench).
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

HALF, CYCLE, TABLE = 64, 128, 512
H = np.arange(1, HALF)                     # armoniche 1..63 (la 64 sarebbe la Nyquist di 128 campioni)


def _gauss(h: np.ndarray, center: float, width: float) -> np.ndarray:
    return np.exp(-0.5 * ((h - center) / width) ** 2)


def _rolloff(h: np.ndarray, corner: float, slope: float = 4.0) -> np.ndarray:
    """Taglio morbido sopra 'corner' (nessun gradino: niente ringing)."""
    return 1.0 / (1.0 + (h / corner) ** slope)


def _sync_spectrum(ratio: float) -> np.ndarray:
    """Modulo delle armoniche di un dente di sega 'slave' risincronizzato a ogni ciclo (hard sync)."""
    t = (np.arange(4096) + 0.5) / 4096
    slave = 2.0 * ((t * ratio) % 1.0) - 1.0
    a = np.abs(np.fft.rfft(slave))[1:HALF] / 2048
    a[0] = max(a[0], 0.6 * a.max())                  # fondamentale piena: l'intonazione resta chiara negli accordi
    return a


# --- spettri (modulo per armonica 1..63). Obiettivo: synth-pop / EBM anni '80, suono digitale
# brillante, "vuoto" o nasale, che resta definito negli accordi.
SPECTRA: dict[str, tuple[str, Callable[[], np.ndarray]]] = {
    "hollow": ("dispari + formante sulla 7a: quadra nasale e vuota, pad e arpeggi",
               lambda: (H % 2 == 1) / H * (1 + 2.5 * _gauss(H, 7, 2)) * _rolloff(H, 36)),
    "brass": ("dente di sega con picco 5a-7a: stab di ottoni digitali",
              lambda: 1 / H * (1 + 1.8 * _gauss(H, 6, 2.5)) * _rolloff(H, 40)),
    "vox": ("tre formanti fisse (3a-4a, 9a-10a, 19a): coro 'aah' digitale",
            lambda: H ** -0.6 * (0.12 + _gauss(H, 3.5, 1.2) + 0.7 * _gauss(H, 9.5, 2)
                                 + 0.35 * _gauss(H, 19, 3)) * _rolloff(H, 32)),
    "glass": ("armoniche sparse 1-2-5-9-14-23-31: campana / vetro metallico",
              lambda: np.array([{1: 1.0, 2: 0.35, 5: 0.5, 9: 0.4, 14: 0.3, 23: 0.22, 31: 0.12}.get(int(h), 0.0)
                                for h in H])),
    "reso": ("dente di sega in un passa-basso risonante fermo sulla 12a: lo 'sweep' congelato",
             lambda: 1 / H / np.sqrt((1 - (H / 12) ** 2) ** 2 + (H / (12 * 5)) ** 2) * _rolloff(H, 20, 6)),
    "sync": ("hard sync, rapporto 3.7: aggressivo, lead e bassi EBM",
             lambda: _sync_spectrum(3.7) * _rolloff(H, 44)),
    "organ": ("registri 1-2-3-4-6-8: organo digitale pulito, accordi larghi",
              lambda: np.array([{1: 1.0, 2: 0.8, 3: 0.6, 4: 0.5, 6: 0.35, 8: 0.25}.get(int(h), 0.0)
                                for h in H])),
}


@dataclass(frozen=True)
class Wave:
    name: str
    cycle: np.ndarray        # 128 campioni float, ciclo PPG gia' espanso (dopo la quantizzazione)


def _odd_cycle(amps: np.ndarray, signs: np.ndarray) -> np.ndarray:
    """Ciclo di 128 campioni con x[n] = -x[127-n] (la simmetria delle onde PPG)."""
    u = (np.arange(CYCLE) - (CYCLE - 1) / 2) / CYCLE
    return (amps * signs) @ np.sin(2 * np.pi * np.outer(H, u))


def _best_signs(name: str, amps: np.ndarray, tries: int = 3000) -> np.ndarray:
    """Segni delle armoniche che minimizzano il fattore di cresta (piu' volume a parita' di picco).

    Il timbro dipende dal modulo; i segni decidono la forma, quindi il picco. Ricerca casuale con
    seme fisso (risultato riproducibile) e poi miglioramento a un segno per volta.
    """
    rng = np.random.default_rng(zlib.crc32(name.encode()))
    crest = lambda s: np.max(np.abs(c := _odd_cycle(amps, s))) / (np.sqrt(np.mean(c ** 2)) + 1e-12)  # noqa: E731
    best = np.ones_like(amps)
    best_c = crest(best)
    for _ in range(tries):
        s = rng.choice((-1.0, 1.0), size=amps.size)
        if (c := crest(s)) < best_c:
            best, best_c = s, c
    improved = True
    while improved:
        improved = False
        for k in np.nonzero(amps)[0]:
            s = best.copy()
            s[k] = -s[k]
            if (c := crest(s)) < best_c - 1e-9:
                best, best_c, improved = s, c, True
    return best


def ppg_expand(half: np.ndarray) -> np.ndarray:
    """64 byte (0..255) -> ciclo di 128 campioni centrati: seconda meta' = ~half[127-p]."""
    half = np.asarray(half, dtype=np.int64)
    if half.shape != (HALF,) or half.min() < 0 or half.max() > 255:
        raise ValueError("servono 64 campioni a 8 bit senza segno")
    full = np.concatenate([half, 255 - half[::-1]])
    return full.astype(np.float64) - 128.0


def design(name: str, bits: int = 8) -> Wave:
    """Una delle onde di SPECTRA, quantizzata nel formato PPG (bits=8) o quasi pulita (bits=16)."""
    if name not in SPECTRA:
        raise KeyError(f"onda sconosciuta '{name}': {', '.join(SPECTRA)}")
    amps = SPECTRA[name][1]().astype(np.float64)
    x = _odd_cycle(amps, _best_signs(name, amps))
    x /= np.max(np.abs(x))
    if bits == 8:
        half = np.clip(np.round(128 + 127 * x[:HALF]), 0, 255)
        return Wave(name, ppg_expand(half))
    q = float(2 ** (bits - 1) - 1)
    return Wave(name, np.round(x * q) / q * 128)


def _c_array(text: str, name: str) -> list[int]:
    m = re.search(name + r"\s*\[[^\]]*\]\s*=\s*\{(.*?)\}", text, re.S)
    if not m:
        raise ValueError(f"array '{name}' non trovato")
    body = re.sub(r"/\*.*?\*/|//[^\n]*", "", m.group(1), flags=re.S)
    return [int(v, 0) for v in re.findall(r"0[xX][0-9a-fA-F]+|\d+", body)]


def parse_ppg_rom(path: Path) -> np.ndarray:
    """Legge `ppg_waveforms[] = {...}` da una copia locale di wave-stuff/data/ppg_data.c -> (N, 64)."""
    vals = _c_array(Path(path).read_text(encoding="utf-8", errors="replace"), "ppg_waveforms")
    if len(vals) < HALF or len(vals) % HALF or max(vals) > 255:
        raise ValueError(f"{path}: {len(vals)} valori, attesi multipli di 64 byte")
    return np.array(vals, dtype=np.int64).reshape(-1, HALF)


SLOTS = 61                                 # posizioni usate di una wavetable (0..60), come in wave-stuff


def parse_ppg_wavetables(path: Path) -> list[list[tuple[int, int]]]:
    """`ppg_wavetable[]`: per ogni tabella un byte (ignorato), poi coppie (onda, posizione) fino
    alla posizione 60. Le posizioni fra due onde chiave si interpolano (ppg_wt_dump.c di wave-stuff).
    Ritorna, per tabella, la lista delle chiavi [(posizione, onda), ...].
    Dopo l'ultima tabella il file ha altri byte (non tabelle): ci si ferma al primo record che non
    e' una tabella valida (posizioni da 0, crescenti, fino a 60 esatto)."""
    data = _c_array(Path(path).read_text(encoding="utf-8", errors="replace"), "ppg_wavetable")
    tables, i = [], 0
    while i + 2 < len(data):
        i += 1
        keys = []
        while i + 1 < len(data):
            wave, pos = data[i], data[i + 1]
            i += 2
            keys.append((pos, wave))
            if pos >= SLOTS - 1:
                break
        pos = [p for p, _ in keys]
        if not pos or pos[0] != 0 or pos[-1] != SLOTS - 1 or pos != sorted(pos):
            break
        tables.append(sorted(dict(keys).items()))
    return tables


def table_slot_cycle(rom: np.ndarray, keys: list[tuple[int, int]], slot: int) -> tuple[np.ndarray, str]:
    """Ciclo (128 campioni centrati) alla posizione 'slot' di una wavetable: interpolazione lineare
    fra le due onde chiave vicine, come fa il PPG scorrendo la tabella."""
    if not 0 <= slot < SLOTS:
        raise ValueError(f"posizione {slot} fuori da 0..{SLOTS - 1}")
    left = max((k for k in keys if k[0] <= slot), default=keys[0])
    right = min((k for k in keys if k[0] >= slot), default=keys[-1])
    a = ppg_expand(rom[left[1]])
    if right[0] == left[0]:
        return a, f"onda {left[1]}"
    t = (slot - left[0]) / (right[0] - left[0])
    return (1 - t) * a + t * ppg_expand(rom[right[1]]), f"{1 - t:.2f}*onda {left[1]} + {t:.2f}*onda {right[1]}"


def from_ppg_rom(path: Path, index: int) -> Wave:
    rom = parse_ppg_rom(path)
    if not 0 <= index < len(rom):
        raise ValueError(f"onda {index} fuori dalla ROM (0..{len(rom) - 1})")
    return Wave(f"ppg{index:03d}", ppg_expand(rom[index]))


def from_ppg_table(path: Path, table: int, slot: int) -> tuple[Wave, str]:
    rom, tables = parse_ppg_rom(path), parse_ppg_wavetables(path)
    if not 0 <= table < len(tables):
        raise ValueError(f"wavetable {table} fuori da 0..{len(tables) - 1}")
    cycle, how = table_slot_cycle(rom, tables[table], slot)
    return Wave(f"wt{table:02d}s{slot:02d}", cycle), how


# --- banco di SY CHORD (formato misurato da syntakt-firmware-workbench, Bezronczek, MIT)
FRAMES, FRAME_SAMPLES = 31, 256            # WAVE 4, 8 ... 124; 256 campioni + 1 di guardia
PEAK = 0x7FFF0000                          # picco di ogni frame, come i frame stock
TABLE_POSITIONS = list(range(0, SLOTS, 2))  # 0, 2 ... 60: 31 posizioni = 31 frame, esatto
assert len(TABLE_POSITIONS) == FRAMES


def condition(cycle: np.ndarray, harmonics: int = 40) -> np.ndarray:
    """Ciclo PPG (128) -> frame di 256 campioni: banda limitata, ruotato di mezzo ciclo, picco 1.

    Le onde PPG sono dispari attorno a meta' ciclo (x[n] = -x[127-n] - 1): la versione a banda
    limitata passa per zero ESATTAMENTE a meta' ciclo. Ruotando di mezzo ciclo ogni frame inizia da
    0 (come vuole il formato, y[0] = 0) e tutti i frame hanno la stessa fase: SY CHORD interpola fra
    frame vicini senza cancellazioni.
    """
    if not 1 <= harmonics <= HALF - 1:
        raise ValueError(f"harmonics: 1..{HALF - 1} (le onde PPG non hanno armoniche oltre la 63a)")
    spec = np.fft.rfft(np.asarray(cycle, dtype=np.float64))
    spec[0] = 0
    spec[harmonics + 1:] = 0
    k = np.arange(spec.size)
    spec *= np.exp(2j * np.pi * k * ((CYCLE - 1) / 2) / CYCLE)   # x(t + 63.5): lo zero di simmetria va a t = 0
    big = np.zeros(FRAME_SAMPLES // 2 + 1, dtype=complex)
    big[:spec.size] = spec
    y = np.fft.irfft(big, n=FRAME_SAMPLES)
    peak = np.max(np.abs(y))
    if peak < 1e-9:
        raise ValueError("onda vuota")
    return y / peak


def bank(cycles: list[np.ndarray], harmonics: int = 40) -> np.ndarray:
    """31 cicli PPG -> (31, 256) float. Una sola polarita' per tutto il banco: in salita da 0
    (pendenza media positiva), come i frame stock; invertire tutto il banco non si sente."""
    if len(cycles) != FRAMES:
        raise ValueError(f"servono {FRAMES} cicli, non {len(cycles)}")
    frames = np.array([condition(c, harmonics) for c in cycles])
    if np.sum(frames[:, 1] - frames[:, -1]) < 0:
        frames = -frames
    frames[:, 0] = 0.0
    return frames


def bank_q31(frames: np.ndarray) -> np.ndarray:
    """(31, 256) float -> (31, 257) int32: picco PEAK, campione di guardia = y[0] = 0."""
    q = np.round(np.asarray(frames) * PEAK).astype(np.int64)
    q[:, 0] = 0
    return np.concatenate([q, q[:, :1]], axis=1)


def table_cycles(rom: np.ndarray, keys: list[tuple[int, int]]) -> list[np.ndarray]:
    """Le 31 posizioni pari di una wavetable PPG (interpolate fra le chiavi come fa il PPG)."""
    return [table_slot_cycle(rom, keys, p)[0] for p in TABLE_POSITIONS]


def designed_cycles(names: list[str] | None = None) -> list[np.ndarray]:
    """Wavetable fatta con le onde progettate: chiavi distribuite su 0..60, interpolate."""
    names = names or list(SPECTRA)
    if len(names) < 2:
        raise ValueError("servono almeno due onde")
    cyc = [design(n).cycle for n in names]
    pos = np.linspace(0, SLOTS - 1, len(names))
    out = []
    for p in TABLE_POSITIONS:
        j = min(int(np.searchsorted(pos, p, side="right")) - 1, len(names) - 2)
        t = (p - pos[j]) / (pos[j + 1] - pos[j])
        out.append((1 - t) * cyc[j] + t * cyc[j + 1])
    return out


def harmonics(table: np.ndarray, n: int = 12) -> list[tuple[int, float]]:
    """Le n armoniche piu' forti: (numero, livello in dB rispetto alla piu' forte)."""
    mag = np.abs(np.fft.rfft(np.asarray(table, dtype=np.float64)))[1:]
    order = np.argsort(mag)[::-1][:n]
    ref = mag[order[0]] or 1.0
    return [(int(k) + 1, float(20 * np.log10(mag[k] / ref + 1e-12))) for k in sorted(order)]
