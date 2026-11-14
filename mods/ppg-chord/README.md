# ppg-chord

Replaces the single-cycle wave of **SY CHORD** with a PPG-style digital wave, aimed at 80s synth-pop / EBM chords: bright, hollow, nasal, a bit grainy.

- **What changes:** the 512 × int32 (Q31) table SY CHORD reads at `0x4001A300`, in section 7 (voice engine, CPU #2). 2048 bytes of data, no code.
- **CPU cost:** zero. The engine reads the same table at the same rate.
- **Needs:** nothing else. This works with or without the other mods.

## The waves

They are built in the **PPG Wave 2.x wave format**, as documented by [wave-stuff](https://github.com/Jacajack/wave-stuff):

- 64 unsigned 8-bit samples per half cycle;
- the second half is the first half reversed and inverted (`~w[127-p]`), giving odd symmetry around mid-cycle;
- 128 samples per cycle, carrying the grain of 8-bit samples.

They are then stretched to 512 samples, band-limited by default, and leveled to the stock wave. The spectra are our own (`waves.py`):

| Wave | Character | Try it for |
|---|---|---|
| `hollow` | odd harmonics + formant on the 7th: nasal square | pads, arpeggios (default) |
| `brass` | saw with a peak on the 5th–7th | stabs |
| `vox` | three fixed formants: digital "aah" | choir pads |
| `glass` | sparse harmonics 1-2-5-9-14-23-31 | bells, metallic plucks |
| `reso` | saw through a resonant low-pass frozen on the 12th | the "frozen sweep" sound |
| `sync` | hard-sync spectrum (ratio 3.7) | aggressive leads, EBM bass |
| `organ` | drawbars 1-2-3-4-6-8 | wide, clean chords |

![waves](waves.png)

Formants are fixed to harmonic numbers, not to frequencies. A wave keeps its character up and down the keyboard, the way a single PPG wave does.

## All the waves: the catalog

The 7 waves above are our own. To choose from **everything**, use the catalog. Put your copy of wave-stuff's `data/ppg_data.c` in `local/` (git-ignored) and run:

```sh
python mods/ppg-chord/make_patch.py catalog --ppg-rom local/ppg_data.c    # -> out/ppg-chord/catalog.html
```

It writes one self-contained page with three tabs:

- **Designed:** the 7 waves above.
- **ROM waves:** all 256 PPG waves. Each shows a brightness score (spectral centroid, in harmonics); empty waves and duplicates are hidden by default. Sort by number or brightness.
- **Wavetables:** all 29 tables × 61 slots. Key waves are outlined, and the slots between them are interpolated as the PPG does. That's ~1,800 more waves.

Click a wave to hear it as a chord. Chord type and root are selectable; playback is Web Audio, band-limited like `--interp fft`. The footer shows the exact `build` command for that wave. ★ shortlists a wave; the shortlist stays in your browser.

The page contains the ROM data read from your local file. It lives in `out/`, so keep it out of the repo.

## Use

```sh
python mods/ppg-chord/make_patch.py list
python mods/ppg-chord/make_patch.py preview                 # WAV chords per wave in out/ppg-chord/preview (no firmware needed)
python mods/ppg-chord/make_patch.py preview --chord sus4 --root 43
python mods/ppg-chord/make_patch.py build --ppg-rom local/ppg_data.c --ppg-index 23
python mods/ppg-chord/make_patch.py build --ppg-rom local/ppg_data.c --ppg-table 5 --ppg-slot 30
python mods/ppg-chord/make_patch.py build --wave vox         # writes patch.json (needs firmware/Syntakt_OS1.41.syx)
python mods/ppg-chord/make_patch.py build --wave vox --emu   # + SY CHORD rendered by the original engine, stock vs new
python tools/build/build.py --stock firmware/Syntakt_OS1.41.syx mods/ppg-chord ... -o out/synthack.syx
```

With the stock OS in `firmware/`, `preview` also renders the **stock** wave (`stock_min.wav`) for A/B.

### Options

- `--interp fft` (default): clean, band-limited, no harmonics above the 63rd.
- `--interp step`: each 8-bit sample held 4×, like a non-interpolating 8-bit player. Brighter and dirtier, with some aliasing on high notes.
- `--bits 16`: skip the 8-bit quantisation for a cleaner wave.
- `--gain-db`: level trim. The level is matched to the stock wave's RMS and never goes above the stock peak, because chords sum several voices.
- `--ppg-rom local/ppg_data.c --ppg-table T --ppg-slot S`: use slot S (0–60) of wavetable T, interpolated between its key waves.
- `--ppg-rom local/ppg_data.c --ppg-index N`: use wave N from your own local copy of wave-stuff's `data/ppg_data.c`. Keep it in `local/`, which is git-ignored. A `patch.json` built this way contains bytes derived from that data.

### Checks done by `build`

- The section 7 hash must be OS 1.41.
- The stock table must look like a wave: amplitude, no DC, no jumps.
- The 2 KB blocks around it are scanned and listed if they also look like waves. If they do, SY CHORD's WAV parameter may pick among several tables; check the disassembly before patching them.
- The new cycle is phase-rotated so that its first and last samples meet the stock ones. If the engine reads a guard sample past the table, it finds no step there.

## Status

- ✅ Wave design, format, levels, patch generation: `tests/test_ppg_chord.py`, runs without firmware.
- ⬜ Emulator check with the stock section 7 (`test_emulated_sy_chord_follows_new_table`): skipped until the stock OS is in `firmware/`.
- ⬜ Not yet tried on hardware.
- **Known unknown:** whether *all* SY CHORD WAV settings use this table, or only one. `build` prints the neighbouring tables to help find out.
