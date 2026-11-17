"""Wavetable progettate per synth-pop / EBM anni '80, 31 frame ciascuna, nel formato del banco.

Ogni tabella e' una famiglia d'onde con un parametro p che va da 0 a 1 lungo i 31 frame (WAVE 4 ->
124): girare WAVE (o un LFO in modalita' ONE su WAVE, come l'inviluppo sulla wavetable del PPG)
scorre la famiglia con continuita'.

- reso   dente di sega in un passa-basso risonante che si apre: bassi e lead EBM, lo "sweep" PPG
- pwm    impulso dal 50 % al 5 %: pad e bassi a modulazione d'ampiezza d'impulso
- vowel  vocali A E I O U (formanti): cori digitali, ottimo con l'unisono di SY CHORD
- sync   hard sync, rapporto 1 -> 8, piu' il master: lead aggressivi
- fold   wavefolder, guadagno 1 -> 12: digitale e ruvido
- brass  FM 1:1, indice 0 -> 7: ottoni digitali che si aprono
- metal  FM 1:3, indice 0 -> 6: campane e metalli digitali
- ebm    zone di 5-7 frame da reso, pwm, vowel, sync, metal: molta varieta' in un solo banco

Tutto e' generato qui (nessun dato di terzi). Passi per ogni famiglia (family()):

1. spettro della forma per ogni p, limitato a `harmonics` armoniche;
2. volume (loud=True): stesse ampiezze armoniche, fasi scelte per un picco basso (_low_crest),
   partendo dalle fasi del frame precedente e restando simili a lui (_loudest_continuous):
   stesso timbro, ~+2..+4 dB a parita' di picco, morph continuo;
3. ogni frame parte da uno zero in salita (y[0] = 0, come i frame stock); il punto di partenza di
   tutti i frame (dritti o capovolti) e' scelto insieme (_align_chain) per la massima somiglianza
   fra vicini: l'interpolazione di SY CHORD fra frame non si svuota.

Nel banco ebm le zone reso, sync e metal passano anche da deformant(): le "gobbe" dello spettro
che si muovono con WAVE suonavano come vocali; restano solo nella zona vowel.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

import waves

FINE = 8192                         # campioni per ciclo per generare le forme nel tempo
DEFAULT_HARMONICS = 64              # piu' brillante delle onde PPG (40); 1..127


def _saw_spectrum(h: np.ndarray) -> np.ndarray:
    return 1.0 / h


def _from_time(fn: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """Spettro complesso (indici 0..FINE/2) di una forma definita nel tempo su un ciclo."""
    t = np.arange(FINE) / FINE
    return np.fft.rfft(fn(t))


def _from_sine_series(b: np.ndarray) -> np.ndarray:
    """Spettro complesso di sum_h b[h-1] sin(2 pi h t): dispari attorno a 0, passa per 0 a t = 0."""
    spec = np.zeros(FINE // 2 + 1, dtype=complex)
    spec[1:b.size + 1] = -0.5j * FINE * b
    return spec


def _frame(spec: np.ndarray, harmonics: int, prev: np.ndarray | None) -> np.ndarray:
    """Spettro -> frame di 256 campioni: banda limitata, partenza su uno zero in salita, picco 1.

    Primo frame: lo zero in salita piu' vicino all'inizio del ciclo. Poi: fra tutti gli zeri in
    salita, della forma e della forma capovolta (che da sola suona identica), quello che rende il
    frame piu' simile al precedente: l'interpolazione di SY CHORD fra frame vicini non si svuota."""
    spec = spec.copy()
    spec[0] = 0
    spec[harmonics + 1:] = 0
    k = np.arange(harmonics + 1)
    best, best_score = None, -np.inf
    for sign in ((1.0,) if prev is None else (1.0, -1.0)):
        sp = sign * spec
        fine = np.fft.irfft(sp, n=FINE)
        for i in np.nonzero((fine <= 0) & (np.roll(fine, -1) > 0))[0]:
            a, b = fine[i], fine[(i + 1) % FINE]
            tau = (i + a / (a - b)) / FINE                   # stima lineare, poi Newton sul segnale
            for _ in range(6):                               # a banda limitata: zero esatto
                ph = sp[:harmonics + 1] * np.exp(2j * np.pi * k * tau) / FINE * 2
                val, slope = ph[1:].real.sum(), (-(2 * np.pi * k[1:]) * ph[1:].imag).sum()
                tau -= val / slope
            tau %= 1.0
            small = np.zeros(waves.FRAME_SAMPLES // 2 + 1, dtype=complex)
            small[:harmonics + 1] = sp[:harmonics + 1] * np.exp(2j * np.pi * k * tau)
            y = np.fft.irfft(small, n=waves.FRAME_SAMPLES)
            score = -min(tau, 1 - tau) if prev is None else float(y @ prev) / (np.linalg.norm(y) + 1e-12)
            if score > best_score:
                best, best_score = y, score
    if best is None:
        raise ValueError("onda senza passaggi per lo zero")
    best = best / np.max(np.abs(best))
    best[0] = 0.0
    return best


def _low_crest(spec: np.ndarray, harmonics: int, start: np.ndarray | None, iters: int = 150) -> np.ndarray:
    """Stesse ampiezze armoniche, fasi scelte per un picco basso (meno "spigoli" = piu' energia a
    parita' di picco, cioe' piu' volume senza distorcere e senza cambiare il timbro).

    Proiezione alternata: si taglia la forma all'80 % del picco e si rimettono le ampiezze giuste,
    tenendo le fasi. `start` = fasi da cui partire (quelle del frame precedente): passi piccoli fra
    frame vicini, quindi il morph resta continuo."""
    n = waves.FRAME_SAMPLES
    mag = np.abs(spec[:harmonics + 1]) * (n / FINE)
    mag[0] = 0
    phase = np.angle(spec[:harmonics + 1]) if start is None else start.copy()
    full = np.zeros(n // 2 + 1, dtype=complex)
    for _ in range(iters):
        full[:harmonics + 1] = mag * np.exp(1j * phase)
        x = np.fft.irfft(full, n=n)
        lim = 0.8 * np.max(np.abs(x))
        phase = np.angle(np.fft.rfft(np.clip(x, -lim, lim))[:harmonics + 1])
    out = np.zeros(FINE // 2 + 1, dtype=complex)
    out[:harmonics + 1] = mag * np.exp(1j * phase) * (FINE / n)
    return out


def family(make: Callable[[float], np.ndarray], n: int = waves.FRAMES,
           harmonics: int = DEFAULT_HARMONICS, loud: bool = True) -> np.ndarray:
    """n frame (n, 256) da make(p) -> spettro complesso, p = 0..1. loud: fasi a picco basso
    (circa +4 dB a parita' di picco, stesso timbro), partendo ogni volta dal frame precedente."""
    if not 1 <= harmonics <= waves.FRAME_SAMPLES // 2 - 1:
        raise ValueError("harmonics: 1..127")
    frames, prev = [], None
    for p in np.linspace(0.0, 1.0, n):
        spec = make(float(p))
        if not loud:
            prev = _frame(spec, harmonics, prev)
        elif prev is None:
            prev = _frame(_low_crest(spec, harmonics, None), harmonics, None)
        else:
            prev = _loudest_continuous(spec, harmonics, prev)
        frames.append(prev)
    return _align_chain(np.array(frames), harmonics)


def _start_candidates(frame: np.ndarray, harmonics: int) -> list[np.ndarray]:
    """Tutte le versioni del frame che partono da uno zero in salita (dritte o capovolte): stesso
    suono, punto di partenza diverso. Zeri esatti sul segnale a banda limitata (Newton)."""
    n = waves.FRAME_SAMPLES
    spec = np.fft.rfft(frame)[:harmonics + 1]
    spec[0] = 0
    k = np.arange(harmonics + 1)
    full = np.zeros(FINE // 2 + 1, dtype=complex)
    out = []
    for sign in (1.0, -1.0):
        sp = sign * spec
        full[:harmonics + 1] = sp * (FINE / n)
        fine = np.fft.irfft(full, n=FINE)
        for i in np.nonzero((fine <= 0) & (np.roll(fine, -1) > 0))[0]:
            a, b = fine[i], fine[(i + 1) % FINE]
            tau = (i + a / (a - b)) / FINE
            for _ in range(6):
                ph = sp * np.exp(2j * np.pi * k * tau)
                tau -= ph[1:].real.sum() / (-(2 * np.pi * k[1:]) * ph[1:].imag).sum()
            small = np.zeros(n // 2 + 1, dtype=complex)
            small[:harmonics + 1] = sp * np.exp(2j * np.pi * k * (tau % 1.0))
            y = np.fft.irfft(small, n=n)
            y /= np.max(np.abs(y))
            y[0] = 0.0
            out.append(y)
    return out


def _align_chain(frames: np.ndarray, harmonics: int) -> np.ndarray:
    """Sceglie insieme il punto di partenza (zero in salita, dritto o capovolto) di tutti i frame,
    massimizzando la somma delle somiglianze fra vicini (programmazione dinamica): una scelta
    frame per frame puo' mettere all'angolo i frame successivi."""
    cands = [_start_candidates(f, harmonics) for f in frames]
    unit = [np.array([c / np.linalg.norm(c) for c in cs]) for cs in cands]
    first = unit[0] @ (frames[0] / np.linalg.norm(frames[0]))        # il primo resta com'era (o quasi)
    score, back = first * 1e-3, []
    for t in range(1, len(frames)):
        trans = unit[t - 1] @ unit[t].T                               # (candidati t-1) x (candidati t)
        total = score[:, None] + trans
        back.append(np.argmax(total, axis=0))
        score = np.max(total, axis=0)
    pick = [int(np.argmax(score))]
    for b in reversed(back):
        pick.append(int(b[pick[-1]]))
    pick.reverse()
    return np.array([cands[t][i] for t, i in enumerate(pick)])


MIN_NEIGHBOUR = 0.75      # somiglianza minima fra frame vicini: a meta' miscela il calo e' < 0.6 dB


def _loudest_continuous(spec: np.ndarray, harmonics: int, prev: np.ndarray) -> np.ndarray:
    """Il frame piu' forte fra varie intensita' di ottimizzazione (partendo dalle fasi del
    precedente) e il frame con le fasi originali, purche' resti simile al precedente: almeno
    MIN_NEIGHBOUR, oppure, se nessun candidato ci arriva, quasi quanto il piu' simile."""
    start = np.angle(np.fft.rfft(prev)[:harmonics + 1])
    norm_prev = np.linalg.norm(prev)

    def judge(y: np.ndarray) -> tuple[float, float]:
        return float(y @ prev) / (np.linalg.norm(y) * norm_prev + 1e-12), float(np.sqrt(np.mean(y ** 2)))

    plain = _frame(spec, harmonics, prev)
    cands = [plain] + [_frame(_low_crest(spec, harmonics, start, it), harmonics, prev) for it in (150, 60, 25, 10, 4, 0)]
    scored = [(judge(y), y) for y in cands]
    need = min(MIN_NEIGHBOUR, max(c for (c, _), _ in scored) - 0.05)
    return max((sc for sc in scored if sc[0][0] >= need - 1e-9), key=lambda sc: sc[0][1])[1]


# --- famiglie ----------------------------------------------------------------------------------

def _reso(p: float) -> np.ndarray:
    h = np.arange(1, FINE // 2 + 1)
    fc = 1.5 * (48 / 1.5) ** p                              # taglio: dalla 1.5a alla 48a armonica
    q = 5.0
    resp = 1 / np.sqrt((1 - (h / fc) ** 2) ** 2 + (h / (fc * q)) ** 2) / (1 + (h / fc) ** 2)   # 4 poli circa
    return _from_sine_series(_saw_spectrum(h) * resp)


def _pwm(p: float) -> np.ndarray:
    w = 0.5 - 0.45 * p                                       # larghezza 50 % -> 5 %
    return _from_time(lambda t: np.where(t < w, 1.0, -1.0))


# formanti delle vocali, in Hz (valori medi da letteratura fonetica), per una fondamentale di ~130 Hz
_VOWELS = {"A": (730, 1090, 2440), "E": (530, 1840, 2480), "I": (270, 2290, 3010),
           "O": (570, 840, 2410), "U": (300, 870, 2240)}
_F0 = 130.0


def _vowel(p: float) -> np.ndarray:
    seq = ["A", "E", "I", "O", "U"]
    x = p * (len(seq) - 1)
    j = min(int(x), len(seq) - 2)
    t = x - j
    f = [(1 - t) * a + t * b for a, b in zip(_VOWELS[seq[j]], _VOWELS[seq[j + 1]])]
    h = np.arange(1, FINE // 2 + 1)
    hz = h * _F0
    env = sum(g * np.exp(-0.5 * ((hz - fk) / bw) ** 2) for fk, g, bw in zip(f, (1.0, 0.7, 0.35), (90, 120, 160)))
    return _from_sine_series(h ** -0.7 * (0.06 + env))


def _sync(p: float) -> np.ndarray:
    r = 1.0 + 7.0 * p                                        # rapporto slave/master 1 -> 8
    # piu' un po' del dente di sega "master", come un lead sync classico: la fondamentale resta
    return _from_time(lambda t: 2.0 * ((t * r) % 1.0) - 1.0 + 0.45 * (2.0 * t - 1.0))


def _fold(p: float) -> np.ndarray:
    g = 1.0 + 11.0 * p
    return _from_time(lambda t: np.sin(g * np.sin(2 * np.pi * t)))


def _fm(ratio: int, top: float) -> Callable[[float], np.ndarray]:
    return lambda p: _from_time(lambda t: np.sin(2 * np.pi * t + top * p * np.sin(2 * np.pi * ratio * t)))


FAMILIES: dict[str, tuple[str, Callable[[float], np.ndarray]]] = {
    "reso": ("dente di sega in un passa-basso risonante che si apre (bassi e lead EBM)", _reso),
    "pwm": ("impulso 50 % -> 5 % (pad e bassi PWM)", _pwm),
    "vowel": ("vocali A E I O U (cori digitali; bene con l'unisono)", _vowel),
    "sync": ("hard sync, rapporto 1 -> 8, piu' il master (lead aggressivi)", _sync),
    "fold": ("wavefolder, guadagno 1 -> 12 (digitale, ruvido)", _fold),
    "brass": ("FM 1:1, indice 0 -> 7 (ottoni digitali che si aprono)", _fm(1, 7.0)),
    "metal": ("FM 1:3, indice 0 -> 6 (campane, metalli)", _fm(3, 6.0)),
}

def _trend(mag: np.ndarray, top: int = 64) -> np.ndarray:
    """Andamento liscio dello spettro: retta in scala log-log sulle armoniche 1..top non nulle."""
    h = np.arange(1, mag.size)
    sel = (h <= top) & (mag[1:] > mag[1:].max() * 1e-4)
    slope, icpt = np.polyfit(np.log(h[sel]), np.log(mag[1:][sel]), 1)
    out = np.zeros_like(mag)
    out[1:] = np.exp(icpt + slope * np.log(h))
    return out


def deformant(make: Callable[[float], np.ndarray], amount: float) -> Callable[[float], np.ndarray]:
    """Rende un'onda meno "vocale": le gobbe dello spettro (formanti, risonanze, picchi del sync)
    vengono avvicinate all'andamento liscio. amount 0 = invariata, 1 = gobbe spianate (in dB le
    gobbe si riducono della frazione amount). Le fasi restano quelle originali."""
    def wrapped(p: float) -> np.ndarray:
        spec = make(p)
        mag = np.abs(spec)
        env = _trend(mag)
        new = np.where(mag > 0, mag ** (1 - amount) * np.maximum(env, 1e-30) ** amount, 0.0)
        return spec * np.divide(new, mag, out=np.zeros_like(mag), where=mag > 0)
    return wrapped


def formant_prominence(frame: np.ndarray, top: int = 40) -> float:
    """dB della gobba piu' alta sopra l'andamento liscio (armoniche 2..top): quanto "parla" un'onda."""
    mag = np.abs(np.fft.rfft(frame))
    env = _trend(mag)
    h = np.arange(2, top + 1)
    ok = mag[h] > mag.max() * 1e-4
    return float(np.max(20 * np.log10(mag[h][ok] / env[h][ok]))) if ok.any() else 0.0


# --- banchi a zone ------------------------------------------------------------------------------
# Un banco a zone mette piu' tabelle piccole nei 31 frame: WAVE sceglie la zona, un LFO con poca
# profondita' la scorre. Una zona e' "nome:frame" o "nome:frame:spianatura"; il nome e' una famiglia
# di FAMILIES o "ppgN" (wavetable N della ROM PPG, serve la copia locale dei dati).

# Per ogni famiglia: (p iniziale, p finale, quanto spianare le gobbe). Solo la zona vowel deve
# suonare come una vocale: su hardware le gobbe che si muovono con WAVE (risonanza, picco del sync,
# bande laterali FM) si sentivano come vocali "a ciclo" su tutto il banco.
ZONE_DEFAULTS = {"reso": (0.05, 0.85, 0.6), "pwm": (0.0, 0.9, 0.0), "vowel": (0.0, 1.0, 0.0),
                 "sync": (0.1, 0.8, 0.6), "fold": (0.0, 1.0, 0.0), "brass": (0.0, 1.0, 0.0),
                 "metal": (0.15, 0.8, 0.5)}
PPG_FLATTEN = 0.4                 # zone PPG: molte onde della ROM hanno formanti forti
PPG_HARMONICS = waves.HALF - 1    # 63: le onde PPG non hanno armoniche oltre

ZONE_PRESETS = {
    "ebm": "reso:7,pwm:6,vowel:7,sync:6,metal:5",
    # synth-pop/EBM con tre wavetable PPG (serve --ppg-rom): sweep pieno (23), densa (26), che si apre (14)
    "ebm7": "reso:5,pwm:4,vowel:5,sync:4,ppg23:5,ppg26:4,ppg14:4:0.6",
}


def parse_zones(spec: str) -> list[tuple[str, int, float | None]]:
    """"reso:5,ppg23:5:0.2,..." (o il nome di un preset) -> [(nome, frame, spianatura o None)]."""
    spec = ZONE_PRESETS.get(spec, spec)
    out = []
    for part in spec.split(","):
        bits = part.strip().split(":")
        if len(bits) not in (2, 3) or not bits[1].isdigit() or int(bits[1]) < 2:
            raise ValueError(f"zona '{part}': serve nome:frame (frame >= 2) o nome:frame:spianatura")
        name = bits[0]
        if name not in FAMILIES and not (name.startswith("ppg") and name[3:].isdigit()):
            raise ValueError(f"zona '{name}': famiglie {', '.join(FAMILIES)} oppure ppgN")
        out.append((name, int(bits[1]), float(bits[2]) if len(bits) == 3 else None))
    if sum(n for _, n, _ in out) != waves.FRAMES:
        raise ValueError(f"le zone devono sommare {waves.FRAMES} frame, non {sum(n for _, n, _ in out)}")
    return out


def needs_ppg(spec: str) -> bool:
    return any(name.startswith("ppg") for name, _, _ in parse_zones(spec))


def ppg_family(rom: np.ndarray, keys: list[tuple[int, int]]) -> Callable[[float], np.ndarray]:
    """Una wavetable PPG come famiglia: p = 0..1 percorre le posizioni 0..60, interpolando fra
    posizioni vicine come il PPG; ritorna lo spettro (formato FINE) del ciclo a quella posizione."""
    def make(p: float) -> np.ndarray:
        x = p * (waves.SLOTS - 1)
        lo = min(int(x), waves.SLOTS - 2)
        t = x - lo
        cycle = (1 - t) * waves.table_slot_cycle(rom, keys, lo)[0] + t * waves.table_slot_cycle(rom, keys, lo + 1)[0]
        small = np.fft.rfft(cycle - cycle.mean())
        spec = np.zeros(FINE // 2 + 1, dtype=complex)
        spec[1:waves.HALF] = small[1:waves.HALF] * (FINE / waves.CYCLE)
        return spec
    return make


def zone_bank(spec: str, harmonics: int = DEFAULT_HARMONICS, loud: bool = True,
              rom: np.ndarray | None = None, ppg_tables: list | None = None
              ) -> tuple[np.ndarray, list[str], list[tuple[str, int, int]]]:
    """Banco a zone -> ((31, 256) frame, etichetta per frame, [(zona, primo WAVE, ultimo WAVE)])."""
    frames, labels, ranges, k = [], [], [], 1
    for name, n, flat in parse_zones(spec):
        if name.startswith("ppg"):
            t = int(name[3:])
            if rom is None or ppg_tables is None:
                raise ValueError(f"zona {name}: serve --ppg-rom (copia locale dei dati PPG)")
            if not 0 <= t < len(ppg_tables):
                raise ValueError(f"zona {name}: wavetable PPG 0..{len(ppg_tables) - 1}")
            make, p0, p1 = ppg_family(rom, ppg_tables[t]), 0.0, 1.0
            flat = PPG_FLATTEN if flat is None else flat
            h = min(harmonics, PPG_HARMONICS)
        else:
            p0, p1, default_flat = ZONE_DEFAULTS[name]
            make, flat, h = FAMILIES[name][1], default_flat if flat is None else flat, harmonics
        if flat:
            make = deformant(make, flat)
        part = family(lambda p, m=make, a=p0, b=p1: m(a + (b - a) * p), n=n, harmonics=h, loud=loud)
        frames.append(part)
        labels += [f"{name} p={p0 + (p1 - p0) * p:.2f}" for p in np.linspace(0, 1, n)]
        ranges.append((name, 4 * k, 4 * (k + n - 1)))
        k += n
    return np.concatenate(frames), labels, ranges


TABLES = {**{k: d for k, (d, _) in FAMILIES.items()},
          "ebm": "zone: reso (WAVE 4-28), pwm (32-52), vowel (56-80), sync (84-104), metal (108-124)"}


def zones(spec: str = "ebm") -> list[tuple[str, int, int]]:
    """(zona, primo WAVE, ultimo WAVE) per ogni zona di un banco a zone."""
    out, k = [], 1
    for name, n, _ in parse_zones(spec):
        out.append((name, 4 * k, 4 * (k + n - 1)))
        k += n
    return out


def table(name: str, harmonics: int = DEFAULT_HARMONICS, loud: bool = True) -> tuple[np.ndarray, list[str]]:
    """(31, 256) frame float e un'etichetta per frame: una famiglia intera, o il banco ebm."""
    if name in FAMILIES:
        make = FAMILIES[name][1]
        return (family(make, harmonics=harmonics, loud=loud),
                [f"{name} p={p:.2f}" for p in np.linspace(0, 1, waves.FRAMES)])
    if name != "ebm":
        raise KeyError(f"tabella sconosciuta '{name}': {', '.join(TABLES)}")
    frames, labels, _ = zone_bank("ebm", harmonics, loud)
    return frames, labels
