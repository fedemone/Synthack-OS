"""ppg-chord: sostituisce l'onda a ciclo singolo di SY CHORD con un'onda "stile PPG".

SY CHORD legge 512 x int32 (Q31) a 0x4001A300, sezione 7 (motore audio, CPU #2; docs/audio-path.md).
La patch riscrive solo quei 2048 byte: nessun codice cambia.

    python mods/ppg-chord/make_patch.py list                       # le onde disponibili
    python mods/ppg-chord/make_patch.py preview                    # WAV di accordi, senza firmware
    python mods/ppg-chord/make_patch.py build --wave hollow        # patch.json (serve l'OS stock)
    python mods/ppg-chord/make_patch.py build --wave vox --emu     # + SY CHORD nell'emulatore, prima/dopo
    python mods/ppg-chord/make_patch.py catalog --ppg-rom local/ppg_data.c   # TUTTE le onde, pagina HTML locale
    python mods/ppg-chord/make_patch.py build --ppg-rom local/ppg_data.c --ppg-index 23
    python mods/ppg-chord/make_patch.py build --ppg-rom local/ppg_data.c --ppg-table 5 --ppg-slot 30

Le onde sono descritte in waves.py. --ppg-rom legge una copia LOCALE dei dati di wave-stuff
(data/ppg_data.c): mettila in local/ (git-ignored), non nel repo.
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

LOAD = 0x4000_0400                 # la sezione 7 si carica qui
TABLE_ADDR = 0x4001_A300           # onda di SY CHORD (docs/audio-path.md)
TABLE_LEN = waves.TABLE * 4        # 2048 B
SECTION7_SHA256 = "daf6451cf9587c0b628e901b7bb6b25f4e2633d448c534c0c181dd35ec783bc2"   # OS 1.41
SY_CHORD_MACHINE = 5               # ID machine per tools/emu (engine 5 = SY CHORD)
OUT = REPO / "out" / "ppg-chord"

CHORDS = {"min": (0, 3, 7, 12), "maj": (0, 4, 7, 12), "sus4": (0, 5, 7, 12), "min7": (0, 3, 7, 10),
          "fifth": (0, 7, 12)}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ------------------------------------------------------------------ tabella stock

def load_section7(stock: Path) -> bytes:
    import eft
    path = eft.unpack(stock, REPO / "unpacked" / stock.stem, ids=[7])[7] if stock.suffix.lower() == ".syx" \
        else stock
    data = Path(path).read_bytes()
    if sha(data) != SECTION7_SHA256:
        raise SystemExit(f"{stock}: la sezione 7 non e' quella di Syntakt OS 1.41")
    return data


def read_table(sec7: bytes, addr: int = TABLE_ADDR) -> np.ndarray:
    o = addr - LOAD
    return np.array(struct.unpack_from(f">{waves.TABLE}i", sec7, o), dtype=np.int64)


def looks_like_wave(t: np.ndarray) -> tuple[bool, str]:
    """Una tabella di 512 int32 sembra un ciclo d'onda? (ampia, centrata, pochi salti)"""
    t = t.astype(np.float64)
    peak = np.max(np.abs(t))
    if peak < 2 ** 24:
        return False, f"picco troppo basso ({peak:.3g})"
    if abs(np.mean(t)) > 0.05 * peak:
        return False, f"componente continua {np.mean(t) / peak:+.1%} del picco"
    jumps = int(np.sum(np.abs(np.diff(np.append(t, t[0]))) > 0.25 * peak))
    if jumps > 2:
        return False, f"{jumps} salti: non e' un ciclo liscio"
    return True, f"picco {20 * np.log10(peak / 2 ** 31):.1f} dBFS, RMS/picco {np.sqrt(np.mean(t ** 2)) / peak:.2f}"


def survey(sec7: bytes) -> list[str]:
    """Blocchi da 2 KB vicini all'onda nota: se anche loro sembrano onde, il parametro WAV
    potrebbe scegliere fra piu' tabelle (da verificare nel disassemblato prima di toccarle)."""
    lines = []
    for k in range(-8, 9):
        addr = TABLE_ADDR + k * TABLE_LEN
        if addr < LOAD or addr + TABLE_LEN - LOAD > len(sec7):
            continue
        ok, why = looks_like_wave(read_table(sec7, addr))
        if ok or k == 0:
            lines.append(f"  {addr:#010x}{'  <- SY CHORD (patch)' if k == 0 else ''}: {why}")
    return lines


# ------------------------------------------------------------------ patch

def make_table(wave: waves.Wave, stock: np.ndarray | None, interp: str, gain_db: float) -> np.ndarray:
    return waves.fit_level(waves.to_table(wave.cycle, interp), stock, gain_db)


