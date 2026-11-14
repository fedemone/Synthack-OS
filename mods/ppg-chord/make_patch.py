"""ppg-chord: una wavetable PPG nel banco di SY CHORD. Girare WAVE la scorre come sul PPG.

SY CHORD ha un banco di 32 frame: WAVE 0 = seno condiviso (non lo tocchiamo), WAVE 4, 8 ... 124 =
frame 1..31, e i valori in mezzo sono interpolati dalla machine (docs/audio-path.md). Una wavetable
PPG ha 61 posizioni: le 31 pari (0, 2 ... 60) riempiono esattamente i 31 frame.

    python mods/ppg-chord/make_patch.py catalog --ppg-rom local/ppg_data.c   # tutte le onde e tabelle
    python mods/ppg-chord/make_patch.py preview --ppg-rom local/ppg_data.c --ppg-table 5
    python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --ppg-table 5
    python mods/ppg-chord/make_patch.py build   --designed                 # senza ROM: le 7 onde nostre

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


def make_bank(cycles: list[np.ndarray], harmonics: int) -> np.ndarray:
    return waves.bank_q31(waves.bank(cycles, harmonics))


def build_spec(q31: np.ndarray, source: str, harmonics: int) -> dict:
    return {"name": "ppg-chord", "os": "1.41",
            "description": f"SY CHORD: wavetable {source} nei frame WAVE 4..124 ({harmonics} armoniche); "
                           "WAVE 0 e immagini dello schermo invariati.",
            "generated_by": "mods/ppg-chord/make_patch.py",
            "conflicts": ["sy-chord"],
            "wave": {"source": source, "harmonics": harmonics,
                     "frames": {str(4 * k): f"posizione {waves.TABLE_POSITIONS[k - 1]}" for k in range(1, 32)}},
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


# ------------------------------------------------------------------ riga di comando

def pick_source(a: argparse.Namespace) -> list[tuple[str, list[np.ndarray]]]:
    """[(nome, 31 cicli)] secondo le opzioni."""
    if a.designed is not None:
        return [("designed", waves.designed_cycles(a.designed or None))]
    if not a.ppg_rom:
        raise SystemExit("serve --ppg-rom local/ppg_data.c con --ppg-table T (o --designed)")
    rom, tables = waves.parse_ppg_rom(a.ppg_rom), waves.parse_ppg_wavetables(a.ppg_rom)
    ids = range(len(tables)) if getattr(a, "all", False) else [a.ppg_table]
    out = []
    for t in ids:
        if t is None or not 0 <= t < len(tables):
            raise SystemExit(f"--ppg-table: 0..{len(tables) - 1}")
        out.append((f"ppg-wt{t:02d}", waves.table_cycles(rom, tables[t])))
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
        p.add_argument("--harmonics", type=int, default=40,
                       help="limite di banda (1..63, default 40 come Workbench): piu' alto = piu' brillante, "
                            "ma SY CHORD usa un solo frame per tutte le note, quindi aliasing in alto")

    p = sub.add_parser("preview", help="WAV: un accordo che scorre WAVE 4 -> 124 (non serve il firmware)")
    src_args(p)
    p.add_argument("--all", action="store_true", help="tutte le wavetable della ROM, un file ciascuna")
    p.add_argument("--chord", choices=CHORDS, default="min")
    p.add_argument("--root", type=int, default=48, help="nota MIDI (48 = C3)")
    p.add_argument("--seconds", type=float, default=6.0)
    p.add_argument("--hold", type=float, help="WAVE fisso invece dello scorrimento (4..124)")
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

    sources = pick_source(a)
    if a.cmd == "preview":
        for name, cycles in sources:
            q = make_bank(cycles, a.harmonics)
            lo, hi = (a.hold, a.hold) if a.hold is not None else (4, 124)
            path = a.out / f"{name}_{a.chord}{'' if a.hold is None else f'_w{a.hold:g}'}.wav"
            write_wav(path, render(q, lo, hi, a.seconds, a.root, a.chord))
            print(f"  {name}: WAVE {lo:g}->{hi:g} -> {path}")
        return 0

    if len(sources) != 1:
        raise SystemExit("build: una sola sorgente")
    name, cycles = sources[0]
    q = make_bank(cycles, a.harmonics)
    sec7 = None
    if a.stock.exists():
        sec7 = load_section7(a.stock)
        stock_region(sec7)
        print("banco stock verificato (OS 1.41)")
    else:
        print(f"{a.stock} assente: impronta del banco stock presa dal manifest di MAX (il build la riverifica)")
    spec = build_spec(q, name, a.harmonics)
    (HERE / "patch.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"patch.json: {name} -> WAVE 4..124 ({BANK_LEN} B a {BANK_ADDR:#x}); WAVE 0 e schermo invariati")
    if a.emu:
        if sec7 is None:
            raise SystemExit("--emu richiede l'OS stock")
        OUT.mkdir(parents=True, exist_ok=True)
        for label, region in (("stock", None), (name, bank_bytes(q))):
            path = OUT / f"emu_{label}.wav"
            peak = write_q31(path, emu_render(region, 64, 48, 0.5), normalize=True)
            print(f"  emulatore {label}: picco {peak:.1f} dBFS -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
