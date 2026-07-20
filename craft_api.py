#!/usr/bin/env python3
"""CRAFT Screenwriting Suite — Web API using Agnes AI."""
import json,os,re,sys,time,threading,logging,requests,urllib.request
from http.server import HTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,parse_qs
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.WARNING)
import logging; logger=logging.getLogger(__name__)

# Agnes API
cfg_path=os.path.join(os.path.dirname(__file__),".agnes_config","config.json")
try: _keys=json.load(open(cfg_path))['api_keys']
except: _keys=[]
_API_KEY=_keys[2] if len(_keys)>2 else (_keys[0] if _keys else "")
_BASE="https://apihub.agnes-ai.com/v1"

def _call(text,max_tokens=2048,timeout=120):
    for _ in range(3):
        for key in _keys if _keys else [_API_KEY]:
            try:
                r=requests.post(f"{_BASE}/chat/completions",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json={"model":"agnes-2.0-flash","messages":[{"role":"user","content":text}],"max_tokens":max_tokens,"temperature":0.7},timeout=timeout)
                if r.status_code==200: return r.json()["choices"][0]["message"]["content"],None
                if r.status_code==401: continue
                if r.status_code>=500: time.sleep(5); break
            except (requests.ConnectionError,requests.Timeout): time.sleep(5); break
    return None,"API error"

def _call_json(text,max_tokens=2048):
    raw,err=_call(text,max_tokens)
    if err or not raw: return {},err
    t=raw.strip()
    if t.startswith("```"):
        lines=t.split("\n")
        if lines[0].startswith("```"): lines=lines[1:]
        if lines and lines[-1].strip()=="```": lines=lines[:-1]
        t="\n".join(lines).strip()
    m=re.search(r'\{[\s\S]*\}',t)
    if m:
        try: return json.loads(m.group()),None
        except: pass
    try: return json.loads(t),None
    except: return {},f"JSON fail: {raw[:80]}"

LANG=os.environ.get("CRAFT_LANGUAGE",os.environ.get("PROMPT_LANGUAGE","zh"))
STRUCTURES={"three_act":{"name":"Three-Act","desc":"Setup-Confrontation-Resolution"},"save_the_cat":{"name":"Save the Cat","desc":"15-beat commercial"},"hero_journey":{"name":"Hero's Journey","desc":"12 stages"},"fichtean":{"name":"Fichtean","desc":"Rapid crises"},"five_act":{"name":"Five-Act","desc":"Shakespearean"}}
GENRES={"action":{"pacing":"Fast","proto":"Capable hero","anti":"Intelligent adversary","elements":["Set pieces","Chase"]},"thriller":{"pacing":"Tension building","proto":"Reluctant investigator","anti":"Hidden threat","elements":["Suspense","Revelation"]},"drama":{"pacing":"Character-driven","proto":"Flawed person","anti":"Internal+external","elements":["Emotion","Transformation"]},"horror":{"pacing":"Dread builds","proto":"Survivor","anti":"Unseen force","elements":["Atmosphere"]},"comedy":{"pacing":"Rapid gags","proto":"Lovable fool","anti":"Obstacle","elements":["Wit","Timing"]},"scifi":{"pacing":"World-building","proto":"Ordinary in extraordinary","anti":"The system","elements":["World rules"]},"fantasy":{"pacing":"Epic","proto":"Unlikely hero","anti":"Dark force","elements":["Magic"]},"romance":{"pacing":"Emotional","proto":"Two people","anti":"Circumstance","elements":["Chemistry"]}}

