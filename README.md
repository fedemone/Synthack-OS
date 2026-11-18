# Syntakt MAX 1.0

Unofficial community mod bundle for **Elektron Syntakt OS 1.41**, built locally from your own official OS file with a standalone Windows builder. No Elektron firmware is distributed. Not affiliated with or supported by Elektron.

**Hardware evidence:** Kári's upstream-based MAX image booted and its musical features functioned on one Syntakt. Known-good output SHA-256: `7cb4bfd3da4af9c417ae812ec205036a85a430f3be62263cf58e6ae31df2c093`. Kári also manually completed the Windows GUI build workflow. Other hardware/software configurations and exhaustive regressions are not certified.

**Release preparation:** local draft only; no release has been published by this run. See [release notes](tools/max/release_1_0/RELEASE_NOTES.md), [installation](tools/max/release_1_0/INSTALL.md), [attribution](tools/max/release_1_0/ATTRIBUTION.md), and [release validation](tools/max/release_1_0/REVIEW.md). Windows 11 x64 is the tested builder platform. Read [recovery guidance](RECOVERY.md) before installing modified firmware.

## This fork: MAX + PPG-style wavetables for SY CHORD

This fork builds the MAX feature set with **[`mods/ppg-chord`](mods/ppg-chord) in place of MAX's SY CHORD wave bank**. SY CHORD's WAVE 4 … 124 then scan PPG-style wavetables. The default bank, `ebm`, has zones of resonant saw, PWM, vowels, sync and FM metal for synth-pop / EBM; PPG ROM tables and curated PPG waves are options. WAVE 0, the screen pictures and every other machine are unchanged.

**Hardware:** verified on a Syntakt (OS 1.41) with MAX + FM4 + `ppg-chord`, with both the `ebm` bank (the default) and the `ebm7` zone bank (with PPG tables): it boots, the waves sweep, envelopes and level are normal. The build is reproducible: the same inputs give the same SHA-256.

## Build and install (this fork)

Linux or WSL. Nothing here talks to the Syntakt; you flash the resulting file yourself with Elektron Transfer.

### 1. One-time setup

```sh
git clone https://github.com/fedemone/Synthack-OS.git && cd Synthack-OS
git checkout claude/funny-lovelace-otvta4          # the branch of this fork (PR #1)
bash tools/unpack/setup_eft.sh                       # builds elektron-firmware-tool in third_party/
git config core.hooksPath tools/hooks                # blocks firmware files from commits
pip install numpy                                    # only to regenerate banks (make_patch.py)
```

Put your official **Syntakt OS 1.41** from elektron.se at `firmware/Syntakt_OS1.41.syx` (git-ignored) and check it:

```sh
sha256sum firmware/Syntakt_OS1.41.syx   # 8e2488f462c4a5656396a895f113bcd415e9900fa8709340dccf45d4cb9ed19e
```

### 2. Choose the SY CHORD bank (optional)

