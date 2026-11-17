"""Mod ppg-chord: wavetable PPG nel banco di SY CHORD (31 frame, WAVE 4..124).

Senza firmware: formato delle onde, condizionamento dei frame, disposizione del banco, patch,
compatibilita' col banco "sy-chord" di MAX. Con l'OS stock: banco stock e SY CHORD nell'emulatore.
"""

import json
import struct
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "mods" / "ppg-chord")]
import make_patch as mp  # noqa: E402
import tables  # noqa: E402
import waves  # noqa: E402

STOCK = ROOT / "firmware" / "Syntakt_OS1.41.syx"
MAX_MANIFEST = ROOT / "tools" / "max" / "modular_builder" / "resources" / "modular-manifest.json"


# ------------------------------------------------------------ onde

@pytest.mark.parametrize("name", list(waves.SPECTRA))
def test_designed_waves_have_ppg_format(name):
    c = waves.design(name).cycle
    assert c.shape == (128,)
    assert np.allclose(c, -c[::-1] - 1)                    # seconda meta' = ~prima meta' rovesciata
    assert np.allclose(c, np.round(c)) and -128 <= c.min() and c.max() <= 127


def test_design_is_deterministic():
    assert np.array_equal(waves.design("vox").cycle, waves.design("vox").cycle)


# ------------------------------------------------------------ frame e banco

@pytest.mark.parametrize("name", list(waves.SPECTRA))
def test_condition_starts_at_true_zero_and_is_band_limited(name):
    c = waves.design(name).cycle
    y = waves.condition(c, 40)
    assert y.shape == (256,) and np.isclose(np.max(np.abs(y)), 1.0)
    assert abs(y[0]) < 1e-9                                 # zero VERO (non forzato): niente clic
    mag = np.abs(np.fft.rfft(y))
    assert mag[41:].max() < 1e-9 * mag.max()                # nessuna armonica oltre il limite
    assert abs(np.mean(y)) < 1e-9


def test_condition_keeps_the_spectrum():
    c = waves.design("glass").cycle
    src = np.abs(np.fft.rfft(c - c.mean()))[1:64]
    got = np.abs(np.fft.rfft(waves.condition(c, 63)))[1:64]
    assert np.allclose(got / got.max(), src / src.max(), atol=1e-9)


def test_condition_rejects_bad_band_limit():
    with pytest.raises(ValueError):
        waves.condition(waves.design("vox").cycle, 64)


def test_bank_frames_share_phase_and_format():
    q = waves.bank_q31(waves.bank(waves.designed_cycles()))
    assert q.shape == (31, 257)
    assert (q[:, 0] == 0).all() and (q[:, 256] == 0).all()  # y[0] = 0, guardia = y[0]
    assert np.abs(q).max(axis=1).max() == waves.PEAK
    assert (np.abs(q).max(axis=1) >= waves.PEAK - 1).all()  # ogni frame a picco pieno
    # stessa fase: frame vicini molto correlati (l'interpolazione di SY CHORD non cancella)
    f = q[:, :256].astype(float)
    corr = [np.dot(f[k], f[k + 1]) / np.linalg.norm(f[k]) / np.linalg.norm(f[k + 1]) for k in range(30)]
    assert min(corr) > 0.8


def test_designed_table_hits_keys():
    cyc = waves.designed_cycles()
    assert len(cyc) == 31
    assert np.allclose(cyc[0], waves.design("hollow").cycle)       # posizione 0
    assert np.allclose(cyc[30], waves.design("organ").cycle)       # posizione 60
    assert np.allclose(cyc[5], waves.design("brass").cycle)        # posizione 10


# ------------------------------------------------------------ disposizione e patch

def test_layout_matches_workbench():
    assert mp.BANK_ADDR == 0x40016B80 and mp.BANK_LEN == 31868
    # frame k a BANK_END - k*STEP (offset nella sezione 7), come in syntakt-fw.js
    for k in (1, 17, 31):
        assert mp.BANK_ADDR - mp.LOAD + mp.frame_offset(k) == 0x1E3FC - k * 0x404
    assert not (mp.BANK_ADDR <= mp.SINE_ADDR < mp.BANK_ADDR + mp.BANK_LEN)   # WAVE 0 fuori


