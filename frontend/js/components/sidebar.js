// ================================================================
// Sidebar — resource library tree (Hana style, lazy loading)
// ================================================================

const Sidebar = {
  tree: null,
  currentPath: null,
  rootPath: null,
  loadedPaths: new Set(),

  init() {
    this.tree = document.getElementById('sidebar-tree');
    this.tree.addEventListener('click', (e) => this._handleClick(e));
    this.tree.addEventListener('contextmenu', (e) => this._handleContextMenu(e));
  },

  async load(path) {
    this.tree.innerHTML = '<div class="caption" style="padding:12px 14px">加载中…</div>';
    try {
      const data = await API.getLibraryTree(path);
      this.rootPath = data.path || this.rootPath;
      this.tree.innerHTML = '';
      if (data.children && data.children.length > 0) {
        for (const child of data.children) {
          this.tree.appendChild(this._createNode(child, 0));
        }
        // Preload children of level-1 nodes in background
        this._preloadLevel1(data.children);
      } else {
        this.tree.innerHTML = '<div class="caption" style="padding:12px 14px;font-style:italic">点击"设置"配置资源库路径</div>';
      }
    } catch (err) {
      this.tree.innerHTML = '<div class="caption" style="padding:12px 14px;color:var(--danger)">加载失败</div>';
    }
  },

  async _preloadLevel1(children) {
    for (const child of children) {
      if (!child.path) continue;
      try {
        const data = await API.getLibraryTree(child.path);
        // Update node with real children
        const node = this.tree.querySelector('[data-path="' + child.path.replace(/"/g, '\\"') + '"]');
        if (node && data.children && data.children.length > 0) {
          const wrap = node.querySelector('.tree-children');
          if (wrap) {
            wrap.innerHTML = '';
            const depth = parseInt(node.dataset.depth) + 1;
            for (const c of data.children) {
              wrap.appendChild(this._createNode(c, depth));
            }
            node.dataset.loaded = '1';
          }
        }
      } catch (e) {}
    }
  },

  _createNode(item, depth) {
    const container = document.createElement('div');
    container.className = 'tree-node';
    container.dataset.path = item.path || '';
    container.dataset.depth = depth;
    container.dataset.hasChildren = (item.children && item.children.length > 0) ? '1' : '0';
    container.dataset.loaded = '0';

    const row = document.createElement('div');
    row.className = 'tree-node-row';
    row.style.paddingLeft = (12 + depth * 18) + 'px';

    const arrow = document.createElement('span');
    arrow.className = 'tree-node-arrow';
    arrow.innerHTML = Icons.arrowRight;
    if (!(item.children && item.children.length > 0)) arrow.classList.add('hidden');
    row.appendChild(arrow);

    const icon = document.createElement('span');
    icon.className = 'tree-node-icon';
    icon.innerHTML = Icons.folder;
    row.appendChild(icon);

    const label = document.createElement('span');
    label.className = 'tree-node-label';
    label.textContent = item.name;
    row.appendChild(label);

    container.appendChild(row);

    if (item.children && item.children.length > 0) {
      const childrenWrap = document.createElement('div');
      childrenWrap.className = 'tree-children hidden';
      for (const child of item.children) {
        childrenWrap.appendChild(this._createNode(child, depth + 1));
      }
      container.appendChild(childrenWrap);
    }
    return container;
  },

  async _handleClick(e) {
    const row = e.target.closest('.tree-node-row');
    if (!row) return;
    const node = row.parentElement;
    const path = node.dataset.path;
    const arrow = row.querySelector('.tree-node-arrow');
    if (e.target.closest('.tree-node-arrow') && !arrow.classList.contains('hidden')) {
      await this._toggleExpand(node, path, arrow);
      return;
    }
    this._selectPath(path, row);
  },

  async _handleContextMenu(e) {
    const row = e.target.closest('.tree-node-row');
    if (!row) return;
    e.preventDefault();
    const node = row.parentElement;
    const parent = node.dataset.path || this.rootPath || '';
    App._openMenu([
      { label: '新建文件夹', action: () => this._createFolder(parent) },
      { label: '刷新', action: async () => {
        await this.load(parent === this.rootPath ? '' : parent);
        await App.loadLibraryCards(parent);
      }},
    ], e.clientX, e.clientY);
  },

  async _createFolder(parent) {
    const name = prompt('新文件夹名称：');
    if (!name) return;
    try {
      await API.createFolder(parent, name);
      App.setStatus('已新建文件夹：' + name);
      await this.load(parent === this.rootPath ? '' : parent);
    } catch (e) {
      App.setStatus('新建文件夹失败：' + e.message);
    }
  },

  async _toggleExpand(node, path, arrow) {
    const childrenWrap = node.querySelector('.tree-children');
    if (!childrenWrap) return;
    if (!childrenWrap.classList.contains('hidden')) {
      childrenWrap.classList.add('hidden');
      arrow.classList.remove('expanded');
      node.querySelector('.tree-node-icon').innerHTML = Icons.folder;
      return;
    }
    if (node.dataset.loaded !== '1') {
      arrow.classList.add('expanded');
      childrenWrap.classList.remove('hidden');
      childrenWrap.innerHTML = '<div class="caption" style="padding:4px 0 4px ' + (12 + (parseInt(node.dataset.depth) + 1) * 18) + 'px">加载中…</div>';
      try {
        const data = await API.getLibraryTree(path);
        childrenWrap.innerHTML = '';
        if (data.children && data.children.length > 0) {
          for (const child of data.children) {
            childrenWrap.appendChild(this._createNode(child, parseInt(node.dataset.depth) + 1));
          }
        } else {
          childrenWrap.innerHTML = '<div class="caption" style="padding:4px 0 4px ' + (12 + (parseInt(node.dataset.depth) + 1) * 18) + 'px;opacity:0.5">（空）</div>';
        }
        node.dataset.loaded = '1';
      } catch (err) {
        childrenWrap.innerHTML = '<div class="caption" style="padding:4px 0;color:var(--danger)">加载失败</div>';
        return;
      }
    } else {
      childrenWrap.classList.remove('hidden');
      arrow.classList.add('expanded');
    }
    node.querySelector('.tree-node-icon').innerHTML = Icons.folderOpen;
  },

  _selectPath(path, row) {
    this.tree.querySelectorAll('.tree-node-row.active').forEach(r => r.classList.remove('active'));
    row.classList.add('active');
    this.currentPath = path;
    App.loadLibraryCards(path);
    this._preloadChildren(path);
  },

  async _preloadChildren(path) {
    try {
      const data = await API.getLibraryTree(path);
      if (data.children) {
        for (const child of data.children) {
          if (child.path) this.loadedPaths.add(child.path);
        }
      }
    } catch (e) {}
  },
};
