"""One-time PR14 source repair; removed from the resulting verified tree."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    file = ROOT / path
    text = file.read_text(encoding='utf-8')
    if text.count(old) != 1:
        raise RuntimeError('Unexpected source: ' + path + ' (' + old[:60] + ')')
    file.write_text(text.replace(old, new), encoding='utf-8')


replace('web/index.html',
    '<div class="model-status"><span class="status-indicator"></span><div><strong>Model chưa kết nối</strong><span>Các nút tra đơn vẫn hoạt động</span></div></div>',
    '<div class="model-status" role="status" aria-live="polite"><span class="status-indicator" aria-hidden="true"></span><div class="model-status-copy"><strong id="model-status-title">Model chưa kết nối</strong><span id="model-status-detail">Các nút tra đơn vẫn hoạt động</span></div></div>')

replace('web/app.js', 'function renderProvider() {', '''function setModelStatus(title, detail) {
  const titleNode = byId('model-status-title'), detailNode = byId('model-status-detail');
  titleNode.textContent = title; titleNode.title = title;
  detailNode.textContent = detail; detailNode.title = detail;
}
function renderProvider() {''')

replace('web/app.js',
    '''  document.querySelector('.model-status strong').textContent = provider?.configured ? 'Đã chọn nguồn model' : 'Model chưa sẵn sàng';
  document.querySelector('.model-status div span').textContent = provider?.label || 'Có thể dùng các nút tra đơn';''',
    '''  setModelStatus(provider?.configured ? 'Đã chọn nguồn model' : 'Model chưa sẵn sàng',
    provider?.label || 'Có thể dùng các nút tra đơn');''')

replace('web/app.js',
    '''  const status = document.querySelector('.model-status');
  status.querySelector('strong').textContent = 'Model đang xử lý…';
  status.querySelector('div span').textContent = 'Đang đọc hội thoại và gọi công cụ khi cần';''',
    "  setModelStatus('Model đang xử lý…', 'Đang đọc hội thoại và gọi công cụ khi cần');")

replace('web/app.js',
    '''    status.querySelector('strong').textContent = 'Chat chưa hoàn tất';
    status.querySelector('div span').textContent = 'Có thể thử lại hoặc dùng các nút thao tác';''',
    "    setModelStatus('Chat chưa hoàn tất', 'Có thể thử lại hoặc dùng các nút thao tác');")

replace('web/app.js',
    '''  status.querySelector('strong').textContent = 'Model vừa phản hồi';
  status.querySelector('div span').textContent = 'Xem công cụ và thời gian bên dưới câu trả lời';''',
    '''  setModelStatus(result.replayed ? 'Kết quả đã lưu' : 'Đã phản hồi',
    selectedProvider()?.label || 'Model đã chọn');''')

replace('web/app.js', 'if (!b.disabled) { b.dataset.busyDisabled',
    'if (!b.disabled && !b.dataset.layoutControl) { b.dataset.busyDisabled')
replace('web/app.js', "'Chi tiết lượt trả lời' + (replayed",
    "'Công cụ & thời gian' + (replayed")

for path in ('retailops/http/public.py', 'retailops/http/private.py'):
    replace(path, 'from retailops.http.routes import api_result',
            'from retailops.http.routes import api_result\nfrom retailops.http.assets import ASSETS')

replace('retailops/http/public.py',
    '''        assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
        if method == 'GET' and path in assets:
            name, mime = assets[path]''',
    '''        if method == 'GET' and path in ASSETS:
            name, mime = ASSETS[path]''')

replace('retailops/http/private.py',
    '''        assets = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8")}
        if self.command == "GET" and path in assets:
            name, mime = assets[path]''',
    '''        if self.command == "GET" and path in ASSETS:
            name, mime = ASSETS[path]''')

replace('.github/workflows/ci.yml', '          node --check web/app.js',
    '''          for file in web/*.js; do node --check "$file"; done
          node tests/test_chat_focus.js
          node tests/test_model_status.js''')

replace('scripts/check_public_https.py',
    "            assert request('/healthz')[1]['hosting'] == 'public-https'",
    '''            assert request('/healthz')[1]['hosting'] == 'public-https'
            for asset in ('app.js', 'styles.css', 'chat-focus.js', 'chat-focus.css'):
                actual = run(curl + ['--fail', 'https://' + HOST + '/' + asset])
                assert actual == (ROOT/'web'/asset).read_text(), asset
            print('PUBLIC_UI_ASSETS_OK (four same-origin assets through Caddy)')''')

print('PR14_SOURCE_REPAIR_OK')
