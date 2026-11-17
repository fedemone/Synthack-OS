"""Catalogo locale di TUTTE le onde per ppg-chord: una pagina HTML autonoma da aprire nel browser.

    python mods/ppg-chord/make_patch.py catalog --ppg-rom local/ppg_data.c

Contiene le onde progettate (waves.SPECTRA), le onde della ROM PPG e le wavetable con tutte le
posizioni interpolate. La mod mette UNA wavetable nel banco di SY CHORD: le posizioni pari
(0, 2 ... 60) diventano WAVE 4, 8 ... 124. Clic su un'onda: la suona come accordo (Web Audio);
"sweep" scorre i 31 frame come girare WAVE; il piede della pagina mostra il comando `build`.

La pagina contiene i dati della ROM letti dalla TUA copia locale: generala in out/ (git-ignored)
e non pubblicarla.
"""

from __future__ import annotations

import base64
import html
import json
from pathlib import Path

import numpy as np

import waves


def _b64_cycles(cycles: list[np.ndarray]) -> str:
    """Cicli di 128 campioni centrati (-128..127) -> int8 base64, concatenati."""
    raw = np.concatenate([np.clip(np.round(c), -128, 127) for c in cycles]).astype(np.int8)
    return base64.b64encode(raw.tobytes()).decode()


def _brightness(cycle: np.ndarray) -> float:
    """Baricentro spettrale in armoniche: ~1 = scuro, 10+ = molto brillante."""
    mag = np.abs(np.fft.rfft(cycle - np.mean(cycle)))[1:waves.HALF]
    return float((np.arange(1, waves.HALF) * mag).sum() / (mag.sum() or 1))


def build(ppg_rom: Path | None, out: Path, cmd: str = "python mods/ppg-chord/make_patch.py") -> dict:
    designed = [(n, d, waves.design(n).cycle) for n, (d, _) in waves.SPECTRA.items()]
    data = {"designed": [{"name": n, "desc": d, "b": round(_brightness(c), 1)} for n, d, c in designed],
            "designedCycles": _b64_cycles([c for _, _, c in designed]),
            "rom": [], "romCycles": "", "tables": [], "curated": [], "rel": str(ppg_rom) if ppg_rom else "", "cmd": cmd}
    if ppg_rom:
        rom = waves.parse_ppg_rom(ppg_rom)
        cycles = [waves.ppg_expand(h) for h in rom]
        seen: dict[bytes, int] = {}
        for i, (h, c) in enumerate(zip(rom, cycles)):
            key = h.astype(np.uint8).tobytes()
            dup = seen.setdefault(key, i)
            data["rom"].append({"b": round(_brightness(c), 1), "empty": int(np.ptp(h) < 4),
                                "dup": dup if dup != i else -1, "basic": waves.basic_shape(c) or "",
                                "body": round(waves.body(c), 2)})
        data["romCycles"] = _b64_cycles(cycles)
        # il banco curato di default (stesso calcolo di make_patch.py build --curated)
        try:
            picked = waves.curate(rom)
        except ValueError:                       # ROM troppo piccola per 31 onde con corpo
            picked = []
        frames = [waves.condition(cycles[i]) for i in picked]
        data["curated"] = [picked[k] for k in waves.order_smooth(frames)] if picked else []
        tables = waves.parse_ppg_wavetables(ppg_rom)
        data["tables"] = [[[p, w] for p, w in keys] for keys in tables]
        data["tableBody"] = [round(float(np.median([waves.body(c) for c in waves.table_cycles(rom, k)])), 2)
                             for k in tables]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(PAGE.replace("/*DATA*/null", json.dumps(data, separators=(",", ":")))
                   .replace("__TITLE__", html.escape("PPG Chord Waves")), encoding="utf-8")
    return {"designed": len(designed), "rom": len(data["rom"]), "tables": len(data["tables"])}


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f6f3;--card:#fff;--ink:#1d1d1b;--mute:#6b6b66;--line:#ddddd6;--wave:#0f7d6b;--acc:#c2410c;--sel:#fff4e6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#131413;--card:#1c1d1c;--ink:#ecece6;--mute:#9a9a92;--line:#2e2f2d;--wave:#5fd4bd;--acc:#fb923c;--sel:#2a2118}}
:root[data-theme="dark"]{--bg:#131413;--card:#1c1d1c;--ink:#ecece6;--mute:#9a9a92;--line:#2e2f2d;--wave:#5fd4bd;--acc:#fb923c;--sel:#2a2118}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.4 system-ui,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px}
h1{font-size:18px;margin:0 0 8px}.row{display:flex;flex-wrap:wrap;gap:8px;align-items:center}
button,select,input{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:5px 9px}
button.on{border-color:var(--acc);color:var(--acc)}main{padding:12px 16px 120px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(132px,1fr));gap:8px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px;cursor:pointer;position:relative}
.card.sel{background:var(--sel);border-color:var(--acc)}.card canvas{width:100%;height:56px;display:block}
.meta{display:flex;justify-content:space-between;font-size:12px;color:var(--mute);margin-top:3px}
.meta b{color:var(--ink)}.star{position:absolute;top:4px;right:6px;color:var(--mute);font-size:15px}.star.on{color:var(--acc)}
.tbl{margin:0 0 18px}.tbl h3{font-size:14px;margin:0 0 4px}.tbl .keys{color:var(--mute);font-size:12px;margin-bottom:6px}
.strip{display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:4px}.strip .card{padding:3px}.strip canvas{height:34px}
.strip .card.key{border-color:var(--wave)}.card.off{opacity:.45}.tbl h3 button{margin-left:8px;font-size:12px;padding:2px 8px}footer{position:fixed;bottom:0;left:0;right:0;background:var(--card);border-top:1px solid var(--line);padding:10px 16px}
code{font:12px ui-monospace,monospace;word-break:break-all}.desc{font-size:12px;color:var(--mute)}.note{color:var(--mute);font-size:12px}
</style></head><body>
<header><h1>PPG Chord Waves</h1>
<div class="row">
 <button data-tab="designed">Designed</button><button data-tab="rom">ROM waves</button><button data-tab="tables">Wavetables</button><button data-tab="curated">Curated bank</button>
 <select id="sort"><option value="i">by number</option><option value="b">by brightness</option></select>
 <label class="note"><input type="checkbox" id="hide" checked> hide empty/duplicates</label>
 <label class="note"><input type="checkbox" id="hidebasic"> hide basic shapes</label>
 <label class="note"><input type="checkbox" id="hidethin"> hide thin waves (body &lt; 0.7)</label>
 <button id="usestars">Starred ROM waves → bank</button>
 <label class="note"><input type="checkbox" id="stars"> starred only</label>
 <select id="chord"><option value="0,3,7,12">minor</option><option value="0,4,7,12">major</option><option value="0,5,7,12">sus4</option><option value="0,3,7,10">min7</option><option value="0,7,12">fifth</option><option value="0">single note</option></select>
 <select id="root"><option value="36">C2</option><option value="48" selected>C3</option><option value="60">C4</option></select>
