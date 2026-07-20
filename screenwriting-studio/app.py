"""
Screenwriting Studio — Professional AI Screenplay Tool
Workflow: Idea → Writer (full screenplay) → Director (shot list & storyboarding) → Export (polished) → Continue
"""
import json, os, re, time, uuid, hashlib
from pathlib import Path
from dotenv import load_dotenv

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────
OR_KEY = os.getenv("OPENROUTER_KEY", "")
OR_MODEL = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct")
OR_API = os.getenv("OPENROUTER_API", "https://openrouter.ai/api/v1/chat/completions")
PORT = int(os.getenv("PORT", "8899"))
DATA_DIR = Path("sessions")
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Screenwriting Studio", version="2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── AI Engine ──────────────────────────────────────────────────────
def ai(prompt, system, max_tokens=8192, temp=0.85):
    r = requests.post(OR_API, json={
        "model": OR_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "max_tokens": max_tokens,
        "temperature": temp,
    }, headers={
        "Authorization": f"Bearer {OR_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost",
        "X-Title": "Screenwriting Studio"
    }, timeout=300)
    if r.status_code != 200:
        raise HTTPException(502, f"AI Error [{r.status_code}]: {r.text[:300]}")
    return r.json()["choices"][0]["message"]["content"]

def extract_json(text):
    """Extract JSON from text, handling markdown code blocks and nested braces."""
    # Strip markdown code blocks
    cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip())
    cleaned = re.sub(r'\s*```$', '', cleaned)
    # Find the first { and match balanced braces
    start = cleaned.find('{')
    if start == -1: return json.loads(cleaned)
    depth = 0
    for i in range(start, len(cleaned)):
        if cleaned[i] == '{': depth += 1
        elif cleaned[i] == '}':
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start:i+1])
    # Fallback
    m = re.search(r'\{[\s\S]*\}', cleaned)
    if m: return json.loads(m.group())
    raise json.JSONDecodeError("No valid JSON found", "", 0)

def ai_json(prompt, system, max_tokens=8192):
    """Ask AI and parse JSON response."""
    text = ai(prompt, system + "\n\nReturn ONLY valid JSON. No markdown, no backticks.", max_tokens)
    try:
        return extract_json(text)
    except (json.JSONDecodeError, TypeError):
        raise ValueError(f"AI returned invalid JSON: {text[:300]}")

# ── Session Helpers ─────────────────────────────────────────────────
def load_session(sid):
    p = DATA_DIR / f"{sid}.json"
    return json.loads(p.read_text()) if p.exists() else None

