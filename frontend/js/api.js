// ================================================================
// API Client — communicates with Python backend via /api/* endpoints
// Supports both card_id (new) and legacy index (backwards compat)
// ================================================================

const API = {
  base: '/api',

  async _fetch(path, options = {}) {
    const url = this.base + path;
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      throw new Error(err.error || `HTTP ${res.status}`);
    }
    return res.json();
  },

  async _post(path, data) {
    return this._fetch(path, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  },

  // ── Scan & analyse ──────────────────────────────────────────

  async scan(paths) {
    return this._post('/scan', { paths });
  },

  async analyze(paths, settings) {
    return this._post('/analyze', { paths, settings });
  },

  async cancelAnalysis() {
    return this._post('/cancel-analysis', {});
  },

  async getTaskStatus() {
    return this._fetch('/task-status');
  },

  // ── Cards ───────────────────────────────────────────────────

  async getCards() {
    return this._fetch('/cards');
  },

  async getCard(index) {
    return this._fetch(`/cards/${index}`);
  },

  // Preview by card_id (preferred) or index (legacy)
  async getPreview(cardIdOrIndex) {
    if (typeof cardIdOrIndex === 'string' && cardIdOrIndex) {
      return this._fetch(`/preview/${encodeURIComponent(cardIdOrIndex)}`);
    }
    // Legacy: POST /api/preview-by-index
    return this._post('/preview-by-index', { index: cardIdOrIndex });
  },

  // ── Library ─────────────────────────────────────────────────

  async getLibraryTree(path) {
    return this._post('/library-tree', { path: path || '' });
  },

  async getLibraryCards(path) {
    return this._post('/library-cards', { path });
  },

  // ── Translation ──────────────────────────────────────────────

  async translateCard(cardId, legacyIndex) {
    const payload = {};
    if (cardId) payload.card_id = cardId;
    if (legacyIndex !== undefined && legacyIndex >= 0) payload.index = legacyIndex;
    return this._post('/translate', payload);
  },

  async translateAll() {
    return this._post('/translate-all', {});
  },

  // ── Move ─────────────────────────────────────────────────────

  async moveCard(cardId, targetPath, dryRun, legacyIndex) {
    const payload = { target_path: targetPath, dry_run: !!dryRun };
    if (cardId) payload.card_id = cardId;
    if (legacyIndex !== undefined && legacyIndex >= 0) payload.index = legacyIndex;
    return this._post('/move', payload);
  },

  async moveSelected(indices, targetPath, dryRun) {
    return this._post('/move-selected', { indices, target_path: targetPath, dry_run: !!dryRun });
  },

  // ── Target recommendation ───────────────────────────────────

  async recommendTarget(cardId, legacyIndex) {
    const payload = {};
    if (cardId) payload.card_id = cardId;
    if (legacyIndex !== undefined && legacyIndex >= 0) payload.index = legacyIndex;
    return this._post('/recommend-target', payload);
  },

  async browseTargetFolders(path) {
    return this._post('/browse-folders', { path });
  },

  // ── Settings ─────────────────────────────────────────────────

  async getSettings() {
    return this._fetch('/settings');
  },

  async saveSettings(settings) {
    return this._post('/settings', settings);
  },

  // ── Review queue ─────────────────────────────────────────────

  async getReviewQueue() {
    return this._fetch('/review-queue');
  },

  async updateReviewQueue(cardId, status) {
    return this._post('/review-queue', { card_id: cardId, status });
  },

  // ── History ──────────────────────────────────────────────────

  async getHistory() {
    return this._fetch('/history');
  },

  // ── Maintenance ──────────────────────────────────────────────

  async openFolder(path) {
    return this._post('/open-folder', { path });
  },

  async findDuplicates() {
    return this._post('/dedupe', {});
  },

  async cleanupEmptyDirs() {
    return this._post('/cleanup', {});
  },

  // ── Status ───────────────────────────────────────────────────

  async getStatus() {
    return this._fetch('/status');
  },

  // ── Web Card ─────────────────────────────────────────────────

  async createWebCard(url) {
    return this._post('/web-card', { url });
  },

  // ── Folder ───────────────────────────────────────────────────

  async createFolder(parent, name) {
    return this._post('/create-folder', { parent, name });
  },

  async testDeepseek(apiKey) {
    return this._post('/test-deepseek', { deepseek_api_key: apiKey || '' });
  },

  async undo(kind, recordId) {
    return this._post('/undo', { kind, record_id: recordId });
  },

  async getOverview() {
    return this._fetch('/overview');
  },
};
