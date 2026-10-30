import json,sys
for line in sys.stdin:
    try: msg=json.loads(line)
    except Exception: continue
    method=msg.get('method'); mid=msg.get('id')
    if mid is None: continue
    if method=='initialize': result={'protocolVersion':msg.get('params',{}).get('protocolVersion'),'capabilities':{'tools':{}},'serverInfo':{'name':'fixture','version':'1'}}
    elif method=='tools/list': result={'tools':[{'name':'echo','description':'fixture only','inputSchema':{'type':'object'}}]}
    elif method=='tools/call': result={'content':[{'type':'text','text':json.dumps(msg.get('params',{}).get('arguments',{}))}],'isError':False}
    else:
        print(json.dumps({'jsonrpc':'2.0','id':mid,'error':{'code':-32601,'message':'method not found'}}),flush=True); continue
    print(json.dumps({'jsonrpc':'2.0','id':mid,'result':result}),flush=True)
