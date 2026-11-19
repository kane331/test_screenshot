import argparse
import asyncio
import io
import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from PIL import Image
from playwright.async_api import async_playwright
from .store import Store, sheet_name

SCRIPT = r'''(hotkey) => {
 if(window.top!==window || window.__archiveInstalled) return;
 window.__archiveInstalled=true;
 window.__archiveNotice=(message)=>{
   let el=document.getElementById('__archive_notice'); if(el) el.remove();
   el=document.createElement('div'); el.id='__archive_notice'; el.textContent=message;
   el.style='position:fixed;right:15px;top:15px;background:#17324d;color:white;padding:16px;z-index:2147483647;max-width:600px;white-space:pre-wrap';
   document.documentElement.append(el); setTimeout(()=>el.remove(),10000);
 };
 document.addEventListener('keydown',e=>{
   if(e.code===hotkey.code && e.ctrlKey===!!hotkey.ctrl && e.shiftKey===!!hotkey.shift && e.altKey===!!hotkey.alt && !e.repeat){
     e.preventDefault(); e.stopImmediatePropagation();
     window.__archiveCapture({url:location.href,title:document.title,time:new Date().toISOString()});
   }
 },true);
}'''


class Recorder:
    def __init__(self, store, config, config_path):
        self.store, self.config, self.config_path = store, config, Path(config_path)
        self.busy = set()
        self.write_lock = asyncio.Lock()
        self.pending = {}

    async def notice(self, page, message):
        print(message, flush=True)
        try:
            await page.evaluate('(m)=>window.__archiveNotice?.(m)', message)
        except Exception:
            pass

    async def rule(self, page, meta):
        candidates = []
        for i, rule in enumerate(self.config.get('rules', [])):
            if not re.search(rule.get('path', '.*'), urlsplit(meta['url']).path):
                continue
            if rule.get('origin') and rule['origin'] != urlsplit(meta['url']).netloc:
                continue
            if rule.get('title') and not re.search(rule['title'], meta['title']):
                continue
            if rule.get('selector') and not await page.locator(rule['selector']).first.is_visible():
                continue
            if rule.get('dialog_title') and not await page.get_by_role('dialog').filter(has_text=re.compile(rule['dialog_title'])).first.is_visible():
                continue
            score = (sum(k in rule for k in ('title','selector','dialog_title','origin')), len(rule.get('path','')), rule.get('priority',0), -i)
            candidates.append((score, rule))
        return max(candidates, key=lambda x:x[0])[1] if candidates else {}

    async def capture(self, source, meta):
        page = source['page']
        if page in self.busy:
            await self.notice(page, '截图进行中，请等待完成后再按快捷键')
            return
        self.busy.add(page)
        capture_id = uuid.uuid4().hex
        png = self.store.root / (capture_id + '.png')
        status = '完整截图（静态页面范围）'
        pieces = []
        changed = False
        def navigated(frame):
            nonlocal changed
            if frame == page.main_frame:
                changed = True
        page.on('framenavigated', navigated)
        async def check():
            if changed or page.url != meta['url'] or not await page.evaluate('document.visibilityState === "visible"'):
                raise RuntimeError('捕获期间切换标签页或导航')
        try:
            await page.evaluate('document.getElementById("__archive_notice")?.remove()')
            rule = await self.rule(page, meta)
            await check()
            risky = await page.locator('[aria-rowcount], [class*="virtual"], [class*="Virtual"], img[loading="lazy"], [data-lazy]').count()
            if risky or rule.get('partial'):
                status = '部分截图：检测到虚拟列表/懒加载或配置标记，完整性无法确认'
            selector = rule.get('container')
            if selector:
                loc = page.locator(selector)
                if await loc.count() != 1:
                    raise ValueError('滚动容器必须唯一匹配')
                window_scroll = await page.evaluate('({x:scrollX,y:scrollY})')
                original = await loc.evaluate('(e)=>({top:e.scrollTop,left:e.scrollLeft,height:e.scrollHeight,width:e.scrollWidth,client:e.clientHeight,cw:e.clientWidth})')
                if not rule.get('static_content') or original['width'] > original['cw']:
                    status = '部分截图：容器完整性未确认或存在横向滚动'
                try:
                    await loc.scroll_into_view_if_needed()
                    await loc.evaluate('(e)=>e.scrollLeft=0')
                    offset = 0
                    while offset < original['height']:
                        await check()
                        actual = await loc.evaluate('(e,y)=>{e.scrollTop=y;return e.scrollTop}', offset)
                        await page.wait_for_timeout(100)
                        await check()
                        box = await loc.bounding_box()
                        if not box:
                            raise RuntimeError('容器消失')
                        metrics = await loc.evaluate('(e)=>({x:e.clientLeft,y:e.clientTop,w:e.clientWidth,h:e.clientHeight,sh:e.scrollHeight})')
                        if metrics['sh'] != original['height']:
                            status = '部分截图：滚动时内容高度变化（可能懒加载）'
                        viewport = await page.evaluate('({w:innerWidth,h:innerHeight})')
                        if box['y'] + metrics['y'] < 0 or box['y'] + metrics['y'] + metrics['h'] > viewport['h'] or box['x'] + metrics['x'] + metrics['w'] > viewport['w']:
                            raise RuntimeError('容器未完全位于视口内，请调整窗口或缩放')
                        data = await page.screenshot(clip={'x':box['x']+metrics['x'],'y':box['y']+metrics['y'],'width':metrics['w'],'height':metrics['h']}, scale='css')
                        piece = Image.open(io.BytesIO(data)).convert('RGB')
                        skip = max(0, offset - actual)
                        take = min(piece.height - skip, original['height'] - offset)
                        if take <= 0 or len(pieces) >= 200:
                            raise RuntimeError('滚动无法前进或超过 200 段限制')
                        pieces.append(piece.crop((0,skip,piece.width,skip+take)))
                        offset += take
                finally:
                    await loc.evaluate('(e,p)=>{e.scrollTop=p.top;e.scrollLeft=p.left}', original)
                    await page.evaluate('(p)=>window.scrollTo(p.x,p.y)', window_scroll)
            else:
                data = await page.screenshot(full_page=True, scale='css')
                pieces.append(Image.open(io.BytesIO(data)).convert('RGB'))
                await check()
            if not rule.get('static_content') and not selector and not risky and not rule.get('partial'):
                status = '部分截图：已捕获页面全高，动态/懒加载内容完整性未经确认'
        except Exception as exc:
            if not pieces:
                await self.notice(page, f'截图失败：{exc}；请重新截图')
                return
            status = f'部分截图：捕获中断：{exc}'
        finally:
            page.remove_listener('framenavigated', navigated)
            self.busy.discard(page)
        canvas = Image.new('RGB', (max(p.width for p in pieces), sum(p.height for p in pieces)), 'white')
        y = 0
        for p in pieces:
            canvas.paste(p,(0,y)); y += p.height
        canvas.save(png)
        record = {'id':capture_id,'png':str(png),'time':meta['time'],'name':rule.get('name',meta['title']),'url':meta['url'],'sheet':rule.get('sheet','待分类'),'status':status}
        self.store.add(record)
        await self.notice(page, f"截图完成，已保存 PNG；归类：{record['sheet']}\n{status}\nID: {capture_id}")
        if record['sheet'] == '待分类':
            target = await page.evaluate('()=>prompt("截图已保存到待分类。输入目标 Sheet 并记住当前路径规则；取消则保留待分类：")')
            if target:
                try:
                    sheet_name(target)
                    self.config.setdefault('rules',[]).append({'path':'^'+re.escape(urlsplit(meta['url']).path)+'$','origin':urlsplit(meta['url']).netloc,'sheet':target})
                    tmp = self.config_path.with_suffix('.tmp')
                    tmp.write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')
                    tmp.replace(self.config_path)
                    self.store.classify(capture_id,target)
                    record['sheet'] = target
                except Exception as exc:
                    await self.notice(page,f'分类失败，截图仍保留：{exc}')
        await self.flush(page,record)

    async def flush(self, page=None, record=None):
        async with self.write_lock:
            try:
                counts = await asyncio.to_thread(self.store.flush)
                notifications = dict(self.pending)
                if record:
                    notifications[record['id']] = (page, record)
                records = self.store.records()
                for target_page, item in notifications.values():
                    ordinal = 0
                    for entry in records:
                        if entry['sheet'] == item['sheet']:
                            ordinal += 1
                        if entry['id'] == item['id']:
                            break
                    await self.notice(target_page, f"Excel 已更新：{item['sheet']}，第 {ordinal} 张；{item['status']}")
                self.pending.clear()
                return True
            except Exception as exc:
                if page:
                    if record:
                        self.pending[record['id']] = (page, record)
                    await self.notice(page,f'截图已保存，Excel 待更新：{exc}')
                else:
                    print(f'Excel 待更新：{exc}',flush=True)
                return False