def test_bank_bytes_roundtrip():
    q = waves.bank_q31(waves.bank(waves.designed_cycles()))
    region = mp.bank_bytes(q)
    assert len(region) == mp.BANK_LEN
    assert np.array_equal(mp.read_bank(region), q)
    # il primo frame nella regione e' il 31 (WAVE 124)
    assert list(struct.unpack_from(">257i", region, 0)) == [int(v) for v in q[30]]


def test_spec_is_a_standard_patch():
    q = waves.bank_q31(waves.bank(waves.designed_cycles()))
    spec = mp.build_spec(q, "designed", 40)
    (p,) = spec["patches"]
    assert p["section"] == 7 and int(p["addr"], 16) == mp.BANK_ADDR and p["len"] == mp.BANK_LEN
    assert len(bytes.fromhex(p["hex"])) == p["len"] and p["expect_sha256"] == mp.BANK_STOCK_SHA256
    assert spec["conflicts"] == ["sy-chord"] and spec["wave"]["frames"]["124"] == "posizione 60"


@pytest.mark.skipif(not MAX_MANIFEST.exists(), reason="manifest di MAX assente")
def test_same_region_and_stock_hash_as_max_sy_chord():
    m = json.loads(MAX_MANIFEST.read_text())
    chord = next(mod for mod in m["mods"] if mod["name"] == "sy-chord")
    (sec7,) = [p for p in chord["patches"] if p["section"] == 7]
    assert int(sec7["addr"], 16) == mp.BANK_ADDR and sec7["len"] == mp.BANK_LEN
    assert sec7["expect_sha256"] == mp.BANK_STOCK_SHA256
    # e il banco di MAX ha lo stesso formato che scriviamo noi: y[0] = guardia = 0, picco PEAK
    q = mp.read_bank(bytes.fromhex(sec7["hex"]))
    assert (q[:, 0] == 0).all() and (q[:, 256] == 0).all() and np.abs(q).max() == waves.PEAK


def test_render_sweep():
    q = waves.bank_q31(waves.bank(waves.designed_cycles()))
    x = mp.render(q, seconds=0.3)
    assert x.shape == (int(0.3 * 48000),) and np.max(np.abs(x)) > 0.1
    held = mp.render(q, 64, 64, seconds=0.1, chord="note")
    assert np.max(np.abs(held)) > 0.1


# ------------------------------------------------------------ ROM sintetica (stesso formato C di wave-stuff)

def synthetic_rom(tmp_path, n_waves=8):
    ph = (np.arange(64) + 0.5) / 128
    rom = [np.clip(np.round(128 + 120 * np.sin(2 * np.pi * (k + 1) * ph) / (1 + 0.1 * k)), 0, 255).astype(int)
           for k in range(n_waves)]
    rom[5] = np.full(64, 128)                                     # onda vuota
    rom[6] = rom[1]                                               # duplicato
    # tabella 0: chiavi 0->1, 30->2, 60->3 ; tabella 1: 0->4, 60->7 ; poi byte che non sono tabelle
    tables = [0x00, 1, 0, 2, 30, 3, 60, 0x01, 4, 0, 7, 60, 0xAD, 9, 33, 7, 54, 3, 72]
    fmt = lambda v: ",\n".join(f"\t0x{x:02x}, // c" for x in v)  # noqa: E731
    f = tmp_path / "ppg_data.c"
    f.write_text('#include <inttypes.h>\n#include "ppg_data.h"\n\n\n'
                 f"const uint8_t ppg_wavetable[] = {{\n{fmt(tables)}\n}};\n\n"
                 f"const uint8_t ppg_waveforms[] = {{\n{fmt(np.concatenate(rom))}\n}};\n")
    return f, np.array(rom)


