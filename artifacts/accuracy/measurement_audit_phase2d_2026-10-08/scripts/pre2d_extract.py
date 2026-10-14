import json, ast, re, sys
T=sys.argv[1]; OUT=sys.argv[2]
lines=[json.loads(l) for l in open(T)]
start=4393
edits=[]
for i,l in enumerate(lines[start:],start):
    m=l.get("message",{})
    if l.get("type")!="assistant" or not isinstance(m.get("content"),list): continue
    for c in m["content"]:
        if c.get("type")!="tool_use" or c["name"]!="Bash": continue
        cmd=c["input"]["command"]
        if "src/regulus" not in cmd: continue
        for body in re.findall(r"<<'EOF'\n(.*?)\nEOF", cmd, re.S):
            if "src/regulus" not in body or not re.search(r'write_text|open\(p,\s*"w"\)', body): continue
            tree=ast.parse(body); names={}; cur=None; ops=[]
            def val(n):
                if isinstance(n,ast.Constant) and isinstance(n.value,str): return n.value
                if isinstance(n,ast.Name): return names.get(n.id)
                if isinstance(n,ast.Call) and getattr(n.func,"id",None)=="Path": return val(n.args[0])
                return None
            for node in ast.walk(tree): pass
            # walk statements in order (including inside for loops over literal lists)
            def run(stmts):
                global cur
                for st in stmts:
                    if isinstance(st,ast.Assign) and isinstance(st.targets[0],ast.Name):
                        v=val(st.value)
                        if v is not None: names[st.targets[0].id]=v
                        if st.targets[0].id=="p" and v: names["__file"]=v
                    elif isinstance(st,ast.Assign) and isinstance(st.targets[0],ast.Tuple) and isinstance(st.value,ast.Tuple):
                        for t,vv in zip(st.targets[0].elts, st.value.elts):
                            v=val(vv)
                            if v is not None: names[t.id]=v
                    elif isinstance(st,ast.For) and isinstance(st.iter,(ast.List,ast.Tuple)) and isinstance(st.target,ast.Tuple):
                        for el in st.iter.elts:
                            for t,vv in zip(st.target.elts, el.elts): names[t.id]=val(vv)
                            run(st.body)
                    elif isinstance(st,ast.For) and isinstance(st.iter,ast.Name) and st.iter.id in names.get("__lists",{}):
                        for el in names["__lists"][st.iter.id]:
                            for t,v in zip(st.target.elts, el): names[t.id]=v
                            run(st.body)
                    if isinstance(st,ast.Assign) and isinstance(st.value,ast.List) and isinstance(st.targets[0],ast.Name):
                        names.setdefault("__lists",{})[st.targets[0].id]=[tuple(val(x) for x in e.elts) for e in st.value.elts if isinstance(e,ast.Tuple)]
                    for node in ast.walk(st) if not isinstance(st,ast.For) else []:
                        if isinstance(node,ast.Call):
                            f=node.func; fn=getattr(f,"id",None) or getattr(f,"attr",None)
                            if fn=="rep" and len(node.args)>=2: ops.append((names.get("__file"),val(node.args[0]),val(node.args[1])))
                            elif fn=="edit" and len(node.args)>=3: ops.append((val(node.args[0]),val(node.args[1]),val(node.args[2])))
                            elif fn=="replace" and isinstance(f.value,ast.Name) and f.value.id=="s" and len(node.args)>=2:
                                ops.append((names.get("__file"),val(node.args[0]),val(node.args[1])))
            run(tree.body)
            for o in ops: edits.append({"line":i,"file":o[0],"old":o[1],"new":o[2]})
bad=[e for e in edits if None in (e["file"],e["old"],e["new"])]
print("edits",len(edits),"unresolved",len(bad))
for b in bad: print("  UNRESOLVED",b["line"],b["file"],(b["old"] or "")[:60],(b["new"] or "")[:60])
from collections import Counter; print(Counter((e["line"],e["file"]) for e in edits))
json.dump(edits,open(OUT,"w"),indent=1)