class CRAFT:
    @staticmethod
    def direct_story(idea,genre,structure,runtime="medium"):
        g=GENRES.get(genre,GENRES["action"]); s=STRUCTURES.get(structure,STRUCTURES["three_act"])
        if LANG=="zh":
            prompt=f"你是顶级电影导演。输出纯JSON:\n创意:{idea}\n类型:{genre}(节奏:{g['pacing']},主角:{g['proto']},反派:{g['anti']})\n结构:{s['name']}\nJSON:{{\"title\":\"标题\",\"logline\":\"一句话故事\",\"theme\":\"主题\",\"characters\":[{{\"name\":\"名\",\"role\":\"角色\",\"want\":\"想要\",\"need\":\"需要\",\"flaw\":\"缺陷\",\"arc\":\"转变\"}}],\"structure_map\":{{\"节拍\":{{\"act\":\"幕\",\"page\":\"页\",\"event\":\"事件\",\"purpose\":\"作用\"}}}},\"key_scenes\":[{{\"index\":1,\"name\":\"名\",\"location\":\"地点\",\"conflict\":\"冲突\",\"visual\":\"画面\"}}],\"twists\":[{{\"description\":\"反转\",\"impact\":\"影响\"}}],\"climax\":{{\"description\":\"高潮\",\"external_conflict\":\"外\",\"internal_conflict\":\"内\"}},\"visual_style\":{{\"color_palette\":\"色彩\",\"lighting\":\"用光\",\"camera_style\":\"摄影\"}},\"pacing_guide\":\"节奏\"}}\n10节拍,2反转,值用中文"
        else:
            prompt=f"You are a top film director. Output ONLY JSON:\nIdea:{idea}\nGenre:{genre}(pacing:{g['pacing']},hero:{g['proto']},villain:{g['anti']})\nStructure:{s['name']}\nJSON:{{\"title\":\"Title\",\"logline\":\"One-sentence\",\"theme\":\"Theme\",\"characters\":[{{\"name\":\"Name\",\"role\":\"role\",\"want\":\"Want\",\"need\":\"Need\",\"flaw\":\"Flaw\",\"arc\":\"Arc\"}}],\"structure_map\":{{\"beat\":{{\"act\":\"Act\",\"page\":\"Page\",\"event\":\"Event\",\"purpose\":\"Purpose\"}}}},\"key_scenes\":[{{\"index\":1,\"name\":\"Name\",\"location\":\"Location\",\"conflict\":\"Conflict\",\"visual\":\"Visual\"}}],\"twists\":[{{\"description\":\"Desc\",\"impact\":\"Impact\"}}],\"climax\":{{\"description\":\"Desc\",\"external_conflict\":\"Ext\",\"internal_conflict\":\"Int\"}},\"visual_style\":{{\"color_palette\":\"Color\",\"lighting\":\"Lighting\",\"camera_style\":\"Camera\"}},\"pacing_guide\":\"Guide\"}}\n10 beats,2+ twists,values Chinese"
        return _call_json(prompt,max_tokens=4096)

    @classmethod
    def generate_beat_sheet(cls,idea,genre,structure,fmt="text"):
        s=STRUCTURES.get(structure,STRUCTURES["three_act"])
        if LANG=="zh":
            prompt=f"你是专业编剧。输出纯JSON:\n创意:{idea}\n结构:{s['name']},类型:{genre}\nJSON:{{\"title\":\"标题\",\"structure_used\":\"{s['name']}\",\"genre\":\"{genre}\",\"beats\":[{{\"name\":\"节拍\",\"position\":\"%\",\"description\":\"事件\",\"purpose\":\"为什么\",\"emotional_beat\":\"感受\"}}],\"pacing_analysis\":\"节奏\",\"recommended_scenes\":7}}\n6-8节拍,值用中文"
        else:
            prompt=f"You are a screenwriter. Output ONLY JSON:\nIdea:{idea}\nStructure:{s['name']},Genre:{genre}\nJSON:{{\"title\":\"Title\",\"structure_used\":\"{s['name']}\",\"genre\":\"{genre}\",\"beats\":[{{\"name\":\"Beat\",\"position\":\"%\",\"description\":\"Event\",\"purpose\":\"Why\",\"emotional_beat\":\"Feeling\"}}],\"pacing_analysis\":\"Pacing\",\"recommended_scenes\":7}}\n6-8 beats,values Chinese"
        result,err=_call_json(prompt,max_tokens=2048)
        if err: return "",{}
        if fmt=="text":
            lines=[f"{'='*70}",f"  BEAT SHEET: {result.get('title','Untitled')}",f"{'='*70}",f"Structure: {result.get('structure_used','')}",f"Genre: {result.get('genre','')}",'']
            for i,b in enumerate(result.get("beats",[]),1):
                lines+=[f"  {i}. [{b.get('position','')}] {b.get('name','')}",f"     {b.get('description','')}",f"     Purpose: {b.get('purpose','')}",f"     Audience: {b.get('emotional_beat','')}",'']
            lines+=[f"{'='*70}",f"Pacing: {result.get('pacing_analysis','')}"]
            return "\n".join(lines),result
        return result

    @classmethod
    def write_screenplay(cls,blueprint,fmt_type="industry"):
        title=blueprint.get("title","Untitled"); logline=blueprint.get("logline","")
        scenes=blueprint.get("key_scenes",[]); chars=blueprint.get("characters",[])
        if LANG=="zh":
            prompt=f"按好莱坞格式写剧本:\n标题:{title}\nLOG LINE:{logline}\n角色:{json.dumps(chars,ensure_ascii=False)}\n场景:{json.dumps(scenes,ensure_ascii=False)}\n格式:INT/EXT标题、动作(现在时中文)、角色名(大写)、对白、FADE OUT"
        else:
            prompt=f"Write screenplay in industry format:\nTitle:{title}\nLOG LINE:{logline}\nCharacters:{json.dumps(chars,ensure_ascii=False)}\nScenes:{json.dumps(scenes,ensure_ascii=False)}\nFormat:Scene headings,action(present tense Chinese),CHARACTER(uppercase),dialogue,FADE OUT"
        raw,err=_call(prompt,max_tokens=4096)
        if err or not raw: return ""
        lines=["="*78,f"  {title}",f"  LOG LINE: {logline}","="*78,"","CHARACTERS","-"*40]
        for c in chars: lines.append(f"  {c.get('name','').upper():30} {c.get('role','')}")
        lines.append("")
        for sc in scenes:
            loc=sc.get("location","UNKNOWN"); act=sc.get("act","")
            lines+=[f"\n  {'INT.' if 'INT' in loc.upper() else 'EXT.'} {loc.upper()} - {act}",""]
            vis=sc.get("visual","")
            if vis:
                for l in vis.split('\n'):
                    if l.strip(): lines.append(f"  {l.strip()}")
            dlg=sc.get("dialogue","")
            if dlg:
                for dl in dlg.split('\n'):
                    dl=dl.strip()
                    if not dl: continue
                    m=re.match(r'(.+?):\s*"(.+?)"',dl)
                    if m: lines+=["",f"  {m.group(1).upper():35}",f"  {m.group(2).strip()}"]
                    elif ':' in dl: lines.append(f"  {dl}")
        lines+=["\n  FADE OUT."]
        return "\n".join(lines)

    @classmethod
    def review_script(cls,script,genre=""):
        if LANG=="zh":
            prompt=f"你是好莱坞剧本审稿人。评审:\n类型:{genre}\n剧本:{script[:5000]}\n输出:1.总评(A+-C)2.摘要3.优点4.缺点5.分析6.建议7.对标"
        else:
            prompt=f"You are a Hollywood script reader. Review:\nGenre:{genre}\nScript:{script[:5000]}\nOutput:1.Score(A+-C)2.Summary3.Strengths4.Weaknesses5.Analysis6.Revisions7.Comparables"
        return _call(prompt,max_tokens=2048)[0] or ""

    @classmethod
    def analyze_idea(cls,idea,genre):
        g=GENRES.get(genre,GENRES["action"])
        if LANG=="zh":
            prompt=f"你是编剧顾问。输出纯JSON:\n类型:{genre}(节奏:{g['pacing']},主角:{g['proto']},反派:{g['anti']})\n创意:{idea}\nJSON:{{\"logline\":\"\",\"structure_recommendation\":\"\",\"why_this_structure\":\"\",\"protagonist_profile\":{{\"archetype\":\"\",\"external_goal\":\"\",\"internal_need\":\"\",\"fatal_flaw\":\"\"}},\"antagonist_profile\":{{\"archetype\":\"\",\"motivation\":\"\",\"threat\":\"\"}},\"key_scenes_idea\":[],\"potential_twists\":[],\"pitfalls_to_avoid\":[],\"comparable_films\":[]}}"
        else:
            prompt=f"You are a consultant. Output ONLY JSON:\nGenre:{genre}(pacing:{g['pacing']},hero:{g['proto']},villain:{g['anti']})\nIdea:{idea}\nJSON:{{\"logline\":\"\",\"structure_recommendation\":\"\",\"why_this_structure\":\"\",\"protagonist_profile\":{{\"archetype\":\"\",\"external_goal\":\"\",\"internal_need\":\"\",\"fatal_flaw\":\"\"}},\"antagonist_profile\":{{\"archetype\":\"\",\"motivation\":\"\",\"threat\":\"\"}},\"key_scenes_idea\":[],\"potential_twists\":[],\"pitfalls_to_avoid\":[],\"comparable_films\":[]}}"
        return _call_json(prompt,max_tokens=2048)