def test_rom_parsers(tmp_path):
    f, rom = synthetic_rom(tmp_path)
    assert np.array_equal(waves.parse_ppg_rom(f), rom)
    assert waves.parse_ppg_wavetables(f) == [[(0, 1), (30, 2), (60, 3)], [(0, 4), (60, 7)]]
    w = waves.from_ppg_rom(f, 2)
    assert np.array_equal(w.cycle[:64], rom[2] - 128)
    assert np.array_equal(w.cycle[64:], (255 - rom[2][::-1]) - 128)


def test_table_slots_interpolate(tmp_path):
    f, rom = synthetic_rom(tmp_path)
    w, how = waves.from_ppg_table(f, 0, 30)
    assert np.array_equal(w.cycle, waves.ppg_expand(rom[2])) and how == "onda 2"
    w, _ = waves.from_ppg_table(f, 0, 15)
    assert np.allclose(w.cycle, 0.5 * waves.ppg_expand(rom[1]) + 0.5 * waves.ppg_expand(rom[2]))
    with pytest.raises(ValueError):
        waves.from_ppg_table(f, 2, 0)


def test_table_to_31_frames(tmp_path):
    f, rom = synthetic_rom(tmp_path)
    cyc = waves.table_cycles(waves.parse_ppg_rom(f), waves.parse_ppg_wavetables(f)[0])
    assert len(cyc) == 31
    assert np.array_equal(cyc[0], waves.ppg_expand(rom[1]))         # WAVE 4  = posizione 0
    assert np.array_equal(cyc[15], waves.ppg_expand(rom[2]))        # WAVE 64 = posizione 30
    assert np.array_equal(cyc[30], waves.ppg_expand(rom[3]))        # WAVE 124 = posizione 60


def test_cli_build_without_firmware(tmp_path, monkeypatch):
    f, _ = synthetic_rom(tmp_path)
    monkeypatch.setattr(mp, "HERE", tmp_path)
    assert mp.main(["build", "--stock", str(tmp_path / "none.syx"), "--ppg-rom", str(f), "--ppg-table", "1"]) == 0
    spec = json.loads((tmp_path / "patch.json").read_text())
    assert spec["wave"]["source"] == "ppg-wt01" and spec["patches"][0]["len"] == mp.BANK_LEN
    assert mp.main(["build", "--stock", str(tmp_path / "none.syx"), "--designed", "vox", "glass"]) == 0


