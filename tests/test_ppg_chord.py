"""Mod ppg-chord: onde nel formato PPG, livelli, patch; con l'OS stock anche SY CHORD nell'emulatore."""

import struct
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "mods" / "ppg-chord")]
import make_patch as mp  # noqa: E402
import waves  # noqa: E402

STOCK = ROOT / "firmware" / "Syntakt_OS1.41.syx"
SEC7_LEN = 383_760


def fake_section7(table: np.ndarray) -> bytes:
    sec = bytearray(SEC7_LEN)
    struct.pack_into(">512i", sec, mp.TABLE_ADDR - mp.LOAD, *(int(v) for v in table))
    return bytes(sec)


def stock_like() -> np.ndarray:
    return np.round(np.sin(2 * np.pi * np.arange(512) / 512) * 0.7 * 2 ** 31).astype(np.int64)


@pytest.mark.parametrize("name", list(waves.SPECTRA))
def test_designed_waves_have_ppg_format(name):
    c = waves.design(name).cycle
    assert c.shape == (128,)
    assert np.allclose(c, -c[::-1] - 1)                    # seconda meta' = ~prima meta' rovesciata
    assert np.allclose(c, np.round(c))                     # 8 bit
    assert -128 <= c.min() and c.max() <= 127


@pytest.mark.parametrize("name", list(waves.SPECTRA))
@pytest.mark.parametrize("interp", ["fft", "step"])
def test_table_is_512_peak_1_no_dc(name, interp):
    t = waves.to_table(waves.design(name).cycle, interp)
    assert t.shape == (512,)
    assert np.isclose(np.max(np.abs(t)), 1.0)
    assert abs(np.mean(t)) < 1e-9


def test_fft_table_is_band_limited():
    for name in waves.SPECTRA:
        mag = np.abs(np.fft.rfft(waves.to_table(waves.design(name).cycle, "fft")))
        assert mag[64:].max() < 1e-9 * mag.max(), name


def test_design_is_deterministic():
    assert np.array_equal(waves.design("vox").cycle, waves.design("vox").cycle)


def test_level_follows_stock_rms_never_its_peak():
    stock = stock_like()
    for name in waves.SPECTRA:
        y = waves.fit_level(waves.to_table(waves.design(name).cycle), stock).astype(float)
        assert np.max(np.abs(y)) <= np.max(np.abs(stock)) + 1, name
        rms, s_rms = np.sqrt(np.mean(y ** 2)), np.sqrt(np.mean(stock.astype(float) ** 2))
        assert rms <= s_rms * 1.001, name
        assert rms >= s_rms * 0.5, name                    # non troppo piu' piano dell'originale


def test_rotation_matches_stock_ends():
    stock = stock_like()
    y = waves.fit_level(waves.to_table(waves.design("hollow").cycle), stock).astype(float)
    step = np.max(np.abs(np.diff(y)))                      # passo massimo dentro il ciclo
    assert abs(y[0] - stock[0]) <= step and abs(y[-1] - stock[-1]) <= 2 * step


def test_build_spec_hash_and_bytes():
    sec = fake_section7(stock_like())
    spec, table = mp.build_spec(sec, waves.design("brass"))
    p = spec["patches"][0]
    assert p["section"] == 7 and int(p["addr"], 16) == mp.TABLE_ADDR and p["len"] == 2048
    o = mp.TABLE_ADDR - mp.LOAD
    assert p["expect_sha256"] == mp.sha(sec[o:o + 2048])
    assert bytes.fromhex(p["hex"]) == mp.table_bytes(table)
    assert list(struct.unpack(">512i", bytes.fromhex(p["hex"]))) == [int(v) for v in table]


def test_build_spec_refuses_unexpected_bytes():
    with pytest.raises(SystemExit):
        mp.build_spec(bytes(SEC7_LEN), waves.design("brass"))


def test_ppg_rom_parser(tmp_path):
    rng = np.random.default_rng(1)
    rom = rng.integers(0, 256, size=(3, 64))
    body = ",\n".join(", ".join(f"0x{v:02X}" for v in row) for row in rom)
    f = tmp_path / "ppg_data.c"
    f.write_text("#include <stdint.h>\nconst uint8_t ppg_wavetable[] = {1, 2};\n"
                 f"const uint8_t ppg_waveforms[] = {{ /* onda 0 */\n{body}\n}};\n")
    assert np.array_equal(waves.parse_ppg_rom(f), rom)
    w = waves.from_ppg_rom(f, 2)
    assert np.array_equal(w.cycle[:64], rom[2] - 128)
    assert np.array_equal(w.cycle[64:], (255 - rom[2][::-1]) - 128)


def test_chord_preview_renders():
    x = mp.render_chord(waves.fit_level(waves.to_table(waves.design("organ").cycle), None), seconds=0.2)
    assert x.shape == (int(0.2 * 48000),) and np.max(np.abs(x)) > 0.1


# ------------------------------------------------------------ con l'OS stock

needs_stock = pytest.mark.skipif(not STOCK.exists(), reason="firmware stock assente")


