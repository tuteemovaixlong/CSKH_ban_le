/**
 * RetailOps Embeddable LiveChat Widget (v1.0)
 * Allows any merchant website to embed the AI Customer Care agent via a single script tag:
 * <script src="https://retailops.example.com/embed.js" data-shop="retailops-demo" defer></script>
 */
(function () {
  'use strict';

  if (document.getElementById('retailops-widget-root')) return;

  const CSS = `
    #retailops-widget-root {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 999999;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    }
    #retailops-bubble-btn {
      width: 58px;
      height: 58px;
      border-radius: 50%;
      background: linear-gradient(135deg, #4f46e5, #6366f1);
      box-shadow: 0 8px 24px rgba(79, 70, 229, 0.45);
      border: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #ffffff;
      transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1), box-shadow 0.2s ease;
    }
    #retailops-bubble-btn:hover {
      transform: scale(1.08);
      box-shadow: 0 12px 28px rgba(79, 70, 229, 0.6);
    }
    #retailops-bubble-btn svg {
      width: 28px;
      height: 28px;
      fill: currentColor;
    }
    #retailops-widget-window {
      position: fixed;
      bottom: 96px;
      right: 24px;
      width: 380px;
      height: 560px;
      max-width: calc(100vw - 48px);
      max-height: calc(100vh - 120px);
      background: #111827;
      border: 1px solid #374151;
      border-radius: 16px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6);
      display: none;
      flex-direction: column;
      overflow: hidden;
      animation: ro-slide-up 0.25s ease-out;
    }
    @keyframes ro-slide-up {
      from { opacity: 0; transform: translateY(16px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .ro-header {
      background: #1f2937;
      padding: 14px 18px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #374151;
    }
    .ro-header-title {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .ro-avatar {
      width: 34px;
      height: 34px;
      border-radius: 50%;
      background: #4f46e5;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-weight: bold;
      font-size: 15px;
    }
    .ro-title-text strong {
      display: block;
      color: #f9fafb;
      font-size: 14px;
    }
    .ro-title-text small {
      color: #10b981;
      font-size: 12px;
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .ro-title-text small::before {
      content: '';
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: #10b981;
      display: inline-block;
    }
    .ro-close-btn {
      background: transparent;
      border: none;
      color: #9ca3af;
      cursor: pointer;
      font-size: 20px;
      line-height: 1;
      padding: 4px;
    }
    .ro-close-btn:hover { color: #fff; }
    .ro-messages {
      flex: 1;
      padding: 16px;
      overflow-y: auto;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .ro-msg {
      max-width: 85%;
      padding: 10px 14px;
      border-radius: 12px;
      font-size: 13.5px;
      line-height: 1.5;
      word-break: break-word;
    }
    .ro-msg-bot {
      background: #1f2937;
      color: #f3f4f6;
      border: 1px solid #374151;
      align-self: flex-start;
      border-bottom-left-radius: 4px;
    }
    .ro-msg-user {
      background: #4f46e5;
      color: #ffffff;
      align-self: flex-end;
      border-bottom-right-radius: 4px;
    }
    .ro-quick-bar {
      padding: 8px 12px;
      display: flex;
      gap: 6px;
      overflow-x: auto;
      background: #182234;
      border-top: 1px solid #2d3748;
    }
    .ro-chip {
      white-space: nowrap;
      background: #2d3748;
      color: #cbd5e1;
      border: 1px solid #4a5568;
      border-radius: 14px;
      padding: 4px 10px;
      font-size: 11.5px;
      cursor: pointer;
      transition: background 0.15s;
    }
    .ro-chip:hover {
      background: #4f46e5;
      color: #fff;
      border-color: #6366f1;
    }
    .ro-input-area {
      padding: 12px;
      background: #1f2937;
      border-top: 1px solid #374151;
      display: flex;
      gap: 8px;
    }
    .ro-input {
      flex: 1;
      background: #111827;
      border: 1px solid #4b5563;
      border-radius: 8px;
      padding: 8px 12px;
      color: #f9fafb;
      font-size: 13px;
      outline: none;
    }
    .ro-input:focus { border-color: #6366f1; }
    .ro-send-btn {
      background: #4f46e5;
      color: #fff;
      border: none;
      border-radius: 8px;
      padding: 0 14px;
      cursor: pointer;
      font-weight: 600;
      font-size: 13px;
    }
    .ro-send-btn:disabled { opacity: 0.5; cursor: not-allowed; }
  `;

  // Inject CSS
  const style = document.createElement('style');
  style.textContent = CSS;
  document.head.appendChild(style);

  // Build DOM Root
  const root = document.createElement('div');
  root.id = 'retailops-widget-root';

  // Bubble Button
  const bubble = document.createElement('button');
  bubble.id = 'retailops-bubble-btn';
  bubble.setAttribute('aria-label', 'Mở trợ lý CSKH RetailOps');
  bubble.innerHTML = `
    <svg viewBox="0 0 24 24">
      <path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8z"/>
    </svg>
  `;

  // Chat Window
  const win = document.createElement('div');
  win.id = 'retailops-widget-window';
  win.innerHTML = `
    <div class="ro-header">
      <div class="ro-header-title">
        <div class="ro-avatar">R</div>
        <div class="ro-title-text">
          <strong>RetailOps AI Care</strong>
          <small>Trực tuyến 24/7 · Sẵn sàng</small>
        </div>
      </div>
      <button class="ro-close-btn" id="ro-close-btn" aria-label="Đóng">&times;</button>
    </div>
    <div class="ro-messages" id="ro-messages">
      <div class="ro-msg ro-msg-bot">Xin chào! Em là trợ lý AI của shop. Em có thể hỗ trợ anh/chị tra cứu đơn hàng, kiểm tra hành trình vận chuyển hoặc giải đáp chính sách ạ.</div>
    </div>
    <div class="ro-quick-bar">
      <button class="ro-chip" data-text="Tra cứu đơn hàng O-101">📦 Đơn O-101</button>
      <button class="ro-chip" data-text="Hành trình vận chuyển đơn O-101">🚚 Vận đơn GHTK</button>
      <button class="ro-chip" data-text="Chính sách đổi trả hàng">🔄 Đổi trả 7 ngày</button>
      <button class="ro-chip" data-text="Tôi muốn gặp nhân viên tư vấn">🙋 Gặp nhân viên</button>
    </div>
    <form class="ro-input-area" id="ro-form">
      <input class="ro-input" id="ro-input" type="text" placeholder="Nhập tin nhắn..." autocomplete="off" required>
      <button class="ro-send-btn" id="ro-send" type="submit">Gửi</button>
    </form>
  `;

  root.appendChild(win);
  root.appendChild(bubble);
  document.body.appendChild(root);

  // Widget Interaction Logic
  const msgBox = win.querySelector('#ro-messages');
  const input = win.querySelector('#ro-input');
  const form = win.querySelector('#ro-form');
  const closeBtn = win.querySelector('#ro-close-btn');

  function toggle() {
    const isHidden = win.style.display === '' || win.style.display === 'none';
    win.style.display = isHidden ? 'flex' : 'none';
    if (isHidden) input.focus();
  }

  bubble.onclick = toggle;
  closeBtn.onclick = () => { win.style.display = 'none'; };

  function appendMsg(text, isUser = false) {
    const msg = document.createElement('div');
    msg.className = 'ro-msg ' + (isUser ? 'ro-msg-user' : 'ro-msg-bot');
    msg.textContent = text;
    msgBox.appendChild(msg);
    msgBox.scrollTop = msgBox.scrollHeight;
  }

  async function handleSend(text) {
    if (!text || !text.trim()) return;
    appendMsg(text, true);
    input.value = '';

    // Typing indicator
    const typing = document.createElement('div');
    typing.className = 'ro-msg ro-msg-bot';
    typing.textContent = '...';
    msgBox.appendChild(typing);
    msgBox.scrollTop = msgBox.scrollHeight;

    try {
      // Connect to standard RetailOps chat API if on same origin or use fallback
      let resText = 'Em đã ghi nhận yêu cầu của anh/chị ạ.';
      if (window.api && typeof window.api === 'function') {
        const res = await window.api('/api/chat', {
          conversation_id: window.conversationId || undefined,
          text: text,
          request_id: 'embed_' + Math.random().toString(36).substring(2, 18)
        });
        resText = res.message || resText;
      } else {
        // Standalone widget demo simulation
        if (/đơn|o-101|o-102/i.test(text)) {
          resText = 'Đơn hàng O-101 của bạn hiện đang trên xe trung chuyển GHTK tới bưu cục Tân Bình. Dự kiến giao ngày mai trước 17:00 ạ.';
        } else if (/đổi trả|chính sách/i.test(text)) {
          resText = '⚡ (Cache Hit 0ms): Quý khách được đổi trả hàng trong vòng 7 ngày kể từ ngày nhận hàng với sản phẩm còn nguyên tem mác ạ.';
        } else if (/nhân viên|gặp người|hỗ trợ viên/i.test(text)) {
          resText = '🙋 Đã chuyển tiếp yêu cầu đến Chuyên viên CSKH Nguyễn Mai Anh. Bạn đợi trong 30 giây nhân viên sẽ vào hỗ trợ trực tiếp nhé!';
        }
      }
      typing.textContent = resText;
    } catch (err) {
      typing.textContent = 'Hệ thống đã nhận yêu cầu. Cảm ơn quý khách!';
    }
    msgBox.scrollTop = msgBox.scrollHeight;
  }

  form.onsubmit = function (e) {
    e.preventDefault();
    handleSend(input.value);
  };

  win.querySelectorAll('.ro-chip').forEach(function (btn) {
    btn.onclick = function () {
      handleSend(this.dataset.text);
    };
  });
})();