def table_bytes(table: np.ndarray) -> bytes:
    return struct.pack(f">{waves.TABLE}i", *(int(v) for v in table))


def build_spec(sec7: bytes, wave: waves.Wave, interp: str = "fft", gain_db: float = 0.0,
               bits: int | None = None, source: str = "") -> tuple[dict, np.ndarray]:
    stock = read_table(sec7)
    ok, why = looks_like_wave(stock)
    if not ok:
        raise SystemExit(f"a {TABLE_ADDR:#x} non c'e' l'onda attesa ({why}): OS diverso?")
    table = make_table(wave, stock, interp, gain_db)
    original = sec7[TABLE_ADDR - LOAD:TABLE_ADDR - LOAD + TABLE_LEN]
    desc = (f"SY CHORD: onda '{wave.name}' ({source or 'progettata in waves.py'}"
            f"{f', {bits} bit' if bits else ''}, interp {interp}, {gain_db:+.1f} dB) al posto di quella stock.")
    spec = {"name": "ppg-chord", "os": "1.41", "description": desc,
            "generated_by": "mods/ppg-chord/make_patch.py",
            "wave": {"name": wave.name, "interp": interp, "gain_db": gain_db, "bits": bits, "source": source},
            "patches": [{"section": 7, "addr": f"{TABLE_ADDR:#010X}", "len": TABLE_LEN,
                         "expect_sha256": sha(original), "hex": table_bytes(table).hex(),
                         "what": f"onda di SY CHORD: 512 x int32 Q31, '{wave.name}'"}]}
    return spec, table


# ------------------------------------------------------------------ ascolto