@needs_stock
def test_stock_table_is_a_wave():
    ok, why = mp.looks_like_wave(mp.read_table(mp.load_section7(STOCK)))
    assert ok, why


@needs_stock
def test_emulated_sy_chord_follows_new_table():
    pytest.importorskip("unicorn")
    sec = mp.load_section7(STOCK)
    _, table = mp.build_spec(sec, waves.design("hollow"))
    stock = np.array(mp.emu_render(None, 48, 0.15), dtype=float)
    new = np.array(mp.emu_render(mp.table_bytes(table), 48, 0.15), dtype=float)
    assert np.max(np.abs(new)) > 0                          # suona
    assert not np.allclose(stock, new)                      # e suona diverso
    # il nuovo livello resta vicino a quello stock (stesso RMS della tabella, mai piu' picco)
    assert np.sqrt(np.mean(new ** 2)) < 2.0 * np.sqrt(np.mean(stock ** 2))


# ------------------------------------------------------------ wavetable e catalogo (ROM sintetica)

def synthetic_rom(tmp_path, n_waves=8):
    """Stesso formato C di wave-stuff/data/ppg_data.c, dati nostri (onde sinusoidali con armoniche)."""
    ph = (np.arange(64) + 0.5) / 128
    rom = [np.clip(np.round(128 + 120 * np.sin(2 * np.pi * (k + 1) * ph) / (1 + 0.1 * k)), 0, 255).astype(int)
           for k in range(n_waves)]
    rom[5] = np.full(64, 128)                                     # onda vuota
    rom[6] = rom[1]                                               # duplicato
    # tabella 0: chiavi 0->1, 30->2, 60->3 ; tabella 1: 0->4, 60->7
    tables = [0x00, 1, 0, 2, 30, 3, 60, 0x01, 4, 0, 7, 60]
    fmt = lambda v: ",\n".join(f"\t0x{x:02x}, // c" for x in v)  # noqa: E731
    f = tmp_path / "ppg_data.c"
    f.write_text('#include <inttypes.h>\n#include "ppg_data.h"\n\n\n'
                 f"const uint8_t ppg_wavetable[] = {{\n{fmt(tables)}\n}};\n\n"
                 f"const uint8_t ppg_waveforms[] = {{\n{fmt(np.concatenate(rom))}\n}};\n")
    return f, np.array(rom)


def test_wavetable_parser_and_slots(tmp_path):
    f, rom = synthetic_rom(tmp_path)
    assert waves.parse_ppg_wavetables(f) == [[(0, 1), (30, 2), (60, 3)], [(0, 4), (60, 7)]]
    w, how = waves.from_ppg_table(f, 0, 30)                     # chiave esatta
    assert np.array_equal(w.cycle, waves.ppg_expand(rom[2])) and how == "onda 2"
    w, how = waves.from_ppg_table(f, 0, 15)                     # a meta' fra 1 e 2
    assert np.allclose(w.cycle, 0.5 * waves.ppg_expand(rom[1]) + 0.5 * waves.ppg_expand(rom[2]))
    w, _ = waves.from_ppg_table(f, 1, 45)
    assert np.allclose(w.cycle, 0.25 * waves.ppg_expand(rom[4]) + 0.75 * waves.ppg_expand(rom[7]))
    with pytest.raises(ValueError):
        waves.from_ppg_table(f, 2, 0)
    with pytest.raises(ValueError):
        waves.from_ppg_table(f, 0, 61)


def test_cli_ppg_table_patch(tmp_path, monkeypatch):
    f, _ = synthetic_rom(tmp_path)
    monkeypatch.setattr(mp, "load_section7", lambda _: fake_section7(stock_like()))
    monkeypatch.setattr(mp, "HERE", tmp_path)
    stock = tmp_path / "stock.syx"
    stock.write_bytes(b"x")
    assert mp.main(["build", "--stock", str(stock), "--ppg-rom", str(f), "--ppg-table", "0", "--ppg-slot", "15"]) == 0
    import json
    spec = json.loads((tmp_path / "patch.json").read_text())
    assert spec["wave"]["name"] == "wt00s15" and "0.50*onda 1 + 0.50*onda 2" in spec["wave"]["source"]


def test_catalog_page(tmp_path):
    import json
    import catalog
    f, rom = synthetic_rom(tmp_path)
    out = tmp_path / "catalog.html"
    n = catalog.build(f, out)
    assert n == {"designed": len(waves.SPECTRA), "rom": len(rom), "tables": 2}
    page = out.read_text()
    data = json.loads(page.split("const D=", 1)[1].split(";\n", 1)[0])
    assert data["rom"][5]["empty"] == 1 and data["rom"][6]["dup"] == 1
    assert data["tables"] == [[[0, 1], [30, 2], [60, 3]], [[0, 4], [60, 7]]]
    assert len(data["romCycles"]) == 4 * ((len(rom) * 128 + 2) // 3)
    assert catalog.build(None, tmp_path / "d.html")["rom"] == 0
