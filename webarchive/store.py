"""Durable journal and deterministic, atomic workbook materialization."""
import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path
from filelock import FileLock
from openpyxl import Workbook, load_workbook
from openpyxl.drawing.image import Image


def sheet_name(value):
    if not value or len(value) > 31 or re.search(r"[\\/*?:\[\]]", value) or value.startswith("'") or value.endswith("'"):
        raise ValueError("Sheet 名称须为 1–31 字符，且不能含 Excel 禁用字符或首尾单引号")
    if value == '_截图索引':
        raise ValueError('保留名称')
    return value


class Store:
    def __init__(self, output, template=None):
        self.output = Path(output).resolve()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.root = self.output.with_suffix('.archive')
        self.root.mkdir(exist_ok=True)
        self.lock = FileLock(str(self.root / 'session.lock'), timeout=0)
        self.lock.acquire()
        self.db = sqlite3.connect(self.root / 'journal.sqlite', check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS captures (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self._last_records = None
        self._last_counts = {}
        self.base = self.root / 'baseline.xlsx'
        if not self.base.exists():
            source = Path(template).resolve() if template else (self.output if self.output.exists() else None)
            if source:
                if template and source == self.output:
                    raise ValueError('模板与输出路径必须不同')
                shutil.copy2(source, self.base)
            else:
                wb = Workbook()
                wb.active.title = '_截图索引'
                wb.save(self.base)

    def records(self):
        return [json.loads(row[0]) for row in self.db.execute('SELECT data FROM captures ORDER BY rowid')]

    def add(self, record):
        self.db.execute('INSERT INTO captures VALUES (?,?)', (record['id'], json.dumps(record, ensure_ascii=False)))
        self.db.commit()

    def classify(self, capture_id, sheet):
        sheet_name(sheet)
        record = next(r for r in self.records() if r['id'] == capture_id)
        record['sheet'] = sheet
        self.db.execute('UPDATE captures SET data=? WHERE id=?', (json.dumps(record, ensure_ascii=False), capture_id))
        self.db.commit()

    def flush(self):
        records = self.records()
        if records == self._last_records and self.output.exists():
            return self._last_counts
        wb = load_workbook(self.base)
        index = wb['_截图索引'] if '_截图索引' in wb.sheetnames else wb.create_sheet('_截图索引')
        index.sheet_state = 'visible'
        index.append(['截图 ID', 'Sheet', '序号', '时间', '页面', 'URL', '完整性', 'PNG'])
        positions, counts = {}, {}
        for r in records:
            name = sheet_name(r['sheet'])
            ws = wb[name] if name in wb.sheetnames else wb.create_sheet(name)
            if name not in positions:
                bottom = ws.max_row + 2 if ws.max_row > 1 or ws['A1'].value else 1
                for old in ws._images:
                    anchor = old.anchor
                    if hasattr(anchor, '_to'):
                        bottom = max(bottom, anchor._to.row + 4)
                    elif hasattr(anchor, '_from'):
                        height = anchor.ext.cy / 9525 if hasattr(anchor, 'ext') else old.height
                        bottom = max(bottom, anchor._from.row + math.ceil(height / 20) + 4)
                positions[name] = bottom
            row = positions[name]
            counts[name] = counts.get(name, 0) + 1
            ws.cell(row, 1, f"#{counts[name]}  {r['time']}  {r['name']}")
            ws.cell(row + 1, 1, r['status'])
            ws.cell(row + 2, 1, r['url'])
            pic = Image(r['png'])
            scale = min(1, 960 / pic.width)
            pic.width *= scale
            pic.height *= scale
            ws.add_image(pic, f'A{row + 3}')
            for n in range(row + 3, row + 4 + math.ceil(pic.height / 20)):
                ws.row_dimensions[n].height = 15
            positions[name] = row + 6 + math.ceil(pic.height / 20)
            ws.column_dimensions['A'].width = 135
            index.append([r['id'], name, counts[name], r['time'], r['name'], r['url'], r['status'], r['png']])
        if len(wb.sheetnames) > 1:
            index.sheet_state = 'hidden'
            wb.active = next(i for i,s in enumerate(wb) if s.sheet_state == 'visible')
        fd, tmp = tempfile.mkstemp(suffix='.xlsx', dir=self.output.parent)
        os.close(fd)
        try:
            wb.save(tmp)
            with open(tmp, 'rb') as stream:
                os.fsync(stream.fileno())
            if self.output.with_name('~$' + self.output.name).exists():
                raise PermissionError('Excel 锁文件存在，请关闭 Excel')
            os.replace(tmp, self.output)
        finally:
            Path(tmp).unlink(missing_ok=True)
            wb.close()
        self._last_records = records
        self._last_counts = counts
        return counts
