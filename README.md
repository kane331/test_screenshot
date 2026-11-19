# Web 手工测试截图归档工具

Python + Playwright + openpyxl，本地处理，不上传页面、账号、截图或 Excel。手工登录和判断测试结果；按快捷键保存当前标签页截图，自动分类并持续写入同一份 Excel。

## 安装

需要 Python 3.10+。在项目目录执行：

```bash
python -m venv .venv
# Linux / macOS
source .venv/bin/activate
# Windows PowerShell 使用：.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m playwright install chromium
# Linux 若缺系统库：python -m playwright install --with-deps chromium
```

## 启动与手工登录

```bash
webarchive --output ./output/本轮测试.xlsx --config examples/config.json --profile .browser-profile --url http://127.0.0.1:8765/orders
```

默认打开独立的 Chromium 持久浏览器。在这个窗口手工登录、打开多个标签、操作业务；下次使用同一个 `--profile` 会保留登录会话。用已安装的 Chrome 加 `--channel chrome`，Edge 加 `--channel msedge`。不要让两个进程同时使用同一个 profile。

基于模板启动新一轮：

```bash
webarchive --output ./output/第二轮.xlsx --template ./模板.xlsx --config examples/config.json
```

模板不会被修改，输出和模板必须不同。普通 .xlsx 的单元格、格式和图片由 openpyxl 保留；复杂 Excel 特性（如切片器、部分绘图对象）不保证保真。请使用模板副本先验收。

### 连接已经登录的浏览器

已有浏览器必须事先启用远程调试；无法接管普通方式启动的任意 Chrome/Edge。可先关闭专用测试实例，再这样启动并手工登录（按平台替换可执行文件路径）：

```bash
# Chrome，必须使用专用用户目录，不能指向日常默认用户目录
chrome --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 --user-data-dir=/绝对路径/test-chrome
# Edge 可将 chrome 换成 msedge
webarchive --output ./output/本轮测试.xlsx --config examples/config.json --cdp http://127.0.0.1:9222
```

直接复用该实例中已登录的标签页。只连接第一个默认浏览器上下文；不支持隐私窗口。调试端口仅供本机使用。CDP 模式退出工具不关闭浏览器。

## 使用快捷键

默认 **Ctrl+Shift+S**，焦点需要位于网页中（不在地址栏、开发者工具或跨域 iframe 内）。切换 Chrome/Edge 标签后按键，即截取触发按键的标签页；实现不依赖标签创建顺序。

1. 操作到要留证的页面状态，按一次快捷键。
2. **等待“截图完成”后再切页或继续改变页面**。普通页面尽早调用全页截图；内部滚动区需要逐段滚动，此时不要交互。Excel 写入会在截图后进行。
3. 浏览器提示及终端会显示归类、完整性和“Excel 已更新：Sheet，第 N 张”。可继续操作。
4. 未匹配时 PNG 和待分类记录先落盘，弹窗输入 Sheet 名称会记住当前域名与精确路径规则，并将本次截图归入目标 Sheet。取消则保留到“待分类”。浏览器若抑制 prompt，可退出后用下面的命令行方式处理。
5. 结束后 Ctrl+C，直接打开输出 .xlsx，图片已内嵌，无需导出或附带 PNG。

配置快捷键，保存后重启工具：

```json
"hotkey": {"code": "KeyS", "ctrl": true, "shift": true, "alt": false}
```

`code` 是浏览器 KeyboardEvent.code，如 `KeyP`、`F8`；修饰键必须精确匹配，避免使用浏览器/系统保留键。本工具不注册全局系统快捷键。网页禁止脚本、PDF、浏览器设置页、Chrome 内置页不支持。

## 页面分类配置

`examples/config.json` 是可直接运行的配置。`rules` 中每条规则包含 `path`（URL 路径正则）和 `sheet`，可加：

| 字段 | 用途 |
| --- | --- |
| `origin` | 限定 URL 的 host:port（字段不含协议） |
| `title` | 页面标题正则 |
| `selector` | CSS 特征元素，必须可见 |
| `dialog_title` | 可见 role=dialog 弹窗内的文本正则 |
| `name` | 写入 Excel 的页面名称；默认使用标题 |
| `container` | 唯一的内部滚动容器 CSS 选择器 |
| `static_content` | 只有确认内容已完整加载、无虚拟渲染时设为 true |
| `partial` | 强制标记部分截图 |
| `priority` | 相同具体程度时的优先级整数 |

