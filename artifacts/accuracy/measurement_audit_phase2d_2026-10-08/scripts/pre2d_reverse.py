import json, sys
P=sys.argv[1]; T=sys.argv[2]
lines=[json.loads(l) for l in open(T)]
res=lines[4405]["message"]["content"]
t=next((c["content"] if isinstance(c["content"],str) else "".join(x.get("text","") for x in c["content"] if isinstance(x,dict))) for c in res if c.get("type")=="tool_result")
a=t.index("    # A claim that is a verbatim passage of ONE candidate is supported by that")
b=t.index("# ------------------------------------------------------------ list items")
old_tail=t[a:b]
edits=json.load(open(P+"pre2d/edits.json"))
real=[]
for e in edits:
    if e["file"] and e["new"] is not None and e["old"] is None and e["new"].startswith("    # A claim that is a verbatim passage"):
        e["old"]=old_tail; real.append(e)
    elif None not in (e["file"],e["old"],e["new"]): real.append(e)
print("real edits:",len(real))
root=P+"pre2d/"
deleted=[]
for e in reversed(real):
    path=root+e["file"]; s=open(path).read()
    if e["new"]=="":
        deleted.append(e["old"]); continue          # a deletion: undone with the edit that inserted it
    for d in deleted:
        if d in e["new"] and s.count(e["new"])==0 and s.count(e["new"].replace(d,""))==1:
            e=dict(e,new=e["new"].replace(d,""),old=e["old"].replace(d,"")); deleted.remove(d); break
    n=s.count(e["new"])
    if n!=1:
        print("CANNOT REVERSE (count=%d)"%n, e["line"], e["file"], repr(e["new"][:80])); sys.exit(1)
    open(path,"w").write(s.replace(e["new"],e["old"]))
# cosmetic sed of this session
p=root+"src/regulus/accuracy/answer.py"; s=open(p).read()
s=s.replace("# sentence | descriptive | list_item | adjacent_window","# sentence | list_item | adjacent_window"); open(p,"w").write(s)
print("reversed OK; unmatched deletions:",len(deleted))