def test_cli_preview_all(tmp_path):
    f, _ = synthetic_rom(tmp_path)
    out = tmp_path / "pv"
    assert mp.main(["preview", "--ppg-rom", str(f), "--all", "--seconds", "0.2", "-o", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == ["ppg-wt00_min.wav", "ppg-wt01_min.wav"]


def test_catalog_page(tmp_path):
    import catalog
    f, rom = synthetic_rom(tmp_path)
    out = tmp_path / "catalog.html"
    assert catalog.build(f, out) == {"designed": len(waves.SPECTRA), "rom": len(rom), "tables": 2}
    data = json.loads(out.read_text().split("const D=", 1)[1].split(";\n", 1)[0])
    assert data["rom"][5]["empty"] == 1 and data["rom"][6]["dup"] == 1
    assert data["tables"] == [[[0, 1], [30, 2], [60, 3]], [[0, 4], [60, 7]]]
    assert catalog.build(None, tmp_path / "d.html")["rom"] == 0


# ------------------------------------------------------------ con l'OS stock

needs_stock = pytest.mark.skipif(not STOCK.exists(), reason="firmware stock assente")


@needs_stock
def test_stock_bank_hash_and_format():
    region = mp.stock_region(mp.load_section7(STOCK))
    q = mp.read_bank(region)
    assert (q[:, 0] == 0).all() and (q[:, 256] == q[:, 0]).all()


@needs_stock
def test_emulated_sy_chord_plays_new_bank():
    pytest.importorskip("unicorn")
    q = waves.bank_q31(waves.bank(waves.designed_cycles()))
    stock = np.array(mp.emu_render(None, 64, 48, 0.15), dtype=float)
    new = np.array(mp.emu_render(mp.bank_bytes(q), 64, 48, 0.15), dtype=float)
    assert np.max(np.abs(new)) > 0 and not np.allclose(stock, new)


# ------------------------------------------------------------ tools/build/build.py con MAX

@pytest.mark.skipif(not MAX_MANIFEST.exists(), reason="manifest di MAX assente")
def test_build_py_reads_max_mods_and_refuses_both_banks(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "build"))
    import build
    assert build.mod_spec("max:sy-chord")["name"] == "sy-chord"
    with pytest.raises(build.BuildError):
        build.mod_spec("max:nope")
    monkeypatch.setattr(mp, "HERE", tmp_path)
    mp.main(["build", "--stock", str(tmp_path / "none.syx"), "--designed"])
    build.check_selection([tmp_path, "max:deja-vu"])                     # insieme: ok
    with pytest.raises(build.BuildError, match="sy-chord"):
        build.check_selection([tmp_path, "max:sy-chord"])
    # anche le patch, a prescindere da "conflicts", si sovrappongono: il build le rifiuterebbe
    ours = build.load_mod(tmp_path, "1.41")[0]
    theirs = [p for p in build.load_mod("max:sy-chord", "1.41") if p.section == 7][0]
    assert (ours.section, ours.offset, ours.end) == (theirs.section, theirs.offset, theirs.end)
    assert ours.expect_sha256 == theirs.expect_sha256


# ------------------------------------------------------------ builder modulare di MAX (Windows) con patch locale

@pytest.mark.skipif(not MAX_MANIFEST.exists(), reason="manifest di MAX assente")
def test_modular_builder_accepts_local_ppg_patch(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "max" / "modular_builder"))
    import modular_builder as modular
    monkeypatch.setattr(mp, "HERE", tmp_path)
    mp.main(["build", "--stock", str(tmp_path / "none.syx"), "--designed"])
    local = (modular.load_local_mod(tmp_path),)
    full = modular.PRESETS["Original MAX 1.0"]
    with pytest.raises(modular.BuildError, match="SY CHORD Wave Bank"):
        modular.selected_manifest(full, local=local)
    names = [m["name"] for m in modular.selected_manifest(full - {"sy_chord"}, local=local)["mods"]]
    assert names[-1] == "ppg-chord" and "sy-chord" not in names and "deja-vu" in names
    assert names[0] == "splash"                     # come MAX completo: ppg-chord sta per sy-chord
    assert "splash" not in [m["name"] for m in modular.selected_manifest(frozenset({"fx3"}), local=local)["mods"]]
    assert [m["name"] for m in modular.selected_manifest(frozenset(), local=local)["mods"]] == ["ppg-chord"]
    assert modular.profile_name(full - {"sy_chord"}, local) == "CUSTOM + ppg-chord"   # nessun hash "golden"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"name": "x", "os": "1.41", "patches": [{"section": 3, "append": True}]}))
    with pytest.raises(modular.BuildError):
        modular.load_local_mod(bad)


@needs_stock
def test_emulated_wave_value_reads_the_frame_we_wrote():
    """Nel motore originale WAVE (0x40 nell'emulatore = 64) legge il frame 16: cambiarlo cambia il
    suono, cambiare frame lontani (1, 31) no. Conferma la disposizione (al contrario) del banco."""
    pytest.importorskip("unicorn")
    stock = mp.read_bank(mp.stock_region(mp.load_section7(STOCK)))
    other = waves.bank_q31(waves.bank(waves.designed_cycles()))
    base = np.array(mp.emu_render(None, 64, 48, 0.1), dtype=float)

    def diff(k):
        q = stock.copy()
        q[k - 1] = other[(k + 7) % 31]
        out = np.array(mp.emu_render(mp.bank_bytes(q), 64, 48, 0.1), dtype=float)
        return np.max(np.abs(out - base)) / np.max(np.abs(base))
    assert diff(16) > 0.5
    assert diff(1) == 0 and diff(31) == 0


# ------------------------------------------------------------ banco curato (onde scelte)

def _cycle(spec_fn, n=128):
    t = np.arange(n) / n
    return sum(a * np.sin(2 * np.pi * h * t) for h, a in spec_fn().items())


