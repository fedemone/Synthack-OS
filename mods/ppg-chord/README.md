# ppg-chord: PPG wavetable for SY CHORD

This mod puts **PPG-style wavetables** into SY CHORD's wave bank. There are designed tables for synth-pop / EBM, tables from the PPG ROM, or a curated selection of PPG waves. Turning **WAVE** from 4 to 124 then sweeps through the table, and SY CHORD blends neighbouring frames, much as the PPG Wave scans its tables. You can p-lock WAVE or modulate it like any other machine parameter.

- **Replaces:** MAX's *SY CHORD Wave Bank*. It writes the same region, so you use one or the other (see [Builds](#builds)).
- **Unchanged:** WAVE 0 (a sine shared with other machines), every other machine, and the screen pictures. The small wave picture for WAVE still shows the stock shapes, by choice.
- **Cost:** data only, no code, no CPU load.
- **Existing sounds:** those that use SY CHORD with WAVE above 0 will sound different.

## How a PPG table becomes the bank

| PPG Wave | SY CHORD bank |
|---|---|
| 61 positions per wavetable; key waves at some positions, interpolated in between | 31 frames, WAVE 4, 8 … 124; SY CHORD interpolates in between |
| each wave: 64 8-bit samples per half cycle, mirrored and inverted to 128 | each frame: 256 samples + 1 guard sample, int32, peak `0x7FFF0000`, starting at 0 |

