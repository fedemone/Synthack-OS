"""ppg-chord: una wavetable PPG nel banco di SY CHORD. Girare WAVE la scorre come sul PPG.

SY CHORD ha un banco di 32 frame: WAVE 0 = seno condiviso (non lo tocchiamo), WAVE 4, 8 ... 124 =
frame 1..31, e i valori in mezzo sono interpolati dalla machine (docs/audio-path.md). Una wavetable
PPG ha 61 posizioni: le 31 pari (0, 2 ... 60) riempiono esattamente i 31 frame.

    python mods/ppg-chord/make_patch.py catalog --ppg-rom local/ppg_data.c   # tutte le onde e tabelle
    python mods/ppg-chord/make_patch.py preview --ppg-rom local/ppg_data.c --ppg-table 5
    python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --ppg-table 5
    python mods/ppg-chord/make_patch.py build   --designed                 # senza ROM: le 7 onde nostre
    python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --curated   # 31 onde scelte
    python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --ppg-waves 12,40,77 --fill-max

La patch scrive la stessa regione del banco "sy-chord" di MAX (0x40016B80, 31868 B): le due mod
si escludono (il build rifiuta le sovrapposizioni). Le immagini delle onde sullo schermo NON
vengono ridisegnate: mostrano ancora le forme stock.

--ppg-rom legge una copia LOCALE dei dati di wave-stuff (data/ppg_data.c): tienila in local/
(git-ignored). Una patch.json fatta cosi' contiene dati derivati da quella ROM.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(HERE), str(REPO / "tools" / "unpack"), str(REPO / "tools" / "emu")]
import tables  # noqa: E402
import waves  # noqa: E402
from wav import SAMPLE_RATE, write_q31  # noqa: E402

LOAD = 0x4000_0400                     # la sezione 7 si carica qui
BANK_END = 0x1E3FC                     # offset nella sezione 7: frame k a BANK_END - k * STEP
STEP = 0x404                           # 257 x int32
BANK_ADDR = LOAD + BANK_END - waves.FRAMES * STEP      # 0x40016B80, frame 31 ... frame 1
BANK_LEN = waves.FRAMES * STEP                          # 31868 B
SINE_ADDR = LOAD + 0x53E50             # WAVE 0, seno condiviso con altre machine: mai toccato
# Impronta dei byte stock della regione: la stessa che dichiara il banco "sy-chord" di MAX
# (tools/max/modular_builder/resources/modular-manifest.json), verificata contro l'OS 1.41.
BANK_STOCK_SHA256 = "c3ddef55f4b413a40067432f741f832a5c082bbe3afb66fe5044ec540be3bf1e"
SECTION7_SHA256 = "daf6451cf9587c0b628e901b7bb6b25f4e2633d448c534c0c181dd35ec783bc2"   # OS 1.41
SY_CHORD_MACHINE = 5                   # ID machine per tools/emu
OUT = REPO / "out" / "ppg-chord"
MAX_MANIFEST = REPO / "tools" / "max" / "modular_builder" / "resources" / "modular-manifest.json"
STOCK = REPO / "firmware" / "Syntakt_OS1.41.syx"

CHORDS = {"min": (0, 3, 7, 12), "maj": (0, 4, 7, 12), "sus4": (0, 5, 7, 12), "min7": (0, 3, 7, 10),
          "fifth": (0, 7, 12), "note": (0,)}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ banco

def frame_offset(k: int) -> int:
    """Offset del frame k (1..31) DENTRO la regione della patch (il banco e' al contrario)."""
    if not 1 <= k <= waves.FRAMES:
        raise ValueError("frame 1..31")
    return (waves.FRAMES - k) * STEP


def bank_bytes(q31: np.ndarray) -> bytes:
    """(31, 257) int32, frame 1..31 -> i 31868 byte della regione (frame 31 per primo)."""
    out = bytearray(BANK_LEN)
    for k in range(1, waves.FRAMES + 1):
        struct.pack_into(f">{waves.FRAME_SAMPLES + 1}i", out, frame_offset(k), *(int(v) for v in q31[k - 1]))
    return bytes(out)


def read_bank(region: bytes) -> np.ndarray:
    """I 31868 byte della regione -> (31, 257) int32, frame 1..31."""
    return np.array([struct.unpack_from(f">{waves.FRAME_SAMPLES + 1}i", region, frame_offset(k))
                     for k in range(1, waves.FRAMES + 1)], dtype=np.int64)


def load_section7(stock: Path) -> bytes:
    import eft
    path = eft.unpack(stock, REPO / "unpacked" / stock.stem, ids=[7])[7] if stock.suffix.lower() == ".syx" \
        else stock
    data = Path(path).read_bytes()
    if sha(data) != SECTION7_SHA256:
        raise SystemExit(f"{stock}: la sezione 7 non e' quella di Syntakt OS 1.41")
    return data


def stock_region(sec7: bytes) -> bytes:
    o = BANK_ADDR - LOAD
    region = sec7[o:o + BANK_LEN]
    if sha(region) != BANK_STOCK_SHA256:
        raise SystemExit("il banco di SY CHORD non e' quello stock di OS 1.41")
    return region


def make_bank(cycles: list[np.ndarray], harmonics: int, grit: bool = False) -> np.ndarray:
    return waves.bank_q31(waves.bank(cycles, harmonics, grit))


def build_spec(q31: np.ndarray, source: str, harmonics: int, labels: list[str] | None = None) -> dict:
    labels = labels or [f"posizione {p}" for p in waves.TABLE_POSITIONS]
    return {"name": "ppg-chord", "os": "1.41",
            "description": f"SY CHORD: {source} nei frame WAVE 4..124 ({harmonics} armoniche); "
                           "WAVE 0 e immagini dello schermo invariati.",
            "generated_by": "mods/ppg-chord/make_patch.py",
            "conflicts": ["sy-chord"],
            "wave": {"source": source, "harmonics": harmonics,
                     "frames": {str(4 * k): labels[k - 1] for k in range(1, 32)}},
            "patches": [{"section": 7, "addr": f"{BANK_ADDR:#010X}", "len": BANK_LEN,
                         "expect_sha256": BANK_STOCK_SHA256, "hex": bank_bytes(q31).hex(),
                         "what": "banco SY CHORD, frame 31..1 (WAVE 124..4), 257 x int32 ciascuno"}]}


# ------------------------------------------------------------------ ascolto

def render(q31: np.ndarray, wave_from: float = 4, wave_to: float = 124, seconds: float = 6.0,
           root: int = 48, chord: str = "min", detune_cents: float = 4.0) -> np.ndarray:
    """Accordo che scorre il banco da WAVE wave_from a wave_to, interpolando fra frame vicini come
    SY CHORD (WAVE/4 = frame; in mezzo, miscela lineare). Solo ascolto: niente filtro o inviluppo."""
    fr = np.asarray(q31, dtype=np.float64)[:, :waves.FRAME_SAMPLES] / 2 ** 31
    n = int(seconds * SAMPLE_RATE)
    pos = np.clip(np.linspace(wave_from, wave_to, n) / 4 - 1, 0, waves.FRAMES - 1)   # 0 = frame 1
    lo = np.minimum(pos.astype(np.int64), waves.FRAMES - 2)
    mix = pos - lo
    out = np.zeros(n)
    notes = CHORDS[chord]
    for i, semi in enumerate(notes):
        cents = detune_cents * (i - (len(notes) - 1) / 2)
        f = 440.0 * 2 ** ((root + semi - 69) / 12 + cents / 1200)
        ph = (np.arange(n) * f / SAMPLE_RATE + 0.13 * i) % 1.0 * waves.FRAME_SAMPLES
        k = ph.astype(np.int64)
        fr_ = ph - k
        k2 = (k + 1) % waves.FRAME_SAMPLES
        a = fr[lo, k] * (1 - fr_) + fr[lo, k2] * fr_
        b = fr[lo + 1, k] * (1 - fr_) + fr[lo + 1, k2] * fr_
        out += a * (1 - mix) + b * mix
    env = np.minimum(1.0, np.arange(n) / (0.005 * SAMPLE_RATE))
    rel = min(int(0.3 * SAMPLE_RATE), n // 2)
    env[-rel:] *= np.linspace(1, 0, rel)
    return out * env / len(notes)


def render_sequence(q31: np.ndarray, wave: float = 4, depth: float = 24, bpm: float = 125,
                    notes: tuple[int, ...] = (36, 36, 48, 36, 36, 39, 36, 43) * 4) -> np.ndarray:
    """Basso EBM in sedicesimi: ogni nota parte da WAVE `wave` e sale di `depth` in ~0.12 s, come
    un LFO in modalita' ONE su WAVE (l'inviluppo sulla wavetable del PPG). Inviluppo d'ampiezza
    corto. Solo ascolto."""
    fr = np.asarray(q31, dtype=np.float64)[:, :waves.FRAME_SAMPLES] / 2 ** 31
    step = int(SAMPLE_RATE * 60 / bpm / 4)
    out = np.zeros(step * len(notes))
    t = np.arange(step) / SAMPLE_RATE
    sweep = wave + depth * (1 - np.exp(-t / 0.04))
    pos = np.clip(sweep / 4 - 1, 0, waves.FRAMES - 1)
    lo = np.minimum(pos.astype(np.int64), waves.FRAMES - 2)
    mix = pos - lo
    amp = np.minimum(1, t / 0.002) * np.exp(-t / 0.09)
    for i, note in enumerate(notes):
        f = 440.0 * 2 ** ((note - 69) / 12)
        ph = (t * f) % 1.0 * waves.FRAME_SAMPLES
        k = ph.astype(np.int64)
        u = ph - k
        k2 = (k + 1) % waves.FRAME_SAMPLES
        a = fr[lo, k] * (1 - u) + fr[lo, k2] * u
        b = fr[lo + 1, k] * (1 - u) + fr[lo + 1, k2] * u
        out[i * step:(i + 1) * step] = (a * (1 - mix) + b * mix) * amp
    return out


def write_wav(path: Path, x: np.ndarray) -> None:
    write_q31(path, [int(v) for v in np.clip(x, -1, 1) * (2 ** 31 - 1)], normalize=True)


def emu_render(region: bytes | None, wave: int, note: int, seconds: float) -> list[int]:
    """SY CHORD nel motore ORIGINALE (tools/emu), col banco sostituito in memoria prima dell'avvio.
    Nota: i parametri machine di tools/emu sono tutti a 0x40, quindi WAVE e' quello che e'."""
    import cli
    import engine as eng
    e = eng.Engine()
    if region is not None:
        e.uc.mem_write(BANK_ADDR, region)
    e.boot()
    params = cli.make_params(SY_CHORD_MACHINE, note)
    out: list[int] = []
    for b in range(int(seconds * SAMPLE_RATE / eng.BLOCK)):
        q = bytearray(params)
        if b in (cli.TRIG_LOAD, cli.TRIG_NOTE):
            q[0x180] = 0x01
        out += e.render_block(bytes(q))[0]
    return out


def body_report(q31: np.ndarray) -> str:
    """Corpo del banco (quota di energia nelle armoniche 1-3), confrontato con stock e MAX."""
    b = np.array([waves.body(f) for f in np.asarray(q31)[:, :waves.FRAME_SAMPLES].astype(np.float64)])
    note = "" if np.median(b) >= 0.5 else "  <- poco corpo: col filtro che si chiude suonera' corto e piano"
    return (f"corpo (energia armoniche 1-3): mediana {np.median(b):.2f}, minimo {b.min():.2f} "
            f"(stock 0.96, MAX 0.76){note}")


# ------------------------------------------------------------------ banco curato

def max_frames(threshold: float = 0.95, basic: bool = False) -> list[tuple[str, np.ndarray]]:
    """I frame del banco SY CHORD di MAX letti dal manifest del builder modulare, [(nome, 256
    campioni)] nell'ordine di MAX: quelli che NON sono forme di base (FM, formanti, accordi...),
    oppure, con basic=True, solo quelli che lo sono (dente di sega, impulsi...)."""
    m = json.loads(MAX_MANIFEST.read_text(encoding="utf-8"))
    chord = next(mod for mod in m["mods"] if mod["name"] == "sy-chord")
    (p,) = [p for p in chord["patches"] if p["section"] == 7]
    if int(p["addr"], 16) != BANK_ADDR or p["len"] != BANK_LEN:
        raise SystemExit("il banco di MAX non e' dove ce lo aspettiamo")
    q = read_bank(bytes.fromhex(p["hex"]))
    names = {w["wave"]: w["name"] for w in m.get("waves", [])}
    out = []
    for k in range(1, waves.FRAMES + 1):
        frame = q[k - 1, :waves.FRAME_SAMPLES].astype(np.float64)
        if (waves.basic_shape(frame, threshold) is None) != basic:
            out.append((f"MAX {names.get(4 * k, f'WAVE {4 * k}')}", frame))
    return out


def curated(a: argparse.Namespace) -> tuple[str, np.ndarray, list[str]]:
    """Banco di 31 onde scelte -> (nome, (31, 257) int32, etichette per frame)."""
    rom = waves.parse_ppg_rom(a.ppg_rom)
    if a.ppg_waves:
        idx = [int(v) for v in a.ppg_waves.split(",") if v.strip()]
        bad = [i for i in idx if not 0 <= i < len(rom)]
        if bad or len(set(idx)) != len(idx):
            raise SystemExit(f"--ppg-waves: indici 0..{len(rom) - 1}, senza ripetizioni ({bad or 'doppioni'})")
        if len(idx) > waves.FRAMES:
            raise SystemExit(f"--ppg-waves: al massimo {waves.FRAMES} onde, non {len(idx)}")
        name = "ppg-custom"
    else:
        try:
            idx = waves.curate(rom, waves.FRAMES, a.basic_threshold, a.min_body, a.min_density)
        except ValueError as error:
            raise SystemExit(str(error)) from error
        name = "ppg-curated"
    items = [(f"PPG #{i}", waves.condition(waves.ppg_expand(rom[i]), a.harmonics, a.grit)) for i in idx]
    if len(items) < waves.FRAMES:
        if not a.fill_max:
            raise SystemExit(f"{len(items)} onde per {waves.FRAMES} frame: aggiungi --fill-max (onde di MAX) "
                             "o altre onde")
        # prima le onde di MAX che non sono forme di base, poi (solo se servono) le altre
        for extra in (max_frames(a.basic_threshold), max_frames(a.basic_threshold, basic=True)):
            need = waves.FRAMES - len(items)
            if need <= 0:
                break
            mine = [f for _, f in items]
            pick = waves.most_diverse(mine + [f for _, f in extra], len(mine) + len(extra))
            pick = [k - len(mine) for k in pick if k >= len(mine)][:need]
            items += [(extra[k][0], waves.condition_frame(extra[k][1], min(a.harmonics, 127))) for k in pick]
        name += "+max"
    frames = [f for _, f in items]
    order = waves.order_smooth(frames) if a.order == "smooth" else \
        sorted(range(len(frames)), key=lambda k: waves.brightness(frames[k]))
    bank = waves.mixed_bank([frames[k] for k in order])
    return name, waves.bank_q31(bank), [items[k][0] for k in order]


# ------------------------------------------------------------------ riga di comando

def pick_source(a: argparse.Namespace) -> list[tuple[str, list[np.ndarray]]]:
    """[(nome, 31 cicli)] secondo le opzioni."""
    if a.designed is not None:
        return [("designed", waves.designed_cycles(a.designed or None))]
    if not a.ppg_rom:
        raise SystemExit("serve --ppg-rom local/ppg_data.c con --ppg-table T (o --designed)")
    rom, tabs = waves.parse_ppg_rom(a.ppg_rom), waves.parse_ppg_wavetables(a.ppg_rom)
    ids = range(len(tabs)) if getattr(a, "all", False) else [a.ppg_table]
    out = []
    for t in ids:
        if t is None or not 0 <= t < len(tabs):
            raise SystemExit(f"--ppg-table: 0..{len(tabs) - 1}")
        out.append((f"ppg-wt{t:02d}", waves.table_cycles(rom, tabs[t])))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="onde progettate (per la ROM PPG: catalog)")
    c = sub.add_parser("catalog", help="pagina HTML locale con tutte le onde e le wavetable")
    c.add_argument("--ppg-rom", type=Path, help="copia locale di wave-stuff/data/ppg_data.c")
    c.add_argument("-o", "--out", type=Path, default=OUT / "catalog.html")

    def src_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--ppg-rom", type=Path, help="copia locale di wave-stuff/data/ppg_data.c")
        p.add_argument("--ppg-table", type=int, help="wavetable PPG 0..28")
        p.add_argument("--designed", nargs="*", metavar="ONDA",
                       help="wavetable con le onde progettate (default: tutte e 7, in ordine)")
        p.add_argument("--curated", action="store_true",
                       help="31 onde ROM scelte (non forme di base, le piu' diverse) invece di una wavetable")
        p.add_argument("--ppg-waves", help="onde ROM scelte a mano, es. 12,40,77 (al massimo 31)")
        p.add_argument("--fill-max", action="store_true",
                       help="se le onde sono meno di 31, completa con le onde di MAX che non sono forme di base")
        p.add_argument("--order", choices=("smooth", "brightness"), default="smooth",
                       help="banco curato: smooth = ogni onda simile alla successiva (default), "
                            "brightness = da scura a brillante")
        p.add_argument("--table", choices=[*tables.TABLES, "all"],
                       help="wavetable progettata per synth-pop/EBM (nostra, senza ROM): "
                            + "; ".join(f"{k}: {v}" for k, v in tables.TABLES.items()))
        p.add_argument("--grit", action="store_true",
                       help="onde PPG lette 'a gradini' come il PPG (immagini fino alla 127a armonica): "
                            "un po' di brillantezza digitale in piu'")
        p.add_argument("--min-body", type=float, default=waves.MIN_BODY,
                       help=f"banco curato: quota minima di energia nelle armoniche 1-3 (default {waves.MIN_BODY}; "
                            "stock 0.96, MAX 0.76): senza corpo il suono e' corto col filtro che si chiude")
        p.add_argument("--min-density", type=int, default=waves.MIN_DENSITY,
                       help=f"banco curato: armoniche forti (entro 30 dB) minime fra le prime 40 (default "
                            f"{waves.MIN_DENSITY}; organo ~4-8, dente di sega 31): evita il suono d'organo")
        p.add_argument("--basic-threshold", type=float, default=0.95,
                       help="somiglianza (0..1) oltre la quale un'onda conta come forma di base")
        p.add_argument("--harmonics", type=int,
                       help="limite di banda: default 40 per le onde PPG (max 63), 127 con --grit, "
                            f"{tables.DEFAULT_HARMONICS} per --table (max 127). Piu' alto = piu' brillante, ma SY "
                            "CHORD usa un solo frame per tutte le note: aliasing sulle note alte")

    p = sub.add_parser("preview", help="WAV: un accordo che scorre WAVE 4 -> 124 (non serve il firmware)")
    src_args(p)
    p.add_argument("--all", action="store_true", help="tutte le wavetable della ROM, un file ciascuna")
    p.add_argument("--chord", choices=CHORDS, default="min")
    p.add_argument("--root", type=int, default=48, help="nota MIDI (48 = C3)")
    p.add_argument("--seconds", type=float, default=6.0)
    p.add_argument("--hold", type=float, help="WAVE fisso invece dello scorrimento (4..124)")
    p.add_argument("--ebm", action="store_true",
                   help="invece dell'accordo: basso EBM in sedicesimi, ogni nota scorre WAVE una volta "
                        "(come un LFO in modalita' ONE su WAVE)")
    p.add_argument("--ebm-wave", type=float, default=4, help="WAVE di partenza di ogni nota (default 4)")
    p.add_argument("--ebm-depth", type=float, default=24, help="di quanto sale WAVE in ogni nota (default 24)")
    p.add_argument("-o", "--out", type=Path, default=OUT / "preview")

    b = sub.add_parser("build", help="scrive mods/ppg-chord/patch.json")
    src_args(b)
    b.add_argument("--stock", type=Path, default=STOCK, help="se presente, verifica il banco stock")
    b.add_argument("--emu", action="store_true", help="anche SY CHORD nell'emulatore, stock e banco nuovo")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for name, (desc, _) in waves.SPECTRA.items():
            print(f"  {name:8s} {desc}")
        return 0
    if a.cmd == "catalog":
        import catalog
        n = catalog.build(a.ppg_rom, a.out)
        print(f"{a.out}: {n['designed']} onde progettate, {n['rom']} onde ROM, {n['tables']} wavetable"
              f"{'' if a.ppg_rom else ' (senza --ppg-rom: solo le progettate)'}")
        return 0

    if (a.curated or a.ppg_waves) and not a.ppg_rom:
        raise SystemExit("--curated / --ppg-waves richiedono --ppg-rom")
    banks = resolve_banks(a)
    if a.cmd == "preview":
        for name, q, labels in banks:
            if a.ebm:
                path = a.out / f"{name}_ebm.wav"
                write_wav(path, render_sequence(q, a.ebm_wave, a.ebm_depth))
                print(f"  {name}: basso EBM, WAVE {a.ebm_wave:g} -> {a.ebm_wave + a.ebm_depth:g} per nota -> {path}")
                continue
            lo, hi = (a.hold, a.hold) if a.hold is not None else (4, 124)
            path = a.out / f"{name}_{a.chord}{'' if a.hold is None else f'_w{a.hold:g}'}.wav"
            write_wav(path, render(q, lo, hi, a.seconds, a.root, a.chord))
            print(f"  {name}: WAVE {lo:g}->{hi:g} -> {path}")
        return 0

    if len(banks) != 1:
        raise SystemExit("build: una sola sorgente")
    name, q, labels = banks[0]
    sec7 = None
    if a.stock.exists():
        sec7 = load_section7(a.stock)
        stock_region(sec7)
        print("banco stock verificato (OS 1.41)")
    else:
        print(f"{a.stock} assente: impronta del banco stock presa dal manifest di MAX (il build la riverifica)")
    spec = build_spec(q, name, a.harmonics, labels)
    (HERE / "patch.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"patch.json: {name} -> WAVE 4..124 ({BANK_LEN} B a {BANK_ADDR:#x}); WAVE 0 e schermo invariati")
    if a.table == "ebm":
        for fam, lo, hi in tables.zones():
            print(f"  WAVE {lo:3d}-{hi:3d}: {fam}")
    elif not a.table and labels and not labels[0].startswith("posizione"):
        for k, label in enumerate(labels, 1):
            print(f"  WAVE {4 * k:3d}: {label}")
    print(body_report(q))
    if a.emu:
        if sec7 is None:
            raise SystemExit("--emu richiede l'OS stock")
        OUT.mkdir(parents=True, exist_ok=True)
        for label, region in (("stock", None), (name, bank_bytes(q))):
            path = OUT / f"emu_{label}.wav"
            peak = write_q31(path, emu_render(region, 64, 48, 0.5), normalize=True)
            print(f"  emulatore {label}: picco {peak:.1f} dBFS -> {path}")
    return 0


def resolve_banks(a: argparse.Namespace) -> list[tuple[str, np.ndarray, list[str]]]:
    """[(nome, (31, 257) int32, etichette)] secondo le opzioni; fissa anche a.harmonics se manca."""
    if a.table:
        a.harmonics = a.harmonics or tables.DEFAULT_HARMONICS
        names = list(tables.TABLES) if a.table == "all" else [a.table]
        out = []
        for n in names:
            frames, labels = tables.table(n, a.harmonics)
            out.append((f"table-{n}", waves.bank_q31(frames), labels))
        return out
    a.harmonics = a.harmonics or (127 if a.grit else 40)
    if a.curated or a.ppg_waves:
        return [curated(a)]
    labels = [f"posizione {p}" for p in waves.TABLE_POSITIONS]
    return [(name + ("-grit" if a.grit else ""), make_bank(cycles, a.harmonics, a.grit), labels)
            for name, cycles in pick_source(a)]

if __name__ == "__main__":
    sys.exit(main())
