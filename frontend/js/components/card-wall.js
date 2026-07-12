// ================================================================
// Card Wall — Pinterest-style masonry waterfall layout
// Supports multiple instances (library / work)
// ================================================================

const CardWall = {
  _instances: {},
  _cardWidth: 250,
  _gap: 14,
  _pad: 16,

  init() {
    this._instances.library = {
      container: document.getElementById('card-wall-library'),
      cards: [],
      relayoutTimer: null,
    };
    this._instances.work = {
      container: document.getElementById('card-wall-work'),
      cards: [],
      relayoutTimer: null,
    };
    this.emptyState = document.getElementById('empty-state');
    window.addEventListener('resize', () => {
      this._scheduleRelayout('library', 80);
      this._scheduleRelayout('work', 80);
    });
  },

  _active() {
    return this._instances[App.currentView] || this._instances.library;
  },

  _activeContainer() {
    var inst = this._active();
    return inst ? inst.container : null;
  },

  show(view) {
    var lib = document.getElementById('card-wall-library');
    var work = document.getElementById('card-wall-work');
    if (view === 'library') { lib.style.display = ''; work.style.display = 'none'; }
    else { lib.style.display = 'none'; work.style.display = ''; }
    this._scheduleRelayout(view, 20);
  },

  setCards(cards, view) {
    view = view || App.currentView;
    var inst = this._instances[view];
    if (!inst) return;
    inst.cards = cards;
    this._render(view);
  },

  getCards(view) {
    view = view || App.currentView;
    var inst = this._instances[view];
    return inst ? inst.cards : [];
  },

  _render(view) {
    var inst = this._instances[view];
    if (!inst) return;
    var container = inst.container;
    var cards = inst.cards;

    container.innerHTML = '';
    if (cards.length === 0) {
      if (view === App.currentView) this.emptyState.style.display = 'flex';
      container.style.height = 'auto';
      return;
    }
    if (view === App.currentView) this.emptyState.style.display = 'none';

    var frag = document.createDocumentFragment();
    for (var i = 0; i < cards.length; i++) {
      var card = cards[i];
      var el = CardComponent.create(card, i);
      el.style.position = 'absolute';
      el.style.visibility = 'hidden';
      frag.appendChild(el);
      var cardId = card.card_id;
      if (!card.preview_url && cardId) {
        this._loadPreview(cardId, el, view);
      }
    }
    container.appendChild(frag);
    requestAnimationFrame(() => this._doLayout(view));
  },

  _doLayout(view) {
    var inst = this._instances[view];
    if (!inst) return;
    var container = inst.container;
    var parentWidth = container.parentElement ? container.parentElement.clientWidth : 1200;
    var containerWidth = parentWidth - this._pad * 2;
    var cardWidth = this._cardWidth;
    var gap = this._gap;
    var pad = this._pad;
    var columns = Math.max(1, Math.floor((containerWidth + gap) / (cardWidth + gap)));
    var totalWidth = columns * cardWidth + (columns - 1) * gap;
    var leftPad = Math.max(pad, Math.floor((containerWidth - totalWidth) / 2));
    var heights = new Array(columns).fill(pad);
    var children = container.children;

    for (var i = 0; i < children.length; i++) {
      var el = children[i];
      if (!el.classList.contains('resource-card')) continue;
      var minCol = 0;
      for (var c = 1; c < columns; c++) {
        if (heights[c] < heights[minCol]) minCol = c;
      }
      el.style.left = (leftPad + minCol * (cardWidth + gap)) + 'px';
      el.style.top = heights[minCol] + 'px';
      el.style.width = cardWidth + 'px';
      el.style.visibility = 'visible';
      heights[minCol] += (el.offsetHeight || 200) + gap;
    }
    container.style.height = (Math.max.apply(null, heights) + pad) + 'px';
    container.style.position = 'relative';
  },

  _scheduleRelayout(view, ms) {
    var inst = this._instances[view];
    if (!inst) return;
    if (inst.relayoutTimer) clearTimeout(inst.relayoutTimer);
    inst.relayoutTimer = setTimeout(() => this._doLayout(view), ms || 60);
  },

  _loadPreview(cardId, el, view) {
    var self = this;
    API.getPreview(cardId).then(function(data) {
      if (data.ok && data.url) {
        var previewDiv = el.querySelector('.card-preview');
        if (previewDiv) {
          var img = document.createElement('img');
          img.src = data.url;
          img.alt = '';
          img.onload = function() { self._scheduleRelayout(view, 60); };
          previewDiv.innerHTML = '';
          previewDiv.appendChild(img);
        }
      }
    }).catch(function() {
      var previewDiv = el.querySelector('.card-preview');
      if (previewDiv) previewDiv.innerHTML = '<span class="preview-placeholder">无预览</span>';
    });
  },

  getCard(index) {
    var inst = this._active();
    return (inst && inst.cards[index]) || null;
  },

  getSelectedIndices() {
    return CardComponent.getSelected ? [...CardComponent.getSelected()] : [];
  },

  get cards() {
    var inst = this._active();
    return inst ? inst.cards : [];
  },
  set cards(v) {
    var inst = this._active();
    if (inst) inst.cards = v;
  },
};