规则条件全部满足才匹配。先比较 title/selector/dialog_title/origin 条件数，再比较 path 表达式长度，再比较 priority，最后按配置顺序。更具体规则优先。相同 URL 的状态既可以进入同一 Sheet，也可以指定不同 Sheet。更改配置后重启。

### 内部滚动容器

```json
{"path":"^/table$","sheet":"长表格","container":"#rows","static_content":true}
```

工具把容器滚到顶部，按可视高度分段截图、裁去末段重复区域，再拼接为完整容器 PNG；恢复容器横纵滚动位置及页面滚动位置。容器截图只包含容器内容，页面名称、时间、URL 另外记录在 Excel。容器须唯一匹配且完整放入视口，必要时调整窗口或浏览器缩放。当前只拼接纵向内容；横向溢出明确标记部分截图。

虚拟列表会回收 DOM，懒加载可能边滚边增加内容，无法保证复原按键瞬间的全部数据。未声明静态内容、检测到虚拟列表标记/懒加载图片、内容高度变化或中途切页时，Excel 与终端明确标记“部分截图”。无已完成片段时提示失败；已有片段则保留部分 PNG。`static_content` 是使用者对页面数据机制的确认，不应为消除提示而盲目开启。Canvas、异步后台刷新、未标记的自定义虚拟组件仍需人工检查。

## 文件与恢复

例如输出 `output/本轮测试.xlsx`：

- `output/本轮测试.xlsx`：每次成功截图后自动更新，图片等比缩至最多 960 像素宽，按顺序纵向排列。
- `output/本轮测试.archive/*.png`：原始截图。
- 同目录 `journal.sqlite`：持久截图记录及分类。
- 同目录 `baseline.xlsx`：本轮开始时的模板或已有工作簿快照。
- 工作簿隐藏的 `_截图索引`：截图 ID、时间、路径及完整性，可在 Excel 中取消隐藏查看。

Excel 被占用、发现 `~$文件名.xlsx` 锁文件或写入异常时提示 **“截图已保存，Excel 待更新”**。关闭 Excel 后，工具每 5 秒自动重试；也可退出后执行：

```bash
webarchive --output ./output/本轮测试.xlsx --config examples/config.json --retry
```

同一路径重启会恢复同一轮；新一轮请换输出路径。以 SQLite 唯一截图 ID 为记录源，每次从 baseline 重建，再原子替换输出；连续重试或替换后崩溃不会重复插图。单轮有进程锁，避免两个工具同时覆盖。失败时原 Excel 不被截断。

运行期间不要手工编辑输出 Excel，因为下次生成会覆盖本轮开始后在 Excel 内的手工改动。请完整保留 `.archive` 文件夹用于恢复；最终分享时只需分享 `.xlsx`。已有输出在首次启动时作为 baseline，原内容保留；后续必须连同本轮 journal 使用。不要删除 journal 后把本轮输出当作新一轮继续。

手工重新分类（先退出运行中的工具；ID 可从终端或隐藏索引读取）：

```bash
python -m webarchive.classify --output ./output/本轮测试.xlsx --config examples/config.json --id 截图ID --sheet 新功能
```

该命令记住域名和精确路径规则，移动本次截图并重建 Excel。写入失败后同样可用 `--retry` 补写。

## 本地演示与验证

```bash
# 第一个终端
python examples/server.py
# 第二个终端
webarchive --output ./output/demo.xlsx --url http://127.0.0.1:8765/orders
# 自动验收（真实 Chromium，按键通过 Playwright keyboard 发送）
python tests/verify.py
```

实际自动验收覆盖：同页面两种状态按键截图并按序进入订单 Sheet；切到另一个标签后归入报表；4000 像素内部表格首尾像素验证、滚动位置恢复至 777；未知页面先落盘再弹窗分类与规则记忆；模拟原子替换 PermissionError 后重试、重启均只插一次；模板字节未改、模板单元格保留；虚拟列表被标记部分截图；7 张图确实位于 xlsx 的 xl/media，锚点不重叠。

另外实测了命令行重新分类（总图片数不变）、`--retry` 恢复命令，并用 LibreOffice 无界面打开输出工作簿、生成 PDF、查看渲染预览；未在桌面版 Microsoft Excel 中人工打开检查。

验收输出保存在 `verification/result.xlsx`。自动验收使用 Chromium headless，未实测用户机器的 Chrome/Edge 热键冲突、真实 Windows Excel 文件锁、企业 SSO、跨域 iframe 内焦点、复杂固定表头/浮层、特殊虚拟组件、超大图片内存和真实业务页面。工具不会自动判断业务测试是否通过。截图期间页面持续变化时，也不能承诺所有像素属于按键的同一瞬间。
