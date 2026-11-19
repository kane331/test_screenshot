import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from .store import Store, sheet_name

def main():
    p=argparse.ArgumentParser(description='重新分类并记住路径规则（先退出截图工具）')
    p.add_argument('--output',required=True); p.add_argument('--config',required=True)
    p.add_argument('--id',required=True); p.add_argument('--sheet',required=True)
    args=p.parse_args(); sheet_name(args.sheet)
    store=Store(args.output)
    record=next(r for r in store.records() if r['id']==args.id)
    path=Path(args.config); config=json.loads(path.read_text(encoding='utf-8'))
    config.setdefault('rules',[]).append({'origin':urlsplit(record['url']).netloc,'path':'^'+re.escape(urlsplit(record['url']).path)+'$','sheet':args.sheet})
    tmp=path.with_suffix('.tmp'); tmp.write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8'); tmp.replace(path)
    store.classify(args.id,args.sheet)
    try:
        counts=store.flush(); print(f'Excel 已更新：{args.sheet}，共 {counts[args.sheet]} 张')
    except Exception as exc:
        print(f'截图已保存，Excel 待更新：{exc}'); raise SystemExit(1)

if __name__=='__main__':
    main()
