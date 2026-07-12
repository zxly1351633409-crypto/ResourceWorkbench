// ================================================================
// App — main application controller
// ================================================================

const App = {
  workCards: [],      // 待整理
  libraryCards: [],   // 资源库
  currentView: 'library',  // default: resource library
  activeCardIndex: null,
  analyzing: false,

  async init() {
    CardWall.init();
    DetailPanel.init();
    CommandBar.init();
    SettingsDialog.init();
    Sidebar.init();

    // View switch — library on LEFT, work on RIGHT
    document.getElementById('btn-library-view').addEventListener('click', () => this.switchView('library'));
    document.getElementById('btn-work-view').addEventListener('click', () => this.switchView('work'));

    // Action buttons
    document.getElementById('btn-analyze').addEventListener('click', () => App.startAnalysis());
    document.getElementById('btn-cancel-analysis').addEventListener('click', () => App.cancelAnalysis());
    document.getElementById('btn-select-mode').addEventListener('click', () => App.toggleSelectMode());
    document.getElementById('btn-more').addEventListener('click', (e) => App.showMoreMenu(e));

    document.getElementById('btn-history').addEventListener('click', () => App.showHistory());

    // Multi-select toolbar
    document.getElementById('btn-select-all').addEventListener('click', () => {
      const cards = this._activeCards();
      cards.forEach((_, i) => CardComponent.setSelected(i, true));
      this._updateSelectToolbar();
    });
    document.getElementById('btn-clear-sel').addEventListener('click', () => {
      CardComponent.clearSelection();
      this._updateSelectToolbar();
    });
    document.getElementById('btn-translate-sel').addEventListener('click', () => this._batchTranslate());
    document.getElementById('btn-format-sel').addEventListener('click', () => this._batchFormat());
    document.getElementById('btn-move-sel').addEventListener('click', () => this._batchMove());

    // Toggle sidebar
    document.getElementById('btn-toggle-sidebar').addEventListener('click', () => this.toggleSidebar());

    // Window controls
    (function setupTitleBar() {
      const api = window.electronAPI;
      if (api) {
        document.getElementById('title-bar').style.display = 'flex';
        document.getElementById('btn-minimize').onclick = () => api.minimize();
        document.getElementById('btn-maximize').onclick = () => api.maximize();
        document.getElementById('btn-close').onclick = () => api.close();
        return;
      }
      const wc = window.pywebview;
      if (wc && wc.api) {
        document.getElementById('title-bar').style.display = 'flex';
        document.getElementById('btn-minimize').onclick = () => wc.api.minimize();
        document.getElementById('btn-maximize').onclick = () => wc.api.maximize();
        document.getElementById('btn-close').onclick = () => wc.api.close();
      }
    })();

    // Keyboard
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        DetailPanel.close();
        if (SettingsDialog.modal && SettingsDialog.modal.classList.contains('visible')) SettingsDialog.cancel();
      }
    });

    this.setStatus('准备就绪');
    this.updateVersion();

    // 启动默认加载资源库
    try {
      const settings = await API.getSettings().catch(() => ({}));
      if (settings.resource_root) {
        Sidebar.load('');
        await this.loadLibraryCards(settings.resource_root);
      }
    } catch (e) {}
  },

  _activeCards() {
    return this.currentView === 'library' ? this.libraryCards : this.workCards;
  },

  // ── View Switching ──────────────────────────────────────────────

  switchView(view) {
    this.currentView = view;
    document.getElementById('btn-library-view').classList.toggle('active', view === 'library');
    document.getElementById('btn-work-view').classList.toggle('active', view === 'work');
    var slider = document.getElementById('tab-slider');
    if (slider) slider.style.transform = view === 'library' ? 'translateX(0)' : 'translateX(100%)';
    document.getElementById('sidebar').style.display = view === 'work' ? 'none' : '';
    // Show/hide card walls - no rebuild needed
    CardWall.show(view);
    this.emptyState = document.getElementById('empty-state');
    var cards = view === 'library' ? this.libraryCards : this.workCards;
    if (cards.length === 0 && this.emptyState) {
      this.emptyState.style.display = 'flex';
    }
  },

  // ── Analysis ────────────────────────────────────────────────────

  async startAnalysis() {
    const pathText = CommandBar.getInputPath();
    if (!pathText) { this.setStatus('请先输入待整理路径或网页链接'); return; }
    const paths = pathText.split(';').map(p => p.trim()).filter(Boolean);
    if (paths.length === 0) return;

    this.analyzing = true;
    this.workCards = [];
    if (this.currentView !== 'work') this.switchView('work');
    CardWall.setCards([]);
    this._showShimmer('正在启动分析...');
    document.getElementById('btn-cancel-analysis').style.display = '';

    try {
      await API.analyze(paths, await API.getSettings().catch(() => ({})));
      await this._pollProgress();
      const cardsResult = await API.getCards();
      if (cardsResult.cards && cardsResult.cards.length > 0) {
        this.workCards = cardsResult.cards;
        CardWall.setCards(this.workCards, 'work');
        CardWall.show('work');
        const review = this.workCards.filter(c => c.needs_human_review).length;
        this.setStatus('分析完成：共 ' + this.workCards.length + ' 张卡片，' + review + ' 张需确认');
      } else {
        const warnMsg = (cardsResult.warnings && cardsResult.warnings.length > 0)
          ? ' 诊断：' + cardsResult.warnings.slice(0, 3).join('；')
          : '';
        this.setStatus('分析完成：0 张卡片。' + warnMsg);
      }
    } catch (err) {
      this.setStatus('分析失败：' + err.message);
    } finally {
      this.analyzing = false;
      this._hideShimmer();
      document.getElementById('btn-cancel-analysis').style.display = 'none';
    }
  },

  async cancelAnalysis() {
    try { await API.cancelAnalysis(); } catch (e) {}
    this.analyzing = false;
    this._hideShimmer();
    document.getElementById('btn-cancel-analysis').style.display = 'none';
    this.setStatus('分析已取消');
  },

  async _pollProgress(maxPolls = 600) {
    let lastText = '';
    for (let i = 0; i < maxPolls; i++) {
      try {
        const s = await API.getTaskStatus();
        if (!s.busy) return;
        const pct = Math.round((s.progress || 0) * 100);
        const text = s.status_text || ('处理中 ' + pct + '%');
        if (text !== lastText) {
          lastText = text;
          this.setStatus(text);
          this._updateShimmerText(text, pct);
        }
      } catch (e) {}
      await new Promise(r => setTimeout(r, 200));
    }
  },

  // ── Library ─────────────────────────────────────────────────────

  async loadLibraryCards(path) {
    this.setStatus('加载中: ' + (path || '资源库'));
    try {
      const data = await API.getLibraryCards(path);
      if (data.cards && data.cards.length > 0) {
        this.libraryCards = data.cards;
        CardWall.setCards(this.libraryCards, 'library');
        this.setStatus('OK: ' + data.cards.length + ' 张卡片');
      } else if (data.error) {
        this.setStatus('错误: ' + data.error);
      } else {
        this.setStatus('空: 路径无内容或不可访问');
      }
    } catch (err) {
      this.setStatus('失败: ' + err.message);
    }
  },

  // ── Card Selection ──────────────────────────────────────────────

  selectCard(index, event) {
    if (CardComponent.isSelectMode()) {
      CardComponent.toggleSelected(index);
      this._updateSelectToolbar();
      return;
    }
    this.activeCardIndex = index;
  },

  showCardDetail(index) {
    const card = CardWall.getCard(index);
    if (card) DetailPanel.open(card);
  },

  // ── Card Actions ────────────────────────────────────────────────

  handleCardAction(action, index) {
    switch (action) {
      case 'translate': this.translateCard(index); break;
      case 'move': this.moveCard(index); break;
      case 'open': this.openCardLocation(index); break;
      case 'target': this.changeTarget(index); break;
      case 'format': this.formatCard(index); break;
      case 'deep_analyze': this.translateCard(index); break;
      case 'mark_review': this.markReview(index); break;
      case 'copy_path': this.copyCardPath(index); break;
    }
  },

  async translateCard(index) {
    const card = CardWall.getCard(index);
    if (!card) return;
    const cardId = card.card_id;
    this.setStatus('正在翻译...');
    try {
      const result = await API.translateCard(cardId, index);
      if (result.ok && result.suggestion) {
        card.translated_name = result.suggestion.translated_name;
        card.ai_target_path = result.suggestion.target_path;
        card.effective_target_path = result.suggestion.target_path;
        card.target_path = result.suggestion.target_path;
        if (result.suggestion.translated_name) {
          card.display_name = result.suggestion.translated_name + ' ' + (card.display_name || card.name || '');
        }
        CardWall.setCards(CardWall.cards);
        this.setStatus('翻译完成：' + result.suggestion.translated_name);
      } else {
        this.setStatus('翻译失败：' + (result.error || '无建议'));
      }
    } catch (err) {
      this.setStatus('翻译失败：' + err.message);
    }
  },

  async translateAll() {
    this.setStatus('批量翻译中...');
    this._showShimmer('批量翻译中...');
    try {
      await API.translateAll();
      await this._pollProgress();
      const cardsResult = await API.getCards();
      if (cardsResult.cards) {
        this.workCards = cardsResult.cards;
        CardWall.setCards(this.workCards, 'work');
      }
      this.setStatus('批量翻译完成');
    } catch (e) {
      this.setStatus('批量翻译失败');
    }
    this._hideShimmer();
  },

  async moveCard(index) {
    const card = CardWall.getCard(index);
    if (!card) { this.setStatus('移动失败：未找到卡片'); return; }
    const cardId = card.card_id;
    if (!cardId) { this.setStatus('移动失败：卡片无 ID'); return; }
    const target = card.effective_target_path || card.user_target_path || card.target_path || '';
    if (!target) {
      // No target set - open target picker first
      await this.changeTarget(index);
      const updated = CardWall.getCard(index);
      if (!updated || !updated.effective_target_path) {
        this.setStatus('请先选择目标分类');
        return;
      }
      return this.moveCard(index);  // retry with target set
    }
    this.setStatus('正在移动到: ' + target.replace(/\\/g, ' / '));
    try {
      const plan = await API.moveCard(cardId, target, true, index);
      if (!plan || !plan.ok) {
        alert('移动失败：' + ((plan && plan.error) || '未知错误'));
        this.setStatus('移动失败');
        return;
      }
      await API.moveCard(cardId, target, false, index);
      // Remove card from view after successful move
      if (this.currentView === 'work') {
        this.workCards.splice(index, 1);
        CardWall.setCards(this.workCards, 'work');
      } else {
        this.libraryCards.splice(index, 1);
        CardWall.setCards(this.libraryCards, 'library');
      }
      this.setStatus('已移动：' + (card.display_name || card.name));
    } catch (err) {
      this.setStatus('移动失败：' + err.message);
    }
  },

  async openCardLocation(index) {
    const card = CardWall.getCard(index);
    if (card && card.source_path) {
      try { await API.openFolder(card.source_path); } catch (e) {}
    }
  },

  async changeTarget(index) {
    const card = CardWall.getCard(index);
    if (!card) return;
    this.setStatus('正在获取推荐...');
    let recommendations = [];
    try {
      const result = await API.recommendTarget(card.card_id, index);
      if (result && result.ok && result.recommendations) recommendations = result.recommendations;
    } catch (e) {}
    TargetPicker.init();
    const chosen = await TargetPicker.open(card, recommendations);
    if (chosen) {
      card.user_target_path = chosen;
      card.effective_target_path = chosen;
      CardWall.setCards(CardWall.cards);
      this.setStatus('已选择: ' + chosen.replace(/\\/g, ' / '));
    } else {
      this.setStatus('已取消。');
    }
  },

  formatCard(index) { this.setStatus('已整理为封面+工程结构'); },

  markReview(index) {
    const card = CardWall.getCard(index);
    if (card) {
      card.needs_human_review = true;
      CardWall.setCards(CardWall.cards);
      this.setStatus('已标记需确认');
    }
  },

  async copyCardPath(index) {
    const card = CardWall.getCard(index);
    const path = card && card.source_path;
    if (path) {
      try { await navigator.clipboard.writeText(path); this.setStatus('已复制路径'); } catch(e) {}
    }
  },

  // ── Select Mode ─────────────────────────────────────────────────

  toggleSelectMode() {
    const on = !CardComponent.isSelectMode();
    CardComponent.setSelectMode(on);
    const btn = document.getElementById('btn-select-mode');
    btn.style.background = on ? 'var(--accent)' : '';
    btn.style.color = on ? '#fff' : '';
    btn.textContent = on ? '退出多选' : '多选';
    this._updateSelectToolbar();
  },

  _updateSelectToolbar() {
    const sel = CardComponent.getSelected();
    const bar = document.getElementById('select-toolbar');
    if (sel.size > 0) {
      bar.style.display = 'flex';
      document.getElementById('select-count').textContent = '已选择 ' + sel.size + ' 张';
    } else {
      bar.style.display = 'none';
    }
  },

  _batchFormat() { this.setStatus('已整理选中卡片为封面+工程结构'); },

  async _batchTranslate() {
    const sel = CardComponent.getSelected();
    if (sel.size === 0) return;
    this.setStatus('批量翻译中...');
    let done = 0;
    for (const i of sel) {
      const card = CardWall.getCard(i);
      if (!card) continue;
      try {
        const r = await API.translateCard(card.card_id, i);
        if (r.ok) { done++; card.translated_name = r.suggestion?.translated_name; }
      } catch(e) {}
    }
    CardWall.setCards(CardWall.cards);
    this.setStatus('翻译完成：' + done + '/' + sel.size);
  },

  async _batchMove() {
    const sel = CardComponent.getSelected();
    if (sel.size === 0) return;
    const target = prompt('目标分类路径：');
    if (!target) return;
    const indices = [...sel].sort((a,b) => b - a);  // reverse order to avoid index shift
    for (const i of indices) {
      const card = CardWall.getCard(i);
      if (!card) continue;
      try {
        const r = await API.moveCard(card.card_id, target, true, i);
        if (r.ok) await API.moveCard(card.card_id, target, false, i);
        // Remove from array
        if (this.currentView === 'work') this.workCards.splice(i, 1);
        else this.libraryCards.splice(i, 1);
      } catch(e) {}
    }
    CardWall.setCards(this._activeCards(), this.currentView);
    this.setStatus('移动完成');
  },

  // ── Context Menu ────────────────────────────────────────────────

  showContextMenu(index, x, y) {
    const menu = document.getElementById('context-menu');
    const card = CardWall.getCard(index);
    if (!card) return;

    const items = [
      { label: '打开所在文件夹', action: () => App.openCardLocation(index) },
      { label: '复制来源路径', action: () => App.copyCardPath(index) },
      { label: '修改目标分类', action: () => App.changeTarget(index) },
      { label: '标记需确认', action: () => App.markReview(index) },
      { sep: true },
      { label: '重新分析', action: () => App.translateCard(index) },
      { label: '整理为封面+工程', action: () => App.formatCard(index) },
      { sep: true },
      { label: 'AI 翻译命名', action: () => App.translateCard(index) },
      { label: '移动入库', action: () => App.moveCard(index) },
    ];

    menu.innerHTML = '';
    items.forEach(item => {
      if (item.sep) {
        menu.appendChild(document.createElement('div')).className = 'context-menu-separator';
      } else {
        const el = document.createElement('div');
        el.className = 'context-menu-item';
        el.textContent = item.label;
        el.addEventListener('click', () => { item.action(); menu.classList.remove('visible'); });
        menu.appendChild(el);
      }
    });

    menu.style.left = Math.min(x, window.innerWidth - 200) + 'px';
    menu.style.top = Math.min(y, window.innerHeight - 350) + 'px';
    menu.classList.add('visible');
    const close = () => { menu.classList.remove('visible'); document.removeEventListener('click', close); };
    setTimeout(() => document.addEventListener('click', close), 50);
  },

  // ── History ────────────────────────────────────────────────────

  async showHistory() {
    this.setStatus('加载历史...');
    let moves = [], renames = [];
    try {
      const data = await API.getHistory();
      moves = data.moves || [];
      renames = data.renames || [];
    } catch (e) {}

    let html = '<div style="max-height:420px;overflow-y:auto">';
    html += '<h2 style="margin-bottom:12px">操作历史</h2>';
    if (moves.length > 0) {
      html += '<div class="caption" style="margin-bottom:6px">移动记录</div>';
      moves.slice(0, 40).forEach(m => {
        const src = (m.source || '').replace(/\\/g, '/').split('/').pop();
        const moved = m.status === 'moved';
        html += '<div style="font-size:0.78rem;padding:4px 0;border-bottom:0.5px solid var(--border);color:var(--text)">📦 ' + esc(src) + ' → ' + esc(m.destination || '') +
          (moved ? ' <button class="btn btn-sm" onclick="App.undoRecord(\'move\',\'' + esc(m.move_id || '') + '\')" style="margin-left:8px">撤销</button>' : '') +
          '</div>';
      });
    }
    if (renames.length > 0) {
      html += '<div class="caption" style="margin:10px 0 6px">重命名记录</div>';
      renames.slice(0, 40).forEach(r => {
        html += '<div style="font-size:0.78rem;padding:4px 0;border-bottom:0.5px solid var(--border);color:var(--text)">✎ ' + esc(r.old_name || '') + ' → ' + esc(r.new_name || '') + '</div>';
      });
    }
    if (moves.length === 0 && renames.length === 0) {
      html += '<div class="caption" style="padding:20px;text-align:center">暂无操作记录</div>';
    }
    html += '</div><div class="modal-actions"><button class="btn" onclick="document.getElementById(\'modal-overlay\').classList.remove(\'visible\')">关闭</button></div>';
    const overlay = document.getElementById('modal-overlay');
    const box = document.getElementById('modal-box');
    box.innerHTML = html;
    box.style.maxWidth = '560px'; box.style.width = '520px';
    overlay.classList.add('visible');
    overlay.onclick = (e) => { if (e.target === overlay) overlay.classList.remove('visible'); };
  },

  _openMenu(items, x, y) {
    const menu = document.getElementById('context-menu');
    menu.innerHTML = '';
    items.forEach(item => {
      const el = document.createElement('div');
      el.className = 'context-menu-item';
      el.textContent = item.label;
      el.addEventListener('click', () => { menu.classList.remove('visible'); item.action(); });
      menu.appendChild(el);
    });
    menu.style.left = Math.min(x, window.innerWidth - 200) + 'px';
    menu.style.top = Math.min(y, window.innerHeight - 200) + 'px';
    menu.classList.add('visible');
    const close = () => { menu.classList.remove('visible'); document.removeEventListener('click', close); };
    setTimeout(() => document.addEventListener('click', close), 50);
  },

  async undoRecord(kind, recordId) {
    try {
      const r = await API.undo(kind, recordId);
      if (r.ok) this.setStatus('已撤销');
      else alert('撤销失败：' + (r.error || '未知错误'));
      document.getElementById('modal-overlay').classList.remove('visible');
    } catch (e) { alert('撤销失败：' + e.message); }
  },

  showMoreMenu(e) {
    const btn = e.target.closest('button');
    if (!btn) return;
    const rect = btn.getBoundingClientRect();
    const menu = document.getElementById('context-menu');
    menu.innerHTML = '';
    [
      { label: '设置', action: () => SettingsDialog.open() },
      { label: '一键翻译全部', action: () => App.translateAll() },
      { label: '查找重复', action: async () => { App.setStatus('查重中...'); try { const r = await API.findDuplicates(); App.setStatus(r.count > 0 ? '发现 ' + r.count + ' 组重复' : '未发现重复'); } catch(e) { App.setStatus('查重失败'); } } },
      { label: '清理空目录', action: async () => { if (!confirm('确认清理空目录？')) return; try { const r = await API.cleanupEmptyDirs(); App.setStatus('清理完成：' + (r.count || 0) + ' 个'); } catch(e) { App.setStatus('清理失败'); } } },
    ].forEach(item => {
      const el = document.createElement('div');
      el.className = 'context-menu-item';
      el.textContent = item.label;
      el.addEventListener('click', () => { item.action(); menu.classList.remove('visible'); });
      menu.appendChild(el);
    });
    menu.style.left = Math.min(rect.left, window.innerWidth - 200) + 'px';
    menu.style.top = Math.min(rect.bottom + 4, window.innerHeight - 160) + 'px';
    menu.classList.add('visible');
    const close = () => { menu.classList.remove('visible'); document.removeEventListener('click', close); };
    setTimeout(() => document.addEventListener('click', close), 50);
  },

  // ── Shimmer ─────────────────────────────────────────────────────

  _showShimmer(msg) {
    const el = document.getElementById('analysis-overlay');
    if (!el) return;
    el.style.display = 'flex';
    const t = document.getElementById('shimmer-text');
    if (t) t.textContent = msg || '正在分析中...';
    const bar = el.querySelector('.shimmer-progress-bar');
    if (bar) bar.style.width = '0%';
  },

  _updateShimmerText(msg, pct) {
    const t = document.getElementById('shimmer-text');
    if (t) t.textContent = msg;
    const bar = document.querySelector('.shimmer-progress-bar');
    if (bar) bar.style.width = (pct || 0) + '%';
  },

  _hideShimmer() {
    const el = document.getElementById('analysis-overlay');
    if (el) el.style.display = 'none';
  },

  // ── UI ──────────────────────────────────────────────────────────

  toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    sidebar.style.display = sidebar.style.display === 'none' ? '' : 'none';
  },

  setStatus(msg) {
    const el = document.getElementById('status-text');
    if (el) el.textContent = msg;
  },

  updateVersion() {
    const el = document.getElementById('version-text');
    if (el) el.textContent = 'v0.3.5';
  },
};

document.addEventListener('DOMContentLoaded', () => App.init());
