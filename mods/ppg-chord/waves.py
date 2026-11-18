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


def _zoh_spectrum(cycle: np.ndarray, harmonics: int) -> np.ndarray:
    """Armoniche 1..harmonics del ciclo PPG letto "a gradini" (ogni campione tenuto per tutta la sua
    cella, come un lettore a 8 bit senza interpolazione): oltre la 63a compaiono le immagini
    (128 - h, 128 + h ...) attenuate dal sinc. E' la "sparkle" digitale del PPG."""
    c = np.asarray(cycle, dtype=np.float64)
    h = np.arange(1, harmonics + 1)
    n = np.arange(CYCLE) + 0.5                               # centro di ogni cella
    spec = np.exp(-2j * np.pi * np.outer(h, n) / CYCLE) @ c / CYCLE
    return spec * np.sinc(h / CYCLE)


def condition(cycle: np.ndarray, harmonics: int = 40, grit: bool = False) -> np.ndarray:
    """Ciclo PPG (128) -> frame di 256 campioni: banda limitata, ruotato di mezzo ciclo, picco 1.

    Le onde PPG sono dispari attorno a meta' ciclo (x[n] = -x[127-n] - 1): la versione a banda
    limitata passa per zero ESATTAMENTE a meta' ciclo. Ruotando di mezzo ciclo ogni frame inizia da
    0 (come vuole il formato, y[0] = 0) e tutti i frame hanno la stessa fase: SY CHORD interpola fra
    frame vicini senza cancellazioni.
    """
    if grit:
        # a gradini: le celle sono [n, n+1) e la simmetria e' esattamente a meta' ciclo (cella 64)
        if not 1 <= harmonics <= FRAME_SAMPLES // 2 - 1:
            raise ValueError(f"harmonics con grit: 1..{FRAME_SAMPLES // 2 - 1}")
        spec = _zoh_spectrum(cycle, harmonics) * (-1.0) ** np.arange(1, harmonics + 1)   # mezzo ciclo
        big = np.zeros(FRAME_SAMPLES // 2 + 1, dtype=complex)
        big[1:harmonics + 1] = spec * FRAME_SAMPLES
        y = np.fft.irfft(big, n=FRAME_SAMPLES)
        peak = np.max(np.abs(y))
        if peak < 1e-9:
            raise ValueError("onda vuota")
        return y / peak
    if not 1 <= harmonics <= HALF - 1:
        raise ValueError(f"harmonics: 1..{HALF - 1} (le onde PPG non hanno armoniche oltre la 63a; "
                         "con --grit fino a 127)")
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


def bank(cycles: list[np.ndarray], harmonics: int = 40, grit: bool = False) -> np.ndarray:
    """31 cicli PPG -> (31, 256) float. Una sola polarita' per tutto il banco: in salita da 0
    (pendenza media positiva), come i frame stock; invertire tutto il banco non si sente."""
    if len(cycles) != FRAMES:
        raise ValueError(f"servono {FRAMES} cicli, non {len(cycles)}")
    frames = np.array([condition(c, harmonics, grit) for c in cycles])
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


# --- banco "curato": 31 onde scelte, non una wavetable --------------------------------------
# Le onde della ROM sono molte di piu' dei 31 frame. Si scartano vuote, doppioni e forme di base
# (seno, dente di sega, quadra, triangolo, impulsi); fra le rimanenti si scelgono le 31 piu'
# diverse fra loro e si ordinano da scure a brillanti: girare WAVE diventa una scala di colori.

BAND = 40                                      # armoniche usate per confrontare gli spettri
_HB = np.arange(1, BAND + 1)
BASIC = {"sine": (_HB == 1) * 1.0, "saw": 1 / _HB, "square": (_HB % 2 == 1) / _HB,
         "triangle": (_HB % 2 == 1) / _HB ** 2,
         **{f"pulse {round(100 * d)}%": np.abs(np.sin(np.pi * _HB * d)) / _HB
            for d in (0.0625, 0.125, 0.25, 0.375)}}
BASIC = {k: v / np.linalg.norm(v) for k, v in BASIC.items()}


def spectrum(cycle: np.ndarray) -> np.ndarray:
    """Modulo delle armoniche 1..40, norma 1 (qualunque lunghezza di ciclo)."""
    m = np.abs(np.fft.rfft(np.asarray(cycle, dtype=np.float64)))[1:BAND + 1]
    return m / (np.linalg.norm(m) + 1e-12)


def basic_shape(cycle: np.ndarray, threshold: float = 0.95) -> str | None:
    """Nome della forma di base a cui lo spettro somiglia (coseno >= threshold), o None."""
    s = spectrum(cycle)
    name, sim = max(((k, float(s @ v)) for k, v in BASIC.items()), key=lambda kv: kv[1])
    return name if sim >= threshold else None


def brightness(cycle: np.ndarray) -> float:
    """Baricentro spettrale in armoniche."""
    m = np.abs(np.fft.rfft(np.asarray(cycle, dtype=np.float64)))[1:]
    return float((np.arange(1, m.size + 1) * m).sum() / (m.sum() or 1))


def body(cycle: np.ndarray, n: int = 3) -> float:
    """Quota dell'energia nelle armoniche 1..n (su 1..40): il "corpo" dell'onda.

    Misurato su hardware emulato: un banco con poco corpo (onde quasi senza fondamentale) suona
    piu' corto e piu' piano, perche' il filtro passa-basso che si chiude toglie quasi tutto. Banco
    stock: mediana 0.96; banco di MAX: 0.76; banco "piu' diverso" senza vincolo: 0.29.
    """
    mag = np.abs(np.fft.rfft(np.asarray(cycle, dtype=np.float64)))[1:BAND + 1]
    e = mag ** 2
    return float(e[:n].sum() / (e.sum() or 1))


def density(cycle: np.ndarray, db: float = -30.0) -> int:
    """Quante armoniche (fra le prime 40) stanno entro `db` dalla piu' forte. Organo a registri:
    ~4-8; dente di sega: 31. I timbri synth-pop/EBM (sega, impulsi, sync, formanti) sono densi."""
    m = np.abs(np.fft.rfft(np.asarray(cycle, dtype=np.float64)))[1:BAND + 1]
    return int(np.sum(20 * np.log10(m / (m.max() or 1) + 1e-12) > db))


def candidates(rom: np.ndarray, threshold: float = 0.95, min_body: float = 0.0,
               min_density: int = 0) -> list[int]:
    """Indici delle onde ROM non vuote, non doppie, non forme di base, con corpo >= min_body e
    almeno min_density armoniche forti."""
    seen, out = set(), []
    for i, h in enumerate(rom):
        key = h.tobytes()
        if np.ptp(h) < 4 or key in seen:
            continue
        seen.add(key)
        c = ppg_expand(h)
        if basic_shape(c, threshold) is None and body(c) >= min_body and density(c) >= min_density:
            out.append(i)
    return out


def most_diverse(cycles: list[np.ndarray], n: int) -> list[int]:
    """n indici scelti per massima diversita' (farthest-point sui radicali degli spettri),
    partendo dall'onda piu' lontana da tutte le forme di base. Deterministico."""
    feats = np.array([np.sqrt(spectrum(c)) for c in cycles])
    feats /= np.linalg.norm(feats, axis=1, keepdims=True)
    basics = np.array([np.sqrt(v) / np.linalg.norm(np.sqrt(v)) for v in BASIC.values()])
    first = int(np.argmin((feats @ basics.T).max(axis=1)))
    picked = [first]
    dist = 1 - feats @ feats[first]
    while len(picked) < min(n, len(cycles)):
        k = int(np.argmax(dist))
        picked.append(k)
        dist = np.minimum(dist, 1 - feats @ feats[k])
    return picked


# Default di --curated. Su hardware: senza corpo il banco suonava corto (filtro); con il solo corpo
# (>= 0.7) diventava un organo (6 armoniche forti per frame). Densita' + un po' di corpo.
MIN_BODY = 0.3
MIN_DENSITY = 15


def curate(rom: np.ndarray, n: int = FRAMES, threshold: float = 0.95, min_body: float = MIN_BODY,
           min_density: int = MIN_DENSITY) -> list[int]:
    """Le n onde ROM piu' diverse fra quelle non di base, dense e con corpo."""
    cand = candidates(rom, threshold, min_body, min_density)
    if len(cand) < n:
        raise ValueError(f"solo {len(cand)} onde con corpo >= {min_body} e densita' >= {min_density}: "
                         "abbassa --min-body / --min-density o usa --fill-max")
    cyc = [ppg_expand(rom[i]) for i in cand]
    picked = [cand[k] for k in most_diverse(cyc, n)]
    return sorted(picked, key=lambda i: brightness(ppg_expand(rom[i])))


def condition_frame(frame: np.ndarray, harmonics: int = 40) -> np.ndarray:
    """Un frame gia' nel formato del banco (256 campioni, parte da zero) con lo stesso limite di
    banda e picco 1: per mescolare frame di MAX con onde PPG."""
    spec = np.fft.rfft(np.asarray(frame, dtype=np.float64)[:FRAME_SAMPLES])
    spec[0] = 0
    spec[harmonics + 1:] = 0
    y = np.fft.irfft(spec, n=FRAME_SAMPLES)
    return y / np.max(np.abs(y))


def mixed_bank(frames: list[np.ndarray]) -> np.ndarray:
    """(31, 256) da frame gia' condizionati, di origine diversa. Polarita' scelta frame per frame
    per somigliare al precedente: l'interpolazione di SY CHORD fra onde diverse non si svuota."""
    if len(frames) != FRAMES:
        raise ValueError(f"servono {FRAMES} frame, non {len(frames)}")
    out = [np.asarray(frames[0], dtype=np.float64)]
    for f in frames[1:]:
        f = np.asarray(f, dtype=np.float64)
        out.append(f if f @ out[-1] >= 0 else -f)
    bank_ = np.array(out)
    bank_[:, 0] = 0.0
    return bank_


def _similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Somiglianza di forma, senza segno (la polarita' la sceglie mixed_bank)."""
    return abs(float(a @ b)) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12)


def order_smooth(frames: list[np.ndarray]) -> list[int]:
    """Ordine dei frame che rende ogni frame simile al successivo, partendo dal piu' scuro:
    catena del vicino piu' simile, poi 2-opt. Le miscele di SY CHORD fra frame vicini restano
    musicali (sui dati PPG: correlazione mediana fra vicini da ~0.25 a ~0.6)."""
    n = len(frames)
    sim = np.array([[_similarity(frames[i], frames[j]) for j in range(n)] for i in range(n)])
    left = set(range(n))
    order = [min(left, key=lambda i: brightness(frames[i]))]
    left.remove(order[0])
    while left:
        nxt = max(sorted(left), key=lambda j: sim[order[-1], j])
        order.append(nxt)
        left.remove(nxt)
    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                a, b, c = order[i - 1], order[i], order[j]
                d = order[j + 1] if j + 1 < n else None
                old = sim[a, b] + (sim[c, d] if d is not None else 0)
                new = sim[a, c] + (sim[b, d] if d is not None else 0)
                if new > old + 1e-9:
                    order[i:j + 1] = order[i:j + 1][::-1]
                    improved = True
    return order
