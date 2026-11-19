from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        body = '<h1>未配置页面 UNKNOWN</h1>'
        if path == '/orders':
            body = '''<h1 id="state">订单待审核 STATE-A</h1><button onclick="document.title='已审核';document.querySelector('h1').textContent='订单已审核 STATE-B'">切换状态</button><div style="height:1500px;background:linear-gradient(white,lightblue)">订单长页面</div><h2>订单底部 END</h2>'''
        elif path == '/reports':
            body = '<h1>REPORT CURRENT TAB</h1><div style="height:1000px;background:lightgreen">统计报表</div><h2>REPORT END</h2>'
        elif path == '/table':
            body = '<h1>内部滚动表格</h1><div id="rows" style="height:350px;width:750px;overflow:auto;border:2px solid black">'+''.join(f'<div style="height:50px;background:rgb({i%200},220,240)">ROW {i:03d} '+('TOP' if i==0 else 'BOTTOM' if i==79 else '')+'</div>' for i in range(80))+'</div>'
        elif path == '/virtual':
            body = '<h1>虚拟列表示例</h1><div class="virtual-list" aria-rowcount="1000">仅渲染 10 行</div>'
        html = '<!doctype html><meta charset="utf-8"><title>测试页面</title><style>body{font:20px sans-serif}</style><nav><a href="/orders">订单</a> <a href="/reports" target="_blank">报表新标签</a> <a href="/table">表格</a> <a href="/unknown">未知</a></nav>'+body
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers(); self.wfile.write(html.encode())

if __name__ == '__main__':
    HTTPServer(('127.0.0.1',8765),Handler).serve_forever()
