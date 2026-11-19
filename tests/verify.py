"""Real Chromium keyboard/tab integration and workbook recovery acceptance."""
import asyncio
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from openpyxl import load_workbook, Workbook
from playwright.async_api import async_playwright
from webarchive.app import Recorder, SCRIPT
from webarchive.store import Store

ROOT = Path('verification').resolve()

async def main():
    shutil.rmtree(ROOT,ignore_errors=True); ROOT.mkdir()
    config_path=ROOT/'config.json'; shutil.copy('examples/config.json',config_path)
    config=json.loads(config_path.read_text())
    template=ROOT/'template.xlsx'; wb=Workbook(); wb.active.title='模板说明'; wb.active['A1']='保留模板'; wb.save(template)
    original=template.read_bytes()
    store=Store(ROOT/'result.xlsx',template)
    rec=Recorder(store,config,config_path)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=True,args=['--no-sandbox'])
        context=await browser.new_context(viewport={'width':1100,'height':800},device_scale_factor=1)
        await context.expose_binding('__archiveCapture',rec.capture)
        await context.add_init_script('('+SCRIPT+')('+json.dumps(config['hotkey'])+')')
        async def shoot(page, count):
            await page.bring_to_front()
            await page.keyboard.press('Control+Shift+s')
            for _ in range(200):
                if len(store.records())>=count and not rec.write_lock.locked():
                    await page.wait_for_timeout(100)
                    return
                await page.wait_for_timeout(50)
            raise AssertionError('capture timeout')
        a=await context.new_page(); await a.goto('http://127.0.0.1:8765/orders')
        await shoot(a,1)
        await a.get_by_role('button').click(); await shoot(a,2)
        b=await context.new_page(); await b.goto('http://127.0.0.1:8765/reports'); await shoot(b,3)
        assert store.records()[2]['url'].endswith('/reports')
        report_image=Image.open(store.records()[2]['png'])
        assert report_image.getpixel((500,500)) == (144,238,144)
        assert Path(store.records()[0]['png']).read_bytes() != Path(store.records()[1]['png']).read_bytes()
        await a.bring_to_front(); await a.goto('http://127.0.0.1:8765/table')
        await a.locator('#rows').evaluate('(e)=>e.scrollTop=777')
        await shoot(a,4)
        assert await a.locator('#rows').evaluate('(e)=>e.scrollTop') == 777
        im=Image.open(store.records()[3]['png']); assert im.height==4000
        # Distinct colored first/last rows prove both ends survive stitching.
        assert im.getpixel((700,10)) == (0,220,240)
        assert im.getpixel((700,3990)) == (79,220,240)
        await a.goto('http://127.0.0.1:8765/unknown')
        async def dialog(d):
            assert len(store.records())==5
            assert store.records()[-1]['sheet']=='待分类'
            await d.accept('新功能')
        a.once('dialog',dialog); await shoot(a,5)
        assert store.records()[-1]['sheet']=='新功能'
        assert json.loads(config_path.read_text())['rules'][-1]['sheet']=='新功能'
        # Simulate atomic replacement failure after PNG+journal persist.
        await b.bring_to_front()
        with patch('webarchive.store.os.replace',side_effect=PermissionError('模拟 Excel 占用')):
            await shoot(b,6)
        assert len(store.records())==6
        assert await rec.flush()
        assert await rec.flush()
        await a.goto('http://127.0.0.1:8765/virtual'); a.once('dialog',lambda d:d.dismiss()); await shoot(a,7)
        assert '部分截图' in store.records()[-1]['status']
        await browser.close()
    assert template.read_bytes()==original
    store.lock.release(); store.db.close()
    # Restart materialization is idempotent.
    store2=Store(ROOT/'result.xlsx'); store2.flush(); store2.flush()
    wb=load_workbook(ROOT/'result.xlsx')
    assert wb['模板说明']['A1'].value=='保留模板'
    assert len(wb['订单']._images)==2
    assert len(wb['报表']._images)==2
    assert len(wb['长表格']._images)==1
    assert len(wb['新功能']._images)==1
    assert sum(len(s._images) for s in wb)==7
    for ws in wb:
        images=ws._images
        for left,right in zip(images,images[1:]):
            end=left.anchor._from.row+left.anchor.ext.cy/9525/20
            assert end<right.anchor._from.row
    with zipfile.ZipFile(ROOT/'result.xlsx') as z:
        assert len([n for n in z.namelist() if n.startswith('xl/media/')])==7
    wb.close(); store2.lock.release(); store2.db.close()
    print('PASS: 状态切换、多标签快捷键、容器首尾与恢复、待分类记忆、失败补写、重启幂等、模板保留、7 张内嵌图片及不重叠')

if __name__=='__main__':
    server=subprocess.Popen([sys.executable,'examples/server.py'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        asyncio.run(main())
    finally:
        server.terminate(); server.wait()