</div></header>
<main id="main"></main>
<footer><div id="sel" class="note">Click a wave to hear it as a chord, or ▶ sweep to hear a whole table as WAVE 4→124. ★ to shortlist.</div><code id="cmd"></code></footer>
<script>
const D=/*DATA*/null;
const dec=s=>{const b=atob(s),a=new Int8Array(b.length);for(let i=0;i<b.length;i++)a[i]=(b.charCodeAt(i)<<24)>>24;return a};
const DC=dec(D.designedCycles),RC=D.romCycles?dec(D.romCycles):new Int8Array(0);
const cyc=(src,i)=>Array.from(src.subarray(i*128,i*128+128));
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
let stars=new Set();try{stars=new Set(JSON.parse(localStorage.getItem("ppgStars")||"[]"))}catch(e){}
const saveStars=()=>{try{localStorage.setItem("ppgStars",JSON.stringify([...stars]))}catch(e){}};
function draw(cv,c){const r=devicePixelRatio||1,w=cv.clientWidth*r,h=cv.clientHeight*r;cv.width=w;cv.height=h;
 const g=cv.getContext("2d");g.strokeStyle=css("--line");g.beginPath();g.moveTo(0,h/2);g.lineTo(w,h/2);g.stroke();
 g.strokeStyle=css("--wave");g.lineWidth=1.3*r;g.beginPath();c.forEach((v,i)=>{const x=i/127*w,y=h/2-v/128*h*.45;i?g.lineTo(x,y):g.moveTo(x,y)});g.stroke()}
function slotCycle(keys,s){let L=keys[0],R=keys[keys.length-1];for(const k of keys){if(k[0]<=s)L=k;}for(const k of [...keys].reverse()){if(k[0]>=s)R=k;}
 const a=cyc(RC,L[1]);if(R[0]===L[0])return a;const t=(s-L[0])/(R[0]-L[0]),b=cyc(RC,R[1]);return a.map((v,i)=>(1-t)*v+t*b[i])}
