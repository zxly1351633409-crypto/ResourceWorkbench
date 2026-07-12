// ================================================================
// Settings — Hana-style theme & config panel
// ================================================================

const SettingsDialog = {
  modal: null,
  box: null,
  settings: {},
  _originalColors: null,

  init() {
    this.modal = document.getElementById('modal-overlay');
    this.box = document.getElementById('modal-box');
    // Settings button moved to title bar; bind if present
    const btn = document.getElementById('btn-settings-titlebar');
    if (btn) btn.addEventListener('click', () => this.open());
    if (this.modal) {
      this.modal.addEventListener('click', (e) => {
        if (e.target === this.modal) this.cancel();
      });
    }
  },

  async open() {
    try {
      this.settings = await API.getSettings();
    } catch (err) {
      this.settings = {};
    }
    // 保存当前颜色快照，取消时恢复
    this._originalColors = this._readCurrentColors();

    this.box.innerHTML = this._buildHTML();
    this.box.style.maxWidth = '640px';
    this.box.style.width = '560px';
    this.modal.classList.add('visible');
    this._bindEvents();
  },

  close() {
    this.modal.classList.remove('visible');
  },

  applySavedSettings(settings) {
    this.settings = settings || {};
    this._applyLiveColors({
      bg: this.settings.ui_window_color || '#F4F0EA',
      card: this.settings.ui_card_color || '#FBF8F3',
      sidebar: this.settings.ui_sidebar_color || '#EEE9E1',
      accent: this.settings.ui_accent_color || '#537D96',
      text: this.settings.ui_text_color || '#2A2622',
      border: this.settings.ui_border_color || '#D5CEC3',
      'overlay-translate': this.settings.ui_overlay_translate || '#5B7A9A',
      'overlay-move': this.settings.ui_overlay_move || '#5A7A5A',
    });
    var fs = Number(this.settings.ui_font_size) || 14;
    document.documentElement.style.fontSize = fs + 'px';
  },

  cancel() {
    this._restoreColors();
    this.close();
  },

  _readCurrentColors() {
    const root = document.documentElement;
    return {
      bg: getComputedStyle(root).getPropertyValue('--bg').trim(),
      card: getComputedStyle(root).getPropertyValue('--bg-card').trim(),
      sidebar: getComputedStyle(root).getPropertyValue('--sidebar-bg').trim(),
      accent: getComputedStyle(root).getPropertyValue('--accent').trim(),
      text: getComputedStyle(root).getPropertyValue('--text').trim(),
      textLight: getComputedStyle(root).getPropertyValue('--text-light').trim(),
      textMuted: getComputedStyle(root).getPropertyValue('--text-muted').trim(),
      border: getComputedStyle(root).getPropertyValue('--border').trim(),
      accentHover: getComputedStyle(root).getPropertyValue('--accent-hover').trim(),
      accentLight: getComputedStyle(root).getPropertyValue('--accent-light').trim(),
    };
  },

  _restoreColors() {
    if (!this._originalColors) return;
    const root = document.documentElement;
    const c = this._originalColors;
    root.style.setProperty('--bg', c.bg);
    root.style.setProperty('--bg-card', c.card);
    root.style.setProperty('--sidebar-bg', c.sidebar);
    root.style.setProperty('--accent', c.accent);
    root.style.setProperty('--accent-hover', c.accentHover);
    root.style.setProperty('--accent-light', c.accentLight);
    root.style.setProperty('--text', c.text);
    root.style.setProperty('--text-light', c.textLight);
    root.style.setProperty('--text-muted', c.textMuted);
    root.style.setProperty('--border', c.border);
    this._originalColors = null;
  },

  _applyLiveColors(colors) {
    const root = document.documentElement;
    if (colors.bg) {
      root.style.setProperty('--bg', colors.bg);
      root.style.setProperty('--sidebar-bg', this._mix(colors.bg, '#000000', 0.04));
      root.style.setProperty('--bg-card', this._mix(colors.bg, '#ffffff', 0.5));
      root.style.setProperty('--border', this._mix(colors.bg, '#000000', 0.12));
      const meta = document.querySelector('meta[name="theme-color"]');
      if (meta) meta.content = colors.bg;
    }
    if (colors.card) root.style.setProperty('--bg-card', colors.card);
    if (colors.sidebar) root.style.setProperty('--sidebar-bg', colors.sidebar);
    if (colors.accent) {
      root.style.setProperty('--accent', colors.accent);
      root.style.setProperty('--accent-hover', this._darken(colors.accent, 0.82));
      root.style.setProperty('--accent-light', this._alphaHex(colors.accent, 0.08));
    }
    if (colors.text) {
      root.style.setProperty('--text', colors.text);
      root.style.setProperty('--text-light', this._mix(colors.text, '#ffffff', 0.3));
      root.style.setProperty('--text-muted', this._mix(colors.text, '#ffffff', 0.5));
    }
    if (colors.border) root.style.setProperty('--border', colors.border);
  },

  // Mix two hex colors: color * (1-ratio) + white * ratio
  _mix(hex, white, ratio) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    const wr = 255, wg = 255, wb = 255;
    const mix = (c, w) => Math.round(c * (1 - ratio) + w * ratio);
    return '#' + [mix(r,wr), mix(g,wg), mix(b,wb)].map(v => v.toString(16).padStart(2,'0')).join('');
  },

  _darken(hex, factor) {
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    const dr = Math.round(r * factor), dg = Math.round(g * factor), db = Math.round(b * factor);
    return '#' + [dr,dg,db].map(v => Math.max(0,Math.min(255,v)).toString(16).padStart(2,'0')).join('');
  },

  _alphaHex(hex, alpha) {
    // 返回 rgba 字符串（CSS 变量不支持 hex alpha）
    const r = parseInt(hex.slice(1,3), 16);
    const g = parseInt(hex.slice(3,5), 16);
    const b = parseInt(hex.slice(5,7), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  },

  _buildHTML() {
    const s = this.settings;
    return `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:18px">
        <h2 style="margin:0;border:none;padding:0">设置</h2>
        <div style="display:flex;gap:8px">
          <button class="btn btn-sm btn-primary" onclick="SettingsDialog._save()">保存</button>
          <button class="btn btn-sm" onclick="SettingsDialog.cancel()">取消</button>
        </div>
      </div>

      <div style="display:flex;gap:20px">

        <!-- Left: categories -->
        <div class="settings-sidebar">
          <div class="settings-nav-item active" data-tab="general">通用</div>
          <div class="settings-nav-item" data-tab="theme">主题 · 配色</div>
          <div class="settings-nav-item" data-tab="ai">AI · 翻译</div>
          <div class="settings-nav-item" data-tab="move">移动</div>
        </div>

        <!-- Right: panels -->
        <div style="flex:1;min-width:0;max-height:420px;overflow-y:auto;padding-right:6px">

          <!-- General -->
          <div class="settings-panel" id="panel-general">
            <div style="margin-bottom:14px">
              <div class="caption" style="margin-bottom:4px">资源库根路径</div>
              <div style="display:flex;gap:6px">
                <input type="text" id="set-resource-root" value="${esc(s.resource_root || '')}" style="flex:1;height:32px;border:0.5px solid var(--border);border-radius:var(--radius);padding:0 10px;font-size:0.82rem;background:var(--bg-card);color:var(--text);outline:none">
                <button class="btn btn-sm" onclick="SettingsDialog._pickRoot()">浏览</button>
              </div>
            </div>
            <div style="margin-bottom:14px">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                <input type="checkbox" id="set-rename-local" ${s.rename_local_after_translate ? 'checked' : ''}>
                <span style="font-size:0.82rem;color:var(--text)">翻译后同步重命名本地文件夹</span>
              </label>
            </div>
            <div style="margin-bottom:14px">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                <input type="checkbox" id="set-auto-index" ${s.auto_index_on_library_open !== false ? 'checked' : ''}>
                <span style="font-size:0.82rem;color:var(--text)">启动时自动索引资源库</span>
              </label>
            </div>
          </div>

          <!-- Theme -->
          <div class="settings-panel" id="panel-theme" style="display:none">
            <div class="caption" style="margin-bottom:8px">预设主题</div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px" id="theme-presets">
              ${this._themePreset('warm', '暖白纸', '#F2EFE9', '#537D96')}
              ${this._themePreset('cool', '冷静灰', '#EEEDE8', '#537D96')}
              ${this._themePreset('dark', '深色', '#2A2622', '#6A9AB5')}
              ${this._themePreset('cream', '奶油', '#FAF6EE', '#537D96')}
            </div>
            <div class="caption" style="margin-bottom:8px">自定义语义色</div>
            ${this._colorRow('背景色', 'set-bg', s.ui_window_color || '', '#F4F0EA')}
            ${this._colorRow('卡片色', 'set-card', s.ui_card_color || '', '#FBF8F3')}
            ${this._colorRow('侧栏色', 'set-sidebar', s.ui_sidebar_color || '', '#EEE9E1')}
            ${this._colorRow('强调色', 'set-accent', s.ui_accent_color || '', '#537D96')}
            ${this._colorRow('文字色', 'set-text', s.ui_text_color || '', '#2A2622')}
            ${this._colorRow('边框色', 'set-border', s.ui_border_color || '', '#D5CEC3')}
            <button class="btn btn-sm" onclick="SettingsDialog._resetColors()" style="margin-top:8px">恢复默认</button>

            <div style="margin-top:16px;border-top:0.5px solid var(--border);padding-top:12px">
              <div class="caption" style="margin-bottom:8px">字体大小</div>
              <div style="display:flex;align-items:center;gap:10px">
                <input type="range" id="set-font-size" min="12" max="20" value="${s.ui_font_size || 14}" class="hana-slider">
                <span id="set-font-size-val" style="font-family:var(--font-mono);font-size:0.8rem;color:var(--text);min-width:36px">${s.ui_font_size || 14}px</span>
              </div>
            </div>
          </div>

          <!-- AI -->
          <div class="settings-panel" id="panel-ai" style="display:none">
            <div style="margin-bottom:14px">
              <div class="caption" style="margin-bottom:4px">DeepSeek API Key ${s.deepseek_api_key ? '<span style="color:var(--green);font-weight:400">（已配置）</span>' : '<span style="color:var(--danger)">（未配置）</span>'}</div>
              <input type="password" id="set-api-key" placeholder="${s.deepseek_api_key ? '已保存，重新输入可覆盖' : 'sk-...'}" style="width:100%;height:32px;border:0.5px solid var(--border);border-radius:var(--radius);padding:0 10px;font-size:0.82rem;background:var(--bg-card);color:var(--text);outline:none">
            </div>
            <div style="margin-bottom:14px">
              <div class="caption" style="margin-bottom:4px">默认模型</div>
              <select id="set-model-tier" style="width:100%;height:32px;border:0.5px solid var(--border);border-radius:var(--radius);padding:0 10px;font-size:0.82rem;background:var(--bg-card);color:var(--text);outline:none">
                <option value="flash" ${s.deepseek_default_tier === 'flash' ? 'selected' : ''}>Flash（快速，deepseek-v4-flash）</option>
                <option value="pro" ${s.deepseek_default_tier === 'pro' ? 'selected' : ''}>Pro（深度，deepseek-v4-pro）</option>
              </select>
            </div>
            <div style="margin-bottom:14px">
              <div class="caption" style="margin-bottom:4px">翻译命名格式</div>
              <select id="set-name-mode" style="width:100%;height:32px;border:0.5px solid var(--border);border-radius:var(--radius);padding:0 10px;font-size:0.82rem;background:var(--bg-card);color:var(--text);outline:none">
                <option value="zh_en" ${s.translation_name_mode === 'zh_en' ? 'selected' : ''}>中文名 + 原英文名</option>
                <option value="en_zh" ${s.translation_name_mode === 'en_zh' ? 'selected' : ''}>原英文名 + 中文名</option>
                <option value="zh_only" ${s.translation_name_mode === 'zh_only' ? 'selected' : ''}>只有中文名</option>
                <option value="en_only" ${s.translation_name_mode === 'en_only' ? 'selected' : ''}>保留原英文名</option>
              </select>
            </div>
            <button class="btn btn-sm" onclick="SettingsDialog._testDeepseek()" style="margin-top:4px">验证 API 连接</button>
          </div>

          <!-- Move -->
          <div class="settings-panel" id="panel-move" style="display:none">
            <div style="margin-bottom:14px">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                <input type="checkbox" id="set-formal-move" ${s.enable_formal_move ? 'checked' : ''}>
                <span style="font-size:0.82rem;color:var(--text)">开启正式 Z 盘移动</span>
              </label>
              <div style="font-size:0.72rem;color:var(--text-muted);margin-top:4px;margin-left:24px">开启后移动需二次输入 MOVE 确认，可回滚</div>
            </div>
            <div style="margin-bottom:14px">
              <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
                <input type="checkbox" id="set-cleanup-parents" ${s.cleanup_empty_source_parents_after_move ? 'checked' : ''}>
                <span style="font-size:0.82rem;color:var(--text)">移动后自动清理空来源目录</span>
              </label>
            </div>
          </div>

        </div>
      </div>
    `;
  },

  _themePreset(id, name, bg, accent) {
    return `
      <div class="theme-preset" data-theme="${id}" style="
        width:72px;cursor:pointer;text-align:center;
        border:1px solid var(--border);border-radius:var(--radius);
        padding:8px 4px;transition:border-color 0.12s;
      ">
        <div style="width:100%;height:36px;background:${bg};border-radius:2px;margin-bottom:4px"></div>
        <div style="font-size:0.68rem;color:var(--text-muted)">${name}</div>
      </div>`;
  },

  _colorRow(label, id, value, fallback) {
    const v = value || fallback;
    return `
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="font-size:0.78rem;color:var(--text-light);width:52px">${label}</span>
        <input type="color" id="${id}" value="${v}" style="width:32px;height:26px;border:0.5px solid var(--border);border-radius:2px;cursor:pointer;padding:0;background:transparent">
        <input type="text" id="${id}-hex" value="${v}" style="width:72px;height:26px;border:0.5px solid var(--border);border-radius:var(--radius);padding:0 6px;font-size:0.75rem;font-family:var(--font-mono);background:var(--bg-card);color:var(--text);outline:none">
        <button class="btn btn-sm" onclick="SettingsDialog._resetColor('${id}','${fallback}')" style="height:24px;font-size:0.68rem">默认</button>
      </div>`;
  },

  _bindEvents() {
    // Tab switching
    this.box.querySelectorAll('.settings-nav-item').forEach(item => {
      item.addEventListener('click', () => {
        this.box.querySelectorAll('.settings-nav-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        const tab = item.dataset.tab;
        this.box.querySelectorAll('.settings-panel').forEach(p => p.style.display = 'none');
        const panel = document.getElementById('panel-' + tab);
        if (panel) panel.style.display = '';
      });
    });

    // Theme presets
    this.box.querySelectorAll('.theme-preset').forEach(el => {
      el.addEventListener('click', () => {
        this._applyPreset(el.dataset.theme);
      });
    });

    // Color sync: color picker <-> hex input + live preview
    const colorMap = { 'set-bg':'bg', 'set-card':'card', 'set-sidebar':'sidebar', 'set-accent':'accent', 'set-text':'text', 'set-border':'border' };
    Object.entries(colorMap).forEach(([id, key]) => {
      const colorEl = document.getElementById(id);
      const hexEl = document.getElementById(id + '-hex');
      if (colorEl && hexEl) {
        const applyColor = () => {
          hexEl.value = colorEl.value;
          this._applyLiveColors({ [key]: colorEl.value });
        };
        colorEl.addEventListener('input', applyColor);
        hexEl.addEventListener('input', () => {
          if (/^#[0-9a-fA-F]{6}$/.test(hexEl.value)) {
            colorEl.value = hexEl.value;
            this._applyLiveColors({ [key]: hexEl.value });
          }
        });
      }
    });

    // Font size slider
    const fontSizeEl = document.getElementById('set-font-size');
    const fontSizeVal = document.getElementById('set-font-size-val');
    if (fontSizeEl && fontSizeVal) {
      fontSizeEl.addEventListener('input', () => {
        const v = fontSizeEl.value;
        fontSizeVal.textContent = v + 'px';
        document.documentElement.style.fontSize = v + 'px';
      });
    }
  },

  _applyPreset(theme) {
    const presets = {
      warm:  { bg:'#F4F0EA', card:'#FBF8F3', sidebar:'#EEE9E1', accent:'#537D96', text:'#2A2622', border:'#D5CEC3' },
      cool:  { bg:'#EEEDE8', card:'#F7F5F0', sidebar:'#E5E3DC', accent:'#537D96', text:'#2A2622', border:'#D0CCC3' },
      dark:  { bg:'#2A2622', card:'#322E2A', sidebar:'#1E1C1A', accent:'#6A9AB5', text:'#E0DCD6', border:'#44403A' },
      cream: { bg:'#FAF6EE', card:'#FEFCF7', sidebar:'#F2EDE2', accent:'#537D96', text:'#2A2622', border:'#DDD6C5' },
    };
    const p = presets[theme];
    if (!p) return;
    ['bg','card','sidebar','accent','text','border'].forEach(key => {
      const colorEl = document.getElementById('set-' + key);
      const hexEl = document.getElementById('set-' + key + '-hex');
      if (colorEl) colorEl.value = p[key];
      if (hexEl) hexEl.value = p[key];
    });
    this._applyLiveColors(p);
    this.box.querySelectorAll('.theme-preset').forEach(el => {
      el.style.borderColor = el.dataset.theme === theme ? 'var(--accent)' : 'var(--border)';
    });
  },

  _resetColor(id, fallback) {
    const colorEl = document.getElementById(id);
    const hexEl = document.getElementById(id + '-hex');
    if (colorEl) colorEl.value = fallback;
    if (hexEl) hexEl.value = fallback;
  },

  _resetColors() {
    this._applyPreset('warm');
  },

  async _save() {
    const data = {
      resource_root: (document.getElementById('set-resource-root')?.value || '').trim(),
      deepseek_api_key: (document.getElementById('set-api-key')?.value || '').trim() || undefined,
      deepseek_default_tier: document.getElementById('set-model-tier')?.value || 'flash',
      translation_name_mode: document.getElementById('set-name-mode')?.value || 'zh_en',
      rename_local_after_translate: document.getElementById('set-rename-local')?.checked,
      enable_formal_move: document.getElementById('set-formal-move')?.checked,
      cleanup_empty_source_parents_after_move: document.getElementById('set-cleanup-parents')?.checked,
      auto_index_on_library_open: document.getElementById('set-auto-index')?.checked,
      ui_window_color: document.getElementById('set-bg')?.value || '',
      ui_card_color: document.getElementById('set-card')?.value || '',
      ui_sidebar_color: document.getElementById('set-sidebar')?.value || '',
      ui_accent_color: document.getElementById('set-accent')?.value || '',
      ui_text_color: document.getElementById('set-text')?.value || '',
      ui_border_color: document.getElementById('set-border')?.value || '',
    };
    try {
      await API.saveSettings(data);
      this.settings = data;
      this.applySavedSettings(data);
      this.close();
      App.setStatus('设置已保存');
      // 如果资源库路径变更，刷新侧栏
      if (data.resource_root) Sidebar.load('');
    } catch (err) {
      alert('保存失败：' + err.message);
    }
  },

  _pickRoot() {
    const input = document.getElementById('set-resource-root');
    if (window.electronAPI && window.electronAPI.selectFolder) {
      window.electronAPI.selectFolder().then(path => { if (path && input) input.value = path; });
      return;
    }
    const path = prompt('请输入资源库根路径（如 Z:\\整合——资源管理）：', input?.value || '');
    if (path && input) input.value = path;
  },

  async _testDeepseek() {
    const key = document.getElementById('set-api-key')?.value?.trim();
    if (!key) { alert('请先填写 API Key'); return; }
    try {
      App.setStatus('API 验证中…');
      const r = await API.testDeepseek(key);
      if (r.ok) { alert('连接成功'); App.setStatus('DeepSeek API 连接正常'); }
      else { alert('连接失败：' + (r.error || '未知错误')); }
    } catch (e) {
      alert('连接失败：' + e.message);
    }
  },
};
