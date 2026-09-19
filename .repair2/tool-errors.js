  const toolErrors = {
    order_not_found: 'kh\u00f4ng t\u00ecm th\u1ea5y trong t\u00e0i kho\u1ea3n',
    tool_not_allowed: 'ngo\u00e0i ph\u1ea1m vi worker; kh\u00f4ng th\u1ef1c thi',
    invalid_tool_arguments: 'tham s\u1ed1 kh\u00f4ng h\u1ee3p l\u1ec7',
    product_not_found: 'ch\u01b0a t\u00ecm th\u1ea5y trong danh m\u1ee5c',
    permission_denied: 'kh\u00f4ng \u0111\u1ee7 quy\u1ec1n',
    tool_unavailable: 'ngu\u1ed3n d\u1eef li\u1ec7u ch\u01b0a s\u1eb5n s\u00e0ng'
  };
  const names = (trace.tools || []).map(t => t.name + (t.status === 'error'
    ? ' (' + (toolErrors[t.error_code] || 'b\u1ecb t\u1eeb ch\u1ed1i / l\u1ed7i') + ')' : ''));