let ac,voices=[],timers=[];
const H=40;  // same band limit as the build default
function pwave(c){const N=128,re=new Float32Array(H+1),im=new Float32Array(H+1),m=c.reduce((a,b)=>a+b,0)/N;
 for(let k=1;k<=H;k++){let sr=0,si=0;for(let n=0;n<N;n++){const p=2*Math.PI*k*n/N;sr+=(c[n]-m)*Math.cos(p);si-=(c[n]-m)*Math.sin(p)}re[k]=2*sr/N;im[k]=-2*si/N}
 return ac.createPeriodicWave(re,im)}
function stop(){voices.forEach(v=>{try{v.stop()}catch(e){}});voices=[];timers.forEach(clearTimeout);timers=[]}
function play(c,dur=1.5){ac=ac||new AudioContext();stop();
 const pw=pwave(c),notes=document.getElementById("chord").value.split(",").map(Number),root=+document.getElementById("root").value;
 const g=ac.createGain(),t=ac.currentTime,lv=.5/notes.length;g.gain.setValueAtTime(0,t);g.gain.linearRampToValueAtTime(lv,t+.01);g.gain.setValueAtTime(lv,t+dur-.4);g.gain.linearRampToValueAtTime(0,t+dur);g.connect(ac.destination);
 notes.forEach((n,i)=>{const o=ac.createOscillator();o.setPeriodicWave(pw);o.frequency.value=440*Math.pow(2,(root+n-69)/12)*Math.pow(2,(i-(notes.length-1)/2)*4/1200);o.connect(g);o.start(t);o.stop(t+dur+.1);voices.push(o)});return voices}
function sweep(keys){const cs=[];for(let s=0;s<61;s+=2)cs.push(slotCycle(keys,s));const os=play(cs[0],6.2),pws=cs.map(pwave);
 pws.forEach((pw,i)=>timers.push(setTimeout(()=>os.forEach(o=>{try{o.setPeriodicWave(pw)}catch(e){}}),i*6000/31)))}
function select(card,label,args,c){document.querySelectorAll(".card.sel").forEach(e=>e.classList.remove("sel"));card.classList.add("sel");
 document.getElementById("sel").textContent=label;document.getElementById("cmd").textContent=args?D.cmd+" build "+args:"";play(c)}
function card(id,label,sub,c,args,extra=""){const d=document.createElement("div");d.className="card "+extra;
 d.innerHTML=`<span class="star ${stars.has(id)?"on":""}">★</span><canvas></canvas><div class="meta"><b>${label}</b><span>${sub}</span></div>`;
 d.onclick=e=>{if(e.target.classList.contains("star")){stars.has(id)?stars.delete(id):stars.add(id);e.target.classList.toggle("on");saveStars();return}select(d,label+" "+sub,args,c)};
 requestAnimationFrame(()=>draw(d.querySelector("canvas"),c));return d}
