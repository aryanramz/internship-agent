"""Usable without MCP, an API key or ChatGPT account."""
import argparse
import json
import os
from pathlib import Path
from .service import Agent


def main():
    p=argparse.ArgumentParser(prog="internship-agent")
    p.add_argument("--data",default=os.environ.get("INTERNSHIP_AGENT_DATA","./data"))
    p.add_argument("--credentials-dir",default=None,help="Private Google credential directory (independent of --data)")
    cmds=p.add_subparsers(dest="command",required=True)
    a=cmds.add_parser("discover");a.add_argument("--sources",default="config/sources.json")
    a=cmds.add_parser("rank");a.add_argument("--profile",default="config/profile.json");a.add_argument("--min-score",type=int,default=0);a.add_argument("--limit",type=int,default=25)
    a=cmds.add_parser("preview");a.add_argument("job_id");a.add_argument("--profile",default="config/profile.json")
    a=cmds.add_parser("prepare");a.add_argument("job_id");a.add_argument("--profile",default="config/profile.json")
    a=cmds.add_parser("approve");a.add_argument("job_id");a.add_argument("confirmation_phrase")
    a=cmds.add_parser("mark-submitted");a.add_argument("job_id");a.add_argument("evidence")
    a=cmds.add_parser("status");a.add_argument("job_id");a.add_argument("outcome",choices=["assessment","interview","offer","rejected","withdrawn"]);a.add_argument("--evidence",default="")
    a=cmds.add_parser("export-tracker");a.add_argument("--output",default="data/tracker_append_candidates.csv");a.add_argument("--include-unapplied",action="store_true")
    add=cmds.add_parser("add-source")
    add.add_argument("url",help="Employer careers-board HTTPS URL")
    add.add_argument("--company",required=True)
    add.add_argument("--sources",default="config/sources.json")
    add.add_argument("--careers-url",default=None,help="Public employer careers URL; metadata only, never fetched")
    add.add_argument("--employer-id",default=None,help="Existing stable employer ID for an additional board")
    add.add_argument("--disabled",action="store_true",help="Register without enabling discovery")
    listing=cmds.add_parser("list-sources",help="Inspect local registry metadata without network or database access")
    listing.add_argument("--sources",default="config/sources.json")
    sugg=cmds.add_parser("suggest-sources")
    sugg.add_argument("--sources",default="config/sources.json")
    sugg.add_argument("--limit",type=int,default=50)
    sugg.add_argument("--apply",action="store_true",help="Explicitly register the suggested employer boards")
    b=cmds.add_parser("import-jobs");b.add_argument("file",help="Structured JSON list exported from approved sources or ChatGPT")
    cmds.add_parser("providers")
    g=cmds.add_parser("google-login",help="Authorize local Google API access (separate from ChatGPT connectors)")
    g.add_argument("service",choices=["gmail","sheets"])
    g.add_argument("--client",default=None)
    ga=cmds.add_parser("ingest-alerts",help="Stage Gmail job-alert links for review; no automatic job import")
    ga.add_argument("--query",default="")
    ga.add_argument("--limit",type=int,default=30)
    la=cmds.add_parser("leads",help="Review staged job-alert leads")
    la.add_argument("--limit",type=int,default=50)
    ha=cmds.add_parser("review-lead")
    ha.add_argument("lead_id");ha.add_argument("action",choices=["import","ignore"])
    ha.add_argument("--company",default="");ha.add_argument("--title",default="")
    ha.add_argument("--location",default="");ha.add_argument("--url",default="");ha.add_argument("--description",default="")
    sh=cmds.add_parser("sync-sheet",help="Preview or explicitly apply changes to existing Applications sheet")
    sh.add_argument("--spreadsheet-id",default=os.environ.get("INTERNSHIP_AGENT_SHEET_ID",""))
    sh.add_argument("--apply",action="store_true")
    sh.add_argument("--confirm",default="")
    cmds.add_parser("summary")
    args=p.parse_args()
    if args.command in {"add-source","list-sources"}:
        from .registry import load_registry, register_source
        from .source_detection import detect_source
        try:
            if args.command=="list-sources":
                result=load_registry(args.sources,missing_ok=True)
            else:
                board=detect_source(args.url,args.company)
                board["enabled"]=not args.disabled
                if args.careers_url is not None:
                    board["careers_url"]=args.careers_url
                if args.employer_id is not None:
                    board["employer_id"]=args.employer_id
                result=register_source(args.sources,board)
            print(json.dumps(result,indent=2,ensure_ascii=False))
        except (ValueError,OSError):
            p.exit(2,"Error: source registration or configuration is invalid; check the local registry and public board URL.\n")
        return
    agent=Agent(args.data,credentials_dir=args.credentials_dir)
    try:
        if args.command=="google-login":
            from .integrations.google_auth import credentials
            credentials(args.service,args.credentials_dir,args.client,interactive=True,legacy_dirs=agent.legacy_credential_dirs)
            result={"authorized":args.service,"token_file":str(agent.credentials_dir / ('google_' + args.service + '_token.json')),"note":"Token is local and must not be committed."}
        elif args.command=="ingest-alerts":result=agent.ingest_alerts(args.query,args.limit)
        elif args.command=="leads":result=agent.pending_alerts(args.limit)
        elif args.command=="review-lead":
            result=agent.handle_alert(args.lead_id,args.action,args.company,args.title,args.location,args.url,args.description)
        elif args.command=="sync-sheet":
            result=agent.sync_tracker(args.spreadsheet_id,args.apply,args.confirm)
        elif args.command=="discover": result=agent.discover(args.sources)
        elif args.command=="providers":
            from .sources import PUBLIC_BOARDS, AGGREGATORS, LOCAL_IMPORTS
            result={"public_company_boards":sorted(PUBLIC_BOARDS),"aggregators":sorted(AGGREGATORS),
                    "local_imports":sorted(LOCAL_IMPORTS),"custom_feed":["rss"]}
        elif args.command=="suggest-sources":
            result=agent.suggest_sources(args.sources,args.limit,args.apply)
        elif args.command=="import-jobs":
            with open(args.file,encoding="utf-8") as f: records=json.load(f)
            result=agent.import_external_jobs(records)
        elif args.command=="rank": result=agent.ranked(args.profile,args.limit,args.min_score)
        elif args.command=="preview":result=agent.preview(args.job_id,args.profile)
        elif args.command=="prepare":result=agent.prepare(args.job_id,args.profile)
        elif args.command=="approve":result=agent.store.approve(args.job_id,args.confirmation_phrase)
        elif args.command=="mark-submitted":result=agent.store.mark_submitted(args.job_id,args.evidence)
        elif args.command=="status":result=agent.store.update_status(args.job_id,args.outcome,args.evidence)
        elif args.command=="export-tracker":
            from .tracker import export_append_candidates
            result=export_append_candidates(agent.store,args.output,args.include_unapplied)
        else:result=agent.store.count()
        print(json.dumps(result,indent=2,ensure_ascii=False))
    except (ValueError,FileNotFoundError,RuntimeError) as e:
        p.exit(2,f"Error: {e}\n")

if __name__=="__main__":main()
