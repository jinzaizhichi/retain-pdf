async function loadPartial(relativePath) {
  const url = new URL(relativePath, window.location.href);
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`加载页面片段失败: ${relativePath}`);
  }
  return response.text();
}

export async function renderPageShell() {
  const [mainContent, dialogs] = await Promise.all([
    loadPartial("./src/partials/main-content.html"),
    loadPartial("./src/partials/dialogs.html"),
  ]);

  document.body.innerHTML = `${mainContent}${dialogs}`;
}