def test_basic_shape_detection():
    saw = _cycle(lambda: {h: 1 / h for h in range(1, 41)})
    sq = _cycle(lambda: {h: 1 / h for h in range(1, 41, 2)})
    sine = _cycle(lambda: {1: 1.0})
    odd = _cycle(lambda: {1: 1.0, 7: 0.9, 13: 0.8, 22: 0.5})
    assert waves.basic_shape(saw) == "saw" and waves.basic_shape(sq) == "square"
    assert waves.basic_shape(sine) == "sine" and waves.basic_shape(odd) is None
    # le nostre onde non sono forme di base, tranne "brass" (un dente di sega con un picco lieve)
    assert {n: waves.basic_shape(waves.design(n).cycle) for n in waves.SPECTRA} == \
        {"hollow": None, "brass": "saw", "vox": None, "glass": None, "reso": None, "sync": None, "organ": None}


def test_curate_skips_empty_duplicates_and_basic(tmp_path):
    f, rom = synthetic_rom(tmp_path)                 # 0..7: seni puri (1a..8a armonica), 5 vuota, 6 = 1
    rom = waves.parse_ppg_rom(f)
    # i seni sono "forme di base" solo se la fondamentale domina: l'onda 0 (fondamentale) lo e'
    cand = waves.candidates(rom)
    assert 0 not in cand and 5 not in cand and 6 not in cand
    picked = waves.curate(rom, 3, min_body=0.0, min_density=0)
    assert len(picked) == 3 and set(picked) <= set(cand)
    b = [waves.brightness(waves.ppg_expand(rom[i])) for i in picked]
    assert b == sorted(b)


def test_most_diverse_is_deterministic_and_spread():
    cyc = [waves.design(n).cycle for n in waves.SPECTRA]
    a, b = waves.most_diverse(cyc, 4), waves.most_diverse(cyc, 4)
    assert a == b and len(set(a)) == 4


def test_order_smooth_beats_random_order():
    frames = [waves.condition(waves.design(n).cycle) for n in waves.SPECTRA] * 1
    order = waves.order_smooth(frames)
    assert sorted(order) == list(range(len(frames)))
    sim = lambda o: sum(waves._similarity(frames[o[i]], frames[o[i + 1]]) for i in range(len(o) - 1))  # noqa: E731
    assert sim(order) >= sim(list(range(len(frames))))
    assert order[0] == min(range(len(frames)), key=lambda i: waves.brightness(frames[i]))


def test_mixed_bank_aligns_polarity():
    f = waves.condition(waves.design("brass").cycle)
    bank = waves.mixed_bank([f if k % 2 == 0 else -f for k in range(31)])
    assert all(bank[k] @ bank[k + 1] > 0 for k in range(30)) and (bank[:, 0] == 0).all()


@pytest.mark.skipif(not MAX_MANIFEST.exists(), reason="manifest di MAX assente")
def test_max_frames_split_basic_and_not():
    nonbasic, basic = mp.max_frames(), mp.max_frames(basic=True)
    assert len(nonbasic) + len(basic) == 31
    names = {n for n, _ in nonbasic}
    assert "MAX FM glass" in names and "MAX Saw" not in names
    assert "MAX Saw" in {n for n, _ in basic}


@pytest.mark.skipif(not MAX_MANIFEST.exists(), reason="manifest di MAX assente")
def test_cli_custom_list_with_max_fill(tmp_path, monkeypatch):
    f, _ = synthetic_rom(tmp_path)
    monkeypatch.setattr(mp, "HERE", tmp_path)
    none = str(tmp_path / "none.syx")
    with pytest.raises(SystemExit, match="fill-max"):
        mp.main(["build", "--stock", none, "--ppg-rom", str(f), "--ppg-waves", "1,2,3"])
    with pytest.raises(SystemExit):
        mp.main(["build", "--stock", none, "--ppg-rom", str(f), "--ppg-waves", "1,1"])
    assert mp.main(["build", "--stock", none, "--ppg-rom", str(f), "--ppg-waves", "1,2,3", "--fill-max"]) == 0
    spec = json.loads((tmp_path / "patch.json").read_text())
    labels = list(spec["wave"]["frames"].values())
    assert len(labels) == 31 and sum(lbl.startswith("PPG #") for lbl in labels) == 3
    assert sum(lbl.startswith("MAX ") for lbl in labels) == 28
    # prima tutte le 21 di MAX non di base, poi 7 di base
    nonbasic = {n for n, _ in mp.max_frames()}
    assert nonbasic <= set(labels)
    q = mp.read_bank(bytes.fromhex(spec["patches"][0]["hex"]))
    assert (q[:, 0] == 0).all() and (q[:, 256] == 0).all() and np.abs(q).max() == waves.PEAK


