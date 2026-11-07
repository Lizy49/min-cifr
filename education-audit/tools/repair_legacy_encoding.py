"""Repair old saved text without re-fetching pages or erasing historical results."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from sqlalchemy import select
from audit.models import connect, Page, Run, utcnow
from audit.encoding import repair_legacy

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--backup',type=Path,default=Path('encoding-backup.json'))
    args=parser.parse_args()
    engine,factory=connect()
    snapshots,changes,runs=[],[],set()
    with factory() as session:
        for page in session.scalars(select(Page)):
            old={'title':page.title,'text':page.text,'details':page.details}
            new=repair_legacy(old)
            if old!=new:
                snapshots.append({'page_id':page.id,'run_id':page.run_id,**old})
                changes.append((page,new))
                runs.add(page.run_id)
        backup={'created_at_utc':utcnow().isoformat(),'pages':snapshots,'results':[],'run_meta':[]}
        for rid in runs:
            run=session.get(Run,rid)
            backup['run_meta'].append({'run_id':rid,'meta':run.meta})
            for result in run.results:
                old={'title':result.title,'explanation':result.explanation,'recommendation':result.recommendation,'evidence':result.evidence}
                new=repair_legacy(old)
                if old!=new:
                    backup['results'].append({'result_id':result.id,**old})
                    if args.apply:
                        for key,value in new.items():setattr(result,key,value)
        if args.apply and changes:
            # Exclusive creation prevents overwriting a previous recovery file.
            with args.backup.open('x',encoding='utf-8') as stream:
                json.dump(backup,stream,ensure_ascii=False,indent=2)
            for page,new in changes:
                for key,value in new.items():setattr(page,key,value)
            for rid in runs:
                run=session.get(Run,rid)
                run.meta={**run.meta,'encoding_repair':{'at_utc':utcnow().isoformat(),
                    'note':'Исправлена кодировка ранее сохранённого текста. Исторические статусы правил сохранены; для новых выводов запустите проверку повторно.'}}
            session.commit()
        print(f"{'Repaired' if args.apply else 'Would repair'} {len(changes)} page snapshots in runs {sorted(runs)}.")
    engine.dispose()

if __name__=='__main__':main()
