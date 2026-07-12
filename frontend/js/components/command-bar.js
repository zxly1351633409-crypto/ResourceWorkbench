// ================================================================
// Command Bar — path input (analyze button moved to title bar)
// ================================================================

const CommandBar = {
  init() {
    const inputPath = document.getElementById('input-path');
    inputPath.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') App.startAnalysis();
    });
  },

  getInputPath() {
    return document.getElementById('input-path').value.trim();
  },

  setInputPath(path) {
    document.getElementById('input-path').value = path || '';
  },
};
