// ================================================================
// Card — individual resource card component
// ================================================================

const CardComponent = {
  _selected: new Set(),
  _selectMode: false,

  create(card, index) {
    const el = document.createElement('div');
    el.className = 'resource-card';
    el.dataset.index = index;
    el.dataset.cardId = card.card_id || card.id || '';

    if (this._selected.has(index)) el.classList.add('selected');

    // ── Preview ──
    const preview = document.createElement('div');
    preview.className = 'card-preview';
    if (card.preview_url) {
      const img = document.createElement('img');
      img.src = card.preview_url;
      img.alt = card.display_name || card.name || '';
      img.loading = 'lazy';
      preview.appendChild(img);
    } else {
      const ph = document.createElement('span');
      ph.className = 'preview-placeholder';
      ph.textContent = '预览加载中';
      preview.appendChild(ph);
    }
    el.appendChild(preview);

    // ── Selection badge ──
    const badge = document.createElement('div');
    badge.className = 'selection-badge';
    badge.innerHTML = Icons.check;
    el.appendChild(badge);

    // ── Hover overlay ──
    const overlay = document.createElement('div');
    overlay.className = 'card-overlay';

    const topRow = document.createElement('div');
    topRow.className = 'card-overlay-top';

    // Create buttons with DOM API for reliable event binding
    var btnTranslate = document.createElement('button');
    btnTranslate.className = 'overlay-btn overlay-btn-translate';
    btnTranslate.title = 'AI 翻译命名';
    btnTranslate.innerHTML = Icons.translate;
    btnTranslate.onclick = function(e) { e.stopPropagation(); App.handleCardAction('translate', index); };
    topRow.appendChild(btnTranslate);

    var btnMove = document.createElement('button');
    btnMove.className = 'overlay-btn overlay-btn-move';
    btnMove.title = '移动入库';
    btnMove.innerHTML = Icons.move;
    btnMove.onclick = function(e) { e.stopPropagation(); e.preventDefault(); try { App.handleCardAction('move', index); } catch(err) { alert('移动错误: ' + err.message); } };
    topRow.appendChild(btnMove);

    overlay.appendChild(topRow);

    const bottomRow = document.createElement('div');
    bottomRow.className = 'card-overlay-bottom';
    const isLib = card.is_library_card;
    var targetLabel = '';
    if (isLib) {
      // Library card: show first 2 levels, strip letter prefixes
      var raw = card.library_display || card.effective_target_path || '';
      targetLabel = _shortPath(raw);
    } else if (card.effective_target_path || card.user_target_path || card.target_path) {
      var t = card.effective_target_path || card.user_target_path || card.target_path;
      var parts = t.replace(/\\/g, '/').split('/').filter(Boolean);
      targetLabel = parts.slice(-3).map(_stripPrefix).join(' / ');
    }
    bottomRow.innerHTML =
      '<button class="overlay-btn overlay-btn-open" data-action="open" title="打开所在文件夹">' + Icons.open + '</button>' +
      (targetLabel
        ? '<button class="overlay-btn overlay-btn-target" data-action="target" title="修改目标分类">' + esc(targetLabel) + '</button>'
        : '<button class="overlay-btn overlay-btn-target overlay-btn-target-empty" data-action="target" title="设置目标分类">＋ 设置分类</button>');
    overlay.appendChild(bottomRow);

    bottomRow.querySelector('[data-action="open"]').onclick = function(e) { e.stopPropagation(); App.handleCardAction('open', index); };
    var targetBtn = bottomRow.querySelector('[data-action="target"]');
    if (targetBtn) targetBtn.onclick = function(e) { e.stopPropagation(); App.handleCardAction('target', index); };

    // Context menu on overlay (when hovered)
    overlay.addEventListener('contextmenu', function(e) {
      e.preventDefault();
      e.stopPropagation();
      App.showContextMenu(index, e.clientX, e.clientY);
    });

    el.appendChild(overlay);

    // ── Card body ──
    const body = document.createElement('div');
    body.className = 'card-body';

    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = card.display_name || card.name || '未命名';
    title.title = card.display_name || card.name || '';
    body.appendChild(title);

    const meta = document.createElement('div');
    meta.className = 'card-meta';
    if (card.suggested_type) {
      const typeChip = document.createElement('span');
      typeChip.className = 'chip chip-type';
      typeChip.textContent = TYPE_LABELS[card.suggested_type] || card.suggested_type;
      meta.appendChild(typeChip);
    }
    if (card.needs_human_review) {
      const statusChip = document.createElement('span');
      statusChip.className = 'chip chip-status';
      statusChip.textContent = '需确认';
      meta.appendChild(statusChip);
    }
    if (card.manual_tags && card.manual_tags.length > 0) {
      const tagChip = document.createElement('span');
      tagChip.className = 'chip chip-tag';
      tagChip.textContent = card.manual_tags[0];
      meta.appendChild(tagChip);
    }
    body.appendChild(meta);

    if (targetLabel) {
      const targetChip = document.createElement('div');
      targetChip.className = 'chip chip-target';
      targetChip.style.cssText = 'margin-top:5px;display:inline-flex';
      targetChip.textContent = targetLabel.length > 28 ? targetLabel.slice(0, 27) + '…' : targetLabel;
      targetChip.title = card.effective_target_path || card.library_target_path || targetLabel;
      body.appendChild(targetChip);
    }

    el.appendChild(body);

    // ── Card-level events ──
    el.addEventListener('click', function(e) { App.selectCard(index, e); });
    el.addEventListener('dblclick', function() { App.showCardDetail(index); });
    el.addEventListener('contextmenu', function(e) {
      e.preventDefault();
      App.showContextMenu(index, e.clientX, e.clientY);
    });

    return el;
  },

  updateSelectionUI: function(el, index) {
    if (this._selected.has(index)) el.classList.add('selected');
    else el.classList.remove('selected');
  },

  setSelected: function(index, selected) {
    if (selected) this._selected.add(index);
    else this._selected.delete(index);
    var el = document.querySelector('.resource-card[data-index="' + index + '"]');
    if (el) this.updateSelectionUI(el, index);
  },

  toggleSelected: function(index) {
    if (this._selected.has(index)) this._selected.delete(index);
    else this._selected.add(index);
    var el = document.querySelector('.resource-card[data-index="' + index + '"]');
    if (el) this.updateSelectionUI(el, index);
  },

  clearSelection: function() {
    this._selected.clear();
    document.querySelectorAll('.resource-card.selected').forEach(function(c) { c.classList.remove('selected'); });
  },

  getSelected: function() { return new Set(this._selected); },
  isSelectMode: function() { return this._selectMode; },
  setSelectMode: function(on) {
    this._selectMode = !!on;
    if (!on) this.clearSelection();
    document.querySelectorAll('.resource-card').forEach(function(c) {
      if (on) { c.classList.add('select-mode'); }
      else { c.classList.remove('select-mode'); }
    });
  },
};