def render_chord(table: np.ndarray, root: int = 48, chord: str = "min", seconds: float = 2.0,
                 detune_cents: float = 4.0) -> np.ndarray:
    """Accordo sostenuto letto dalla tabella con interpolazione lineare (come un oscillatore a
    tabella). Solo per l'ascolto: il motore vero aggiunge filtro, inviluppo, ecc."""
    t = np.asarray(table, dtype=np.float64) / 2 ** 31
    n = int(seconds * SAMPLE_RATE)
    out = np.zeros(n)
    for i, semi in enumerate(CHORDS[chord]):
        cents = detune_cents * (i - (len(CHORDS[chord]) - 1) / 2)
        f = 440.0 * 2 ** ((root + semi - 69) / 12 + cents / 1200)
        ph = (np.arange(n) * f / SAMPLE_RATE + 0.13 * i) % 1.0 * waves.TABLE
        k = ph.astype(np.int64)
        fr = ph - k
        out += t[k] * (1 - fr) + t[(k + 1) % waves.TABLE] * fr
    env = np.minimum(1.0, np.arange(n) / (0.005 * SAMPLE_RATE))
    rel = min(int(0.3 * SAMPLE_RATE), n // 2)
    env[-rel:] *= np.linspace(1, 0, rel)
    return out * env / len(CHORDS[chord])


def write_wav(path: Path, x: np.ndarray) -> None:
    write_q31(path, [int(v) for v in np.clip(x, -1, 1) * (2 ** 31 - 1)], normalize=True)


def preview(names: list[str], tables: dict[str, np.ndarray], outdir: Path, chord: str, root: int) -> None:
    gap = np.zeros(int(0.25 * SAMPLE_RATE))
    reel = []
    for name in names:
        x = render_chord(tables[name], root, chord)
        write_wav(outdir / f"{name}_{chord}.wav", x)
        reel += [x, gap]
        print(f"  {name:8s} -> {outdir / f'{name}_{chord}.wav'}")
    write_wav(outdir / f"all_{chord}.wav", np.concatenate(reel))
    print(f"  tutte in fila ({', '.join(names)}) -> {outdir / f'all_{chord}.wav'}")


def emu_render(table: bytes | None, note: int, seconds: float) -> list[int]:
    """SY CHORD nel motore ORIGINALE (tools/emu), con la tabella sostituita in memoria prima dell'avvio."""
    import cli
    import engine as eng
    e = eng.Engine()
    if table is not None:
        e.uc.mem_write(TABLE_ADDR, table)
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

def pick_wave(a: argparse.Namespace) -> tuple[waves.Wave, str]:
    if a.ppg_rom:
        if a.ppg_table is not None:
            if a.ppg_slot is None:
                raise SystemExit("--ppg-table richiede --ppg-slot 0..60")
            w, how = waves.from_ppg_table(a.ppg_rom, a.ppg_table, a.ppg_slot)
            return w, f"ROM PPG locale, wavetable {a.ppg_table} posizione {a.ppg_slot} = {how}"
        if a.ppg_index is None:
            raise SystemExit("--ppg-rom richiede --ppg-index N oppure --ppg-table T --ppg-slot S")
        return waves.from_ppg_rom(a.ppg_rom, a.ppg_index), f"ROM PPG locale, onda {a.ppg_index}"
    return waves.design(a.wave, a.bits), ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="onde progettate (per la ROM PPG: catalog)")
    c = sub.add_parser("catalog", help="pagina HTML locale con TUTTE le onde, da ascoltare e scegliere")
    c.add_argument("--ppg-rom", type=Path, help="copia locale di wave-stuff/data/ppg_data.c")
    c.add_argument("-o", "--out", type=Path, default=OUT / "catalog.html")

    def wave_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--interp", choices=("fft", "step"), default="fft",
                       help="fft = pulito (default), step = 8 bit senza interpolazione, piu' sporco")
        p.add_argument("--bits", type=int, choices=(8, 16), default=8, help="quantizzazione dell'onda (8 = PPG)")
        p.add_argument("--gain-db", type=float, default=0.0, help="correzione di livello (mai oltre il picco stock)")
        p.add_argument("--ppg-rom", type=Path, help="copia locale di wave-stuff/data/ppg_data.c")
        p.add_argument("--ppg-index", type=int, help="onda della ROM PPG, 0..255")
        p.add_argument("--ppg-table", type=int, help="wavetable della ROM PPG (con --ppg-slot)")
        p.add_argument("--ppg-slot", type=int, help="posizione nella wavetable, 0..60 (interpolata fra le chiavi)")
        p.add_argument("--stock", type=Path, default=REPO / "firmware" / "Syntakt_OS1.41.syx")

    p = sub.add_parser("preview", help="accordi in WAV per ogni onda (non serve il firmware)")
    p.add_argument("--wave", nargs="+", default=list(waves.SPECTRA))
    p.add_argument("--chord", choices=CHORDS, default="min")
    p.add_argument("--root", type=int, default=48, help="nota MIDI della fondamentale (48 = C3)")
    p.add_argument("-o", "--out", type=Path, default=OUT / "preview")
    wave_args(p)

    b = sub.add_parser("build", help="scrive mods/ppg-chord/patch.json (serve l'OS stock)")
    b.add_argument("--wave", choices=waves.SPECTRA, default="hollow")
    b.add_argument("--emu", action="store_true", help="anche SY CHORD nell'emulatore, stock e patch (lento)")
    b.add_argument("--note", type=int, default=48)
    wave_args(b)
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

    stock_table = None
    if a.stock.exists():
        sec7 = load_section7(a.stock)
        stock_table = read_table(sec7)
    if a.cmd == "preview":
        tables = {}
        if stock_table is not None:
            tables["stock"] = stock_table
        if a.ppg_rom:
            w, _ = pick_wave(a)
            tables[w.name] = make_table(w, stock_table, a.interp, a.gain_db)
        else:
            for name in a.wave:
                tables[name] = make_table(waves.design(name, a.bits), stock_table, a.interp, a.gain_db)
        print(f"accordo {a.chord} su {a.root}" + ("" if stock_table is not None
                                                 else " (OS stock assente: niente confronto con l'onda originale)"))
        preview(list(tables), tables, a.out, a.chord, a.root)
        return 0

    if stock_table is None:
        raise SystemExit(f"{a.stock}: serve l'OS stock 1.41 (vedi firmware/README.md)")
    print("tabelle a 512 x int32 vicino all'onda di SY CHORD:")
    print("\n".join(survey(sec7)))
    wave, source = pick_wave(a)
    spec, table = build_spec(sec7, wave, a.interp, a.gain_db, None if a.ppg_rom else a.bits, source)
    (HERE / "patch.json").write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"patch.json: '{wave.name}' a {TABLE_ADDR:#x} ({TABLE_LEN} B)")
    for label, t in (("stock", stock_table), (wave.name, table)):
        hs = ", ".join(f"{k}:{db:.0f}" for k, db in waves.harmonics(t, 10))
        print(f"  {label:8s} armoniche (n:dB) {hs}")
    if a.emu:
        OUT.mkdir(parents=True, exist_ok=True)
        for label, data in (("stock", None), (wave.name, table_bytes(table))):
            path = OUT / f"emu_{label}_n{a.note}.wav"
            peak = write_q31(path, emu_render(data, a.note, 0.5), normalize=True)
            print(f"  emulatore {label:8s}: picco {peak:.1f} dBFS -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
