"""Local JSON/stdin outreach operator interface. Never sends or activates OAuth."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

def main(argv=None):
    parser=argparse.ArgumentParser(description='Offline verified contact/draft/reply/follow-up workflow. No email sending.')
    parser.add_argument('--root',default=str(Path.cwd()))
    parser.add_argument('operation',choices=['get','action'])
    parser.add_argument('name',help='Read view or explicit mutation name')
    parser.add_argument('--id')
    parser.add_argument('--page',default='1')
    args=parser.parse_args(argv)
    try:
        from .outreach_api import read,mutate
        if args.operation=='get':
            query={'page':args.page} if args.name in {'contacts','drafts'} else {}
            if args.id:query['id']=args.id
            result=read(Path(args.root),args.name,query)
        else:
            raw=sys.stdin.buffer.read(16385)
            if len(raw)>16384:raise ValueError('Input too large')
            def unique(pairs):
                out={}
                for key,value in pairs:
                    if key in out:raise ValueError('Duplicate key')
                    out[key]=value
                return out
            payload=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=unique)
            if not isinstance(payload,dict) or payload.get('action') not in (None,args.name):raise ValueError('Action mismatch')
            payload['action']=args.name
            result=mutate(Path(args.root),payload)
        print(json.dumps(result,ensure_ascii=True,indent=2))
    except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):
        parser.exit(2,'Outreach operation refused. Inspect local evidence, recipient binding and current review; no message was sent.\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