const rom=D.rel?`--ppg-rom ${D.rel} `:"";let tab="designed";
function render(){document.querySelectorAll("[data-tab]").forEach(b=>b.classList.toggle("on",b.dataset.tab===tab));
 const M=document.getElementById("main"),srt=document.getElementById("sort").value,hide=document.getElementById("hide").checked,only=document.getElementById("stars").checked;M.innerHTML="";
 if(tab!=="designed"&&!D.rom.length){M.innerHTML='<p class="note">No ROM loaded. Run <code>make_patch.py catalog --ppg-rom local/ppg_data.c</code> with your local copy of wave-stuff\'s data/ppg_data.c.</p>';return}
 if(tab==="designed"){const G=document.createElement("div");G.className="grid";let L=D.designed.map((w,i)=>({...w,i}));if(srt==="b")L.sort((a,b)=>a.b-b.b);
  M.insertAdjacentHTML("beforeend",'<p class="note">Our 7 waves. As a wavetable they are spread over WAVE 4…124 in this order (or the order you give to <code>--designed</code>).</p>');
  L.filter(w=>!only||stars.has("d:"+w.name)).forEach(w=>{const c=card("d:"+w.name,w.name,"bright "+w.b,cyc(DC,w.i),"--designed");c.title=w.desc;G.append(c)});M.append(G);return}
 if(tab==="rom"){const G=document.createElement("div");G.className="grid";let L=D.rom.map((w,i)=>({...w,i}));if(hide)L=L.filter(w=>!w.empty&&w.dup<0);if(srt==="b")L.sort((a,b)=>a.b-b.b);
  if(document.getElementById("hidebasic").checked)L=L.filter(w=>!w.basic);
  if(document.getElementById("hidethin").checked)L=L.filter(w=>w.body>=0.7);
  L.filter(w=>!only||stars.has("w:"+w.i)).forEach(w=>G.append(card("w:"+w.i,"#"+w.i,w.empty?"empty":w.dup>=0?"= #"+w.dup:w.basic?w.basic:"body "+w.body,cyc(RC,w.i),"",w.basic?"off":"")));
  M.insertAdjacentHTML("beforeend",`<p class="note">${L.length} of ${D.rom.length} waves shown. Dimmed = close to a basic shape (sine, saw, square, triangle, pulse). “body” = share of energy in harmonics 1–3: below ~0.5 a wave sounds thin and short once the filter closes (stock bank ≈ 0.96, MAX ≈ 0.76). Star up to 31 and press “Starred ROM waves → bank”.</p>`);M.append(G);return}
 if(tab==="curated"&&!D.curated.length){M.innerHTML='<p class="note">Not enough waves with body in this ROM for a curated bank of 31.</p>';return}
 if(tab==="curated"){const keys=D.curated.map((w,i)=>[2*i,w]);
  M.insertAdjacentHTML("beforeend",`<p class="note">31 ROM waves chosen automatically: no empty, duplicate or basic-shape waves, body ≥ 0.7; the most different from each other; ordered so each wave resembles the next (smooth morphing as WAVE turns). <button id="cs">▶ sweep</button></p>`);
  const args=rom+"--curated";document.getElementById("cs").onclick=()=>{sweep(keys);document.getElementById("sel").textContent="Curated bank: WAVE 4 → 124";document.getElementById("cmd").textContent=D.cmd+" build "+args};
  const G=document.createElement("div");G.className="grid";
  D.curated.forEach((w,i)=>G.append(card("w:"+w,"W"+(4+4*i),"#"+w+" · bright "+D.rom[w].b,cyc(RC,w),args)));M.append(G);return}
 D.tables.forEach((keys,t)=>{const S=document.createElement("div");S.className="tbl";
  const args=rom+`--ppg-table ${t}`;
  const tb=(D.tableBody||[])[t];
  S.innerHTML=`<h3>Wavetable ${t}${tb!==undefined?` <span class="note">body ${tb}${tb<0.5?" (thin)":""}</span>`:""}<button>▶ sweep</button></h3><div class="keys">key waves (slot→wave): ${keys.map(k=>k[0]+"→#"+k[1]).join("  ")} · dim slots are skipped (only even slots become frames)</div>`;
  S.querySelector("button").onclick=()=>{sweep(keys);document.getElementById("sel").textContent="Wavetable "+t+": WAVE 4 → 124";document.getElementById("cmd").textContent=D.cmd+" build "+args};
  const G=document.createElement("div");G.className="strip";
  for(let s=0;s<61;s++){const id="t:"+t+":"+s;if(only&&!stars.has(id))continue;const isKey=keys.some(k=>k[0]===s),used=s%2===0;
   G.append(card(id,used?"W"+(4+2*s):t+"/"+s,isKey?"key":"",slotCycle(keys,s),args,(isKey?"key ":"")+(used?"":"off")))}
  if(G.children.length){S.append(G);M.append(S)}})}
document.querySelectorAll("[data-tab]").forEach(b=>b.onclick=()=>{tab=b.dataset.tab;render()});
["sort","hide","stars","hidebasic","hidethin"].forEach(i=>document.getElementById(i).onchange=render);
document.getElementById("usestars").onclick=()=>{const w=[...stars].filter(s=>s.startsWith("w:")).map(s=>+s.slice(2)).sort((a,b)=>a-b);
 const sel=document.getElementById("sel"),cmd=document.getElementById("cmd");
 if(!w.length){sel.textContent="Star some ROM waves first (up to 31).";cmd.textContent="";return}
 if(w.length>31){sel.textContent=w.length+" starred: the bank holds 31. Unstar "+(w.length-31)+".";cmd.textContent="";return}
 sel.textContent=w.length+" starred ROM waves"+(w.length<31?" + "+(31-w.length)+" from MAX (non-basic first)":"")+", ordered for smooth morphing";
 cmd.textContent=D.cmd+" build "+rom+"--ppg-waves "+w.join(",")+(w.length<31?" --fill-max":"")};
render();
</script></body></html>
"""