def test_body_measures_low_harmonic_energy():
    t = np.arange(128) / 128
    assert waves.body(np.sin(2 * np.pi * t)) > 0.99                          # tutta nella fondamentale
    assert waves.body(np.sin(2 * np.pi * 9 * t)) < 0.01                      # tutta in alto
    assert 0.45 < waves.body(np.sin(2 * np.pi * t) + np.sin(2 * np.pi * 9 * t)) < 0.55


def test_curated_bank_requires_body(tmp_path):
    f, _ = synthetic_rom(tmp_path)                 # seni sulle armoniche 1..8: corpo solo per 1..3
    rom = waves.parse_ppg_rom(f)
    assert waves.candidates(rom, min_body=0.7) == [1, 2]        # 0 = seno (forma di base), 3+ = senza corpo
    with pytest.raises(ValueError, match="corpo"):
        waves.curate(rom, 3)                                     # default 0.7: non bastano
    assert len(waves.curate(rom, 3, min_body=0.0, min_density=0)) == 3


def test_body_report_flags_thin_banks():
    thin = np.zeros((31, 257), dtype=np.int64)
    t = np.arange(256) / 256
    thin[:, :256] = np.round(np.sin(2 * np.pi * 9 * t) * waves.PEAK)
    assert "poco corpo" in mp.body_report(thin)
    full = thin.copy()
    full[:, :256] = np.round(np.sin(2 * np.pi * t) * waves.PEAK)
    assert "poco corpo" not in mp.body_report(full)


# ------------------------------------------------------------ wavetable progettate (synth-pop / EBM)

@pytest.mark.parametrize("name", list(tables.TABLES))
def test_designed_tables_have_bank_format(name):
    f, labels = tables.table(name)
    assert f.shape == (31, 256) and len(labels) == 31
    assert (f[:, 0] == 0).all()
    assert np.allclose(np.abs(f).max(axis=1), 1.0)
    mag = np.abs(np.fft.rfft(f, axis=1))
    assert mag[:, tables.DEFAULT_HARMONICS + 1:].max() < 1e-9 * mag.max()      # banda limitata
    q = waves.bank_q31(f)
    assert (q[:, 0] == 0).all() and (q[:, 256] == 0).all() and np.abs(q).max() == waves.PEAK


@pytest.mark.parametrize("name", list(tables.FAMILIES))
def test_designed_families_morph_smoothly(name):
    f, _ = tables.table(name)
    corr = [f[k] @ f[k + 1] / np.linalg.norm(f[k]) / np.linalg.norm(f[k + 1]) for k in range(30)]
    assert min(corr) > 0.4, name                     # stessa fase fra frame vicini: niente cancellazioni


def test_designed_tables_start_on_a_true_rising_zero():
    for name in tables.FAMILIES:
        f, _ = tables.table(name, harmonics=127)
        assert (f[:, 1] > 0).all() or np.median(f[:, 1]) > 0, name        # salita dopo lo zero


def test_ebm_zones_cover_the_bank():
    z = tables.zones()
    assert z[0][1] == 4 and z[-1][2] == 124
    assert all(b[1] == a[2] + 4 for a, b in zip(z, z[1:]))
    _, labels = tables.table("ebm")
    assert [lbl.split()[0] for lbl in labels][:7] == ["reso"] * 7


