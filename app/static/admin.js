// Admin UI helpers.
// Most interactivity is in Alpine.js x-data attributes inside templates;
// this file is for shared globals.

window.toast = function (message) {
  window.dispatchEvent(new CustomEvent('toast', { detail: message }));
};

// Helper: copy text to clipboard with feedback toast
window.copyToClipboard = async function (text, label = 'Copied') {
  try {
    await navigator.clipboard.writeText(text);
    window.toast(label);
  } catch (e) {
    window.toast('Copy failed');
  }
};