- **Positions:** positions 0, 2, … 60 become frames 1 … 31, which is exactly 31. Wavetables with a key wave at every second position (16, 26 and 27 in wave-stuff's data) keep every key wave.
- **Band limit:** each frame is band-limited, 40 harmonics by default, as in Workbench. `--harmonics` goes up to 63, the most a PPG wave has. SY CHORD uses the same frame for every note, so brighter means more aliasing on high notes.
- **Phase:** every PPG wave has odd symmetry around mid-cycle, so its band-limited version crosses zero exactly there. Each frame is rotated by that half cycle, so all frames start at a true 0 with the same phase. SY CHORD's blending between frames then never cancels out.
- **Polarity:** one polarity for the whole bank, decided by majority.

The bank layout comes from [syntakt-firmware-workbench](https://github.com/Bezronczek/syntakt-firmware-workbench) (Bezronczek, MIT), measured on hardware; see [docs/audio-path.md](../../docs/audio-path.md). The PPG format comes from [wave-stuff](https://github.com/Jacajack/wave-stuff).

## Designed tables for synth-pop / EBM (default)

![designed tables](tables.png)

These are our own tables, generated in `tables.py`. They need no ROM and are committed. Each is a smooth 31-frame morph: frames stay in phase and every frame starts on a true rising zero.

| Table | Morph (WAVE 4 → 124) | For |
|---|---|---|
| `reso` | saw through a resonant low-pass opening from the 1.5th to the 48th harmonic | EBM bass and leads, the PPG "sweep" |
| `pwm` | pulse 50 % → 5 % | PWM pads and basses |
| `vowel` | vowels A → E → I → O → U (formants) | digital choirs, great with SY CHORD's unison |
| `sync` | hard sync, ratio 1 → 8, with some master saw | aggressive leads |
| `fold` | wavefolder, gain 1 → 12 | rough digital tones |
| `brass` | FM 1:1, index 0 → 7 | digital brass that opens up |
| `metal` | FM 1:3, index 0 → 6 | bells, metallic hits |
| **`ebm`** | **zones:** reso WAVE 4–28 · pwm 32–52 · vowel 56–80 · sync 84–104 · metal 108–124 | variety in one bank; **the committed default** |

- **Band limit:** these are brighter than the PPG conversions: 64 harmonics by default instead of 40, up to 127 with `--harmonics`.
- **Louder by default, same timbre.** Every frame is at full peak, like the stock frames, so the level depends on how "peaky" the waveform is. The ear hears the harmonic levels, not their phase alignment, so the tables keep each frame's exact harmonic levels and choose the phases for a low peak.
  - **Gain** (frame RMS): `reso` +4.1 dB, `vowel` +4.7, `sync` +3.9, `pwm` +2.5. The `ebm` bank goes from −7.0 to −3.0 dBFS median, about 2 dB above the stock bank. `fold`, `brass` and `metal` were already low-peak.
  - **Continuity:** each frame starts from its neighbour's phases and must stay similar to it (≥ 0.75 where achievable), so WAVE sweeps stay smooth. No frame gets quieter. `--keep-phase` keeps the original waveforms.
  - **Rendered:** in offline single-note and chord renders the gain holds at every root (+2 to +3.7 dB per zone). In the original engine (emulator, a 2 s SY CHORD chord at WAVE 64, `vowel` zone):
    - −0.4 dB in the first 0.35 s, then +0.5, +3.3, +3.8 and +2.0 dB in the following 0.4 s windows; +1.0 dB over the whole note;
    - peak 1.7 dB lower, which leaves headroom.

    Partials shared by two chord notes add or partly cancel depending on phase, and that relation drifts as the notes beat. So in chords the gain varies over time, and is smallest at the attack.
- **Only the vowel zone talks.** In `ebm`, the moving spectral bumps of `reso` (resonance), `sync` (sync peak) and `metal` (FM sidebands) are flattened toward the smooth spectral trend, so they no longer sound like vowels gliding while you sweep. The bump above the trend goes from 16.7 to 6.5 dB in `reso`, 12.5 to 5.0 in `sync`, and 22.2 to 11.1 in `metal` (half, to keep the bells). `vowel` stays at 16 dB. The standalone `reso`, `sync` and `metal` tables keep their talking character.
- **Phase alignment:** the starting point of all 31 frames (a rising zero, upright or flipped) is chosen jointly, to maximise the similarity along the whole table rather than frame by frame.
- **`ebm` zones:** pick a zone with WAVE, then sweep inside it per note. LFO in ONE mode with a small depth, e.g. WAVE 4 + 24 for a filter-like bass sweep.
- **`build` vs `preview`:** `build --table NAME` writes the bank. `preview --table all` renders a chord sweep per table, and `preview --table reso --ebm` a 16th-note bass line where each note sweeps WAVE once.

**Why these exist.** The earlier PPG selections sounded like an organ on hardware, and measuring explains it:
- A drawbar organ has ~4–8 strong harmonics (within 30 dB of the loudest); a saw has 31.
- Both curated PPG banks had a median of **6–9** per frame. Two rules caused it: "no basic shapes" removed exactly the saw/pulse family, and the body rule favoured flute/organ spectra.
- Synth-pop and EBM timbres are dense: saw and pulse, resonance, sync, formants.

## Sources

- **A PPG wavetable** (0–28) from your **local** copy of wave-stuff's `data/ppg_data.c`. Keep it in `local/` (git-ignored). A `patch.json` built from it contains data derived from that ROM.
- **A curated bank** (`--curated`): 31 single ROM waves instead of one table. The ROM holds 241 distinct waves for 31 frames, so a choice is made:
  - **sparse (organ-like) waves** are dropped: at least 15 of the first 40 harmonics within 30 dB of the strongest (`--min-density`, default 15).
  - waves **without body** are dropped: harmonics 1–3 must carry at least 30 % of the energy (`--min-body`, default 0.3). An earlier default of 0.7 kept only flute/organ spectra. Without this rule the "most different" waves were almost all high harmonics: body 0.29 against 0.96 for the stock bank. On hardware they sounded short and thin, because the closing low-pass filter removes nearly all of such a wave. In the emulator, same sound: 3.4 dB quieter and decaying 3 dB faster than stock. 37 non-basic PPG waves pass both rules.
  - empty waves, duplicates and **basic shapes** are dropped. A wave counts as basic when its spectrum is ≥ 0.95 similar to a sine, saw, square, triangle or 6–38 % pulse; that's 55 of the 241, leaving 186.
  - the 31 most different from each other are kept;
  - they are ordered so that each wave resembles the next. The order starts from the darkest and roughly brightens; neighbour similarity rises from ~0.25 to ~0.6, so SY CHORD's blends between frames stay musical. `--order brightness` gives a strict dark → bright order instead.
- **Your own list** (`--ppg-waves 12,40,77,…`, up to 31). In the catalog, star ROM waves and press *Starred ROM waves → bank* to get the command. With fewer than 31, `--fill-max` completes the bank from MAX's SY CHORD bank: first its 21 non-basic waves (FM, formant, wavefold, sync, organ, chord waves…), then, only if still needed, its saws and pulses.
- **PPG grit** (`--grit`, for PPG sources): reads each 8-bit PPG wave "in steps", as the PPG did without smoothing. This adds its images above the 63rd harmonic, up to the 127th: a little digital sparkle. The effect is subtle, about 0.2 % of the energy.
- **Our 7 designed waves** (`--designed`): hollow, brass, vox, glass, reso, sync, organ. They are spread over the table in order and interpolated. You can give your own order, for example `--designed vox glass reso`. These need no ROM.

![designed waves](waves.png)

## Making it move like a PPG

Measured in the original engine: **SY CHORD never moves through the bank by itself.** At a fixed WAVE it reads only the one or two frames at that position for the whole note. The output is bit-identical with every other frame silenced.

On a PPG Wave, the evolving sound comes from **modulating the wavetable position on every note**, mainly with an envelope, plus LFO and keyboard. A fixed position gives a static timbre there too.

On the Syntakt, do the same with the track LFO on the SY CHORD track:

| Goal | LFO setting |
|---|---|
| PPG-style sweep on each note (envelope → wavetable) | DEST = WAVE (SYN page), MODE = ONE (runs once per trig), a ramp/exponential shape, DEP sets how far it sweeps, SPD/MULT how fast |
| Continuous cycling while the note holds | DEST = WAVE, MODE = TRG or FREE, TRI or SIN |
| A different wave on every note | DEST = WAVE, Déjà Vu DV-T (MAX), or p-locks on WAVE per step |

Also check the amp envelope (decay/sustain) and the filter envelope of the sound.

**Which bank to use:**
- **Wavetable mode** is the PPG-like choice for sweeps: neighbouring frames are related, so the sweep is a smooth morph.
- **The curated bank** is a palette of 31 distinct timbres: better picked with p-locks than swept.
- **Tables with plenty of body:** 3, 6, 7, 8, 12, 16, 17, 19, 22, 23, 24, 25, 28. The catalog shows each table's body; thin tables are marked.

`build` prints the body of the bank it writes, next to stock (0.96) and MAX (0.76).

## Is the new bank on the device?

Set **WAVE = 52** on SY CHORD and compare it with **WAVE = 0**, which is always the stock sine. Use one note (unison), filter open, and nothing modulating WAVE:

| Bank on the device | WAVE 52 sounds like | WAVE 124 |
|---|---|---|
| stock | a pure sine, almost the same as WAVE 0 | sine-like |
| MAX | Organ 1-2-4 | a major-9 chord in one note |
| ppg-chord `ebm` | a thin, buzzy ~10 % pulse | metallic FM |

To see which bank a `.syx` file contains: `python3 mods/ppg-chord/make_patch.py check out/max-ebm.syx`.

## Use

```sh
python mods/ppg-chord/make_patch.py catalog --ppg-rom local/ppg_data.c    # out/ppg-chord/catalog.html
python mods/ppg-chord/make_patch.py preview --ppg-rom local/ppg_data.c --all   # one WAV per table: chord sweeping WAVE 4 -> 124
python mods/ppg-chord/make_patch.py preview --ppg-rom local/ppg_data.c --ppg-table 5 --hold 64
python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --ppg-table 5    # writes patch.json
python mods/ppg-chord/make_patch.py build   --table ebm                # the committed default; also reso, pwm, vowel, sync, fold, brass, metal
python mods/ppg-chord/make_patch.py preview --table all --ebm          # one EBM bass line per designed table
python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --ppg-table 7 --grit
python mods/ppg-chord/make_patch.py build   --designed
python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --curated
python mods/ppg-chord/make_patch.py build   --ppg-rom local/ppg_data.c --ppg-waves 12,40,77 --fill-max
```

`build` needs no firmware: the stock hash of the region is the one MAX's bank declares, and every build checks it again against your OS. With `firmware/Syntakt_OS1.41.syx` present, `build` also checks the stock bank right away. Add `--emu` to also render SY CHORD with the original engine, before and after.

**The catalog** is one local page with every wave:
- **Designed:** the 7 designed waves.
- **ROM waves:** the 256 ROM waves. Waves close to a basic shape are dimmed and labelled, and *hide basic shapes* removes them. Stars feed *Starred ROM waves → bank*.
- **Curated bank:** the 31 waves `--curated` picks, in bank order, with **▶ sweep**.
- **Wavetables:** the 29 tables. Each has a **▶ sweep** button that plays WAVE 4 → 124, and the slots that become frames are labelled W4 … W124.

The footer shows the `build` command for the table you picked. ★ shortlists a wave in your browser. The page contains ROM data from your local file and is written to `out/`.

## Builds

**Linux / WSL** (`tools/build/build.py`): MAX's features are available as `max:<name>`. To build the MAX set with the PPG wavetable instead of MAX's bank:

```sh
python tools/build/build.py --stock firmware/Syntakt_OS1.41.syx \
    max:splash max:dual-mono max:modarea max:vparams max:master-comp max:readable-values \
    max:beat-repeat max:fx3 max:deja-vu mods/ppg-chord -o out/max-ppg.syx
```

Add `max:fm4` for SY FM4. `ppg-chord` together with `max:sy-chord` is refused, both through `"conflicts"` and through the overlap check.

**Windows modular builder** (`tools/max/modular_builder`): under *Local patch* choose `mods/ppg-chord/patch.json` and untick *SY CHORD Wave Bank*. The builder refuses to combine the two. A build with a local patch is reported as profile `CUSTOM + ppg-chord` and has no pinned "golden" hash. The packaged `.exe` has to be rebuilt from source (`build_windows.ps1`) to get this option.

## Status

- ✅ Bank layout, frame format, conditioning, patch, and compatibility with MAX's manifest: `tests/test_ppg_chord.py`. It checks that MAX's bank occupies the same region, has the same stock hash and uses the same frame format. These run without firmware.
- ✅ All 29 real wave-stuff tables convert (checked locally).
- ⬜ Emulator tests with the stock OS: skipped until it is in `firmware/`.
- ⬜ Windows GUI change: syntax-checked only, not run.
- ⬜ Not yet tried on hardware.
