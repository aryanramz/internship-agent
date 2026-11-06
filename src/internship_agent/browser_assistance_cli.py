"""Local operator inspection/reconciliation, independent of browser dependencies."""
import argparse
import json
from pathlib import Path
import sqlite3
from .browser_assistance import Assistance


def main(argv=None):
    parser=argparse.ArgumentParser(description='Inspect/reconcile fictional sandbox assistance only; never fill or click a real form')
    parser.add_argument('operation',choices=['inspect','reconcile','revoke'])
    parser.add_argument('--root',required=True)
    parser.add_argument('--origin',required=True,help='Exact original numeric loopback origin from the plan')
    parser.add_argument('--plan-id',required=True)
    parser.add_argument('--confirm')
    parser.add_argument('--outcome',choices=['submitted','not_submitted','unknown'])
    parser.add_argument('--provenance')
    args=parser.parse_args(argv)
    try:
        adapter=Assistance(Path(args.root),args.origin,'local-cli-operator',enabled=True)
        plan=adapter.review(args.plan_id)
        if args.operation!='inspect':
            action=args.operation
            payload={'phrase':args.confirm,'outcome':args.outcome,'provenance':args.provenance,
                     'form_fingerprint':plan['form_fingerprint']}
            plan=adapter.act(args.plan_id,action,plan['action_token'],payload)
        # No browser action/session/review tokens are printed by this operator report.
        plan={k:v for k,v in plan.items() if k not in ('action_token','review_token')}
        print(json.dumps(plan,ensure_ascii=True,indent=2))
    except (ValueError,OSError,sqlite3.Error,KeyError,TypeError):
        parser.exit(2,'Sandbox operation refused. Inspect the original plan, approval and manual reconciliation requirements.\n')
    return 0

if __name__=='__main__':raise SystemExit(main())