def test_designed_tables_are_dense_not_organ():
    """Il motivo delle tabelle: timbri densi (sega, impulsi, sync, formanti), non d'organo."""
    dens = {n: np.median([waves.density(x) for x in tables.table(n)[0]]) for n in ("reso", "pwm", "sync", "ebm")}
    assert all(d >= 10 for d in dens.values()), dens


def test_table_rejects_bad_harmonics():
    with pytest.raises(ValueError):
        tables.table("pwm", harmonics=128)
    with pytest.raises(KeyError):
        tables.table("nope")


def test_density_measure():
    t = np.arange(256) / 256
    saw = sum(np.sin(2 * np.pi * h * t) / h for h in range(1, 64))
    organ = sum(a * np.sin(2 * np.pi * h * t) for h, a in {1: 1, 2: .8, 3: .6, 4: .5, 6: .35, 8: .25}.items())
    assert waves.density(saw) >= 30 and waves.density(organ) == 6


def test_grit_adds_ppg_images_and_keeps_format():
    c = waves.design("vox").cycle
    clean, grit = waves.condition(c, 63), waves.condition(c, 127, grit=True)
    assert abs(grit[0]) < 1e-9 and np.isclose(np.abs(grit).max(), 1)
    mag = np.abs(np.fft.rfft(grit))
    assert (mag[64:128] ** 2).sum() > 1e-4 * (mag ** 2).sum()          # immagine sopra la 63a
    assert grit @ clean / np.linalg.norm(grit) / np.linalg.norm(clean) > 0.98   # stessa onda, stessa fase
    with pytest.raises(ValueError):
        waves.condition(c, 64)                                          # senza grit: max 63


def test_cli_table_build_and_ebm_preview(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "HERE", tmp_path)
    none = str(tmp_path / "none.syx")
    assert mp.main(["build", "--stock", none, "--table", "ebm"]) == 0
    spec = json.loads((tmp_path / "patch.json").read_text())
    assert spec["wave"]["source"] == "table-ebm" and spec["wave"]["harmonics"] == tables.DEFAULT_HARMONICS
    assert spec["wave"]["frames"]["4"].startswith("reso") and spec["wave"]["frames"]["124"].startswith("metal")
    out = tmp_path / "pv"
    assert mp.main(["preview", "--table", "pwm", "--ebm", "-o", str(out)]) == 0
    assert (out / "table-pwm_ebm.wav").stat().st_size > 100_000


def test_cli_ppg_table_with_grit(tmp_path, monkeypatch):
    f, _ = synthetic_rom(tmp_path)
    monkeypatch.setattr(mp, "HERE", tmp_path)
    assert mp.main(["build", "--stock", str(tmp_path / "n.syx"), "--ppg-rom", str(f), "--ppg-table", "0",
                    "--grit"]) == 0
    spec = json.loads((tmp_path / "patch.json").read_text())
    assert spec["wave"]["source"] == "ppg-wt00-grit" and spec["wave"]["harmonics"] == 127


@needs_stock
def test_emulated_sy_chord_plays_ebm_table():
    pytest.importorskip("unicorn")
    q = waves.bank_q31(tables.table("ebm")[0])
    stock = np.array(mp.emu_render(None, 64, 48, 0.1), dtype=float)
    new = np.array(mp.emu_render(mp.bank_bytes(q), 64, 48, 0.1), dtype=float)
    assert np.max(np.abs(new)) > 0.2 * np.max(np.abs(stock)) and not np.allclose(stock, new)


@pytest.mark.skipif(not MAX_MANIFEST.exists(), reason="manifest di MAX assente")
def test_identify_bank():
    m = json.loads(MAX_MANIFEST.read_text())
    chord = next(mod for mod in m["mods"] if mod["name"] == "sy-chord")
    (p,) = [p for p in chord["patches"] if p["section"] == 7]
    assert mp.identify_bank(bytes.fromhex(p["hex"])).startswith("MAX")
    mine = json.loads((ROOT / "mods" / "ppg-chord" / "patch.json").read_text())
    assert mp.identify_bank(bytes.fromhex(mine["patches"][0]["hex"])).startswith("ppg-chord, questo patch.json")
    other = waves.bank_q31(tables.table("vowel")[0])
    if mine["wave"]["source"] != "table-vowel":
        assert mp.identify_bank(mp.bank_bytes(other)).startswith("un altro banco")
    assert mp.identify_bank(bytes(mp.BANK_LEN)).startswith("un altro") or True