def save_session(sid, data):
    (DATA_DIR / f"{sid}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2))

def create_session(title, genre, idea):
    sid = uuid.uuid4().hex[:12]
    save_session(sid, {"id": sid, "title": title, "genre": genre, "idea": idea,
                        "characters": [], "scenes": [], "full_script": "",
                        "director": {}, "quality": {}, "status": "idea", "notes": []})
    return sid

# ── Models ──────────────────────────────────────────────────────────
class NewProject(BaseModel):
    idea: str
    title: str = ""
    genre: str = "Drama"

class SessionReq(BaseModel):
    session_id: str

class RewriteReq(BaseModel):
    session_id: str
    instruction: str

class ExportReq(BaseModel):
    session_id: str

# ════════════════════════════════════════════════════════════════════
# API ROUTES
# ════════════════════════════════════════════════════════════════════

@app.post("/api/new")
def new_project(req: NewProject):
    title = req.title or f"Untitled-{uuid.uuid4().hex[:4]}"
    sid = create_session(title, req.genre, req.idea)
    return {"session_id": sid, "title": title, "status": "idea"}

@app.get("/api/sessions")
def sessions():
    return sorted([
        {"id": json.loads(p.read_text())} for p in DATA_DIR.glob("*.json")
    ], key=lambda x: x["id"], reverse=True)

@app.get("/api/session/{sid}")
def session(sid: str):
    s = load_session(sid)
    if not s: raise HTTPException(404, "Not found")
    return s

@app.delete("/api/session/{sid}")
def delete(sid: str):
    p = DATA_DIR / f"{sid}.json"
    if p.exists(): p.unlink()
    return {"ok": True}

# ── PHASE 1: WRITER ────────────────────────────────────────────────
@app.post("/api/write")
def write_script(req: SessionReq):
    s = load_session(req.session_id)
    if not s: raise HTTPException(404, "Session not found")

    script_sys = """You are an Academy Award-winning screenwriter. Write complete, industry-standard screenplays.

FORMAT RULES (STRICT):
- Scene Headings: INT./EXT. LOCATION - TIME (always uppercase)
- Action Lines: Present tense, visual, active. Max 4 lines. Show, don't tell.
- Character Names: CENTERED, ALL CAPS, on their own line
- Parentheticals: (barely audible), (laughing), etc. — use minimally
- Dialogue: Under character name, natural and character-specific
- Transitions: CUT TO: (sparingly), FADE OUT. at end

WRITING QUALITY:
- Each character has a DISTINCT voice (vocabulary, rhythm, attitude)
- Dialogue has subtext — characters don't say exactly what they mean
- Scenes have conflict, turning points, and emotional beats
- Scenes connect naturally — each scene's end creates the next scene's beginning
- Include rich visual detail: lighting, atmosphere, movement, sound
- No exposition dumps. Reveal through action and behavior.
- Pacing: varied scene lengths, build tension, payoff payoffs

OUTPUT: Write the COMPLETE screenplay. Start with scene 1 and end with FADE OUT.
Do NOT output JSON — just write the screenplay in proper format."""

    prompt = f"""Write a complete screenplay:

TITLE: {s['title']}
GENRE: {s['genre']}
PREMISE: {s['idea']}

Write a full short film screenplay (8-15 pages worth). Make it gripping, visual, and emotionally resonant. Every line should pull the reader forward."""

    try:
        script = ai(prompt, script_sys, max_tokens=8192)
    except Exception as e:
        raise HTTPException(500, str(e))

    # Extract characters from script
    chars = list(set(re.findall(r'\n\s{2,}([A-Z][A-Z\s\-]+?)\n', script)))
    # Also grab scene headings
    scenes = re.findall(r'(INT\.|EXT\.|INT/EXT\.)\s+[^\n]+', script)

    s["full_script"] = script
    s["characters"] = [{"name": c.strip(), "description": ""} for c in chars[:10]]
    s["scene_headings"] = scenes[:20]
    s["status"] = "written"
    s["notes"] = s.get("notes", [])
    s["notes"].append({"time": time.time(), "action": "script written", "text": f"{len(scenes)} scenes found"})
    save_session(req.session_id, s)

    return {"session_id": req.session_id, "script": script, "characters": s["characters"],
            "scene_count": len(scenes), "status": "written"}

# ── PHASE 2: DIRECTOR ──────────────────────────────────────────────
@app.post("/api/direct")
def direct_scene(req: SessionReq):
    s = load_session(req.session_id)
    if not s: raise HTTPException(404, "Not found")
    if not s.get("full_script"): raise HTTPException(400, "Write script first")

    director_sys = """You are an Oscar-winning film director and cinematographer. Given a screenplay, create a comprehensive director's blueprint.

Return ONLY valid JSON:
{
  "director_vision": "Overall artistic vision, tone, visual style reference",
  "pacing_breakdown": "Beat-by-beat pacing guide with timestamps",
  "character_arcs": [{"name":"...","start":"...","end":"...","key_moment":"..."}],
  "scene_directing": [
    {
      "scene_num": 1,
      "heading": "INT. LOCATION - TIME",
      "tone": "tense/joyful/melancholic/etc",
      "camera_style": "static/tracking/handheld/panning",
      "shots": [
        {"type": "wide/medium/close-up/insert/aerial/over-shoulder", "description": "...", "lighting": "...", "emotion": "..."}
      ],
      "acting_notes": "Direction for performers in this scene",
      "sound_design": "What we hear — ambient, music cues, silence"
    }
  ],
  "transitions": [{"from": 1, "to": 2, "technique": "match cut / cross dissolve / smash cut / straight cut / iris out", "why": "reason"}],
  "key_visual_moments": ["3-5 visually stunning or emotionally powerful moments"],
  "music_and_soundscape": "Overall music approach and sound design notes",
  "color_palette": "Color grading approach — warm/cool/monochrome/etc with specific references"
}"""

    # Truncate script for context but keep all scenes
    script = s["full_script"][:6000]  # First 6K chars for AI context

    prompt = f"""Create a complete director's blueprint for this screenplay.

TITLE: {s['title']}
GENRE: {s['genre']}

SCRIPT (first part — use your best judgment for the rest):
{script}

Create thorough, professional direction for EVERY scene. Be specific about camera work, lighting, acting notes, and sound design."""

    try:
        blueprint = ai_json(prompt, director_sys, max_tokens=8192)
    except Exception as e:
        raise HTTPException(500, str(e))

    s["director"] = blueprint
    s["status"] = "directed"
    s["notes"].append({"time": time.time(), "action": "blueprint created", "text": f"{len(blueprint.get('scene_directing',[]))} scenes planned"})
    save_session(req.session_id, s)

    return {"session_id": req.session_id, "blueprint": blueprint, "status": "directed"}

# ── PHASE 3: EXPORT ────────────────────────────────────────────────
@app.post("/api/export")
def export_script(req: SessionReq):
    s = load_session(req.session_id)
    if not s: raise HTTPException(404, "Not found")
    if not s.get("full_script"): raise HTTPException(400, "Write script first")

    editor_sys = """You are a senior Hollywood script editor. Polish this screenplay to studio-ready quality.

DO:
- Fix formatting issues (scene headings, action lines, dialogue alignment)
- Sharpen dialogue — make it punchier, more natural
- Tighten action lines — remove redundancy
- Fix continuity errors (character states, timeline, prop placement)
- Enhance visual moments — add more cinematic detail
- Ensure proper screenplay format throughout
- Strengthen emotional beats and turning points

Don't change the plot or add new scenes. Only polish what exists."""

    script = s["full_script"]
    director_notes = json.dumps(s.get("director", {}), ensure_ascii=False)

    title = s['title']
    genre = s['genre']
    dn = json.dumps(s.get("director", {}), ensure_ascii=False)

    prompt = f"""Polish and format this screenplay to professional studio-ready quality:

TITLE: {title}
GENRE: {genre}

SCRIPT TO POLISH:
{script}

Director's vision: {dn}

Output TWO things:
1. The complete polished screenplay in proper format
2. A JSON summary at the very end in this format: {{"quality_check": {{"score": 8.5, "strengths": [...], "weaknesses": [...], "notes": "..."}}}}

Write the screenplay first, then add a blank line, then the JSON summary."""

    try:
        text = ai(prompt, editor_sys, max_tokens=8192)
    except Exception as e:
        raise HTTPException(500, str(e))

    # Extract JSON summary
    m = re.search(r'\{"quality_check"[^}]*\}', text)
    quality = json.loads(m.group()) if m else {"quality_check": {"score": 0, "strengths": [], "weaknesses": [], "notes": "N/A"}}

    # Get script (everything before the JSON)
    script_clean = text.split("\n\n{")[0].strip()
    if not script_clean: script_clean = text

    s["final_script"] = script_clean
    s["quality"] = quality
    s["status"] = "exported"
    s["notes"].append({"time": time.time(), "action": "exported", "text": f"Score: {quality['quality_check'].get('score', '?')}"})
    save_session(req.session_id, s)

    return {"session_id": req.session_id, "script": script_clean, "quality": quality, "status": "exported"}

# ── PHASE 4: CONTINUUM (Rewrite/Continue) ──────────────────────────
@app.post("/api/continue")
def continue_work(req: RewriteReq):
    s = load_session(req.session_id)
    if not s: raise HTTPException(404, "Not found")

    script = s.get("final_script", s.get("full_script", ""))
    if not script: raise HTTPException(400, "No script to work on")

    prompt = f"""REVISE THIS SCREENPLAY based on the instruction below.

INSTRUCTION: {req.instruction}

CURRENT SCRIPT:
{script[:7000]}

Apply the changes requested. Keep everything else the same. Return the FULL revised screenplay."""

    try:
        new_script = ai(prompt, "You are a professional screenwriter revising a script based on specific feedback. Apply changes precisely.", max_tokens=8192)
    except Exception as e:
        raise HTTPException(500, str(e))

    s["full_script"] = new_script
    s["notes"].append({"time": time.time(), "action": "rewritten", "text": req.instruction})
    save_session(req.session_id, s)

    return {"session_id": req.session_id, "script": new_script, "status": "rewritten"}

# ── PHASE 5: SCENE GENERATOR (AI-generated scenes from description) ─
@app.post("/api/new-scene")
def add_scene(req: SessionReq):
    """Generate a new scene based on user description, inserting into existing script."""
    s = load_session(req.session_id)
    if not s: raise HTTPException(404, "Not found")
    if not s.get("full_script"): raise HTTPException(400, "Write script first")

    scene_sys = """You are a screenwriter writing individual scenes. Write in proper screenplay format.
Output ONLY the scene text — no intro, no explanation."""

    scene_description = s.get("new_scene_desc", "Write a dramatic scene")

    prompt = f"""Write a scene for this screenplay:

TITLE: {s['title']} | GENRE: {s['genre']}
LOCATION/VIBE: {scene_description}
CHARACTERS: {', '.join(c['name'] for c in s.get('characters', []))}

The scene should flow naturally and feel like it belongs in a real screenplay. Write it in proper format."""

    try:
        scene = ai(prompt, scene_sys, max_tokens=2048)
    except Exception as e:
        raise HTTPException(500, str(e))

    s["new_scene_desc"] = scene_description
    s["notes"].append({"time": time.time(), "action": "scene generated", "text": scene_description[:50]})
    save_session(req.session_id, s)

    return {"session_id": req.session_id, "scene": scene, "status": "scene_generated"}

# ════════════════════════════════════════════════════════════════════
# FRONTEND
# ════════════════════════════════════════════════════════════════════
@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_RESPONSE


HTML_RESPONSE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Screenwriting Studio</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#06060b;--sf:#111118;--sf2:#1a1a26;--brd:#282840;--tx:#e8e8f0;--tx2:#7777a0;--ac:#6c5ce7;--ac2:#a29bfe;--gold:#f0c040;--dn:#e74c3c;--gr:#2ecc71;--ff:'Georgia',serif;--fu:-apple-system,BlinkMacSystemFont,sans-serif}
body{background:var(--bg);color:var(--tx);font-family:var(--fu);min-height:100vh}
header{background:linear-gradient(135deg,#06060f,#12122a);padding:18px 28px;border-bottom:1px solid var(--brd);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px}
.hdr{display:flex;align-items:center;gap:16px}
header h1{font-family:var(--ff);font-size:22px;letter-spacing:2px}
header h1 span{color:var(--gold)}
.steps{display:flex;gap:6px;align-items:center}
.st{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--tx2);cursor:pointer;padding:4px 10px;border-radius:6px;transition:.2s}
.st:hover{background:var(--sf2)}
.st.act{color:var(--ac2);background:rgba(108,92,231,.15)}
.st.done{color:var(--gr)}
.st .dot{width:26px;height:26px;border-radius:50%;border:2px solid var(--brd);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;transition:.2s}
.st.act .dot{border-color:var(--ac);background:var(--ac);color:#fff}
.st.done .dot{border-color:var(--gr);background:var(--gr);color:#fff}
.sa{color:var(--brd);font-size:14px}
main{max-width:1100px;margin:0 auto;padding:24px 20px 60px}
.pnl{display:none}.pnl.act{display:block}
.card{background:var(--sf);border:1px solid var(--brd);border-radius:14px;padding:24px;margin-bottom:16px}
.card h2{font-family:var(--ff);font-size:18px;margin-bottom:14px}
.card h3{font-size:14px;margin:14px 0 8px;color:var(--ac2)}
label{display:block;font-size:12px;color:var(--tx2);margin-bottom:5px;font-weight:600;text-transform:uppercase;letter-spacing:.5px}
input,textarea,select{width:100%;padding:11px 14px;background:var(--sf2);border:1px solid var(--brd);border-radius:8px;color:var(--tx);font-size:14px;font-family:var(--fu);transition:.2s}
input:focus,textarea:focus,select:focus{outline:none;border-color:var(--ac);box-shadow:0 0 0 3px rgba(108,92,231,.15)}
textarea{min-height:100px;resize:vertical;line-height:1.6}
.btn{padding:11px 24px;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:.2s;font-family:var(--fu)}
.btn-p{background:var(--ac);color:#fff}.btn-p:hover{background:var(--ac2)}
.btn-p:disabled{opacity:.35;cursor:not-allowed}
.btn-g{background:var(--gold);color:#111}.btn-g:hover{background:#f5d060}
.btn-d{background:var(--dn);color:#fff}
.btn-sm{padding:7px 14px;font-size:12px}
.btn-s{padding:7px 14px;font-size:12px;background:var(--sf2);color:var(--tx);border:1px solid var(--brd)}.btn-s:hover{border-color:var(--ac)}
.act{display:flex;gap:10px;flex-wrap:wrap;margin-top:16px}
.lod{display:none;text-align:center;padding:30px}.lod.act{display:block}
.lod .sp{width:40px;height:40px;border:3px solid var(--brd);border-top-color:var(--ac);border-radius:50%;animation:spin 1s linear infinite;margin:0 auto 12px}
@keyframes spin{to{transform:rotate(360deg)}}
.lod p{color:var(--tx2);font-size:13px}
.res{background:var(--sf);border:1px solid var(--brd);border-radius:12px;padding:20px;margin-top:16px;max-height:500px;overflow-y:auto}
.res pre{white-space:pre-wrap;font-family:var(--ff);font-size:14px;line-height:1.7;word-break:break-word}
.res .q{display:flex;gap:16px;margin-top:14px;padding-top:14px;border-top:1px solid var(--brd);flex-wrap:wrap}
.res .qi{background:var(--sf2);padding:10px 16px;border-radius:8px}
.res .qi .v{font-size:22px;font-weight:700;color:var(--gold)}
.res .qi .l{font-size:11px;color:var(--tx2);margin-top:3px}
.sbox{background:var(--sf2);padding:14px;border-radius:8px;margin:10px 0;border-left:3px solid var(--ac)}
.sbox .sh{font-weight:700;color:var(--gold);margin-bottom:6px;font-size:13px}
.sbox .sd{line-height:1.6;font-family:var(--ff);font-size:14px}
.shot{background:var(--sf2);padding:10px;border-radius:6px;margin:6px 0;font-size:13px}
.shot .st{color:var(--ac2);font-weight:600;font-size:11px;text-transform:uppercase}
.char{display:flex;gap:14px;padding:10px;background:var(--sf2);border-radius:8px;margin:6px 0}
.char .cn{font-weight:700;color:var(--gold);min-width:100px}
.char .cd{font-size:13px;color:var(--tx2)}
.arc{background:var(--sf2);padding:12px;border-radius:8px;margin:8px 0}
.arc .an{font-weight:700;color:var(--gold)}
.arc p{font-size:13px;margin:4px 0;color:var(--tx2)}
.arc p strong{color:var(--tx)}
.tag{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px;font-weight:700;margin-right:4px}
.t-idea{background:#2a1a3a;color:#a29bfe}.t-scripted{background:#1a2a3a;color:#74b9ff}.t-directed{background:#1a3a2a;color:#55efc4}.t-exported{background:#3a3a1a;color:#ffeaa7}
.slist{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px}
.si{background:var(--sf);border:1px solid var(--brd);border-radius:8px;padding:14px;cursor:pointer;transition:.2s}
.si:hover{border-color:var(--ac)}
.si .it{font-weight:600;margin-bottom:3px;font-size:14px}
.si .im{font-size:11px;color:var(--tx2)}
.inst{display:none}
@media(max-width:700px){main{padding:12px}header{padding:12px}header h1{font-size:16px}.steps{gap:2px}.st{font-size:10px;padding:3px 6px}}
</style>
</head>
<body>
<header>
<div class="hdr">
<h1>🎬 SCREENWRITING <span>STUDIO</span></h1>
</div>
<div class="steps">
<div class="st act" onclick="go(1)" id="s1"><div class="dot">1</div>Project</div>
<div class="sa">›</div>
<div class="st" onclick="go(2)" id="s2"><div class="dot">2</div>Writer</div>
<div class="sa">›</div>
<div class="st" id="s3"><div class="dot">3</div>Director</div>
<div class="sa">›</div>
<div class="st" id="s4"><div class="dot">4</div>Export</div>
<div class="sa">›</div>
<div class="st" id="s5"><div class="dot">∞</div>Continue</div>
</div>
<button class="btn btn-sm btn-s" onclick="showSessions()">📁 Sessions</button>
</header>

<main>
<div class="pnl act" id="p1">
<div class="card">
<h2>🎬 New Project</h2>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:14px">
<div><label>Title</label><input id="t-title" placeholder="Your movie title..."></div>
<div><label>Genre</label>
<select id="t-genre">
<option>Thriller</option><option>Drama</option><option>Action</option><option>Comedy</option>
<option>Horror</option><option>Sci-Fi</option><option>Romance</option><option>Crime</option><option>Fantasy</option><option>Noir</option>
</select></div>
</div>
<label style="margin-top:14px">Your Idea / Premise — be as specific as possible</label>
<textarea id="t-idea" placeholder="A retired detective, trapped in a locked room by a mysterious force, discovers his wife's murder is connected to a cold case he never solved. The only way out is to solve it from inside the room."></textarea>
<div class="act"><button class="btn btn-p" onclick="doNew()">Create Project →</button></div>
</div>
</div>

<div class="pnl" id="p2">
<div class="card">
<h2>✍️ Screenwriter</h2>
<p style="color:var(--tx2);margin-bottom:12px;font-size:13px" id="s-info">Write your screenplay...</p>
<div class="lod" id="s-lod"><div class="sp"></div><p>🎬 AI Screenwriter is crafting your screenplay...<br><small>This may take 60-120 seconds.</small></p></div>
<div class="res" id="s-res"></div>
<div class="act" id="s-act" style="display:none">
<button class="btn btn-p" onclick="go(3)">Director's Blueprint →</button>
<button class="btn btn-sm btn-s" onclick="toggleRewrite()">✏️ Revise Script</button>
</div>
</div>
<div class="card inst" id="r-box">
<h2>✏️ Revision Instruction</h2>
<label>What should change?</label>
<textarea id="r-instr" placeholder="Make the dialogue sharper in scene 3. Add more visual tension. Make the ending more ambiguous."></textarea>
<div class="act">
<button class="btn btn-p" onclick="doRewrite()">Apply Revision</button>
<button class="btn btn-sm btn-s" onclick="toggleRewrite()">Cancel</button>
</div>
</div>
</div>

<div class="pnl" id="p3">
<div class="card">
<h2>🎥 Director's Blueprint</h2>
<div class="lod" id="d-lod"><div class="sp"></div><p>🎬 AI Director planning your film...</p></div>
<div id="d-res"></div>
<div class="act" id="d-act" style="display:none">
<button class="btn btn-g" onclick="doExport()">📤 Export Final Script</button>
</div>
</div>
</div>

<div class="pnl" id="p4">
<div class="card">
<h2>📤 Final Export</h2>
<div class="lod" id="e-lod"><div class="sp"></div><p>🎬 Polishing your final screenplay...</p></div>
<div id="e-res"></div>
<div class="act" id="e-act" style="display:none">
<button class="btn btn-p" onclick="copyScript()">📋 Copy Script</button>
<button class="btn btn-g" onclick="downloadScript()">💾 Download .txt</button>
<button class="btn btn-sm btn-s" onclick="go(2)">← Go Back to Revise</button>
</div>
</div>
</div>

<div class="pnl" id="p5">
<div class="card">
<h2>∞ Continue & Iterate</h2>
<p style="color:var(--tx2);margin-bottom:12px;font-size:13px">Revise, add scenes, change anything.</p>
<textarea id="c-instr" placeholder="Add a flashback scene where we see the detective and his wife before the murder. Make the antagonist more sympathetic. Change the ending to be ambiguous..."></textarea>
<div class="act">
<button class="btn btn-p" onclick="doContinue()">Apply Revision</button>
<button class="btn btn-sm btn-s" onclick="go(4)">View Export →</button>
</div>
</div>
</div>

<div class="pnl" id="psess">
<div class="card">
<h2>📁 Sessions</h2>
<div class="slist" id="slist"></div>
</div>
</div>
</main>

<script>
let sid=null,scriptText='';
const A=(ep,d)=>fetch('/api'+ep,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).then(r=>r.json());
const E=id=>document.getElementById(id);

function go(n){
  document.querySelectorAll('.pnl').forEach(p=>p.classList.remove('act'));
  E('p'+n).classList.add('act');
  for(let i=1;i<=5;i++){
    let e=E('s'+i);e.classList.remove('act','done');
    if(i<n)e.classList.add('done');
    if(i===n)e.classList.add('act');
  }
}
function show(){
  document.querySelectorAll('.pnl').forEach(p=>p.classList.remove('act'));
  E('psess').classList.add('act');
  document.querySelectorAll('.st').forEach(s=>s.classList.remove('act','done'));
  loadS();
}

async function loadS(){
  const d=await fetch('/api/sessions').then(r=>r.json());
  const t={idea:'t-idea',written:'t-scripted',directed:'t-directed',exported:'t-exported',rewritten:'t-scripted'};
  E('slist').innerHTML=d.length?d.map(s=>{
    const dt=new Date(s.id*1000||Date.now());
    return`<div class="si" onclick="load('${s.id}')"><div class="it">${s.title}</div><div class="im">${s.genre||''}</div><div style="margin-top:6px"><span class="tag ${t[s.status]||''}">${s.status||'idea'}</span></div></div>`
  }).join(''):'<p style="color:var(--tx2)">No sessions yet.</p>';
}

async function load(id){
  sid=id;
  const s=await fetch('/api/session/'+id).then(r=>r.json());
  E('t-title').value=s.title;E('t-genre').value=s.genre||'Drama';E('t-idea').value=s.idea||'';

  if(s.status==='exported'&&s.final_script){go(4);E('e-res').innerHTML='<pre>'+esc(s.final_script)+'</pre>';E('e-act').style.display='flex';scriptText=s.final_script;}
  else if(s.status==='directed'&&s.director){go(3);renderDir(s.director);E('d-act').style.display='flex';}
  else if(s.status==='rewritten'||s.full_script){go(2);E('s-res').innerHTML='<pre>'+esc(s.full_script)+'</pre>';E('s-act').style.display='flex';scriptText=s.full_script;}
  else go(1);
}

async function doNew(){
  const idea=E('t-idea').value.trim();
  if(!idea){alert('Enter your idea!');return}
  try{
    const r=await A('/api/new',{idea,title:E('t-title').value.trim()||'Untitled',genre:E('t-genre').value});
    sid=r.session_id;go(2);
    E('s-info').textContent=`Writing: ${r.title} (${r.genre||'Drama'})`;
    E('s-lod').classList.add('act');
    const res=await A('/api/write',{session_id:sid});
    E('s-lod').classList.remove('act');
    E('s-res').innerHTML=formatWP(res);
    E('s-act').style.display='flex';
    scriptText=res.script||'';
    renderChars(res.characters);
  }catch(e){alert('Error: '+e.message);E('s-lod').classList.remove('act')}
}

async function doDirect(){
  E('d-lod').classList.add('act');
  try{
    const r=await A('/api/direct',{session_id:sid});
    E('d-lod').classList.remove('act');
    renderDir(r.blueprint);E('d-act').style.display='flex';
  }catch(e){alert('Error: '+e.message);E('d-lod').classList.remove('act')}
}

async function doExport(){
  E('e-lod').classList.add('act');
  try{
    const r=await A('/api/export',{session_id:sid});
    E('e-lod').classList.remove('act');
    let qHtml=r.quality?`<div class="q"><div class="qi"><div class="v">${r.quality.quality_check?.score||'?'}</div><div class="l">Quality Score</div></div></div>`:'';
    E('e-res').innerHTML='<pre>'+esc(r.script)+'</pre>'+qHtml;
    E('e-act').style.display='flex';scriptText=r.script;
  }catch(e){alert('Error: '+e.message);E('e-lod').classList.remove('act')}
}

async function doRewrite(){
  const instr=E('r-instr').value.trim();if(!instr){alert('Enter instruction!');return}
  try{const r=await A('/api/continue',{session_id:sid,instruction:instr});E('s-res').innerHTML='<pre>'+esc(r.script)+'</pre>';E('r-box').style.display='none';scriptText=r.script;}
  catch(e){alert('Error: '+e.message)}
}

async function doContinue(){
  const instr=E('c-instr').value.trim();if(!instr){alert('Enter instruction!');return}
  try{const r=await A('/api/continue',{session_id:sid,instruction:instr});E('e-res').innerHTML='<pre>'+esc(r.script)+'</pre>';E('e-act').style.display='flex';scriptText=r.script;}
  catch(e){alert('Error: '+e.message)}
}

function toggleRewrite(){E('r-box').style.display=E('r-box').style.display==='none'?'block':'none'}

function formatWP(res){
  let h='<h3>👥 Characters</h3>';
  (res.characters||[]).forEach(c=>{h+=`<div class="char"><div class="cn">${c.name}</div><div class="cd">${c.description||''}</div></div>`});
  h+='<h3>📝 Screenplay</h3><pre>'+esc(res.script)+'</pre>';
  return h;
}

function renderDir(bp){
  let h='';
  if(bp.director_vision)h+=`<div class="sbox"><div class="sh">🎬 Director's Vision</div>${esc(bp.director_vision)}</div>`;
  if(bp.pacing_breakdown)h+=`<div class="sbox"><div class="sh">⏱️ Pacing</div>${esc(bp.pacing_breakdown)}</div>`;
  if(bp.color_palette)h+=`<div class="sbox"><div class="sh">🎨 Color Palette</div>${esc(bp.color_palette)}</div>`;
  if(bp.music_and_soundscape)h+=`<div class="sbox"><div class="sh">🎵 Music & Sound</div>${esc(bp.music_and_soundscape)}</div>`;
  if(bp.key_visual_moments?.length)h+='<h3>💡 Key Visual Moments</h3>'+(bp.key_visual_moments.map(v=>`<div class="sbox">${esc(v)}</div>`).join(''));
  if(bp.character_arcs?.length){h+='<h3>👤 Character Arcs</h3>';bp.character_arcs.forEach(a=>{h+=`<div class="arc"><div class="an">${a.name}</div><p><strong>Start:</strong> ${a.start}</p><p><strong>Key Moment:</strong> ${a.key_moment}</p><p><strong>End:</strong> ${a.end}</p></div>`})}
  if(bp.scene_directing?.length){h+='<h3>📷 Scene-by-Scene Direction</h3>';bp.scene_directing.forEach(sc=>{
    h+=`<div class="sbox"><div class="sh">Scene ${sc.scene_num}: ${sc.heading}</div>`;
    h+=`<p style="font-size:12px;color:var(--tx2)">Tone: ${sc.tone||''} | Camera: ${sc.camera_style||''}</p>`;
    (sc.shots||[]).forEach(sh=>{h+=`<div class="shot"><div class="st">${sh.type} — ${sh.lighting||''}</div>${esc(sh.description)}<br><small style="color:var(--tx2)">Emotion: ${sh.emotion||''}</small></div>`})
    h+=`<div style="margin-top:8px;font-size:13px"><strong>Acting:</strong> ${esc(sc.acting_notes||'')}</div>`;
    h+=`<div style="font-size:13px;color:var(--tx2)"><strong>Sound:</strong> ${esc(sc.sound_design||'')}</div></div>`
  })}
  if(bp.transitions?.length){h+='<h3>🔄 Transitions</h3>';bp.transitions.forEach(t=>{h+=`<div class="sbox"><div class="sh">Scene ${t.from} → ${t.to}: ${esc(t.technique)}</div><div style="font-size:12px;color:var(--tx2)">${esc(t.why)}</div></div>`})}
  E('d-res').innerHTML=h;
}

function copy(){navigator.clipboard.writeText(scriptText);alert('Copied!')}
function dl(){const b=new Blob([scriptText],{type:'text/plain'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=(E('t-title').value||'script')+'.txt';a.click()}
function esc(t){return t.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')}
function renderChars(chars){
  let h='';
  (chars||[]).forEach(c=>{h+=`<div class="char"><div class="cn">${c.name}</div><div class="cd">${c.description||''}</div></div>`})
  E('s-res').innerHTML=h+'<pre>'+scriptText+'</pre>'
}
</script>
</body>
</html>"""

# ── Run ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