The committed `mods/ppg-chord/patch.json` is the `ebm` bank, which is ready to build. To use another bank, regenerate it first; see [mods/ppg-chord](mods/ppg-chord#banks). For example:

```sh
python3 mods/ppg-chord/make_patch.py preview --table all --ebm    # listen: WAVs in out/ppg-chord/preview
python3 mods/ppg-chord/make_patch.py build --table vowel          # or --ppg-rom local/ppg_data.c --ppg-table 7
python3 mods/ppg-chord/make_patch.py build --zones ebm7 --ppg-rom local/ppg_data.c   # 7 zones, with PPG tables 23, 26, 14
```

Banks built from the PPG data (`--ppg-rom`) contain data derived from the PPG ROM: build them locally and keep them private; don't commit that `patch.json`.

### 3. Build

```sh
python3 tools/build/build.py --stock firmware/Syntakt_OS1.41.syx \
    max:splash max:dual-mono max:modarea max:vparams max:master-comp max:readable-values \
    max:beat-repeat max:fx3 max:deja-vu max:fm4 mods/ppg-chord -o out/synthack-ppg.syx
```

- `max:<name>` takes a feature from MAX's manifest. Drop the ones you don't want, for example `max:fm4` for SY FM4.
- The build refuses a wrong stock OS, overlapping or conflicting mods (`ppg-chord` with `max:sy-chord`), and an unsafe boot margin. It overwrites the output file.

### 4. Verify the file before flashing

```sh
python3 tools/unpack/eft.py info out/synthack-ppg.syx              # Syntakt, version 1.41, checksums : ok
python3 mods/ppg-chord/make_patch.py check out/synthack-ppg.syx    # which SY CHORD bank is inside
sha256sum out/synthack-ppg.syx
```

With the default `ebm` bank and the mod list above, the SHA-256 is `64e84f9ace79b273a0225f17d08e4571a96640df6d30e1cde2b4ef2b2784feb5`.

### 5. Flash

1. Back up your projects and sounds. Keep the official OS file at hand.
2. Send `out/synthack-ppg.syx` with Elektron Transfer using the **OS update** flow.
3. **Accept the confirmation prompt on the Syntakt.** Do not interrupt power until the update has finished and the device has restarted. If there is no prompt, the update did not happen and the old OS is still there.

### 6. Check on the device

On SY CHORD, use one note, an open filter and nothing modulating WAVE, and compare **WAVE 124** with **WAVE 0** (always the stock sine):
- **sine-like:** the stock bank is still installed;
- **a major-9 chord in one note:** MAX's own bank is installed;
- **metallic FM (`ebm`) or a PPG wave (`ebm7`):** the new bank is installed.

With `ebm`, WAVE 52 is also a quick check: a thin, buzzy pulse.

More in [mods/ppg-chord](mods/ppg-chord#playing-it).

### Updating later

```sh
git checkout -- mods/ppg-chord/patch.json    # only if you regenerated it locally
git pull
```

Then repeat steps 2–6. Your projects and sounds stay on the device; sounds that use a changed WAVE value will sound different.

### Back to stock or recovery

Flash the official `Syntakt_OS1.41.syx` the same way. If the device does not boot, follow [RECOVERY.md](RECOVERY.md): STARTUP menu (hold FUNC at power-on), OS UPGRADE, then send the file over DIN MIDI.

### Tests (optional)

```sh
pip install pytest unicorn
python3 -m pytest -q tests/test_ppg_chord.py tests/test_build.py
```

With the stock OS in `firmware/`, the tests also play SY CHORD's bank in the original sound engine (emulator).

## Included in MAX 1.0

| Included feature | What it does | Origin |
| --- | --- | --- |
| Master compressor | Analog-master VCA compression with threshold, attack, release, makeup, ratio, gain-reduction meter and comparison switch on FX SYN. Settings stored with the kit; no dry/wet control. | Angelo-politek / SyntHack |
| Third send FX | SND3 sends audio tracks to chorus, flanger, phaser or crusher; FX REVERB page 2 controls the effect, return and delay send. Kit storage and track send p-locks. | Angelo-politek / SyntHack |
| Beat Repeat | Hold FX-track retrig key 13 or 14 to loop sequencer steps and p-locks on all tracks, including analog tracks; release resumes in time. RPT1/RPT2 select 1/16, 1/8, 3/16, 1/4, 1/2 or one bar. | Angelo-politek / SyntHack |
| Dual mono input | In mono external-input mode, IN L and IN R have independent levels on the External Mixer page. | Angelo-politek / SyntHack |
| Readable values | Shows supported filter, envelope, level, send, delay and reverb values in units such as Hz, dB, ms and percent. | Angelo-politek / SyntHack |
| Déjà Vu LFO | Adds DV-F (free-running) and DV-T (restarts on notes). MODE selects 2/4/8/16/32 steps; SPH moves from new random values (0), through repeating (64), to reordering (127). Retains the seven native shapes. | Bezronczek / Firmware Workbench |
| 31 SY CHORD waves and graphics | Fixed bank of saw, pulse, harmonic, synthetic and chord textures at WAVE 4, 8, …, 124, with matching screen pictures and interpolation between slots. Shared WAVE 0 stays unchanged. | Workbench implementation; MAX bank selection/formulas by Kári's integration work; chord synthesis by Workbench |
| SyntHack splash | Retains the upstream SyntHack v0.8.1 startup graphic. MAX 1.0 is the bundle version, not a changed Elektron OS version. | Angelo-politek / SyntHack |
| Heap modarea and vparams | Reserves 64 KiB of the OS heap for mod code and provides shared kit-parameter dispatch. Infrastructure supporting the musical mods. | Angelo-politek / SyntHack |

The exact 31-wave list is in the release notes. MAX is a fixed build, not the Workbench wave editor. Existing sounds using replaced waves will change timbre. **SY FM4 is not included**: it remains separate development, with unresolved complete page-2 editing and no unified hardware-tested build.

## Credits and source

Original SyntHack mods and heap-based infrastructure: [Angelo-politek and contributors](https://github.com/Angelo-politek/Synthack-OS). Déjà Vu and SY CHORD implementation: [Bezronczek / Firmware Workbench](https://github.com/Bezronczek/syntakt-firmware-workbench). MAX integration, fixed bank recipes and Windows builder: Kári Garðarsson's fork, developed with Codex assistance. Container tooling: [Marcel Bierling / elektron-firmware-tool](https://github.com/mischa85/elektron-firmware-tool).

Pinned source revisions and license requirements: [attribution map](tools/max/release_1_0/ATTRIBUTION.md). Source build: [upstream MAX build notes](tools/max/UPSTREAM_REBUILD.md); Windows packaging: [builder README](tools/max/windows_builder/README.md). Mod details remain under [mods/](mods); reverse-engineering and emulator notes under [docs/](docs). FM4 research is documented separately in [tools/fm4/](tools/fm4/OS141_PORT_STATUS.md).

Repository community code is MIT ([LICENSE](LICENSE)); packaged third-party runtimes have their own terms. These licenses do not grant rights over Elektron firmware. See [LEGAL.md](LEGAL.md). Do not commit stock/generated firmware, extracted OS sections, device projects or samples.
