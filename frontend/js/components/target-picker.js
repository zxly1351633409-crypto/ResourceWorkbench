// ================================================================
// TargetPicker — folder-browser dialog for choosing target path
// ================================================================

const TargetPicker = {
  _overlay: null,
  _box: null,
  _currentBase: '',
  _resourceRoot: '',
  _resolve: null,
  _errorShown: false,

  init() {
    this._overlay = document.getElementById('modal-overlay');
    this._box = document.getElementById('modal-box');
  },

  async open(card, recommendations) {
    // Get resource root from settings
    let root = '';
    try {
      const s = await API.getSettings();
      root = s.resource_root || '';
    } catch (e) {}

    if (!root) {
      alert('请先在设置里配置资源库根路径。');
      return;
    }

    this._resourceRoot = root;
    this._currentBase = root;
    this._errorShown = false;

    // If we got recommendations from the backend, use the recommended base
    if (recommendations && recommendations.length > 0) {
      const first = recommendations[0].path || '';
      if (first) {
        // Navigate to parent of the first recommendation
        const parts = first.replace(/\\/g, '/').split('/').filter(Boolean);
        if (parts.length > 0) {
          const parent = parts.slice(0, -1).join('/');
          if (parent && parent.startsWith(root.replace(/\\/g, '/'))) {
            this._currentBase = parent;
          }
        }
      }
    }

    return new Promise((resolve) => {
      this._resolve = resolve;
      this._render(card, recommendations);
      this._overlay.classList.add('visible');

      this._overlay.onclick = (e) => {
        if (e.target === this._overlay) {
          this._overlay.classList.remove('visible');
          resolve(null);
        }
      };
    });
  },

  _render(card, recommendations) {
    const name = card.display_name || card.name || '未命名';
    const current = card.effective_target_path || card.user_target_path || card.target_path || '';

    let html = `<div class="target-picker">
      <div class="target-picker-header">
        <span style="font-weight:600">选择目标分类</span>
        <span style="font-size:0.75rem;color:var(--text-muted)">为 ${esc(name)} 选择位置，不会立即移动</span>
      </div>
      <div class="target-picker-nav">
        <button class="btn btn-sm" id="tp-up" title="返回上一级">← 上一级</button>
        <span class="target-picker-crumb" id="tp-crumb"></span>
      </div>
      <input type="text" class="target-picker-search" id="tp-search" placeholder="搜索文件夹名">
      <div class="target-picker-list" id="tp-list"></div>
      <div class="target-picker-selected" id="tp-selected">尚未选择目标</div>
      <div class="target-picker-actions">
        <button class="btn" id="tp-pick-here">选择当前这层目录</button>
        <span style="flex:1"></span>
        <button class="btn" id="tp-cancel">取消</button>
        <button class="btn btn-primary" id="tp-confirm">选这个文件夹</button>
      </div>
    </div>`;

    this._box.innerHTML = html;
    this._box.style.maxWidth = '560px';
    this._box.style.width = '520px';

    this._refreshList(recommendations);

    // Events
    document.getElementById('tp-up').onclick = () => this._goUp();
    document.getElementById('tp-search').oninput = () => this._refreshList();
    document.getElementById('tp-pick-here').onclick = () => this._pickCurrent();
    document.getElementById('tp-cancel').onclick = () => this._close(null);
    document.getElementById('tp-confirm').onclick = () => {
      const sel = document.getElementById('tp-selected');
      const path = sel.dataset.path;
      if (!path) {
        alert('请先选中一个文件夹，或点"选择当前这层目录"。');
        return;
      }
      this._close(path);
    };
    document.getElementById('tp-search').onkeydown = (e) => {
      if (e.key === 'Escape') this._close(null);
    };
  },

  async _refreshList(recommendations) {
    const list = document.getElementById('tp-list');
    const crumb = document.getElementById('tp-crumb');
    const filter = (document.getElementById('tp-search').value || '').toLowerCase();

    // Show current path relative to resource root
    const rootClean = this._resourceRoot.replace(/\\/g, '/').replace(/\/$/, '');
    const baseClean = this._currentBase.replace(/\\/g, '/');
    let displayPath = baseClean;
    if (baseClean.startsWith(rootClean)) {
      displayPath = baseClean.slice(rootClean.length).replace(/^\//, '') || '/';
    }
    crumb.textContent = '母路径：' + displayPath;

    list.innerHTML = '<div class="caption" style="padding:8px;text-align:center">加载中…</div>';

    try {
      // Get children via library-tree API
      const data = await API.getLibraryTree(this._currentBase);
      let children = (data && data.children) ? data.children : [];

      if (filter) {
        children = children.filter(c => c.name.toLowerCase().includes(filter));
      }

      list.innerHTML = '';

      // Show recommendations at the top (only when no filter)
      if (recommendations && recommendations.length > 0 && !filter) {
        const header = document.createElement('div');
        header.className = 'tp-section-header';
        header.textContent = '— 推荐分类（按相近度）—';
        list.appendChild(header);

        for (const rec of recommendations.slice(0, 6)) {
          const displayLabel = rec.relative || rec.name || rec.path.replace(/\\/g, ' / ').split('/').pop();
          const item = this._createListItem('★ 推荐  ' + displayLabel, rec.path, true);
          list.appendChild(item);
        }

        const sep = document.createElement('div');
        sep.className = 'tp-section-header';
        sep.textContent = '— 这一层的全部文件夹 —';
        list.appendChild(sep);
      }

      if (children.length === 0) {
        const hint = document.createElement('div');
        hint.className = 'caption';
        hint.style.cssText = 'padding:12px;text-align:center;opacity:0.5';
        hint.textContent = filter ? '没有匹配的文件夹' : '（这一层没有更细的子文件夹）';
        list.appendChild(hint);
      } else {
        for (const child of children) {
          const hasKids = child.children && child.children.length > 0;
          const item = this._createListItem(
            child.name + (hasKids ? '      ›' : ''),
            child.path,
            hasKids
          );
          list.appendChild(item);
        }
      }
    } catch (e) {
      list.innerHTML = '<div class="caption" style="padding:8px;color:var(--danger)">加载失败</div>';
    }
  },

  _createListItem(label, path, isDir) {
    const el = document.createElement('div');
    el.className = 'tp-list-item';
    el.textContent = label;
    el.dataset.path = path;
    el.dataset.isDir = isDir ? '1' : '0';

    el.onclick = () => {
      // Highlight
      document.querySelectorAll('.tp-list-item.selected').forEach(x => x.classList.remove('selected'));
      el.classList.add('selected');
      // Show selection
      const sel = document.getElementById('tp-selected');
      const relPath = path.replace(/\\/g, '/');
      sel.textContent = '已选择：' + relPath;
      sel.dataset.path = path;
    };

    el.ondblclick = () => {
      if (isDir) {
        this._currentBase = path;
        document.getElementById('tp-search').value = '';
        this._refreshList();
      }
    };

    return el;
  },

  _goUp() {
    const rootClean = this._resourceRoot.replace(/\\/g, '/').replace(/\/$/, '');
    const baseClean = this._currentBase.replace(/\\/g, '/').replace(/\/$/, '');
    if (baseClean === rootClean || !baseClean.startsWith(rootClean)) return;
    const parent = baseClean.substring(0, baseClean.lastIndexOf('/'));
    if (parent.length >= rootClean.length) {
      this._currentBase = parent;
      document.getElementById('tp-search').value = '';
      this._refreshList();
    }
  },

  _pickCurrent() {
    const sel = document.getElementById('tp-selected');
    sel.textContent = '已选择：' + this._currentBase.replace(/\\/g, '/');
    sel.dataset.path = this._currentBase;
  },

  _close(path) {
    this._overlay.classList.remove('visible');
    if (this._resolve) {
      this._resolve(path);
      this._resolve = null;
    }
  },
};