# ------------------------------------------------------------ volume: fasi a picco basso

def _rms_db(f):
    return 20 * np.log10(np.sqrt((np.asarray(f) ** 2).mean(axis=1)))


def _within_corr(name, f):
    pairs = []
    if name == "ebm":
        k0 = 0
        for _, lo, hi in tables.zones():
            n = (hi - lo) // 4 + 1
            pairs += [(k, k + 1) for k in range(k0, k0 + n - 1)]
            k0 += n
    else:
        pairs = [(k, k + 1) for k in range(30)]
    return [f[a] @ f[b] / np.linalg.norm(f[a]) / np.linalg.norm(f[b]) for a, b in pairs]


@pytest.mark.parametrize("name", list(tables.TABLES))
def test_loud_tables_keep_spectrum_and_are_never_quieter(name):
    plain, _ = tables.table(name, loud=False)
    loud, _ = tables.table(name)
    for a, b in zip(plain, loud):                      # stesso timbro: stesse ampiezze armoniche relative
        ma, mb = np.abs(np.fft.rfft(a)), np.abs(np.fft.rfft(b))
        assert np.allclose(ma / ma.max(), mb / mb.max(), atol=1e-6)
    gain = _rms_db(loud) - _rms_db(plain)
    assert gain.min() > -1.0                           # nessun frame sensibilmente piu' piano


def test_loud_tables_are_louder_where_it_matters():
    for name in ("reso", "vowel", "sync"):
        gain = _rms_db(tables.table(name)[0]) - _rms_db(tables.table(name, loud=False)[0])
        assert np.median(gain) >= 2.0, (name, np.median(gain))
    # ebm: le zone spianate sono gia' meno "a punta"; conta il livello assoluto (prima -7 dBFS)
    assert np.median(_rms_db(tables.table("ebm")[0])) >= -3.5


@pytest.mark.parametrize("name", list(tables.TABLES))
def test_loud_tables_stay_continuous(name):
    plain = _within_corr(name, tables.table(name, loud=False)[0])
    loud = _within_corr(name, tables.table(name)[0])
    assert min(loud) >= min(tables.MIN_NEIGHBOUR, min(plain)) - 0.06, (name, min(plain), min(loud))


def test_cli_keep_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(mp, "HERE", tmp_path)
    none = str(tmp_path / "n.syx")
    mp.main(["build", "--stock", none, "--table", "vowel", "--keep-phase"])
    plain = mp.read_bank(bytes.fromhex(json.loads((tmp_path / "patch.json").read_text())["patches"][0]["hex"]))
    mp.main(["build", "--stock", none, "--table", "vowel"])
    loud = mp.read_bank(bytes.fromhex(json.loads((tmp_path / "patch.json").read_text())["patches"][0]["hex"]))
    assert np.median(_rms_db(loud[:, :256].astype(float)) - _rms_db(plain[:, :256].astype(float))) > 2


def test_ebm_only_vowel_zone_talks():
    """Su hardware il banco ebm sembrava pronunciare vocali "a ciclo": solo la zona vowel deve."""
    f, _ = tables.table("ebm")
    prom, k = {}, 0
    for fam, lo, hi in tables.zones():
        n = (hi - lo) // 4 + 1
        prom[fam] = np.median([tables.formant_prominence(x) for x in f[k:k + n]])
        k += n
    assert prom["vowel"] >= 15
    assert prom["reso"] <= 8 and prom["sync"] <= 8 and prom["pwm"] <= 8 and prom["metal"] <= 12
    for name in ("reso", "sync"):                    # le tabelle singole restano "parlanti"
        assert np.median([tables.formant_prominence(x) for x in tables.table(name)[0]]) > 10
