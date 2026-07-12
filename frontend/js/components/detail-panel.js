// ================================================================
// Detail Panel — slide-out card detail view
// ================================================================

const DetailPanel = {
  overlay: null,
  panel: null,
  body: null,
  title: null,

  init() {
    this.overlay = document.getElementById('detail-overlay');
    this.panel = document.getElementById('detail-panel');
    this.body = document.getElementById('detail-body');
    this.title = document.getElementById('detail-title');
  },

  open(card) {
    if (!card) return;

    this.title.textContent = card.display_name || card.name || '预览与判断';

    let html = '';

    // Preview
    if (card.preview_url) {
      html += `<div class="detail-preview"><img src="${esc(card.preview_url)}" alt=""></div>`;
    }

    // Status badges
    const badges = [];
    if (card.suggested_type) {
      badges.push(`<span class="chip chip-type">${TYPE_LABELS[card.suggested_type] || card.suggested_type}</span>`);
    }
    if (card.needs_human_review) {
      badges.push(`<span class="chip chip-status">需人工确认</span>`);
    }
    if (badges.length > 0) {
      html += `<div style="display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap">${badges.join('')}</div>`;
    }

    // Info table
    html += '<table class="detail-table">';
    if (card.name) html += `<tr><td>名称</td><td>${esc(card.name)}</td></tr>`;
    if (card.source_path) html += `<tr><td>来源路径</td><td style="font-size:0.78rem;word-break:break-all">${esc(card.source_path)}</td></tr>`;
    if (card.total_files !== undefined) html += `<tr><td>文件数</td><td>${card.total_files}</td></tr>`;
    if (card.total_bytes !== undefined) html += `<tr><td>大小</td><td>${fmtSize(card.total_bytes)}</td></tr>`;
    if (card.total_dirs !== undefined) html += `<tr><td>子目录数</td><td>${card.total_dirs}</td></tr>`;
    if (card.suggested_type) html += `<tr><td>类型判断</td><td>${TYPE_LABELS[card.suggested_type] || card.suggested_type}</td></tr>`;
    if (card.confidence) html += `<tr><td>置信度</td><td>${card.confidence}</td></tr>`;
    if (card.target_path) html += `<tr><td>目标分类</td><td>${esc(card.target_path)}</td></tr>`;
    if (card.translated_name) html += `<tr><td>建议译名</td><td>${esc(card.translated_name)}</td></tr>`;
    html += '</table>';

    // Review reason
    if (card.review_reason) {
      html += `<div class="detail-section"><h3>需要确认的原因</h3><p>${esc(card.review_reason)}</p></div>`;
    }

    // Extensions summary
    if (card.extensions) {
      const exts = typeof card.extensions === 'object' ? Object.entries(card.extensions).slice(0, 8).map(([k,v]) => `${k} (${v})`).join(' &middot; ') : '';
      if (exts) html += `<div class="detail-section"><h3>文件格式</h3><p style="font-size:0.78rem">${exts}</p></div>`;
    }

    // Tags
    if (card.manual_tags && card.manual_tags.length > 0) {
      html += `<div class="detail-section"><h3>标签</h3><div style="display:flex;gap:4px;flex-wrap:wrap">${card.manual_tags.map(t => `<span class="chip chip-tag">${esc(t)}</span>`).join('')}</div></div>`;
    }

    this.body.innerHTML = html;
    this._show();
  },

  _show() {
    this.overlay.classList.add('visible');
    this.panel.classList.add('open');
  },

  close() {
    this.overlay.classList.remove('visible');
    this.panel.classList.remove('open');
  },
};

function closeDetail() {
  DetailPanel.close();
}