class CraftHandler(BaseHTTPRequestHandler):
    def _j(self,data,status=200):
        body=json.dumps(data,ensure_ascii=False,indent=2).encode()
        self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(body))); self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        try: self.wfile.write(body)
        except: pass
    def _h(self,b):
        self.send_response(200); self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",str(len(b))); self.send_header("Access-Control-Allow-Origin","*")
        self.end_headers()
        try: self.wfile.write(b)
        except: pass
    def do_OPTIONS(self):
        self.send_response(200); self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS"); self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.end_headers()
    def do_GET(self):
        p=urlparse(self.path).path
        if p in ("/","/craft"):
            with open(os.path.join(os.path.dirname(__file__),"craft_ui.html"),"rb") as f: self._h(f.read())
        elif p=="/api/info":
            self._j({"name":"CRAFT Screenwriting Suite","version":"2.1.0","api":"Agnes AI","language":LANG,
                "structures":{k:v["name"] for k,v in STRUCTURES.items()},'genres':list(GENRES.keys()),
                "endpoints":{"direct":"POST /api/direct","beat-sheet":"POST /api/beat-sheet","screenplay":"POST /api/screenplay","review":"POST /api/review","analyze":"POST /api/analyze"}})
        elif p=="/api/structures": self._j({k:v for k,v in STRUCTURES.items()})
        elif p=="/api/genres": self._j({k:v for k,v in GENRES.items()})
        else: self._j({"error":"Not found"},404)
    def do_POST(self):
        p=urlparse(self.path).path; cl=int(self.headers.get("Content-Length",0))
        if cl>0:
            try: data=json.loads(self.rfile.read(cl).decode())
            except: data={}
        else: data={}
        for k,v in parse_qs(urlparse(self.path).query).items(): data[k]=v[0] if len(v)==1 else v
        if p=="/api/direct":
            idea=data.get("idea",""); genre=data.get("genre","action"); structure=data.get("structure","three_act")
            if not idea: self._j({"error":"Missing idea"},400); return
            r,e=CRAFT.direct_story(idea,genre,structure); self._j({"status":"ok" if not e else "error","data":r})
        elif p=="/api/beat-sheet":
            idea=data.get("idea",""); genre=data.get("genre","action"); structure=data.get("structure","three_act")
            if not idea: self._j({"error":"Missing idea"},400); return
            text,r=CRAFT.generate_beat_sheet(idea,genre,structure,"text")
            self._j({"status":"ok","text":text,"json":r})
        elif p=="/api/screenplay":
            bp=data.get("blueprint"); ft=data.get("format","industry")
            if not bp: self._j({"error":"Missing blueprint"},400); return
            self._j({"status":"ok","script":CRAFT.write_screenplay(bp,ft)})
        elif p=="/api/review":
            script=data.get("script",""); genre=data.get("genre","")
            if not script: self._j({"error":"Missing script"},400); return
            self._j({"status":"ok","review":CRAFT.review_script(script,genre)})
        elif p=="/api/analyze":
            idea=data.get("idea",""); genre=data.get("genre","action")
            if not idea: self._j({"error":"Missing idea"},400); return
            r,e=CRAFT.analyze_idea(idea,genre); self._j({"status":"ok" if not e else "error","data":r})
        elif p=="/api/export":
            try:
                uid=urllib.request.urlopen(f"http://localhost:8765/api/tasks/{data.get('task_id','')}",timeout=10)
                task=json.loads(uid.read())
                bp={"title":task.get("story_title",""),"logline":task.get("story_summary",""),
                    "characters":[{"name":c["name"],"role":c.get("role","unknown")} for c in task.get("characters",[])],
                    "key_scenes":[{"index":s["index"],"name":f"Scene {s['index']}",
                        "location":s.get("location",""),"visual":s.get("action",""),
                        "dialogue":s.get("dialogue",""),"duration":s.get("duration",30)} for s in task.get("scenes",[])]}
                self._j({"status":"ok","blueprint":bp})
            except Exception as e: self._j({"error":str(e)},500)
        else: self._j({"error":"Unknown"},404)
    def log_message(self,*a): pass

class ThreadedServer(HTTPServer):
    allow_reuse_address=True
    def process_request(self,req,addr):
        t=threading.Thread(target=self._h,args=(req,addr)); t.daemon=True; t.start()
    def _h(self,req,addr):
        try: self.finish_request(req,addr)
        except: pass
        finally: self.shutdown_request(req)

def main():
    port=int(os.environ.get("CRAFT_PORT","8999"))
    srv=ThreadedServer(("0.0.0.0",port),CraftHandler)
    print(f"🎬 CRAFT v2.1 on :{port} | AI:Agnes | Lang:{LANG}")
    srv.serve_forever()

if __name__=="__main__":
    main()