async def run(args):
    store = Store(args.output,args.template)
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    recorder = Recorder(store,config,args.config)
    if args.retry:
        if not await recorder.flush():
            raise SystemExit(1)
        print(f'Excel 已更新：{store.output}（{len(store.records())} 张归档截图）')
        return
    async with async_playwright() as pw:
        browser = None
        if args.cdp:
            browser = await pw.chromium.connect_over_cdp(args.cdp)
            context = browser.contexts[0]
        else:
            context = await pw.chromium.launch_persistent_context(args.profile,headless=args.headless,channel=args.channel,viewport=None)
        await context.expose_binding('__archiveCapture',recorder.capture)
        script = '('+SCRIPT+')('+json.dumps(config.get('hotkey',{'code':'KeyS','ctrl':True,'shift':True}))+')'
        await context.add_init_script(script)
        for page in context.pages:
            await page.evaluate(script)
        if args.url:
            await (await context.new_page()).goto(args.url)
        print(f'就绪：{store.output}；默认 Ctrl+Shift+S；截图完成提示前请勿切页。Ctrl+C 退出。',flush=True)
        await recorder.flush()
        try:
            while True:
                await asyncio.sleep(5)
                await recorder.flush()
        finally:
            if not args.cdp:
                await context.close()


def main():
    parser = argparse.ArgumentParser(description='Web 手工测试截图归档')
    parser.add_argument('--output',required=True)
    parser.add_argument('--config',default='examples/config.json')
    parser.add_argument('--template')
    parser.add_argument('--profile',default='.browser-profile')
    parser.add_argument('--channel',choices=['chrome','msedge','chromium'])
    parser.add_argument('--cdp',help='已启用远程调试的浏览器地址')
    parser.add_argument('--url')
    parser.add_argument('--headless',action='store_true')
    parser.add_argument('--retry',action='store_true')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        print('已退出；PNG 与记录保留，可用同一输出路径重启恢复。')

if __name__ == '__main__':
    main()
