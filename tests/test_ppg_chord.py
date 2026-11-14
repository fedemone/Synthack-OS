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
